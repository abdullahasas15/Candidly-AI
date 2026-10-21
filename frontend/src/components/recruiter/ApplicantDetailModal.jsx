import React, { useState, useEffect } from 'react';
import {
  X, CheckCircle2, AlertTriangle, Clock, ShieldCheck, Download,
  ExternalLink, Mail, Phone, Calendar, DollarSign, Award, Briefcase,
  Layers, Check, ChevronRight, ChevronDown, UserCheck, RefreshCw, FileText,
  Sparkles, Code, FolderGit2, GraduationCap, BarChart3, Edit3, Save,
  RotateCcw, ThumbsUp, ThumbsDown, PauseCircle, Play, Eye
} from 'lucide-react';
import { formatMoney as formatCurrency } from '../../utils/currency';

function parseLevelNumber(lvl) {
  if (!lvl) return 0;
  if (typeof lvl === 'number') return lvl;
  const match = String(lvl).match(/L?([1-5])/i);
  return match ? parseInt(match[1], 10) : 0;
}

export default function ApplicantDetailModal({
  application,
  isOpen,
  onClose,
  onApplicationUpdated
}) {
  if (!isOpen || !application) return null;

  const [currentApp, setCurrentApp] = useState(application);
  const [activeTab, setActiveTab] = useState('scorecard'); // default to scorecard for fast review
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [togglingFlagId, setTogglingFlagId] = useState(null);
  const [actionError, setActionError] = useState(null);

  // Scorecard state
  const [scorecard, setScorecard] = useState(null);
  const [loadingScorecard, setLoadingScorecard] = useState(false);
  const [evaluatingNow, setEvaluatingNow] = useState(false);
  const [highlightedTurnId, setHighlightedTurnId] = useState(null);
  const [recruiterDecision, setRecruiterDecision] = useState(application.recruiter_decision || '');
  const [recruiterNotes, setRecruiterNotes] = useState(application.recruiter_notes || '');
  const [savingDecision, setSavingDecision] = useState(false);
  const [expandedSkills, setExpandedSkills] = useState({});
  const [integrityOpen, setIntegrityOpen] = useState(false);

  // Interview Plan state
  const [planData, setPlanData] = useState(null);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [approvingPlan, setApprovingPlan] = useState(false);
  const [regeneratingPlan, setRegeneratingPlan] = useState(false);
  const [editingQuestionId, setEditingQuestionId] = useState(null);
  const [editQuestionText, setEditQuestionText] = useState('');
  const [editKeyPoints, setEditKeyPoints] = useState('');
  const [savingQuestion, setSavingQuestion] = useState(false);

  const statusOptions = [
    { value: 'submitted', label: 'Submitted' },
    { value: 'under_review', label: 'Under Review' },
    { value: 'ready_for_interview', label: 'Ready for Interview' },
    { value: 'interviewed', label: 'Interviewed' },
    { value: 'rejected', label: 'Rejected' },
    { value: 'hired', label: 'Hired' }
  ];

  const getAuthHeaders = () => {
    const token = localStorage.getItem('candidly-auth-token');
    return {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'Content-Type': 'application/json',
    };
  };

  const fetchScorecard = async () => {
    if (!currentApp?.id) return;
    setLoadingScorecard(true);
    try {
      const res = await fetch(`/api/applications/${currentApp.id}/scorecard`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setScorecard(data);
        if (data.recruiter_decision?.recruiter_decision) {
          setRecruiterDecision(data.recruiter_decision.recruiter_decision);
          setRecruiterNotes(data.recruiter_decision.recruiter_notes || '');
        }
      }
    } catch (e) {
      console.warn('Error loading scorecard:', e);
    } finally {
      setLoadingScorecard(false);
    }
  };

  const fetchPlan = async () => {
    if (!currentApp?.id) return;
    setLoadingPlan(true);
    try {
      const res = await fetch(`/api/applications/${currentApp.id}/interview-plan`, {
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setPlanData(data);
      }
    } catch (e) {
      console.warn('Error loading plan:', e);
    } finally {
      setLoadingPlan(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'scorecard' && !scorecard) {
      fetchScorecard();
    } else if (activeTab === 'plan' && !planData) {
      fetchPlan();
    }
  }, [activeTab, currentApp?.id]);

  const handleTriggerEvaluate = async () => {
    setEvaluatingNow(true);
    setActionError(null);
    try {
      const res = await fetch(`/api/applications/${currentApp.id}/evaluate`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      if (!res.ok) {
        const p = await res.json().catch(() => ({}));
        throw new Error(p.detail || 'Evaluation failed');
      }
      await fetchScorecard();
    } catch (err) {
      setActionError(err.message);
    } finally {
      setEvaluatingNow(false);
    }
  };

  const handleSaveDecision = async () => {
    setSavingDecision(true);
    setActionError(null);
    try {
      const res = await fetch(`/api/applications/${currentApp.id}/decision`, {
        method: 'PATCH',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          decision: recruiterDecision,
          notes: recruiterNotes,
        }),
      });
      if (!res.ok) throw new Error('Failed to record decision');
      const updated = await res.json();
      setCurrentApp((prev) => ({
        ...prev,
        recruiter_decision: updated.recruiter_decision,
        recruiter_notes: updated.recruiter_notes,
      }));
      if (onApplicationUpdated) onApplicationUpdated(updated);
    } catch (err) {
      setActionError(err.message);
    } finally {
      setSavingDecision(false);
    }
  };

  const handleApprovePlan = async () => {
    setApprovingPlan(true);
    setActionError(null);
    try {
      const res = await fetch(`/api/applications/${currentApp.id}/interview-plan/approve`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      if (!res.ok) throw new Error('Failed to approve interview plan');
      await fetchPlan();
    } catch (err) {
      setActionError(err.message);
    } finally {
      setApprovingPlan(false);
    }
  };

  const handleRegeneratePlan = async () => {
    setRegeneratingPlan(true);
    setActionError(null);
    try {
      const res = await fetch(`/api/applications/${currentApp.id}/interview-plan/regenerate`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      if (!res.ok) throw new Error('Failed to regenerate interview plan');
      await fetchPlan();
    } catch (err) {
      setActionError(err.message);
    } finally {
      setRegeneratingPlan(false);
    }
  };

  const handleStartEditQuestion = (q) => {
    setEditingQuestionId(q.id);
    setEditQuestionText(q.question_text || '');
    setEditKeyPoints((q.expected_key_points || []).join('\n'));
  };

  const handleSaveQuestion = async (qid) => {
    setSavingQuestion(true);
    setActionError(null);
    try {
      const points = editKeyPoints
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await fetch(`/api/applications/${currentApp.id}/interview-plan/questions/${qid}`, {
        method: 'PATCH',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          question_text: editQuestionText,
          expected_key_points: points,
        }),
      });
      if (!res.ok) throw new Error('Failed to save question edit');
      setEditingQuestionId(null);
      await fetchPlan();
    } catch (err) {
      setActionError(err.message);
    } finally {
      setSavingQuestion(false);
    }
  };

  const handleStatusChange = async (newStatus) => {
    setUpdatingStatus(true);
    setActionError(null);
    try {
      const res = await fetch(`/api/applications/${currentApp.id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error('Failed to update applicant status');
      const updated = await res.json();
      setCurrentApp(updated);
      if (onApplicationUpdated) onApplicationUpdated(updated);
    } catch (err) {
      setActionError(err.message);
    } finally {
      setUpdatingStatus(false);
    }
  };

  const handleToggleFlag = async (flagId) => {
    setTogglingFlagId(flagId);
    setActionError(null);
    try {
      const res = await fetch(`/api/applications/${currentApp.id}/discrepancies/${flagId}`, {
        method: 'PATCH'
      });
      if (!res.ok) throw new Error('Failed to toggle discrepancy flag');
      const updatedFlag = await res.json();

      setCurrentApp((prev) => ({
        ...prev,
        discrepancy_flags: prev.discrepancy_flags.map((f) =>
          f.id === flagId ? { ...f, reviewed_by_recruiter: updatedFlag.reviewed_by_recruiter } : f
        )
      }));

      if (onApplicationUpdated) {
        onApplicationUpdated({
          ...currentApp,
          discrepancy_flags: currentApp.discrepancy_flags.map((f) =>
            f.id === flagId ? { ...f, reviewed_by_recruiter: updatedFlag.reviewed_by_recruiter } : f
          )
        });
      }
    } catch (err) {
      setActionError(err.message);
    } finally {
      setTogglingFlagId(null);
    }
  };

  const toggleSkillExpand = (id) => {
    setExpandedSkills((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const resume = currentApp.resume;
  const structuredData = resume?.parsed_structured_data || {};
  const workExp = structuredData.work_experience || [];
  const education = structuredData.education || [];
  const certs = structuredData.certifications || [];
  const projects = structuredData.projects || [];
  const skills = structuredData.skills || [];
  const categorizedSkills = structuredData.skills_by_category || {};
  const totalResumeExp = structuredData.total_experience_years || 0.0;
  const flags = currentApp.discrepancy_flags || [];

  // Audio recording URL if exists in API response
  const recordingUrl =
    scorecard?.session?.recording_url ||
    scorecard?.recording_url ||
    currentApp?.recording_url ||
    null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-sm animate-fadeIn">
      <div className="relative w-full max-w-5xl max-h-[92vh] flex flex-col rounded-2xl bg-[#0A0A0B] border border-white/[0.08] shadow-2xl overflow-hidden">
        {actionError && (
          <div className="mx-6 mt-4 rounded-xl border border-rose-500/30 bg-rose-950/40 px-4 py-3 text-xs font-semibold text-rose-300">
            {actionError}
          </div>
        )}

        {/* Header Strip */}
        <div className="p-6 bg-[#0A0A0B] border-b border-white/[0.08] flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] font-mono uppercase tracking-wider text-teal-400">
                Applicant Dossier
              </span>
              <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-white/[0.05] text-zinc-400 border border-white/[0.06]">
                Applied {new Date(currentApp.applied_at).toLocaleDateString()}
              </span>
              {flags.some((f) => !f.reviewed_by_recruiter) && (
                <span className="text-[11px] font-medium px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20 flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" />
                  <span>Unresolved Discrepancies</span>
                </span>
              )}
            </div>

            <h2 className="text-2xl font-bold font-display tracking-tight text-white">
              {currentApp.full_name}
            </h2>

            <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-400">
              <span className="flex items-center gap-1">
                <Mail className="w-3.5 h-3.5 text-zinc-500" />
                <span>{currentApp.email}</span>
              </span>
              {currentApp.phone && (
                <span className="flex items-center gap-1">
                  <Phone className="w-3.5 h-3.5 text-zinc-500" />
                  <span>{currentApp.phone}</span>
                </span>
              )}
              {currentApp.linkedin_url && (
                <a
                  href={currentApp.linkedin_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-teal-400 hover:text-teal-300 hover:underline flex items-center gap-1"
                >
                  <span>LinkedIn</span>
                  <ExternalLink className="w-3 h-3" />
                </a>
              )}
              {currentApp.portfolio_url && (
                <a
                  href={currentApp.portfolio_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-teal-400 hover:text-teal-300 hover:underline flex items-center gap-1"
                >
                  <span>Portfolio/GitHub</span>
                  <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2.5 self-start sm:self-auto">
            {/* Status Selector */}
            <select
              value={currentApp.status}
              disabled={updatingStatus}
              onChange={(e) => handleStatusChange(e.target.value)}
              className="px-3 py-1.5 text-xs font-medium rounded-lg border border-white/[0.12] bg-[#111113] text-zinc-200 focus:outline-none focus:border-teal-400"
            >
              {statusOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  Status: {opt.label}
                </option>
              ))}
            </select>

            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/[0.05] transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Tab Navigation Strip */}
        <div className="flex border-b border-white/[0.08] px-6 bg-[#0A0A0B] text-xs font-medium gap-2">
          <button
            type="button"
            onClick={() => setActiveTab('scorecard')}
            className={`py-3 px-3 border-b-2 transition-all flex items-center gap-1.5 ${
              activeTab === 'scorecard'
                ? 'border-teal-400 text-teal-400 bg-white/[0.02]'
                : 'border-transparent text-zinc-400 hover:text-white'
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Evaluation Scorecard & Evidence</span>
            {currentApp.interview_session_status === 'completed' && (
              <span className="w-1.5 h-1.5 rounded-full bg-teal-400" />
            )}
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('dossier')}
            className={`py-3 px-3 border-b-2 transition-all flex items-center gap-1.5 ${
              activeTab === 'dossier'
                ? 'border-teal-400 text-teal-400 bg-white/[0.02]'
                : 'border-transparent text-zinc-400 hover:text-white'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Applicant Dossier</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('plan')}
            className={`py-3 px-3 border-b-2 transition-all flex items-center gap-1.5 ${
              activeTab === 'plan'
                ? 'border-teal-400 text-teal-400 bg-white/[0.02]'
                : 'border-transparent text-zinc-400 hover:text-white'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Calibrated Interview Plan</span>
          </button>
        </div>

        {/* Scrollable Body */}
        <div className="p-6 overflow-y-auto space-y-6 flex-1 text-xs">
          
          {/* TAB 1: EVALUATION SCORECARD */}
          {activeTab === 'scorecard' && (
            <div className="space-y-6">
              {loadingScorecard && (
                <div className="py-16 text-center space-y-2">
                  <RefreshCw className="w-6 h-6 animate-spin text-teal-400 mx-auto" />
                  <p className="text-zinc-400">Loading interview evaluation scorecard...</p>
                </div>
              )}

              {!loadingScorecard && !scorecard?.evaluation && (
                <div className="p-10 rounded-2xl bg-[#111113] border border-white/[0.08] text-center space-y-4">
                  <BarChart3 className="w-10 h-10 text-zinc-500 mx-auto" />
                  <h4 className="text-base font-semibold text-white">
                    No Evaluation Scorecard Available
                  </h4>
                  <p className="text-xs text-zinc-400 max-w-md mx-auto">
                    {currentApp.interview_session_status === 'completed'
                      ? 'The interview has completed. Click below to run the Evidence-Anchored Judge evaluation.'
                      : 'The candidate has not completed their live voice interview yet. The scorecard will generate automatically upon session completion.'}
                  </p>
                  <button
                    type="button"
                    disabled={evaluatingNow}
                    onClick={handleTriggerEvaluate}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-teal-500 hover:bg-teal-400 text-black font-semibold text-xs shadow-md transition-all cursor-pointer disabled:opacity-50"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>{evaluatingNow ? 'Running Gemini Judge Evaluation...' : 'Run Judge Evaluation Now'}</span>
                  </button>
                </div>
              )}

              {!loadingScorecard && scorecard?.evaluation && (
                <div className="space-y-6">
                  {/* Scorecard Hero: Large Serif Overall Score & Recommendation Badge */}
                  <div className="p-6 rounded-2xl bg-[#111113] border border-white/[0.08] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6">
                    <div className="space-y-2 max-w-2xl">
                      <div className="flex flex-wrap items-center gap-2">
                        {/* Recommendation Badge */}
                        <span
                          className={`px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider border ${
                            scorecard.evaluation.verdict?.includes('HIRE') && !scorecard.evaluation.verdict?.includes('NO')
                              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                              : scorecard.evaluation.verdict === 'BORDERLINE'
                              ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                              : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                          }`}
                        >
                          Recommendation: {scorecard.evaluation.verdict?.replace(/_/g, ' ') || 'UNDECIDED'}
                        </span>

                        {scorecard.evaluation.confidence_level && (
                          <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-white/[0.05] text-zinc-400 border border-white/[0.06]">
                            Confidence: {scorecard.evaluation.confidence_level}
                          </span>
                        )}
                      </div>

                      {scorecard.evaluation.summary_rationale && (
                        <p className="text-xs text-zinc-300 leading-relaxed pt-1">
                          {scorecard.evaluation.summary_rationale}
                        </p>
                      )}
                    </div>

                    {/* Large Serif Overall Score */}
                    <div className="text-left sm:text-right shrink-0 border-t sm:border-t-0 sm:border-l border-white/[0.08] sm:pl-6 pt-3 sm:pt-0">
                      <div className="text-[10px] font-mono uppercase tracking-wider text-zinc-400">
                        Overall Score
                      </div>
                      <div className="flex items-baseline gap-1 mt-1">
                        <span className="font-display text-5xl sm:text-6xl text-white font-normal">
                          {scorecard.evaluation.overall_score !== null && scorecard.evaluation.overall_score !== undefined
                            ? Math.round(scorecard.evaluation.overall_score)
                            : '—'}
                        </span>
                        <span className="text-zinc-500 text-lg font-mono">/100</span>
                      </div>
                    </div>
                  </div>

                  {/* Audio Replay Bar if recording URL exists */}
                  {recordingUrl && (
                    <div className="p-4 rounded-xl bg-[#111113] border border-white/[0.08] space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-xs font-semibold text-zinc-200">
                          <Play className="w-3.5 h-3.5 text-teal-400" />
                          <span>Interview Audio Replay</span>
                        </div>
                        <a
                          href={recordingUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[11px] text-teal-400 hover:text-teal-300 hover:underline flex items-center gap-1 font-mono"
                        >
                          <span>Open audio file</span>
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      </div>
                      <audio controls src={recordingUrl} className="w-full h-8 accent-teal-400" />
                    </div>
                  )}

                  {/* Insufficient Evidence Warning Banner */}
                  {scorecard.evaluation.insufficient_evidence && (
                    <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/25 text-amber-300 flex items-start gap-3">
                      <AlertTriangle className="w-4 h-4 shrink-0 text-amber-400 mt-0.5" />
                      <div className="space-y-0.5 text-xs">
                        <strong className="font-semibold text-amber-200">Insufficient Evidence Warning:</strong>
                        <p className="text-amber-300/90">
                          One or more mandatory (P0) competencies could not be validated with verbatim transcript evidence (rated NOT_ASSESSED). Overall verdict is capped at LEAN_NO_HIRE per policy.
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Key Strengths & Concerns */}
                  {(scorecard.evaluation.key_strengths?.length > 0 || scorecard.evaluation.key_concerns?.length > 0) && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      {scorecard.evaluation.key_strengths && scorecard.evaluation.key_strengths.length > 0 && (
                        <div className="p-4 rounded-xl bg-[#111113] border border-emerald-500/20 space-y-2">
                          <div className="font-semibold text-emerald-400 text-xs flex items-center gap-1.5">
                            <ThumbsUp className="w-3.5 h-3.5" />
                            <span>Key Strengths</span>
                          </div>
                          <ul className="list-disc pl-4 space-y-1 text-zinc-300 text-xs">
                            {scorecard.evaluation.key_strengths.map((s, i) => (
                              <li key={i}>{s}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {scorecard.evaluation.key_concerns && scorecard.evaluation.key_concerns.length > 0 && (
                        <div className="p-4 rounded-xl bg-[#111113] border border-rose-500/20 space-y-2">
                          <div className="font-semibold text-rose-400 text-xs flex items-center gap-1.5">
                            <ThumbsDown className="w-3.5 h-3.5" />
                            <span>Key Concerns / Uncovered Points</span>
                          </div>
                          <ul className="list-disc pl-4 space-y-1 text-zinc-300 text-xs">
                            {scorecard.evaluation.key_concerns.map((c, i) => (
                              <li key={i}>{c}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Per-Skill Score Breakdown with L1-L5 bar, one-line rationale, and expandable evidence */}
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <h4 className="text-xs font-mono uppercase tracking-wider text-zinc-400">
                        Assessed Competencies & Skill Ratings
                      </h4>
                      <span className="text-[11px] text-zinc-500">
                        {scorecard.skill_scores?.length || 0} evaluated skills
                      </span>
                    </div>

                    <div className="space-y-3">
                      {(scorecard.skill_scores || []).map((skill) => {
                        const lvlNum = parseLevelNumber(skill.score_level);
                        const isExpanded = !!expandedSkills[skill.skill_id];
                        const quoteCount = skill.evidence_quotes?.length || 0;

                        return (
                          <div
                            key={skill.skill_id}
                            className="p-4 rounded-xl bg-[#111113] border border-white/[0.08] space-y-3 transition-colors hover:border-white/[0.12]"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div className="flex items-center gap-2">
                                <span
                                  className={`px-2 py-0.5 rounded text-[10px] font-mono font-semibold ${
                                    skill.priority_tier === 'P0'
                                      ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                                      : 'bg-white/[0.05] text-zinc-300 border border-white/[0.08]'
                                  }`}
                                >
                                  {skill.priority_tier || 'P1'}
                                </span>
                                <span className="font-semibold text-white text-sm">
                                  {skill.skill_name}
                                </span>
                                {skill.weight_percentage !== undefined && (
                                  <span className="text-zinc-500 text-xs font-mono">({skill.weight_percentage}%)</span>
                                )}
                              </div>

                              {/* L1-L5 Segmented Bar */}
                              <div className="flex items-center gap-2">
                                <div className="flex items-center gap-1" title={`Level: ${skill.score_level}`}>
                                  {[1, 2, 3, 4, 5].map((idx) => {
                                    const filled = lvlNum >= idx;
                                    return (
                                      <div
                                        key={idx}
                                        className={`h-2 w-5 sm:w-6 rounded-sm transition-all ${
                                          filled
                                            ? lvlNum >= 4
                                              ? 'bg-teal-400'
                                              : lvlNum >= 3
                                              ? 'bg-teal-500'
                                              : 'bg-amber-400'
                                            : 'bg-white/[0.08]'
                                        }`}
                                      />
                                    );
                                  })}
                                </div>
                                <span className="font-mono text-xs font-semibold text-zinc-300 min-w-8 text-right">
                                  {skill.score_level || 'N/A'}
                                </span>
                              </div>
                            </div>

                            {/* One-line rationale */}
                            {skill.rationale && (
                              <p className="text-xs text-zinc-300 leading-relaxed">
                                {skill.rationale}
                              </p>
                            )}

                            {/* Expandable Evidence Section */}
                            <div className="pt-2 border-t border-white/[0.06]">
                              <button
                                type="button"
                                onClick={() => toggleSkillExpand(skill.skill_id)}
                                className="flex items-center justify-between w-full text-left py-1 text-[11px] font-medium text-zinc-400 hover:text-teal-400 transition-colors"
                              >
                                <span>
                                  Anchored Verbatim Evidence ({quoteCount} quote{quoteCount === 1 ? '' : 's'})
                                </span>
                                <div className="flex items-center gap-1">
                                  <span className="text-[10px] text-zinc-500 font-mono">
                                    {isExpanded ? 'Hide' : 'Show'}
                                  </span>
                                  <ChevronDown
                                    className={`w-3.5 h-3.5 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                                  />
                                </div>
                              </button>

                              {isExpanded && (
                                <div className="mt-2 space-y-2">
                                  {quoteCount === 0 ? (
                                    <div className="p-2.5 rounded-lg bg-black/40 border border-white/[0.04] text-[11px] text-zinc-500 italic">
                                      Zero transcript quotes verified for this competency.
                                    </div>
                                  ) : (
                                    skill.evidence_quotes.map((eq, qIdx) => (
                                      <div
                                        key={qIdx}
                                        className="p-3 rounded-lg bg-black/40 border border-white/[0.06] flex flex-col sm:flex-row sm:items-center justify-between gap-2"
                                      >
                                        <div className="text-xs text-zinc-300 italic">
                                          "{eq.quote}"
                                        </div>
                                        <div className="flex items-center gap-2 shrink-0">
                                          {eq.timestamp && (
                                            <span className="text-[10px] font-mono text-zinc-500 flex items-center gap-1">
                                              <Clock className="w-3 h-3" />
                                              {eq.timestamp}
                                            </span>
                                          )}
                                          {eq.turn_id && (
                                            <button
                                              type="button"
                                              onClick={() => {
                                                setHighlightedTurnId(eq.turn_id);
                                                const el = document.getElementById(`turn-${eq.turn_id}`);
                                                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                              }}
                                              className="text-[10px] font-mono text-teal-400 hover:underline hover:text-teal-300 cursor-pointer"
                                            >
                                              Jump to turn →
                                            </button>
                                          )}
                                        </div>
                                      </div>
                                    ))
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Transcript Timeline: Question Left, Answer Right */}
                  <div className="space-y-3 pt-2">
                    <div className="flex items-center justify-between">
                      <h4 className="text-xs font-mono uppercase tracking-wider text-zinc-400">
                        Full Interview Transcript ({scorecard.transcript_turns?.length || 0} Turns)
                      </h4>
                      <span className="text-[11px] text-zinc-500">
                        AI left · Candidate right
                      </span>
                    </div>

                    <div className="space-y-3 max-h-[480px] overflow-y-auto p-2 rounded-xl bg-black/40 border border-white/[0.06]">
                      {(scorecard.transcript_turns || []).length === 0 ? (
                        <div className="p-8 text-center text-zinc-500 text-xs">
                          No transcript turns recorded for this interview session.
                        </div>
                      ) : (
                        (scorecard.transcript_turns || []).map((turn) => {
                          const isAI = turn.speaker === 'ai';
                          const isHighlighted = highlightedTurnId === turn.id;

                          return (
                            <div
                              key={turn.id}
                              id={`turn-${turn.id}`}
                              className={`p-3.5 rounded-xl border transition-all ${
                                isHighlighted
                                  ? 'ring-2 ring-teal-400/50 border-teal-400/80 bg-teal-950/20'
                                  : isAI
                                  ? 'bg-[#111113] border-white/[0.08] mr-6 sm:mr-16'
                                  : 'bg-[#18181B] border-white/[0.12] ml-6 sm:ml-16'
                              }`}
                            >
                              <div className="flex items-center justify-between text-[11px] mb-1.5 gap-2">
                                <div className="flex items-center gap-2">
                                  <span className="font-semibold text-xs text-white">
                                    {isAI ? '🤖 AI Interviewer' : '👤 Candidate'}
                                  </span>
                                  {turn.turn_index !== undefined && (
                                    <span className="font-mono text-zinc-500 text-[10px]">
                                      #{turn.turn_index}
                                    </span>
                                  )}
                                  {turn.target_skill_name && (
                                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-teal-500/10 text-teal-300 border border-teal-500/20">
                                      {turn.target_skill_name}
                                    </span>
                                  )}
                                </div>

                                <div className="flex items-center gap-2">
                                  {turn.was_interrupted && (
                                    <span className="rounded bg-rose-500/20 px-1.5 py-0.5 text-[9px] font-semibold text-rose-300 border border-rose-500/30">
                                      Interrupted
                                    </span>
                                  )}
                                  {turn.total_response_ms && (
                                    <span className="font-mono text-[10px] text-zinc-500">
                                      {turn.total_response_ms}ms
                                    </span>
                                  )}
                                </div>
                              </div>

                              <p className="text-xs text-zinc-200 leading-relaxed whitespace-pre-wrap">
                                {turn.content}
                              </p>

                              {turn.was_interrupted && turn.spoken_text && (
                                <p className="mt-1 text-[11px] text-zinc-400 italic">
                                  Spoken before cut-off: "{turn.spoken_text}"
                                </p>
                              )}
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>

                  {/* Integrity Signal Audit as a Small Collapsed Section */}
                  <div className="rounded-xl border border-white/[0.08] bg-[#111113] overflow-hidden">
                    <button
                      type="button"
                      onClick={() => setIntegrityOpen(!integrityOpen)}
                      className="w-full p-4 flex items-center justify-between text-left hover:bg-white/[0.02] transition-colors"
                    >
                      <div className="flex items-center gap-2.5">
                        <ShieldCheck className="w-4 h-4 text-teal-400" />
                        <span className="text-xs font-semibold text-white">
                          Integrity Signal Audit
                        </span>
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/[0.05] text-zinc-400 border border-white/[0.06]">
                          {scorecard.integrity_events?.length || 0} Events
                        </span>
                      </div>

                      <div className="flex items-center gap-2">
                        {(!scorecard.integrity_events || scorecard.integrity_events.length === 0) ? (
                          <span className="text-[11px] text-teal-400 font-medium">
                            Clean Session ✓
                          </span>
                        ) : (
                          <span className="text-[11px] text-amber-400 font-medium">
                            Flags Recorded
                          </span>
                        )}
                        <ChevronDown
                          className={`w-3.5 h-3.5 text-zinc-400 transition-transform ${
                            integrityOpen ? 'rotate-180' : ''
                          }`}
                        />
                      </div>
                    </button>

                    {integrityOpen && (
                      <div className="p-4 pt-0 border-t border-white/[0.06] space-y-2 mt-2">
                        {(!scorecard.integrity_events || scorecard.integrity_events.length === 0) ? (
                          <div className="p-3 rounded-lg bg-teal-500/10 border border-teal-500/20 text-teal-300 text-xs flex items-center gap-2">
                            <CheckCircle2 className="w-4 h-4 shrink-0" />
                            <span>Clean session: No tab switches, clipboard paste, or webcam occlusion events logged.</span>
                          </div>
                        ) : (
                          <div className="space-y-1.5">
                            {scorecard.integrity_events.map((evt) => (
                              <div
                                key={evt.id}
                                className="p-2.5 rounded-lg bg-black/40 border border-white/[0.06] flex items-center justify-between text-xs"
                              >
                                <div className="flex items-center gap-2">
                                  <span
                                    className={`px-1.5 py-0.5 rounded text-[10px] font-mono uppercase ${
                                      evt.severity === 'critical'
                                        ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                                        : evt.severity === 'warning'
                                        ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                                        : 'bg-white/[0.05] text-zinc-300'
                                    }`}
                                  >
                                    {evt.severity || 'info'}
                                  </span>
                                  <span className="font-medium text-zinc-200">
                                    {evt.event_type}
                                  </span>
                                </div>
                                {evt.occurred_at && (
                                  <span className="text-[10px] font-mono text-zinc-500">
                                    {new Date(evt.occurred_at).toLocaleTimeString()}
                                  </span>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Recruiter Decision & Next Steps */}
                  <div className="p-5 rounded-2xl bg-[#111113] border border-white/[0.08] space-y-3">
                    <h4 className="text-xs font-mono uppercase tracking-wider text-zinc-400">
                      Recruiter Decision & Next Steps
                    </h4>

                    <div className="flex items-center gap-2">
                      {[
                        { id: 'advance', label: 'Advance', activeClass: 'bg-teal-500 text-black font-semibold' },
                        { id: 'hold', label: 'Hold', activeClass: 'bg-amber-500 text-black font-semibold' },
                        { id: 'reject', label: 'Reject', activeClass: 'bg-rose-500 text-white font-semibold' }
                      ].map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => setRecruiterDecision(item.id)}
                          className={`px-4 py-1.5 rounded-lg text-xs tracking-wider transition-all cursor-pointer ${
                            recruiterDecision === item.id
                              ? item.activeClass
                              : 'bg-white/[0.05] border border-white/[0.08] text-zinc-300 hover:text-white hover:bg-white/[0.08]'
                          }`}
                        >
                          {item.label}
                        </button>
                      ))}
                    </div>

                    <textarea
                      rows={2}
                      value={recruiterNotes}
                      onChange={(e) => setRecruiterNotes(e.target.value)}
                      placeholder="Add recruiter notes, debrief rationale, or next steps..."
                      className="w-full rounded-lg bg-black/40 border border-white/[0.12] p-2.5 text-xs text-white focus:outline-none focus:border-teal-400"
                    />

                    <div className="flex justify-end">
                      <button
                        type="button"
                        disabled={savingDecision}
                        onClick={handleSaveDecision}
                        className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-teal-500 hover:bg-teal-400 text-black font-semibold text-xs transition-colors cursor-pointer disabled:opacity-50"
                      >
                        <Save className="w-3.5 h-3.5" />
                        <span>{savingDecision ? 'Saving...' : 'Save Decision'}</span>
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 2: DOSSIER */}
          {activeTab === 'dossier' && (
            <div className="space-y-6">
              {/* Consistency Flags */}
              <div className="p-4 rounded-xl bg-[#111113] border border-white/[0.08] space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 font-semibold text-white">
                    <AlertTriangle className="w-4 h-4 text-amber-400" />
                    <span>Consistency & Verification Audit</span>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/[0.05] text-zinc-400 border border-white/[0.06]">
                    {flags.length} Checked Points
                  </span>
                </div>

                {flags.length === 0 ? (
                  <div className="p-3 rounded-lg bg-teal-500/10 border border-teal-500/20 text-teal-300 flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 shrink-0" />
                    <span>No discrepancies or timeline mismatches detected. Self-reported claims match resume evidence.</span>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {flags.map((flag) => (
                      <div
                        key={flag.id}
                        className={`p-3 rounded-lg border space-y-1.5 transition-colors ${
                          flag.reviewed_by_recruiter
                            ? 'bg-black/30 border-white/[0.06] opacity-60'
                            : 'bg-amber-500/10 border-amber-500/30'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold text-white text-xs">
                            {flag.flag_reason}
                          </span>
                          <button
                            type="button"
                            disabled={togglingFlagId === flag.id}
                            onClick={() => handleToggleFlag(flag.id)}
                            className={`px-2 py-0.5 rounded text-[10px] font-semibold transition-all shrink-0 ${
                              flag.reviewed_by_recruiter
                                ? 'bg-white/[0.08] text-zinc-300'
                                : 'bg-amber-500 text-black hover:bg-amber-400'
                            }`}
                          >
                            {flag.reviewed_by_recruiter ? 'Reviewed ✓' : 'Mark Reviewed'}
                          </button>
                        </div>

                        <div className="grid grid-cols-2 gap-2 text-[10px] pt-1 border-t border-white/[0.06]">
                          <div>
                            <span className="text-zinc-500">Candidate Stated:</span>{' '}
                            <strong className="text-zinc-200">{flag.candidate_stated_value || 'None'}</strong>
                          </div>
                          <div>
                            <span className="text-zinc-500">Resume Derived:</span>{' '}
                            <strong className="text-zinc-200">{flag.resume_derived_value || 'None'}</strong>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Work History */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-mono uppercase tracking-wider text-zinc-400 flex items-center gap-2">
                    <Briefcase className="w-3.5 h-3.5 text-teal-400" />
                    <span>Parsed Work History</span>
                  </h3>
                  <span className="text-xs font-mono text-teal-400">
                    {workExp.length} Roles · {totalResumeExp.toFixed(1)} yrs total
                  </span>
                </div>

                <div className="space-y-3">
                  {workExp.length === 0 ? (
                    <div className="p-4 rounded-xl bg-[#111113] border border-white/[0.08] text-center text-zinc-500">
                      No structured work history entries parsed.
                    </div>
                  ) : (
                    workExp.map((exp, idx) => (
                      <div
                        key={idx}
                        className="p-4 rounded-xl bg-[#111113] border border-white/[0.08] space-y-1.5"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="font-semibold text-white text-sm">
                            {exp.role || 'Role'} <span className="font-normal text-zinc-400">at</span> {exp.company || 'Company'}
                          </div>
                          <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-white/[0.05] border border-white/[0.08] text-zinc-300">
                            {exp.start_date} – {exp.end_date} {exp.duration_years ? `(${exp.duration_years.toFixed(1)}y)` : ''}
                          </span>
                        </div>
                        {(exp.description || (exp.highlights && exp.highlights.length > 0)) && (
                          <p className="text-zinc-300 text-xs pt-1">
                            {exp.description || exp.highlights.join('; ')}
                          </p>
                        )}
                        {exp.technologies && exp.technologies.length > 0 && (
                          <div className="flex flex-wrap gap-1 pt-1.5">
                            {exp.technologies.map((t, tIdx) => (
                              <span key={tIdx} className="px-2 py-0.5 rounded bg-black/40 border border-white/[0.08] text-zinc-300 text-[10px] font-mono">
                                {t}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Academic Credentials */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-mono uppercase tracking-wider text-zinc-400 flex items-center gap-2">
                    <GraduationCap className="w-3.5 h-3.5 text-teal-400" />
                    <span>Education Credentials</span>
                  </h3>
                  <span className="text-xs font-mono text-teal-400">
                    {education.length} Degrees
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {education.length === 0 ? (
                    <div className="p-3 rounded-xl bg-[#111113] border border-white/[0.08] text-zinc-500">
                      No education entries detected.
                    </div>
                  ) : (
                    education.map((edu, idx) => (
                      <div
                        key={idx}
                        className="p-4 rounded-xl bg-[#111113] border border-white/[0.08] space-y-1"
                      >
                        <div className="font-semibold text-white text-sm">{edu.degree}</div>
                        <div className="text-zinc-300">{edu.institution}</div>
                        {edu.field && (
                          <div className="text-zinc-500 text-[11px]">Major: {edu.field}</div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Technical Skills */}
              <div className="space-y-3">
                <h3 className="text-xs font-mono uppercase tracking-wider text-zinc-400 flex items-center gap-2">
                  <Code className="w-3.5 h-3.5 text-teal-400" />
                  <span>Technical Skills ({skills.length})</span>
                </h3>

                <div className="flex flex-wrap gap-1.5 p-3 rounded-xl bg-[#111113] border border-white/[0.08]">
                  {skills.map((s, idx) => (
                    <span
                      key={idx}
                      className="px-2.5 py-1 rounded-lg bg-black/40 border border-white/[0.08] text-zinc-200 text-xs font-mono"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: CALIBRATED INTERVIEW PLAN */}
          {activeTab === 'plan' && (
            <div className="space-y-6">
              {loadingPlan && (
                <div className="py-16 text-center space-y-2">
                  <RefreshCw className="w-6 h-6 animate-spin text-teal-400 mx-auto" />
                  <p className="text-zinc-400">Loading calibrated interview plan...</p>
                </div>
              )}

              {!loadingPlan && !planData && (
                <div className="p-8 rounded-2xl bg-[#111113] border border-white/[0.08] text-center space-y-3">
                  <Sparkles className="w-8 h-8 text-zinc-500 mx-auto" />
                  <h4 className="text-sm font-semibold text-white">Plan Not Generated Yet</h4>
                  <p className="text-xs text-zinc-400">
                    Interview plan questions are generated after candidate resume submission and verification.
                  </p>
                </div>
              )}

              {!loadingPlan && planData && (
                <div className="space-y-6">
                  {/* Status Banner */}
                  <div className="p-4 rounded-xl bg-[#111113] border border-white/[0.08] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono uppercase tracking-wider text-teal-400">
                          Interview Plan:
                        </span>
                        <span className="text-xs font-mono px-2 py-0.5 rounded bg-teal-500/10 text-teal-300 border border-teal-500/20">
                          {planData.status || 'Active'}
                        </span>
                      </div>
                      <p className="text-xs text-zinc-400 mt-1">
                        {planData.questions?.length || 0} questions calibrated for candidate resume and job requirements.
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        disabled={regeneratingPlan}
                        onClick={handleRegeneratePlan}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/[0.05] hover:bg-white/[0.1] text-zinc-300 font-medium text-xs transition-colors cursor-pointer disabled:opacity-50 border border-white/[0.08]"
                      >
                        <RotateCcw className={`w-3.5 h-3.5 ${regeneratingPlan ? 'animate-spin' : ''}`} />
                        <span>Regenerate Questions</span>
                      </button>

                      <button
                        type="button"
                        disabled={approvingPlan}
                        onClick={handleApprovePlan}
                        className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-teal-500 hover:bg-teal-400 text-black font-semibold text-xs shadow transition-colors cursor-pointer disabled:opacity-50"
                      >
                        <Check className="w-3.5 h-3.5" />
                        <span>Approve Plan</span>
                      </button>
                    </div>
                  </div>

                  {/* Interviewer Brief */}
                  {planData.interviewer_brief && (
                    <div className="p-4 rounded-xl bg-[#111113] border border-white/[0.08] space-y-1.5">
                      <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-400">
                        Interviewer Session Brief
                      </span>
                      <p className="text-xs text-zinc-300 whitespace-pre-line leading-relaxed">
                        {planData.interviewer_brief}
                      </p>
                    </div>
                  )}

                  {/* Questions List */}
                  <div className="space-y-3">
                    <h4 className="text-xs font-mono uppercase tracking-wider text-zinc-400">
                      Calibrated Questions & Expected Key Points
                    </h4>

                    <div className="space-y-3">
                      {(planData.questions || []).map((q, idx) => {
                        const isEditing = editingQuestionId === q.id;
                        return (
                          <div
                            key={q.id || idx}
                            className="p-4 rounded-xl bg-[#111113] border border-white/[0.08] space-y-3"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <div className="flex items-center gap-2">
                                <span className="font-mono text-xs text-zinc-500">
                                  #{q.order_index || idx + 1}
                                </span>
                                <span className="font-semibold text-white text-xs">
                                  {q.skill_name || 'Core Competency'}
                                </span>
                                {q.priority_tier && (
                                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-teal-500/10 text-teal-300 border border-teal-500/20">
                                    {q.priority_tier}
                                  </span>
                                )}
                              </div>

                              <button
                                type="button"
                                onClick={() => (isEditing ? setEditingQuestionId(null) : handleStartEditQuestion(q))}
                                className="inline-flex items-center gap-1 text-xs text-teal-400 hover:underline font-medium"
                              >
                                <Edit3 className="w-3.5 h-3.5" />
                                <span>{isEditing ? 'Cancel' : 'Edit'}</span>
                              </button>
                            </div>

                            {isEditing ? (
                              <div className="space-y-2 pt-1">
                                <label className="block text-[10px] font-mono uppercase text-zinc-400">Question Text</label>
                                <textarea
                                  rows={2}
                                  value={editQuestionText}
                                  onChange={(e) => setEditQuestionText(e.target.value)}
                                  className="w-full rounded-lg bg-black/40 border border-white/[0.12] p-2.5 text-xs text-white focus:outline-none focus:border-teal-400"
                                />

                                <label className="block text-[10px] font-mono uppercase text-zinc-400">Expected Key Points (one per line)</label>
                                <textarea
                                  rows={3}
                                  value={editKeyPoints}
                                  onChange={(e) => setEditKeyPoints(e.target.value)}
                                  className="w-full rounded-lg bg-black/40 border border-white/[0.12] p-2.5 text-xs text-white focus:outline-none focus:border-teal-400"
                                />

                                <div className="flex justify-end pt-1">
                                  <button
                                    type="button"
                                    disabled={savingQuestion}
                                    onClick={() => handleSaveQuestion(q.id)}
                                    className="inline-flex items-center gap-1 px-4 py-1.5 rounded-lg bg-teal-500 text-black font-semibold text-xs"
                                  >
                                    <Save className="w-3.5 h-3.5" />
                                    <span>{savingQuestion ? 'Saving...' : 'Save Changes'}</span>
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <div className="space-y-2">
                                <p className="text-xs sm:text-sm font-medium text-zinc-200">
                                  "{q.question_text}"
                                </p>

                                {q.expected_key_points && q.expected_key_points.length > 0 && (
                                  <div className="pt-2 border-t border-white/[0.06]">
                                    <div className="text-[10px] font-mono uppercase text-zinc-400 mb-1">Expected Key Points:</div>
                                    <ul className="list-disc pl-4 space-y-0.5 text-zinc-300 text-xs">
                                      {q.expected_key_points.map((pt, pIdx) => (
                                        <li key={pIdx}>{pt}</li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
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
          )}

        </div>

        {/* Footer */}
        <div className="p-4 bg-[#0A0A0B] border-t border-white/[0.08] flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg text-xs font-medium text-zinc-300 bg-white/[0.05] border border-white/[0.08] hover:bg-white/[0.1] hover:text-white transition-colors"
          >
            Close Dossier
          </button>
        </div>

      </div>
    </div>
  );
}
