import React, { useState, useEffect } from 'react';
import {
  X, CheckCircle2, AlertTriangle, Clock, ShieldCheck, Download,
  ExternalLink, Mail, Phone, Calendar, DollarSign, Award, Briefcase,
  Layers, Check, ChevronRight, UserCheck, RefreshCw, FileText,
  Sparkles, Code, FolderGit2, GraduationCap, BarChart3, Edit3, Save,
  RotateCcw, ThumbsUp, ThumbsDown, PauseCircle, Play, Eye
} from 'lucide-react';
import { formatMoney as formatCurrency } from '../../utils/currency';

export default function ApplicantDetailModal({
  application,
  isOpen,
  onClose,
  onApplicationUpdated
}) {
  if (!isOpen || !application) return null;

  const [currentApp, setCurrentApp] = useState(application);
  const [activeTab, setActiveTab] = useState('dossier'); // 'dossier' | 'scorecard' | 'plan'
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [togglingFlagId, setTogglingFlagId] = useState(null);
  const [actionError, setActionError] = useState(null);

  // Scorecard state (Part E1)
  const [scorecard, setScorecard] = useState(null);
  const [loadingScorecard, setLoadingScorecard] = useState(false);
  const [evaluatingNow, setEvaluatingNow] = useState(false);
  const [highlightedTurnId, setHighlightedTurnId] = useState(null);
  const [recruiterDecision, setRecruiterDecision] = useState(application.recruiter_decision || '');
  const [recruiterNotes, setRecruiterNotes] = useState(application.recruiter_notes || '');
  const [savingDecision, setSavingDecision] = useState(false);

  // Interview Plan state (Part E3)
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

  const resume = currentApp.resume;
  const structuredData = resume?.parsed_structured_data || {};
  const workExp = structuredData.work_experience || [];
  const education = structuredData.education || [];
  const certs = structuredData.certifications || [];
  const projects = structuredData.projects || [];
  const skills = structuredData.skills || [];
  const categorizedSkills = structuredData.skills_by_category || {};
  const totalResumeExp = structuredData.total_experience_years || 0.0;
  const verification = currentApp.id_verification;
  const flags = currentApp.discrepancy_flags || [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
      <div className="relative w-full max-w-5xl max-h-[92vh] flex flex-col rounded-3xl bg-white dark:bg-[#111827] border border-slate-200 dark:border-slate-800 shadow-2xl overflow-hidden">
        {actionError && (
          <div className="mx-6 mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs font-semibold text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">
            {actionError}
          </div>
        )}
        
        {/* Header Strip */}
        <div className="p-6 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
                Applicant Dossier
              </span>
              <span className="text-[11px] font-bold px-2 py-0.5 rounded-md bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
                Applied {new Date(currentApp.applied_at).toLocaleDateString()}
              </span>
              {flags.some((f) => !f.reviewed_by_recruiter) && (
                <span className="text-[11px] font-bold px-2 py-0.5 rounded-md bg-amber-50 dark:bg-amber-950/80 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800 flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" />
                  <span>Unresolved Discrepancies</span>
                </span>
              )}
            </div>

            <h2 className="text-2xl font-black text-slate-900 dark:text-white">
              {currentApp.full_name}
            </h2>

            <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
              <span className="flex items-center gap-1">
                <Mail className="w-3.5 h-3.5" />
                <span>{currentApp.email}</span>
              </span>
              {currentApp.phone && (
                <span className="flex items-center gap-1">
                  <Phone className="w-3.5 h-3.5" />
                  <span>{currentApp.phone}</span>
                </span>
              )}
              {currentApp.linkedin_url && (
                <a
                  href={currentApp.linkedin_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1"
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
                  className="text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1"
                >
                  <span>Portfolio/GitHub</span>
                  <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2.5 self-start sm:self-auto">
            {/* Application Status Selector */}
            <div className="flex items-center gap-1.5">
              <select
                value={currentApp.status}
                disabled={updatingStatus}
                onChange={(e) => handleStatusChange(e.target.value)}
                className="px-3 py-2 text-xs font-bold rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {statusOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    Status: {opt.label}
                  </option>
                ))}
              </select>
            </div>

            <button
              type="button"
              onClick={onClose}
              className="p-2 rounded-xl text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Tab Navigation Strip (Part E1 & E3) */}
        <div className="flex border-b border-slate-200 dark:border-slate-800 px-6 bg-slate-50/50 dark:bg-slate-900/40 text-xs font-bold gap-2">
          <button
            type="button"
            onClick={() => setActiveTab('dossier')}
            className={`py-3 px-3 border-b-2 transition-all flex items-center gap-1.5 ${
              activeTab === 'dossier'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-slate-900/60'
                : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Applicant Dossier</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('scorecard')}
            className={`py-3 px-3 border-b-2 transition-all flex items-center gap-1.5 ${
              activeTab === 'scorecard'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-slate-900/60'
                : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Evaluation Scorecard & Evidence</span>
            {currentApp.interview_session_status === 'completed' && (
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
            )}
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('plan')}
            className={`py-3 px-3 border-b-2 transition-all flex items-center gap-1.5 ${
              activeTab === 'plan'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-slate-900/60'
                : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Calibrated Interview Plan</span>
          </button>
        </div>

        {/* Scrollable Body */}
        <div className="p-6 overflow-y-auto space-y-6 flex-1 text-xs">
          
          {/* TAB 1: DOSSIER */}
          {activeTab === 'dossier' && (
            <div className="space-y-6">
              {/* TOP GRID: Discrepancy Warnings & Biometrics */}
              <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
                
                {/* Left: Discrepancies & Fit Pitch (7 cols) */}
                <div className="md:col-span-7 space-y-4">
                  
                  {/* Discrepancy Flags Audit Panel */}
                  <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 font-bold text-slate-900 dark:text-white">
                        <AlertTriangle className="w-4 h-4 text-amber-500" />
                        <span>Automated Consistency & Verification Audit</span>
                      </div>
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
                        {flags.length} Checked Points
                      </span>
                    </div>

                    {flags.length === 0 ? (
                      <div className="p-3 rounded-xl bg-emerald-50/60 dark:bg-emerald-950/40 border border-emerald-200/60 dark:border-emerald-900/60 text-emerald-700 dark:text-emerald-300 flex items-center gap-2">
                        <CheckCircle2 className="w-4 h-4 shrink-0" />
                        <span>No discrepancies or timeline mismatches detected. Self-reported claims match resume evidence.</span>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {flags.map((flag) => (
                          <div
                            key={flag.id}
                            className={`p-3 rounded-xl border space-y-1.5 transition-colors ${
                              flag.reviewed_by_recruiter
                                ? 'bg-slate-100 dark:bg-slate-800/40 border-slate-200 dark:border-slate-800 opacity-60'
                                : 'bg-amber-50/60 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/60'
                            }`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-bold text-slate-900 dark:text-white">
                                {flag.flag_reason}
                              </span>
                              <button
                                type="button"
                                disabled={togglingFlagId === flag.id}
                                onClick={() => handleToggleFlag(flag.id)}
                                className={`px-2 py-0.5 rounded text-[10px] font-bold transition-all shrink-0 ${
                                  flag.reviewed_by_recruiter
                                    ? 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300'
                                    : 'bg-amber-600 text-white hover:bg-amber-700'
                                }`}
                              >
                                {flag.reviewed_by_recruiter ? 'Reviewed ✓' : 'Mark Reviewed'}
                              </button>
                            </div>

                            <div className="grid grid-cols-2 gap-2 text-[10px] pt-1 border-t border-slate-200/60 dark:border-slate-800">
                              <div>
                                <span className="text-slate-400">Candidate Stated:</span>{' '}
                                <strong className="text-slate-800 dark:text-slate-200">{flag.candidate_stated_value || 'None'}</strong>
                              </div>
                              <div>
                                <span className="text-slate-400">Resume Derived:</span>{' '}
                                <strong className="text-slate-800 dark:text-slate-200">{flag.resume_derived_value || 'None'}</strong>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Fit Pitch & Compensation Analysis */}
                  <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-800 dark:text-slate-200">
                        Compensation & Experience Stated
                      </h3>
                      <div className="text-emerald-600 dark:text-emerald-400 font-bold text-xs flex items-center gap-1">
                        <DollarSign className="w-3.5 h-3.5" />
                        <span>Expected: {formatCurrency(currentApp.expected_salary, currentApp.expected_salary_currency)}</span>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3 text-xs">
                      <div className="p-3 rounded-xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 space-y-0.5">
                        <div className="text-slate-400 text-[10px] uppercase font-bold">Stated Experience</div>
                        <div className="text-base font-extrabold text-slate-900 dark:text-white">
                          {currentApp.self_reported_experience_years} Years
                        </div>
                      </div>

                      <div className="p-3 rounded-xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 space-y-0.5">
                        <div className="text-slate-400 text-[10px] uppercase font-bold">Calculated Timeline</div>
                        <div className="text-base font-extrabold text-indigo-600 dark:text-indigo-400">
                          ~{totalResumeExp.toFixed(1)} Years
                        </div>
                      </div>
                    </div>

                    {currentApp.fit_pitch && (
                      <div className="pt-2 border-t border-slate-200/60 dark:border-slate-800 space-y-1">
                        <span className="font-bold text-slate-500 uppercase text-[10px]">Candidate Fit Pitch</span>
                        <p className="text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-800 p-3 rounded-xl border border-slate-100 dark:border-slate-700 italic">
                          "{currentApp.fit_pitch}"
                        </p>
                      </div>
                    )}
                  </div>

                </div>

                {/* Right: Live Identity Verification & Original Resume (5 cols) */}
                <div className="md:col-span-5 space-y-4">
                  
                  {/* Identity Verification Card */}
                  <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 text-xs font-bold text-slate-900 dark:text-white">
                        <ShieldCheck className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                        <span>Identity & Biometric Baseline</span>
                      </div>
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 border border-emerald-200/60 dark:border-emerald-800">
                        Live Webcam Verified
                      </span>
                    </div>

                    {verification?.live_photo_path ? (
                      <div className="space-y-2">
                        <div className="relative aspect-video rounded-xl bg-slate-950 overflow-hidden border border-slate-200 dark:border-slate-800 shadow-inner">
                          <img
                            src={verification.live_photo_path}
                            alt="Candidate live snapshot"
                            className="w-full h-full object-cover"
                          />
                          <div className="absolute bottom-1.5 left-2 text-[9px] font-mono bg-black/70 px-2 py-0.5 rounded text-white">
                            TIMESTAMP: {new Date(verification.captured_at).toLocaleTimeString()}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="aspect-video rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-400 text-xs">
                        No live webcam snapshot recorded
                      </div>
                    )}

                    {verification?.government_id_path && (
                      <div className="pt-2 border-t border-slate-200/60 dark:border-slate-800 flex items-center justify-between">
                        <span className="text-[11px] text-slate-500 font-semibold">Government ID Document</span>
                        <button
                          type="button"
                          onClick={() => {
                            const win = window.open();
                            if (win) {
                              win.document.write(`<iframe src="${verification.government_id_path}" frameborder="0" style="border:0; top:0px; left:0px; bottom:0px; right:0px; width:100%; height:100%;" allowfullscreen></iframe>`);
                            }
                          }}
                          className="text-xs font-bold text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1 cursor-pointer"
                        >
                          <span>View Document</span>
                          <ExternalLink className="w-3 h-3" />
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Original File Metadata Card */}
                  {resume && (
                    <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5 font-bold text-slate-900 dark:text-white">
                          <FileText className="w-4 h-4 text-indigo-500" />
                          <span>Original Resume File</span>
                        </div>
                        {resume.ocr_used ? (
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-purple-50 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
                            Apple Vision OCR
                          </span>
                        ) : (
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-200 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                            Digital Text PDF
                          </span>
                        )}
                      </div>

                      <div className="text-xs text-slate-600 dark:text-slate-400 space-y-1">
                        <div className="font-semibold text-slate-800 dark:text-slate-200 truncate">
                          {resume.original_file_name}
                        </div>
                        <div className="text-[11px]">
                          {(resume.file_size_bytes / 1024).toFixed(1)} KB · Format: {resume.file_type.toUpperCase()} · <span className="text-emerald-600 dark:text-emerald-400 font-medium">PostgreSQL BYTEA</span>
                        </div>
                      </div>

                      <div className="flex flex-col gap-2 pt-1">
                        <a
                          href={`/api/applications/${currentApp.id}/resume/file`}
                          target="_blank"
                          rel="noreferrer"
                          className="w-full inline-flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs shadow-sm hover:shadow transition-all"
                        >
                          <FileText className="w-3.5 h-3.5" />
                          <span>View PDF Resume (PostgreSQL)</span>
                        </a>
                        <a
                          href={`/api/applications/${currentApp.id}/resume/file`}
                          download={resume.original_file_name || "resume.pdf"}
                          className="w-full inline-flex items-center justify-center gap-2 py-1.5 px-3 rounded-xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 font-bold text-xs hover:bg-slate-100 transition-colors"
                        >
                          <Download className="w-3.5 h-3.5" />
                          <span>Download File</span>
                        </a>
                      </div>
                    </div>
                  )}

                </div>
              </div>

              {/* BOTTOM SECTION: Structured Parsed Resume Data */}
              <div className="space-y-6 pt-2 border-t border-slate-200 dark:border-slate-800">
                {/* Work History */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
                      <Briefcase className="w-4 h-4 text-indigo-600" />
                      <span>Extracted Work History & Timeline</span>
                    </h3>
                    <span className="text-xs font-bold text-indigo-600 dark:text-indigo-400">
                      {workExp.length} Roles Parsed
                    </span>
                  </div>

                  <div className="space-y-3">
                    {workExp.length === 0 ? (
                      <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-center text-slate-400">
                        No structured work history entries parsed.
                      </div>
                    ) : (
                      workExp.map((exp, idx) => (
                        <div
                          key={idx}
                          className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1.5"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="font-extrabold text-slate-900 dark:text-white text-sm">
                              {exp.role || 'Role'} <span className="font-normal text-slate-500">at</span> {exp.company || 'Company'}
                            </div>
                            <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 font-bold text-slate-700 dark:text-slate-300">
                              {exp.start_date} – {exp.end_date} {exp.duration_years ? `(${exp.duration_years.toFixed(1)}y)` : ''}
                            </span>
                          </div>
                          {(exp.description || (exp.highlights && exp.highlights.length > 0)) && (
                            <p className="text-slate-600 dark:text-slate-300 text-xs pt-1">
                              {exp.description || exp.highlights.join('; ')}
                            </p>
                          )}
                          {exp.technologies && exp.technologies.length > 0 && (
                            <div className="flex flex-wrap gap-1 pt-1.5">
                              {exp.technologies.map((t, tIdx) => (
                                <span key={tIdx} className="px-2 py-0.5 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 text-[10px] font-semibold">
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
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
                      <GraduationCap className="w-4 h-4 text-indigo-600" />
                      <span>Education & Academic Credentials</span>
                    </h3>
                    <span className="text-xs font-bold text-indigo-600 dark:text-indigo-400">
                      {education.length} Degrees
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {education.length === 0 ? (
                      <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900 text-slate-400">
                        No education entries detected.
                      </div>
                    ) : (
                      education.map((edu, idx) => (
                        <div
                          key={idx}
                          className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1"
                        >
                          <div className="font-bold text-slate-900 dark:text-white text-sm">{edu.degree}</div>
                          <div className="text-slate-600 dark:text-slate-300 font-semibold">{edu.institution}</div>
                          {edu.field && (
                            <div className="text-slate-500 text-[11px]">Major: {edu.field}</div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Notable Projects */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
                      <FolderGit2 className="w-4 h-4 text-indigo-600" />
                      <span>Notable Software Projects</span>
                    </h3>
                    <span className="text-xs font-bold text-indigo-600 dark:text-indigo-400">
                      {projects.length} Projects
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {projects.length === 0 ? (
                      <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900 text-slate-400">
                        No individual projects parsed.
                      </div>
                    ) : (
                      projects.map((proj, idx) => (
                        <div
                          key={idx}
                          className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1.5"
                        >
                          <div className="font-bold text-slate-900 dark:text-white text-sm">{proj.title}</div>
                          {proj.description && (
                            <p className="text-slate-600 dark:text-slate-300 text-xs">
                              {proj.description}
                            </p>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Technical Skills Extracted */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
                      <Code className="w-4 h-4 text-indigo-600" />
                      <span>Technical Skills ({skills.length})</span>
                    </h3>
                  </div>

                  <div className="flex flex-wrap gap-1.5 p-3 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
                    {skills.map((s, idx) => (
                      <span
                        key={idx}
                        className="px-2.5 py-1 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 font-semibold text-xs"
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: SCORECARD & EVIDENCE (Part E1) */}
          {activeTab === 'scorecard' && (
            <div className="space-y-6">
              {loadingScorecard && (
                <div className="py-16 text-center space-y-2">
                  <RefreshCw className="w-6 h-6 animate-spin text-indigo-600 mx-auto" />
                  <p className="text-slate-400">Loading interview evaluation scorecard...</p>
                </div>
              )}

              {!loadingScorecard && !scorecard?.evaluation && (
                <div className="p-8 rounded-3xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-center space-y-3">
                  <BarChart3 className="w-10 h-10 text-slate-400 mx-auto" />
                  <h4 className="text-base font-bold text-slate-900 dark:text-white">
                    No Evaluation Scorecard Available
                  </h4>
                  <p className="text-xs text-slate-400 max-w-md mx-auto">
                    {currentApp.interview_session_status === 'completed'
                      ? 'The interview has completed. Click below to run the Evidence-Anchored Judge evaluation.'
                      : 'The candidate has not completed their live voice interview yet. The scorecard will generate automatically upon session completion.'}
                  </p>
                  <button
                    type="button"
                    disabled={evaluatingNow}
                    onClick={handleTriggerEvaluate}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs shadow-md transition-all cursor-pointer disabled:opacity-50"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>{evaluatingNow ? 'Running Gemini Judge Evaluation...' : 'Run Judge Evaluation Now'}</span>
                  </button>
                </div>
              )}

              {!loadingScorecard && scorecard?.evaluation && (
                <div className="space-y-6">
                  {/* Verdict & Overall Score Header Banner */}
                  <div className="p-5 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={`px-3 py-1 rounded-full text-xs font-black uppercase tracking-wider border ${
                            scorecard.evaluation.verdict?.includes('HIRE') && !scorecard.evaluation.verdict?.includes('NO')
                              ? 'bg-emerald-50 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800'
                              : scorecard.evaluation.verdict === 'BORDERLINE'
                              ? 'bg-amber-50 dark:bg-amber-950/80 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800'
                              : 'bg-rose-50 dark:bg-rose-950/80 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800'
                          }`}
                        >
                          Verdict: {scorecard.evaluation.verdict?.replace(/_/g, ' ')}
                        </span>
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
                          Confidence: {scorecard.evaluation.confidence_level}
                        </span>
                      </div>
                      <p className="text-xs text-slate-600 dark:text-slate-400 pt-1 max-w-2xl">
                        {scorecard.evaluation.summary_rationale}
                      </p>
                    </div>

                    <div className="text-right shrink-0">
                      <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Overall Evidence Score</div>
                      <div className="text-3xl font-black text-indigo-600 dark:text-indigo-400">
                        {scorecard.evaluation.overall_score !== null ? `${Math.round(scorecard.evaluation.overall_score)}/100` : 'N/A'}
                      </div>
                    </div>
                  </div>

                  {/* Insufficient Evidence Warning Banner (Part D4) */}
                  {scorecard.evaluation.insufficient_evidence && (
                    <div className="p-4 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300 flex items-start gap-3">
                      <AlertTriangle className="w-5 h-5 shrink-0 text-amber-600 dark:text-amber-400" />
                      <div className="space-y-0.5 text-xs">
                        <strong className="font-bold">Insufficient Evidence Warning:</strong>
                        <p>
                          One or more mandatory (P0) competencies could not be validated with verbatim transcript evidence (rated NOT_ASSESSED). Overall verdict is capped at LEAN_NO_HIRE per policy.
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Key Strengths & Concerns */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div className="p-4 rounded-2xl bg-emerald-50/50 dark:bg-emerald-950/20 border border-emerald-200/60 dark:border-emerald-900/40 space-y-2">
                      <div className="font-bold text-emerald-800 dark:text-emerald-300 text-xs flex items-center gap-1.5">
                        <ThumbsUp className="w-3.5 h-3.5" />
                        <span>Key Strengths</span>
                      </div>
                      <ul className="list-disc pl-4 space-y-1 text-slate-700 dark:text-slate-300 text-xs">
                        {(scorecard.evaluation.key_strengths || []).map((s, i) => (
                          <li key={i}>{s}</li>
                        ))}
                      </ul>
                    </div>

                    <div className="p-4 rounded-2xl bg-rose-50/50 dark:bg-rose-950/20 border border-rose-200/60 dark:border-rose-900/40 space-y-2">
                      <div className="font-bold text-rose-800 dark:text-rose-300 text-xs flex items-center gap-1.5">
                        <ThumbsDown className="w-3.5 h-3.5" />
                        <span>Key Concerns / Uncovered Points</span>
                      </div>
                      <ul className="list-disc pl-4 space-y-1 text-slate-700 dark:text-slate-300 text-xs">
                        {(scorecard.evaluation.key_concerns || []).map((c, i) => (
                          <li key={i}>{c}</li>
                        ))}
                      </ul>
                    </div>
                  </div>

                  {/* Per-Skill Score Breakdown with Clickable Quotes (Part E1) */}
                  <div className="space-y-3">
                    <h4 className="text-sm font-bold text-slate-900 dark:text-white flex items-center justify-between">
                      <span>Assessed Competencies & Verbatim Evidence Quotes</span>
                      <span className="text-xs text-slate-400">Click any quote to jump to the transcript</span>
                    </h4>

                    <div className="space-y-3">
                      {(scorecard.skill_scores || []).map((skill) => (
                        <div
                          key={skill.skill_id}
                          className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-3"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                  skill.priority_tier === 'P0'
                                    ? 'bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300'
                                    : 'bg-indigo-100 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                                }`}
                              >
                                {skill.priority_tier}
                              </span>
                              <span className="font-bold text-slate-900 dark:text-white text-sm">
                                {skill.skill_name}
                              </span>
                              <span className="text-slate-400 text-xs">({skill.weight_percentage}%)</span>
                            </div>

                            <span
                              className={`px-3 py-1 rounded-full text-xs font-extrabold ${
                                skill.score_level === 'NOT_ASSESSED'
                                  ? 'bg-slate-200 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                                  : skill.score_level >= 'L3'
                                  ? 'bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300'
                                  : 'bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300'
                              }`}
                            >
                              Level: {skill.score_level}
                            </span>
                          </div>

                          <p className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed">
                            {skill.rationale}
                          </p>

                          {/* Clickable Evidence Quotes (Part E1) */}
                          <div className="space-y-1.5 pt-2 border-t border-slate-200/60 dark:border-slate-800">
                            <span className="text-[10px] font-bold uppercase text-slate-400">
                              Anchored Verbatim Quotes ({skill.evidence_quotes?.length || 0}):
                            </span>
                            {(!skill.evidence_quotes || skill.evidence_quotes.length === 0) ? (
                              <div className="text-[11px] text-slate-400 italic">
                                Zero transcript quotes verified. Level downgraded to NOT_ASSESSED.
                              </div>
                            ) : (
                              <div className="flex flex-col gap-1.5">
                                {skill.evidence_quotes.map((eq, qIdx) => (
                                  <button
                                    key={qIdx}
                                    type="button"
                                    onClick={() => {
                                      setHighlightedTurnId(eq.turn_id);
                                      const el = document.getElementById(`turn-${eq.turn_id}`);
                                      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                    }}
                                    className="text-left p-2.5 rounded-xl bg-white dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 text-indigo-700 dark:text-indigo-300 hover:border-indigo-400 transition-all cursor-pointer group"
                                  >
                                    <span className="font-semibold italic">"{eq.quote}"</span>
                                    <span className="ml-2 text-[10px] text-slate-400 group-hover:text-indigo-500 font-mono">
                                      → Turn {eq.turn_id ? eq.turn_id.slice(0, 8) : ''}
                                    </span>
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Full Interview Transcript with Interruption and Latency Badges (Part E1) */}
                  <div className="space-y-3 pt-2">
                    <h4 className="text-sm font-bold text-slate-900 dark:text-white flex items-center justify-between">
                      <span>Full Interview Transcript ({scorecard.transcript_turns?.length || 0} Turns)</span>
                    </h4>

                    <div className="space-y-2.5 max-h-96 overflow-y-auto p-1">
                      {(scorecard.transcript_turns || []).map((turn) => {
                        const isHighlighted = highlightedTurnId === turn.id;
                        return (
                          <div
                            key={turn.id}
                            id={`turn-${turn.id}`}
                            className={`p-3.5 rounded-2xl border transition-all ${
                              isHighlighted
                                ? 'bg-indigo-50/80 dark:bg-indigo-950/60 border-indigo-500 ring-2 ring-indigo-500/30'
                                : 'bg-slate-50 dark:bg-slate-900 border-slate-200 dark:border-slate-800'
                            }`}
                          >
                            <div className="flex items-center justify-between text-[11px] font-semibold text-slate-400 mb-1">
                              <span className="flex items-center gap-1.5 font-bold uppercase text-slate-700 dark:text-slate-300">
                                {turn.speaker === 'ai' ? '🤖 AI Interviewer' : '👤 Candidate'}
                                <span className="font-mono text-slate-400 font-normal">#{turn.turn_index}</span>
                              </span>

                              <div className="flex items-center gap-2">
                                {turn.was_interrupted && (
                                  <span className="rounded bg-rose-500/20 px-2 py-0.5 text-[9px] font-bold text-rose-400 border border-rose-500/30">
                                    Interrupted
                                  </span>
                                )}
                                {turn.total_response_ms && (
                                  <span className="font-mono text-[10px] text-slate-400">
                                    Latency: {turn.total_response_ms}ms (LLM: {turn.llm_ttft_ms}ms)
                                  </span>
                                )}
                              </div>
                            </div>

                            <p className="text-xs text-slate-800 dark:text-slate-200 leading-relaxed">
                              {turn.content}
                            </p>
                            {turn.was_interrupted && turn.spoken_text && (
                              <p className="mt-1 text-[11px] text-slate-400 italic">
                                Spoken before cut-off: "{turn.spoken_text}"
                              </p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Integrity Event Timeline (Part E1 & Part F1) */}
                  <div className="space-y-3 pt-2">
                    <h4 className="text-sm font-bold text-slate-900 dark:text-white flex items-center justify-between">
                      <span>Integrity Signal Audit Timeline ({scorecard.integrity_events?.length || 0} Events)</span>
                    </h4>

                    {(!scorecard.integrity_events || scorecard.integrity_events.length === 0) ? (
                      <div className="p-3 rounded-xl bg-emerald-50/60 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300 text-xs flex items-center gap-2">
                        <CheckCircle2 className="w-4 h-4 shrink-0" />
                        <span>Clean session: No tab switches, clipboard paste, or webcam occlusion events logged.</span>
                      </div>
                    ) : (
                      <div className="space-y-1.5">
                        {scorecard.integrity_events.map((evt) => (
                          <div
                            key={evt.id}
                            className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 flex items-center justify-between text-xs"
                          >
                            <div className="flex items-center gap-2">
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                                  evt.severity === 'critical'
                                    ? 'bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300'
                                    : evt.severity === 'warning'
                                    ? 'bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300'
                                    : 'bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300'
                                }`}
                              >
                                {evt.severity}
                              </span>
                              <span className="font-bold text-slate-800 dark:text-slate-200">
                                {evt.event_type}
                              </span>
                            </div>
                            <span className="text-[10px] font-mono text-slate-400">
                              {new Date(evt.occurred_at).toLocaleTimeString()}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Recruiter Decision Controls (Advance / Hold / Reject) (Part E1) */}
                  <div className="p-5 rounded-2xl bg-indigo-50/60 dark:bg-indigo-950/30 border border-indigo-200/70 dark:border-indigo-900/50 space-y-3">
                    <h4 className="text-sm font-bold text-slate-900 dark:text-white">
                      Recruiter Decision & Next Steps
                    </h4>

                    <div className="flex items-center gap-2">
                      {['advance', 'hold', 'reject'].map((d) => (
                        <button
                          key={d}
                          type="button"
                          onClick={() => setRecruiterDecision(d)}
                          className={`px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-wider transition-all cursor-pointer ${
                            recruiterDecision === d
                              ? d === 'advance'
                                ? 'bg-emerald-600 text-white shadow-md'
                                : d === 'hold'
                                ? 'bg-amber-600 text-white shadow-md'
                                : 'bg-rose-600 text-white shadow-md'
                              : 'bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-300'
                          }`}
                        >
                          {d}
                        </button>
                      ))}
                    </div>

                    <textarea
                      rows={2}
                      value={recruiterNotes}
                      onChange={(e) => setRecruiterNotes(e.target.value)}
                      placeholder="Add recruiter rationale, follow-up interviewers, or debrief notes..."
                      className="w-full rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-2.5 text-xs text-slate-800 dark:text-slate-200 focus:outline-none focus:border-indigo-500"
                    />

                    <div className="flex justify-end">
                      <button
                        type="button"
                        disabled={savingDecision}
                        onClick={handleSaveDecision}
                        className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs shadow transition-colors cursor-pointer disabled:opacity-50"
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

          {/* TAB 3: CALIBRATED INTERVIEW PLAN (Part E3) */}
          {activeTab === 'plan' && (
            <div className="space-y-6">
              {loadingPlan && (
                <div className="py-16 text-center space-y-2">
                  <RefreshCw className="w-6 h-6 animate-spin text-indigo-600 mx-auto" />
                  <p className="text-slate-400">Loading calibrated interview plan...</p>
                </div>
              )}

              {!loadingPlan && !planData && (
                <div className="p-8 rounded-3xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-center space-y-3">
                  <Sparkles className="w-8 h-8 text-slate-400 mx-auto" />
                  <h4 className="text-sm font-bold text-slate-900 dark:text-white">Plan Not Generated Yet</h4>
                  <p className="text-xs text-slate-400">
                    Interview plan questions are generated after candidate resume submission and ID verification.
                  </p>
                </div>
              )}

              {!loadingPlan && planData && (
                <div className="space-y-6">
                  {/* Status Banner & Action Buttons */}
                  <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
                          Interview Plan Status:
                        </span>
                        <span className="text-xs font-bold px-2 py-0.5 rounded-md bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                          {planData.status || 'Active'}
                        </span>
                      </div>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {planData.questions?.length || 0} questions calibrated for candidate resume and job requirements.
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        disabled={regeneratingPlan}
                        onClick={handleRegeneratePlan}
                        className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-200 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 font-bold text-xs transition-colors cursor-pointer disabled:opacity-50"
                      >
                        <RotateCcw className={`w-3.5 h-3.5 ${regeneratingPlan ? 'animate-spin' : ''}`} />
                        <span>Regenerate Questions</span>
                      </button>

                      <button
                        type="button"
                        disabled={approvingPlan}
                        onClick={handleApprovePlan}
                        className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs shadow transition-colors cursor-pointer disabled:opacity-50"
                      >
                        <Check className="w-3.5 h-3.5" />
                        <span>Approve Plan</span>
                      </button>
                    </div>
                  </div>

                  {/* Interviewer Brief */}
                  {planData.interviewer_brief && (
                    <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                        Interviewer Session Brief
                      </span>
                      <p className="text-xs text-slate-700 dark:text-slate-300 whitespace-pre-line leading-relaxed">
                        {planData.interviewer_brief}
                      </p>
                    </div>
                  )}

                  {/* Questions List */}
                  <div className="space-y-3">
                    <h4 className="text-sm font-bold text-slate-900 dark:text-white">
                      Calibrated Questions & Expected Key Points
                    </h4>

                    <div className="space-y-3">
                      {(planData.questions || []).map((q, idx) => {
                        const isEditing = editingQuestionId === q.id;
                        return (
                          <div
                            key={q.id || idx}
                            className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-3"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <div className="flex items-center gap-2">
                                <span className="font-mono text-xs font-bold text-slate-400">
                                  #{q.order_index || idx + 1}
                                </span>
                                <span className="font-bold text-slate-900 dark:text-white text-xs">
                                  {q.skill_name || 'Core Skill'}
                                </span>
                                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-indigo-50 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400">
                                  {q.priority_tier}
                                </span>
                              </div>

                              <button
                                type="button"
                                onClick={() => (isEditing ? setEditingQuestionId(null) : handleStartEditQuestion(q))}
                                className="inline-flex items-center gap-1 text-xs text-indigo-600 dark:text-indigo-400 hover:underline font-semibold"
                              >
                                <Edit3 className="w-3.5 h-3.5" />
                                <span>{isEditing ? 'Cancel Edit' : 'Edit Question'}</span>
                              </button>
                            </div>

                            {isEditing ? (
                              <div className="space-y-2 pt-1">
                                <label className="block text-[10px] font-bold uppercase text-slate-400">Question Text</label>
                                <textarea
                                  rows={2}
                                  value={editQuestionText}
                                  onChange={(e) => setEditQuestionText(e.target.value)}
                                  className="w-full rounded-xl bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 p-2.5 text-xs text-slate-800 dark:text-slate-200 focus:outline-none"
                                />

                                <label className="block text-[10px] font-bold uppercase text-slate-400">Expected Key Points (one per line)</label>
                                <textarea
                                  rows={3}
                                  value={editKeyPoints}
                                  onChange={(e) => setEditKeyPoints(e.target.value)}
                                  className="w-full rounded-xl bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 p-2.5 text-xs text-slate-800 dark:text-slate-200 focus:outline-none"
                                />

                                <div className="flex justify-end pt-1">
                                  <button
                                    type="button"
                                    disabled={savingQuestion}
                                    onClick={() => handleSaveQuestion(q.id)}
                                    className="inline-flex items-center gap-1 px-4 py-1.5 rounded-xl bg-indigo-600 text-white font-bold text-xs"
                                  >
                                    <Save className="w-3.5 h-3.5" />
                                    <span>{savingQuestion ? 'Saving...' : 'Save Changes'}</span>
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <div className="space-y-2">
                                <p className="text-xs sm:text-sm font-semibold text-slate-900 dark:text-white">
                                  "{q.question_text}"
                                </p>

                                {q.expected_key_points && q.expected_key_points.length > 0 && (
                                  <div className="pt-2 border-t border-slate-200/60 dark:border-slate-800">
                                    <div className="text-[10px] font-bold uppercase text-slate-400 mb-1">Expected Key Points:</div>
                                    <ul className="list-disc pl-4 space-y-0.5 text-slate-600 dark:text-slate-300 text-xs">
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
        <div className="p-4 bg-slate-50 dark:bg-slate-900 border-t border-slate-200 dark:border-slate-800 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-5 py-2 rounded-xl text-xs font-semibold text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-slate-100"
          >
            Close Dossier
          </button>
        </div>

      </div>

    </div>
  );
}
