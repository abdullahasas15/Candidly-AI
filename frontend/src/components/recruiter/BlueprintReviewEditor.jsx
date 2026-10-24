import React, { useState, useEffect, useMemo } from 'react';
import {
  Sparkles, Clock, AlertTriangle, CheckCircle2, ArrowUp, ArrowDown,
  RefreshCw, Trash2, Plus, ShieldCheck, FileText, ChevronRight,
  Info, Layers, Lock, Edit3, AlertCircle, Check, Play, UserCheck
} from 'lucide-react';
import { getRecruiterToken, getAuthHeaders } from '../../utils/auth';

export default function BlueprintReviewEditor({
  job: propJob,
  jobId: propJobId,
  onApproved,
  onBlueprintApproved,
  onClose,
  initialBlueprint = null
}) {
  const job = propJob || (propJobId ? { id: propJobId } : null);
  const [blueprint, setBlueprint] = useState(initialBlueprint);
  const [loading, setLoading] = useState(!initialBlueprint);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [regeneratingSectionId, setRegeneratingSectionId] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);
  const [viewMode, setViewMode] = useState('sections'); // 'sections' | 'script_preview'
  const [confirmWarningModal, setConfirmWarningModal] = useState(false);
  const [budgetPreview, setBudgetPreview] = useState(null);
  const [taskState, setTaskState] = useState(null);
  const [pollEpoch, setPollEpoch] = useState(0);

  // Fetch blueprint and budget preview on mount
  const fetchBlueprint = async () => {
    if (!job?.id) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setErrorMsg(null);
    try {
      const token = getRecruiterToken();
      const headers = getAuthHeaders(token);

      const res = await fetch(`/api/jobs/${job.id}/blueprint`, { headers });
      if (res.ok) {
        const data = await res.json();
        setBlueprint(data);
      } else if (res.status === 404) {
        setBlueprint(null);
      } else {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to load blueprint');
      }
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchBudgetPreview = async () => {
    if (!job?.interview_duration_mins) return;
    try {
      const res = await fetch('/api/budget/blueprint/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          duration_mins: job.interview_duration_mins,
          skills: job.skills || []
        })
      });
      if (res.ok) {
        const data = await res.json();
        setBudgetPreview(data);
      }
    } catch (err) {
      console.warn('Failed to load budget preview:', err);
    }
  };

  useEffect(() => {
    if (!initialBlueprint) {
      fetchBlueprint();
    }
    fetchBudgetPreview();
  }, [job?.id]);

  // Poll background task status (survives page refresh)
  useEffect(() => {
    if (!job?.id) return;
    let timer = null;
    let isSubscribed = true;

    const checkStatus = async () => {
      try {
        const token = getRecruiterToken();
        const headers = getAuthHeaders(token);
        const res = await fetch(`/api/jobs/${job.id}/blueprint/generate/status`, { headers });
        if (!res.ok) {
          // Transient server error: keep polling instead of freezing the progress UI
          if (isSubscribed) timer = setTimeout(checkStatus, 3000);
          return;
        }
        const data = await res.json();
        if (!isSubscribed) return;

        setTaskState(data);
        if (data.status === 'in_progress') {
          setGenerating(true);
          timer = setTimeout(checkStatus, 1500);
        } else if (data.status === 'completed') {
          setGenerating(false);
          if (data.blueprint) {
            setBlueprint(data.blueprint);
          }
          await fetchBlueprint();
        } else if (data.status === 'failed') {
          setGenerating(false);
          setErrorMsg(data.error || 'Blueprint generation failed');
        } else if (data.status === 'idle') {
          setGenerating(false);
        }
      } catch (err) {
        console.warn('Status poll error:', err);
        // Network hiccup: retry with backoff so one dropped request doesn't kill polling
        if (isSubscribed) timer = setTimeout(checkStatus, 3000);
      }
    };

    checkStatus();

    return () => {
      isSubscribed = false;
      if (timer) clearTimeout(timer);
    };
  }, [job?.id, pollEpoch]);

  // Launch background blueprint generation
  const handleGenerateBlueprint = async () => {
    if (!job?.id) return;
    setGenerating(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      const token = getRecruiterToken();
      const headers = getAuthHeaders(token);

      const res = await fetch(`/api/jobs/${job.id}/blueprint/generate`, {
        method: 'POST',
        headers
      });

      if (!res.ok) {
        const err = await res.json();
        const msg = typeof err.detail === 'object' ? err.detail.message : err.detail;
        throw new Error(msg || 'Blueprint generation failed');
      }

      const accepted = await res.json();
      setTaskState(accepted);
      // Restart/resume polling immediately for the accepted run
      setPollEpoch((prev) => prev + 1);
    } catch (err) {
      setGenerating(false);
      setErrorMsg(err.message);
    }
  };

  // Save / Update sections (triggers copy-on-write on server if approved)
  const saveSections = async (updatedSections) => {
    if (!job?.id || !blueprint?.id) return;
    setSaving(true);
    setErrorMsg(null);
    try {
      const token = getRecruiterToken();
      const headers = getAuthHeaders(token, 'application/json');

      const res = await fetch(`/api/jobs/${job.id}/blueprint/${blueprint.id}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({ sections: updatedSections })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to update blueprint');
      }

      const updated = await res.json();
      setBlueprint(updated);
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setSaving(false);
    }
  };

  // Reorder sections
  const handleMoveSection = (index, direction) => {
    if (!blueprint?.sections) return;
    const newIdx = index + direction;
    if (newIdx < 0 || newIdx >= blueprint.sections.length) return;

    const sections = [...blueprint.sections];
    const temp = sections[index];
    sections[index] = sections[newIdx];
    sections[newIdx] = temp;

    // re-index
    sections.forEach((s, i) => { s.order_index = i; });
    saveSections(sections);
  };

  // Delete section
  const handleDeleteSection = (index) => {
    if (!blueprint?.sections) return;
    const sections = blueprint.sections.filter((_, i) => i !== index);
    sections.forEach((s, i) => { s.order_index = i; });
    saveSections(sections);
  };

  // Regenerate single section
  const handleRegenerateSection = async (sectionId) => {
    if (!job?.id || !blueprint?.id) return;
    setRegeneratingSectionId(sectionId);
    setErrorMsg(null);
    try {
      const token = getRecruiterToken();
      const headers = getAuthHeaders(token, 'application/json');

      const res = await fetch(`/api/jobs/${job.id}/blueprint/sections/${sectionId}/regenerate`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ blueprint_id: blueprint.id })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to regenerate section');
      }

      const updated = await res.json();
      setBlueprint(updated);
      setSuccessMsg('Section regenerated successfully!');
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setRegeneratingSectionId(null);
    }
  };

  // Add custom Recruiter Anchor question
  const handleAddRecruiterAnchor = (secIdx) => {
    if (!blueprint?.sections) return;
    const sections = JSON.parse(JSON.stringify(blueprint.sections));
    const sec = sections[secIdx];
    if (!sec) return;

    sec.questions = sec.questions || [];
    sec.questions.push({
      question_role: 'anchor',
      question_text: 'Describe a complex scenario where you applied this skill in production.',
      source: 'recruiter',
      target_expectation_ids: (sec.expectations || []).map((e) => e.id),
      order_index: sec.questions.length
    });

    saveSections(sections);
  };

  // Add Expectation
  const handleAddExpectation = (secIdx) => {
    if (!blueprint?.sections) return;
    const sections = JSON.parse(JSON.stringify(blueprint.sections));
    const sec = sections[secIdx];
    if (!sec) return;

    sec.expectations = sec.expectations || [];
    sec.expectations.push({
      expectation_text: 'Demonstrates deep hands-on mastery of fundamental principles.',
      source_rubric_level: 'L4',
      importance: 'core',
      order_index: sec.expectations.length
    });

    saveSections(sections);
  };

  // Remove Expectation
  const handleRemoveExpectation = (secIdx, expIdx) => {
    if (!blueprint?.sections) return;
    const sections = JSON.parse(JSON.stringify(blueprint.sections));
    const sec = sections[secIdx];
    if (!sec) return;

    sec.expectations.splice(expIdx, 1);
    saveSections(sections);
  };

  // Update Expectation field
  const handleUpdateExpectation = (secIdx, expIdx, field, val) => {
    if (!blueprint?.sections) return;
    const sections = JSON.parse(JSON.stringify(blueprint.sections));
    const sec = sections[secIdx];
    if (!sec || !sec.expectations[expIdx]) return;

    sec.expectations[expIdx][field] = val;
    setBlueprint({ ...blueprint, sections });
  };

  // Update Question text / triggers
  const handleUpdateQuestion = (secIdx, qIdx, field, val) => {
    if (!blueprint?.sections) return;
    const sections = JSON.parse(JSON.stringify(blueprint.sections));
    const sec = sections[secIdx];
    if (!sec || !sec.questions[qIdx]) return;

    sec.questions[qIdx][field] = val;
    setBlueprint({ ...blueprint, sections });
  };

  // Add Probe to Section
  const handleAddProbe = (secIdx) => {
    if (!blueprint?.sections) return;
    const sections = JSON.parse(JSON.stringify(blueprint.sections));
    const sec = sections[secIdx];
    if (!sec) return;

    sec.questions = sec.questions || [];
    sec.questions.push({
      question_role: 'probe',
      question_text: 'What trade-offs did you consider when making this design choice?',
      trigger_condition: 'If candidate skips edge cases or gives an ambiguous explanation.',
      source: 'llm',
      target_expectation_ids: [],
      order_index: sec.questions.length
    });

    saveSections(sections);
  };

  // Remove Question
  const handleRemoveQuestion = (secIdx, qIdx) => {
    if (!blueprint?.sections) return;
    const sections = JSON.parse(JSON.stringify(blueprint.sections));
    const sec = sections[secIdx];
    if (!sec) return;

    sec.questions.splice(qIdx, 1);
    saveSections(sections);
  };

  // Update Section allocated minutes
  const handleUpdateSectionMinutes = (secIdx, minutes) => {
    if (!blueprint?.sections) return;
    const sections = JSON.parse(JSON.stringify(blueprint.sections));
    const sec = sections[secIdx];
    if (!sec) return;

    sec.allocated_minutes = parseFloat(minutes) || 0;
    setBlueprint({ ...blueprint, sections });
  };

  // Approve Blueprint
  const handleApprove = async (confirmedWarnings = false) => {
    if (!job?.id || !blueprint?.id) return;
    setSaving(true);
    setErrorMsg(null);
    try {
      const token = getRecruiterToken();
      const headers = getAuthHeaders(token, 'application/json');

      const res = await fetch(`/api/jobs/${job.id}/blueprint/approve`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          blueprint_id: blueprint.id,
          confirmed_warnings: confirmedWarnings
        })
      });

      if (!res.ok) {
        const err = await res.json();
        if (err.detail?.needs_confirmation || (typeof err.detail === 'string' && err.detail.includes('warnings'))) {
          // Keep this open: the finally block below must not reset it on this path
          setSaving(false);
          setConfirmWarningModal(true);
          return;
        }
        setConfirmWarningModal(false);
        throw new Error(err.detail?.message || err.detail || 'Approval failed');
      }

      const approved = await res.json();
      setBlueprint(approved);
      setSuccessMsg('Blueprint approved! This job is now accepting candidate applications.');
      setConfirmWarningModal(false);
      if (onApproved) onApproved(approved);
      if (onBlueprintApproved) onBlueprintApproved(approved);
    } catch (err) {
      setConfirmWarningModal(false);
      setErrorMsg(err.message);
    } finally {
      setSaving(false);
    }
  };

  // Total allocated minutes calculation
  const totalAllocatedMins = useMemo(() => {
    if (!blueprint?.sections) return 0;
    return blueprint.sections.reduce((acc, s) => acc + (parseFloat(s.allocated_minutes) || 0), 0);
  }, [blueprint?.sections]);

  const durationTarget = job?.interview_duration_mins || 20;
  const timeDifference = Math.round((totalAllocatedMins - durationTarget) * 10) / 10;
  const validatorWarnings = blueprint?.validation_report?.warnings || [];
  const validatorErrors = blueprint?.validation_report?.errors || [];

  if (loading) {
    return (
      <div className="p-12 text-center space-y-4">
        <RefreshCw className="w-8 h-8 text-teal-400 animate-spin mx-auto" />
        <p className="text-sm font-semibold text-slate-600 dark:text-slate-300">
          Loading Interview Blueprint & Validation State...
        </p>
      </div>
    );
  }

  // If no blueprint exists yet
  if (!blueprint) {
    const isProgress = generating || taskState?.status === 'in_progress';
    return (
      <div className="p-8 text-center space-y-6 bg-[#111113]/40 rounded-3xl border border-dashed border-slate-300 dark:border-slate-800">
        <div className="w-16 h-16 rounded-2xl bg-teal-500/10 text-teal-400 flex items-center justify-center mx-auto shadow-inner">
          <Sparkles className="w-8 h-8" />
        </div>
        <div className="max-w-md mx-auto space-y-2">
          <h3 className="text-lg font-extrabold text-white">
            {isProgress ? 'Generating Autonomous Interview Blueprint...' : 'No Interview Blueprint Generated Yet'}
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {isProgress
              ? 'Our pipeline is budgeting sections, synthesizing competencies, auto-repairing question flow, and executing batched LLM quality checks.'
              : 'Generate an evidence-based Layer 1 Blueprint with structured sections, core expectations, anchor questions, and probing triggers calibrated to your 5-level rubric.'}
          </p>
        </div>

        {errorMsg && (
          <div className="p-3 bg-rose-50 dark:bg-rose-950/50 border border-rose-200 dark:border-rose-900 text-xs text-rose-700 dark:text-rose-300 rounded-xl font-medium max-w-lg mx-auto">
            {errorMsg}
          </div>
        )}

        {isProgress ? (
          <div className="max-w-md mx-auto w-full p-4 rounded-2xl bg-white dark:bg-slate-800 border border-teal-500/20 shadow-md space-y-3 text-left">
            <div className="flex items-center justify-between text-xs font-bold text-zinc-300">
              <span className="flex items-center gap-2">
                <RefreshCw className="w-4 h-4 animate-spin text-teal-400" />
                <span>
                  {taskState?.current_stage === 'budgeting' && 'Calculating section budgets...'}
                  {taskState?.current_stage === 'generating_sections' && 'Synthesizing competencies and rubric anchors...'}
                  {taskState?.current_stage === 'repair_passes' && 'Running auto-repair (anchor variety & punctuation)...'}
                  {taskState?.current_stage === 'batched_llm_review' && 'Executing batched LLM quality review...'}
                  {taskState?.current_stage === 'saving' && 'Committing blueprint to database...'}
                  {(!taskState?.current_stage || taskState?.current_stage === 'initializing') && 'Initializing AI generation pipeline...'}
                </span>
              </span>
              <span className="font-mono text-teal-400 font-extrabold">
                {Math.round((taskState?.progress || 0.1) * 100)}%
              </span>
            </div>

            {/* Progress bar */}
            <div className="w-full h-2 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
              <div
                className="h-full bg-teal-500 transition-all duration-500 rounded-full"
                style={{ width: `${Math.round((taskState?.progress || 0.1) * 100)}%` }}
              />
            </div>

            {/* Section progress pills */}
            {taskState?.section_progress && Object.keys(taskState.section_progress).length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {Object.entries(taskState.section_progress).map(([name, s]) => (
                  <span key={name} className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 flex items-center gap-1">
                    <Check className="w-3 h-3 text-emerald-600" />
                    <span>{name}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        ) : (
          <button
            type="button"
            onClick={handleGenerateBlueprint}
            className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-teal-500 hover:bg-teal-400 text-black font-semibold font-bold text-xs shadow-lg shadow-teal-500/10 transition-all hover:-translate-y-0.5"
          >
            <Sparkles className="w-4 h-4" />
            <span>Generate Interview Blueprint</span>
          </button>
        )}
      </div>
    );
  }

  const isLive = blueprint?.status === 'approved' && !blueprint?.is_stale && validatorErrors.length === 0;

  return (
    <div className="space-y-6">
      {/* Top Banner / Status Strip */}
      <div className="p-4 sm:p-5 rounded-3xl bg-[#111113] border border-white/[0.08] space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="px-3 py-1 rounded-full text-xs font-black tracking-wide bg-teal-500/10 text-teal-300 border border-teal-500/20">
              v{blueprint.version} {blueprint.status === 'approved' ? 'Approved' : 'Draft'}
            </span>

            {blueprint.is_generated_with_backup && (
              <span className="px-3 py-1 rounded-full text-xs font-bold bg-amber-100 dark:bg-amber-950 text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-800 flex items-center gap-1.5 shadow-sm">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
                <span>Generated with Backup Provider (TokenHarbor - {blueprint.generation_model || 'DeepSeek'})</span>
              </span>
            )}

            {blueprint.generation_stages_ms && (
              <span className="px-3 py-1 rounded-full text-[11px] font-semibold bg-[#18181B] text-zinc-400 border border-slate-200 dark:border-slate-700 flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-slate-400" />
                <span>
                  Synthesis: {Math.round(blueprint.generation_stages_ms.total_ms || blueprint.generation_latency_ms || 0)}ms
                  (Budget {Math.round(blueprint.generation_stages_ms.budgeting_ms || 0)}ms • Secs {Math.round(blueprint.generation_stages_ms.section_calls_ms || 0)}ms • Review {Math.round(blueprint.generation_stages_ms.llm_review_ms || 0)}ms)
                </span>
              </span>
            )}

            {blueprint.is_stale && (
              <span className="px-3 py-1 rounded-full text-xs font-bold bg-amber-100 dark:bg-amber-950 text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-800 flex items-center gap-1.5 animate-pulse">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
                <span>Stale (Role modified - re-approval required)</span>
              </span>
            )}

            {isLive && (
              <span data-testid="live-status-badge" className="px-3 py-1 rounded-full text-xs font-bold bg-emerald-100 dark:bg-emerald-950 text-emerald-800 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800 flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                <span>Active & Accepting Applications</span>
              </span>
            )}

            {blueprint.status === 'approved' && validatorErrors.length > 0 && (
              <span data-testid="blocked-status-badge" className="px-3 py-1 rounded-full text-xs font-bold bg-rose-100 dark:bg-rose-950 text-rose-800 dark:text-rose-300 border border-rose-300 dark:border-rose-800 flex items-center gap-1.5">
                <AlertCircle className="w-3.5 h-3.5 text-rose-600" />
                <span>Blocked by Validation Errors</span>
              </span>
            )}
          </div>

          {/* View mode toggle */}
          <div className="flex items-center gap-1 bg-[#18181B] p-1 rounded-2xl border border-white/[0.08] text-xs font-bold">
            <button
              type="button"
              onClick={() => setViewMode('sections')}
              className={`px-3 py-1.5 rounded-xl transition-all ${
                viewMode === 'sections'
                  ? 'bg-teal-500 text-black shadow-sm'
                  : 'text-zinc-400 hover:text-white'
              }`}
            >
              Sections & Rubrics
            </button>
            <button
              type="button"
              onClick={() => setViewMode('script_preview')}
              className={`px-3 py-1.5 rounded-xl transition-all ${
                viewMode === 'script_preview'
                  ? 'bg-teal-500 text-black shadow-sm'
                  : 'text-zinc-400 hover:text-white'
              }`}
            >
              Spoken Script Preview
            </button>
          </div>
        </div>

        {/* Time Budget Meter */}
        <div className="p-3.5 rounded-2xl bg-[#0A0A0B] border border-white/[0.08] space-y-2">
          <div className="flex items-center justify-between text-xs font-bold">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-teal-400" />
              <span className="text-zinc-300">
                Time Meter: {totalAllocatedMins} mins allocated / {durationTarget} mins target
              </span>
            </div>
            <span className={`text-[11px] font-bold ${
              timeDifference === 0
                ? 'text-emerald-400'
                : Math.abs(timeDifference) <= 1.0
                ? 'text-amber-400'
                : 'text-rose-400'
            }`}>
              {timeDifference === 0 ? 'Perfect Budget Match' : `${timeDifference > 0 ? '+' : ''}${timeDifference}m variance`}
            </span>
          </div>

          {/* Visual Bar */}
          <div className="w-full h-2 rounded-full bg-[#18181B] overflow-hidden flex">
            {blueprint.sections?.map((s, idx) => {
              const widthPct = Math.min(100, (s.allocated_minutes / durationTarget) * 100);
              const color = s.section_type === 'welcome' || s.section_type === 'closing'
                ? 'bg-zinc-600'
                : s.priority_tier === 'P0'
                ? 'bg-rose-500'
                : s.priority_tier === 'P1'
                ? 'bg-teal-500'
                : 'bg-emerald-500';

              return (
                <div
                  key={idx}
                  title={`${s.title}: ${s.allocated_minutes}m`}
                  style={{ width: `${widthPct}%` }}
                  className={`${color} h-full border-r border-white/10 transition-all`}
                />
              );
            })}
          </div>
        </div>

        {/* Alerts / Warnings / Errors */}
        {validatorErrors.length > 0 && (
          <div className="p-3 rounded-2xl bg-rose-50 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-900/60 space-y-1">
            <div className="flex items-center gap-1.5 text-xs font-bold text-rose-700 dark:text-rose-300">
              <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0" />
              <span>Validation Errors (Must be resolved before approval):</span>
            </div>
            <ul className="text-xs text-rose-600 dark:text-rose-400 list-disc list-inside space-y-0.5 pl-2 font-medium">
              {validatorErrors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Warnings are pre-approval decision aids. On an approved/live blueprint
            they are already acknowledged quality notes — re-showing them is noise. */}
        {validatorWarnings.length > 0 && blueprint.status !== 'approved' && (
          <details className="p-3 rounded-2xl bg-amber-50 dark:bg-amber-950/60 border border-amber-200 dark:border-amber-900/60 space-y-1">
            <summary className="flex items-center gap-1.5 text-xs font-bold text-amber-800 dark:text-amber-300 cursor-pointer">
              <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0" />
              <span>{validatorWarnings.length} non-blocking note{validatorWarnings.length > 1 ? 's' : ''} from the quality review</span>
            </summary>
            <ul className="mt-2 text-xs text-amber-700 dark:text-amber-400 list-disc list-inside space-y-0.5 pl-2 font-medium">
              {validatorWarnings.map((warn, i) => (
                <li key={i}>{warn}</li>
              ))}
            </ul>
          </details>
        )}

        {errorMsg && (
          <div className="p-3 rounded-2xl bg-rose-50 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-900 text-xs font-semibold text-rose-700 dark:text-rose-300 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {successMsg && (
          <div className="p-3 rounded-2xl bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-900 text-xs font-semibold text-emerald-700 dark:text-emerald-300 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0 text-emerald-600" />
            <span>{successMsg}</span>
          </div>
        )}
      </div>

      {/* VIEW MODE 1: Static Spoken Script Preview */}
      {viewMode === 'script_preview' && (
        <div className="space-y-4">
          <div className="p-4 rounded-2xl bg-teal-500/10 border border-teal-500/20 text-xs text-teal-200 font-medium space-y-1">
            <p className="font-bold flex items-center gap-1.5 text-teal-300">
              <FileText className="w-4 h-4" />
              <span>Static Spoken Interview Script Preview</span>
            </p>
            <p className="text-[11px] opacity-80">
              This preview shows the exact spoken narrative the autonomous AI interviewer will deliver: seamless transitions, calibrated anchors, escalation routes, and closing remarks.
            </p>
          </div>

          {blueprint.sections?.map((sec, idx) => {
            const isFixed = sec.section_type === 'welcome' || sec.section_type === 'closing';
            const anchorQ = sec.questions?.find((q) => q.question_role === 'anchor');
            const escQ = sec.questions?.find((q) => q.question_role === 'escalation');
            const probes = sec.questions?.filter((q) => q.question_role === 'probe') || [];

            return (
              <div
                key={sec.id || idx}
                className="p-5 rounded-3xl bg-[#0A0A0B] border border-white/[0.08] shadow-sm space-y-3"
              >
                <div className="flex items-center justify-between pb-3 border-b border-white/[0.08]">
                  <div className="flex items-center gap-2">
                    <span className="w-6 h-6 rounded-lg bg-teal-500/10 text-teal-400 font-black text-xs flex items-center justify-center">
                      {idx + 1}
                    </span>
                    <h4 className="text-sm font-black text-white">
                      {sec.title}
                    </h4>
                  </div>
                  <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-[#18181B] text-zinc-300">
                    {sec.allocated_minutes} minutes
                  </span>
                </div>

                {/* Spoken script content */}
                {sec.section_type === 'welcome' && (
                  <div className="p-3.5 rounded-2xl bg-[#111113] border border-white/[0.08] text-xs text-zinc-300 space-y-2">
                    <p className="font-bold text-zinc-500 uppercase text-[10px]">Spoken Welcome & Agenda</p>
                    <p className="italic leading-relaxed">
                      "{sec.welcome_script || `Hello! Welcome to your interview for ${job?.job_title || 'this role'}. We have ${job?.interview_duration_mins || 20} minutes today. We'll start with a brief introduction, dive into your technical competencies, and reserve time for your questions.`}"
                    </p>
                  </div>
                )}

                {sec.section_type === 'closing' && (
                  <div className="p-3.5 rounded-2xl bg-[#111113] border border-white/[0.08] text-xs text-zinc-300 space-y-2">
                    <p className="font-bold text-zinc-500 uppercase text-[10px]">Spoken Closing & Candidate Q&A</p>
                    <p className="italic leading-relaxed">
                      "{sec.closing_script || 'Thank you for walking us through your experience! We now have a few minutes for any questions you would like to ask us about the role, team, or architecture.'}"
                    </p>
                  </div>
                )}

                {!isFixed && (
                  <div className="space-y-3 text-xs">
                    {/* Spoken Transition */}
                    <div className="p-3 rounded-2xl bg-[#111113] border border-white/[0.08] space-y-1">
                      <span className="text-[10px] font-bold uppercase text-zinc-400">Natural Verbal Transition</span>
                      <p className="italic text-zinc-300">
                        "Now, let's turn our attention to {sec.skill_name}. I'd like to explore how you approach architecture and problem solving in this domain."
                      </p>
                    </div>

                    {/* Calibrated Anchor */}
                    {anchorQ && (
                      <div className="p-3.5 rounded-2xl bg-teal-500/10 border border-teal-500/20 space-y-1.5">
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] font-black uppercase text-teal-400">
                            Spoken Anchor Question ({anchorQ.source === 'recruiter' ? 'Recruiter-Authored' : 'AI-Calibrated'})
                          </span>
                          <span className="text-[10px] text-zinc-400 font-semibold">{anchorQ.word_count || 0} words</span>
                        </div>
                        <p className="font-bold text-white leading-relaxed">
                          "{anchorQ.question_text}"
                        </p>
                      </div>
                    )}

                    {/* Escalation Path */}
                    {escQ && (
                      <div className="p-3 rounded-2xl bg-purple-950/20 border border-purple-900/40 space-y-1">
                        <span className="text-[10px] font-black uppercase text-purple-400">
                          Senior Escalation Path (If candidate shows strong L4+ mastery)
                        </span>
                        <p className="italic text-zinc-300">
                          "{escQ.question_text}"
                        </p>
                      </div>
                    )}

                    {/* Dynamic Probes */}
                    {probes.length > 0 && (
                      <div className="space-y-2 pt-1">
                        <span className="text-[10px] font-black uppercase text-zinc-400 block">
                          Calibrated Follow-Up Probes ({probes.length})
                        </span>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                          {probes.map((pr, pIdx) => (
                            <div
                              key={pIdx}
                              className="p-2.5 rounded-xl bg-[#111113] border border-white/[0.08] text-[11px] space-y-1"
                            >
                              <p className="font-semibold text-zinc-200">"{pr.question_text}"</p>
                              {pr.trigger_condition && (
                                <p className="text-[10px] text-amber-400 font-medium">
                                  Trigger: {pr.trigger_condition}
                                </p>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* VIEW MODE 2: Sections & Rubrics Editor */}
      {viewMode === 'sections' && (
        <div className="space-y-4">
          {(!blueprint.sections || blueprint.sections.length === 0) ? (
            <div className="p-8 text-center space-y-4 bg-[#111113] rounded-3xl border border-dashed border-zinc-800">
              <p className="text-sm text-zinc-400">No sections found in this blueprint.</p>
              <button
                type="button"
                onClick={handleGenerateBlueprint}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-teal-500 hover:bg-teal-400 text-black font-semibold text-xs transition-all"
              >
                <Sparkles className="w-4 h-4" />
                <span>Generate Blueprint Sections</span>
              </button>
            </div>
          ) : (
            blueprint.sections.map((sec, sIdx) => {
            const isFixed = sec.section_type === 'welcome' || sec.section_type === 'closing';
            const isRegenerating = regeneratingSectionId === sec.id;

            return (
              <div
                key={sec.id || sIdx}
                className="p-5 rounded-3xl bg-[#0A0A0B] border border-white/[0.08] shadow-sm space-y-4 transition-all"
              >
                {/* Section Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-100 dark:border-slate-800">
                  <div className="flex items-center gap-2.5">
                    <span className="w-7 h-7 rounded-xl bg-teal-500/10 text-teal-400 font-black text-xs flex items-center justify-center">
                      {sIdx + 1}
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <h4 className="text-sm font-black text-white">
                          {sec.title}
                        </h4>
                        {isFixed ? (
                          <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-[#18181B] text-slate-500">
                            Fixed Section
                          </span>
                        ) : (
                          <span className={`px-2 py-0.5 rounded-md text-[10px] font-black ${
                            sec.priority_tier === 'P0'
                              ? 'bg-rose-500/10 text-rose-300 border border-rose-500/20'
                              : 'bg-teal-500/10 text-teal-300 border border-teal-500/20'
                          }`}>
                            {sec.priority_tier || 'P1'}
                          </span>
                        )}
                      </div>
                      {!isFixed && (
                        <p className="text-[11px] text-zinc-400">
                          Target Rubric Tier: <strong className="text-zinc-200">{sec.target_rubric_tier || 'Not configured'}</strong>
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Section Controls */}
                  <div className="flex items-center gap-2">
                    {/* Time Input */}
                    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-[#18181B] border border-white/[0.08] text-xs">
                      <Clock className="w-3.5 h-3.5 text-zinc-400" />
                      <input
                        type="number"
                        step="0.5"
                        min="1"
                        max="30"
                        value={sec.allocated_minutes}
                        onChange={(e) => handleUpdateSectionMinutes(sIdx, e.target.value)}
                        onBlur={() => saveSections(blueprint.sections)}
                        className="w-12 bg-transparent text-center font-bold text-white focus:outline-none"
                      />
                      <span className="text-zinc-400 text-[11px]">min</span>
                    </div>

                    {!isFixed && (
                      <>
                        {/* Reorder Buttons */}
                        <div className="flex items-center border border-white/[0.08] rounded-xl overflow-hidden bg-[#18181B]">
                          <button
                            type="button"
                            disabled={sIdx <= 1}
                            onClick={() => handleMoveSection(sIdx, -1)}
                            className="p-1.5 hover:bg-[#27272A] disabled:opacity-30 text-zinc-400"
                            title="Move Up"
                          >
                            <ArrowUp className="w-3.5 h-3.5" />
                          </button>
                          <button
                            type="button"
                            disabled={sIdx >= blueprint.sections.length - 2}
                            onClick={() => handleMoveSection(sIdx, 1)}
                            className="p-1.5 hover:bg-[#27272A] disabled:opacity-30 text-zinc-400"
                            title="Move Down"
                          >
                            <ArrowDown className="w-3.5 h-3.5" />
                          </button>
                        </div>

                        {/* Regenerate Section */}
                        <button
                          type="button"
                          disabled={isRegenerating || saving}
                          onClick={() => handleRegenerateSection(sec.id)}
                          className="p-1.5 rounded-xl border border-white/[0.08] text-zinc-300 hover:bg-[#18181B] hover:text-teal-400 transition-colors disabled:opacity-40"
                          title="Regenerate this section with Gemini"
                        >
                          <RefreshCw className={`w-3.5 h-3.5 ${isRegenerating ? 'animate-spin text-teal-400' : ''}`} />
                        </button>

                        {/* Delete Section */}
                        <button
                          type="button"
                          onClick={() => handleDeleteSection(sIdx)}
                          className="p-1.5 rounded-xl border border-white/[0.08] text-rose-400 hover:bg-rose-950/30 transition-colors"
                          title="Delete Section"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* Section Body */}
                {isFixed ? (
                  <p className="text-xs text-slate-500 dark:text-slate-400 italic">
                    Fixed opening & wrapup sections ensure interview compliance and rapport consistency.
                  </p>
                ) : (
                  <div className="space-y-4 text-xs">
                    {/* 1. Expectations */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <label className="font-bold text-zinc-300 text-[11px] uppercase tracking-wider">
                          Evaluator Expectations ({sec.expectations?.length || 0})
                        </label>
                        <button
                          type="button"
                          onClick={() => handleAddExpectation(sIdx)}
                          className="inline-flex items-center gap-1 text-[11px] font-bold text-teal-400 hover:underline"
                        >
                          <Plus className="w-3 h-3" />
                          <span>Add Expectation</span>
                        </button>
                      </div>

                      <div className="space-y-1.5">
                        {sec.expectations?.map((exp, eIdx) => (
                          <div
                            key={exp.id || eIdx}
                            className="flex items-center gap-2 p-2 rounded-xl bg-[#18181B] border border-white/[0.08]"
                          >
                            <input
                              type="text"
                              value={exp.expectation_text}
                              onChange={(e) => handleUpdateExpectation(sIdx, eIdx, 'expectation_text', e.target.value)}
                              onBlur={() => saveSections(blueprint.sections)}
                              className="flex-1 bg-transparent text-xs text-white focus:outline-none"
                            />
                            
                            {/* Importance Toggle */}
                            <select
                              value={exp.importance || 'core'}
                              onChange={(e) => {
                                handleUpdateExpectation(sIdx, eIdx, 'importance', e.target.value);
                                saveSections(blueprint.sections);
                              }}
                              className="px-2 py-0.5 rounded-md border border-white/[0.08] bg-[#111113] text-zinc-300 text-[10px] font-bold"
                            >
                              <option value="core">Core</option>
                              <option value="stretch">Stretch</option>
                            </select>

                            <button
                              type="button"
                              onClick={() => handleRemoveExpectation(sIdx, eIdx)}
                              className="p-1 text-zinc-500 hover:text-rose-400"
                            >
                              <Trash2 className="w-3 h-3" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* 2. Questions (Anchor, Escalation, Probes) */}
                    <div className="space-y-3 pt-2 border-t border-white/[0.08]">
                      <div className="flex items-center justify-between">
                        <label className="font-bold text-zinc-300 text-[11px] uppercase tracking-wider">
                          Questions & Probing Tree
                        </label>
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => handleAddRecruiterAnchor(sIdx)}
                            className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-400 hover:underline"
                          >
                            <Plus className="w-3 h-3" />
                            <span>Add My Custom Anchor</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleAddProbe(sIdx)}
                            className="inline-flex items-center gap-1 text-[11px] font-bold text-teal-400 hover:underline"
                          >
                            <Plus className="w-3 h-3" />
                            <span>Add Probe</span>
                          </button>
                        </div>
                      </div>

                      <div className="space-y-2.5">
                        {sec.questions?.map((q, qIdx) => {
                          const isAnchor = q.question_role === 'anchor';
                          const isEsc = q.question_role === 'escalation';

                          return (
                            <div
                              key={q.id || qIdx}
                              className={`p-3 rounded-2xl border space-y-2 ${
                                isAnchor
                                  ? 'bg-teal-500/10 border-teal-500/30'
                                  : isEsc
                                  ? 'bg-purple-950/20 border-purple-900/60'
                                  : 'bg-[#111113] border-white/[0.08]'
                              }`}
                            >
                              <div className="flex items-center justify-between">
                                <div className="flex items-center gap-1.5">
                                  <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${
                                    isAnchor
                                      ? 'bg-teal-500 text-black'
                                      : isEsc
                                      ? 'bg-purple-600 text-white'
                                      : 'bg-[#27272A] text-zinc-300'
                                  }`}>
                                    {q.question_role}
                                  </span>

                                  {q.source === 'recruiter' && (
                                    <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">
                                      Recruiter Authored
                                    </span>
                                  )}
                                </div>

                                {!isAnchor && (
                                  <button
                                    type="button"
                                    onClick={() => handleRemoveQuestion(sIdx, qIdx)}
                                    className="p-1 text-zinc-500 hover:text-rose-400"
                                  >
                                    <Trash2 className="w-3 h-3" />
                                  </button>
                                )}
                              </div>

                              <textarea
                                rows={2}
                                value={q.question_text}
                                onChange={(e) => handleUpdateQuestion(sIdx, qIdx, 'question_text', e.target.value)}
                                onBlur={() => saveSections(blueprint.sections)}
                                className="w-full p-2.5 rounded-xl bg-[#18181B] border border-white/[0.08] text-xs text-white focus:outline-none focus:border-teal-500/50"
                              />

                              {q.question_role === 'probe' && (
                                <div className="flex items-center gap-2">
                                  <span className="text-[10px] font-bold text-amber-400 whitespace-nowrap">
                                    Trigger Condition:
                                  </span>
                                  <input
                                    type="text"
                                    value={q.trigger_condition || ''}
                                    placeholder="e.g. If candidate skips memory bounds or trade-offs"
                                    onChange={(e) => handleUpdateQuestion(sIdx, qIdx, 'trigger_condition', e.target.value)}
                                    onBlur={() => saveSections(blueprint.sections)}
                                    className="flex-1 px-2.5 py-1 rounded-lg bg-[#18181B] border border-white/[0.08] text-[11px] text-white focus:outline-none focus:border-teal-500/50"
                                  />
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })
          )}
        </div>
      )}

      {/* Bottom Sticky Action Strip */}
      <div className="sticky bottom-0 p-4 rounded-3xl bg-[#0A0A0B]/95 backdrop-blur-md border border-white/[0.08] shadow-2xl flex items-center justify-between gap-4">
        <div className="text-xs text-slate-500 dark:text-slate-400">
          {saving ? (
            <span className="inline-flex items-center gap-1.5 text-teal-400 font-semibold">
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              <span>Saving changes (Copy-on-write)...</span>
            </span>
          ) : isLive ? (
            <span className="text-emerald-400 font-semibold flex items-center gap-1">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
              <span>Approved & Live for Applications</span>
            </span>
          ) : blueprint.status === 'approved' && validatorErrors.length > 0 ? (
            <span className="text-rose-400 font-semibold flex items-center gap-1">
              <AlertCircle className="w-3.5 h-3.5 text-rose-400" />
              <span>Approved with Unresolved Validation Errors — Requires Repair & Re-Approval</span>
            </span>
          ) : (
            <span>Edits are saved as draft. Approval is required before candidates can apply.</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-zinc-400 hover:bg-[#18181B]"
            >
              Close
            </button>
          )}

          <button
            type="button"
            disabled={saving || validatorErrors.length > 0}
            onClick={() => (validatorWarnings.length > 0 ? setConfirmWarningModal(true) : handleApprove(false))}
            className={`inline-flex items-center gap-2 px-6 py-2.5 rounded-xl font-bold text-xs shadow-md transition-all ${
              validatorErrors.length > 0
                ? 'bg-[#18181B] text-zinc-500 cursor-not-allowed'
                : 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-600/20 hover:-translate-y-0.5'
            }`}
          >
            <Check className="w-4 h-4" />
            <span>{blueprint.status === 'approved' && !blueprint.is_stale ? 'Re-Approve Blueprint' : 'Approve Blueprint & Enable Apply'}</span>
          </button>
        </div>
      </div>

      {/* Warning Confirmation Modal */}
      {confirmWarningModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fadeIn">
          <div className="w-full max-w-lg p-6 rounded-3xl bg-[#0A0A0B] border border-amber-500/40 shadow-2xl space-y-4">
            <div className="flex items-center gap-3 text-amber-400">
              <AlertTriangle className="w-6 h-6 flex-shrink-0" />
              <h3 className="text-base font-extrabold text-white">
                Acknowledge Blueprint Warnings
              </h3>
            </div>
            <p className="text-xs text-zinc-400 leading-relaxed">
              The blueprint generator or validator surfaced the following non-blocking warnings:
            </p>
            <div className="max-h-40 overflow-y-auto p-3 rounded-2xl bg-amber-950/20 border border-amber-900/40 text-xs text-amber-300 space-y-1">
              {validatorWarnings.map((w, idx) => (
                <div key={idx} className="flex items-start gap-1.5">
                  <span>•</span>
                  <span>{w}</span>
                </div>
              ))}
            </div>
            <p className="text-xs text-zinc-400 font-medium">
              You can confirm and approve the blueprint anyway, or return to edit the sections.
            </p>
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setConfirmWarningModal(false)}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-zinc-400 hover:bg-[#18181B]"
              >
                Return to Editor
              </button>
              <button
                type="button"
                onClick={() => handleApprove(true)}
                className="px-5 py-2 rounded-xl bg-amber-600 hover:bg-amber-500 text-white font-bold text-xs shadow-md shadow-amber-600/20"
              >
                Confirm & Approve Blueprint
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
