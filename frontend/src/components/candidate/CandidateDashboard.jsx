import React, { useState, useEffect, useRef } from 'react';
import {
  Video, Mic, MicOff, Camera, CameraOff, Volume2, ShieldCheck, CheckCircle2, X,
  AlertCircle, ArrowLeft, Play, Sparkles, RefreshCw, Clock, Award,
  CheckCircle, HelpCircle, Layers, FileText, ChevronRight, LogOut, Briefcase,
  Radio, Cpu, MessageSquare, Zap, Headphones, Check, UserCheck
} from 'lucide-react';
import Header from '../Header';
import { Card, Badge, Stat, EmptyState, PageHeader } from '../ui';
import CandidateJobListing from './CandidateJobListing';
import ApplicationWizard from './ApplicationWizard';
import PreFlightCheckModal from './interview/PreFlightCheckModal';
import LiveInterviewRoom from './interview/LiveInterviewRoom';

function getApplicationStep(app) {
  if (!app) return 1;
  const status = (app.status || '').toLowerCase();
  const sessionStatus = (app.interview_session_status || '').toLowerCase();
  const completed = app.interview_completed || status === 'interview_completed' || sessionStatus === 'completed' || status === 'interviewed';

  if (status === 'hired' || status === 'rejected') return 4;
  if (completed || status === 'under_review') return 3;
  if (app.interview_ready || status === 'ready_for_interview' || status === 'interview_ready' || sessionStatus === 'in_progress' || sessionStatus === 'paused') return 2;
  return 1;
}

const STEP_LABELS = ['Applied', 'Interview', 'Under review', 'Decision'];

export default function CandidateDashboard({ authUser, onBackToLanding, onSignOut }) {
  const [activePortalTab, setActivePortalTab] = useState(() => {
    if (typeof window !== 'undefined') {
      const tab = new URLSearchParams(window.location.search).get('tab');
      if (tab === 'browse') return 'browse';
    }
    return 'applications';
  });
  const [applyingJob, setApplyingJob] = useState(null);
  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Interview flow states
  const [preflightOpen, setPreflightOpen] = useState(false);
  const [interviewStarted, setInterviewStarted] = useState(false);
  const [interviewSession, setInterviewSession] = useState(null);
  const [interviewError, setInterviewError] = useState(null);
  const [startingInterview, setStartingInterview] = useState(false);
  const [startingPractice, setStartingPractice] = useState(false);
  const [isPracticeMode, setIsPracticeMode] = useState(false);

  // Application management states
  const [withdrawalOpen, setWithdrawalOpen] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const [selectedAppIndex, setSelectedAppIndex] = useState(0);

  const getCandidateToken = () =>
    authUser?.access_token ||
    localStorage.getItem('candidly-auth-token-candidate') ||
    localStorage.getItem('candidly-auth-token');

  const fetchApplications = async (silent = false) => {
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const token = getCandidateToken();
      const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
      const url = authUser?.id
        ? `/api/candidate/applications?user_id=${authUser.id}`
        : (authUser?.email ? `/api/candidate/applications?email=${encodeURIComponent(authUser.email)}` : '/api/candidate/applications');
      const res = await fetch(url, { headers });
      if (!res.ok) {
        throw new Error('Failed to load candidate applications');
      }
      const data = await res.json();
      setApplications(data);
      if (data.length === 0) {
        setActivePortalTab('browse');
      }
    } catch (err) {
      if (!silent) {
        setError(err.message);
      }
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    fetchApplications();
  }, [authUser]);

  const pollStartRef = useRef(0);
  useEffect(() => {
    const needsPoll = applications.some((app) =>
      app.interview_generation_status === 'running'
      || app.interview_generation_status === 'queued'
      || (app.status === 'submitted' && !app.interview_ready && !app.interview_completed)
    );
    if (!needsPoll) {
      pollStartRef.current = 0;
      return undefined;
    }
    if (!pollStartRef.current) {
      pollStartRef.current = Date.now();
    }
    if (Date.now() - pollStartRef.current > 360000) {
      return undefined;
    }
    const interval = setInterval(() => fetchApplications(true), 3000);
    return () => clearInterval(interval);
  }, [applications]);

  useEffect(() => {
    if (applications.length > 0 && selectedAppIndex >= applications.length) {
      setSelectedAppIndex(applications.length - 1);
    }
  }, [applications.length, selectedAppIndex]);

  const currentApp = applications[selectedAppIndex] || applications[0];
  const activeJob = currentApp?.job;

  const handleApplicationSubmitted = () => {
    fetchApplications();
    setActivePortalTab('applications');
    setApplyingJob(null);
  };

  const handleStartPracticeInterview = async () => {
    setStartingPractice(true);
    setInterviewError(null);
    try {
      const token = getCandidateToken();
      const headers = {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        'Content-Type': 'application/json',
      };
      const res = await fetch('/api/candidate/practice-interview', {
        method: 'POST',
        headers,
      });
      const payload = await res.json();
      if (!res.ok) {
        throw new Error(payload.detail || 'Could not start practice interview');
      }
      const sessionId = payload.session_id || payload.id;
      const startRes = await fetch(`/api/interview-sessions/${sessionId}/start`, {
        method: 'POST',
        headers,
      });
      const startedPayload = startRes.ok ? await startRes.json() : { id: sessionId };
      setIsPracticeMode(true);
      setInterviewSession({
        ...startedPayload,
        id: sessionId,
        job_title: payload.job_title || 'Practice Interview (General Warm-Up)',
        duration_mins: payload.duration_mins || 5,
      });
      setInterviewStarted(true);
    } catch (err) {
      setInterviewError(err.message);
      alert(err.message || 'Unable to start practice interview.');
    } finally {
      setStartingPractice(false);
    }
  };

  const handleProceedToInterview = async () => {
    if (!currentApp?.id) return;
    setStartingInterview(true);
    setInterviewError(null);
    try {
      const token = getCandidateToken();
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const sessionResponse = await fetch(`/api/applications/${currentApp.id}/interview-session`, { headers });
      const sessionPayload = await sessionResponse.json();
      if (!sessionResponse.ok) {
        if (sessionResponse.status === 409) {
          const generationResponse = await fetch(`/api/applications/${currentApp.id}/interview-generation`, {
            method: 'POST',
            headers,
          });
          const generationPayload = await generationResponse.json();
          if (generationResponse.ok || generationResponse.status === 202) {
            fetchApplications();
            throw new Error(generationPayload.message || 'Interview preparation started. Refresh in a moment.');
          }
          throw new Error(generationPayload.detail || sessionPayload.detail);
        }
        throw new Error(sessionPayload.detail || 'Interview preparation is not complete yet.');
      }

      let activeSession = sessionPayload;
      if (sessionPayload.status === 'scheduled' || sessionPayload.status === 'paused') {
        const startResponse = await fetch(`/api/interview-sessions/${sessionPayload.id}/start`, {
          method: 'POST',
          headers,
        });
        const startedPayload = await startResponse.json();
        if (startResponse.ok) {
          activeSession = startedPayload;
        }
      }

      setIsPracticeMode(false);
      setInterviewSession(activeSession);
      setPreflightOpen(false);
      setInterviewStarted(true);
    } catch (err) {
      setInterviewError(err.message);
      alert(err.message || 'Unable to launch interview session.');
    } finally {
      setStartingInterview(false);
    }
  };

  const withdrawApplication = async () => {
    const applicationId = currentApp?.id || 'all';
    setWithdrawing(true);
    setError(null);
    const token = getCandidateToken();
    try {
      const response = await fetch(`/api/candidate/applications/${applicationId}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        setError(payload.detail || 'Unable to withdraw application.');
        return;
      }
      setApplications([]);
      setActivePortalTab('browse');
      setWithdrawalOpen(false);
      setPreflightOpen(false);
      setInterviewStarted(false);
      setInterviewSession(null);
      setSelectedAppIndex(0);
      fetchApplications();
    } catch (err) {
      setError(err.message || 'Unable to withdraw application.');
    } finally {
      setWithdrawing(false);
    }
  };

  // If live interview is running, render interview room directly
  if (interviewStarted && interviewSession) {
    return (
      <LiveInterviewRoom
        session={interviewSession}
        onEndInterview={() => {
          setInterviewStarted(false);
          setInterviewSession(null);
          setIsPracticeMode(false);
          fetchApplications();
        }}
        isPractice={isPracticeMode}
      />
    );
  }

  const currentStep = getApplicationStep(currentApp);
  const isInterviewCompleted =
    currentApp?.interview_completed ||
    currentApp?.status === 'interview_completed' ||
    currentApp?.interview_session_status === 'completed';

  return (
    <div className="min-h-screen bg-black text-white flex flex-col">
      {/* Header with Role Navigation */}
      <Header
        user={authUser}
        roleNav="candidate"
        activeRoleNav={activePortalTab === 'browse' ? 'jobs' : 'applications'}
        onNavChange={(key) => {
          if (key === 'jobs') setActivePortalTab('browse');
          else if (key === 'applications') setActivePortalTab('applications');
        }}
        onAction={() => setActivePortalTab('browse')}
        actionLabel="Browse Jobs"
        onSignOut={onSignOut}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        
        {/* Page Header with Serif Greeting */}
        <PageHeader
          badge="Candidate Portal"
          title={`Hello, ${authUser?.full_name ? authUser.full_name.split(' ')[0] : 'Candidate'}`}
          subtitle={
            authUser?.headline ||
            'Review active applications, prepare for your voice interviews, and explore open roles.'
          }
          actions={
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleStartPracticeInterview}
                disabled={startingPractice}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium text-zinc-300 bg-white/[0.05] hover:bg-white/[0.1] border border-white/[0.08] transition-colors cursor-pointer"
              >
                <Sparkles className="w-3.5 h-3.5 text-teal-400" />
                <span>{startingPractice ? 'Starting...' : 'Warm-Up (5m)'}</span>
              </button>

              <button
                type="button"
                onClick={() => fetchApplications(false)}
                disabled={loading}
                title="Refresh applications"
                className="p-1.5 rounded-lg text-zinc-400 hover:text-white bg-white/[0.05] border border-white/[0.08] transition-colors"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          }
        />

        {/* Short "How the interview works" strip */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-4 rounded-xl bg-[#0A0A0B] border border-white/[0.08]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-teal-500/10 text-teal-400 flex items-center justify-center shrink-0 border border-teal-500/20">
              <Mic className="w-4 h-4" />
            </div>
            <div>
              <div className="text-xs font-semibold text-white">Voice-only</div>
              <div className="text-[11px] text-zinc-400">Natural conversation</div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-teal-500/10 text-teal-400 flex items-center justify-center shrink-0 border border-teal-500/20">
              <Clock className="w-4 h-4" />
            </div>
            <div>
              <div className="text-xs font-semibold text-white">~30 Minutes</div>
              <div className="text-[11px] text-zinc-400">Structured & adaptive</div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-teal-500/10 text-teal-400 flex items-center justify-center shrink-0 border border-teal-500/20">
              <Cpu className="w-4 h-4" />
            </div>
            <div>
              <div className="text-xs font-semibold text-white">No coding</div>
              <div className="text-[11px] text-zinc-400">Architecture & depth</div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-teal-500/10 text-teal-400 flex items-center justify-center shrink-0 border border-teal-500/20">
              <Headphones className="w-4 h-4" />
            </div>
            <div>
              <div className="text-xs font-semibold text-white">Headphones</div>
              <div className="text-[11px] text-zinc-400">Recommended for clarity</div>
            </div>
          </div>
        </div>

        {/* View Switcher: Applications vs Browse */}
        <div className="flex items-center gap-2 border-b border-white/[0.08] pb-1">
          <button
            type="button"
            onClick={() => setActivePortalTab('applications')}
            className={`pb-2.5 px-3 text-xs font-medium border-b-2 transition-all flex items-center gap-2 ${
              activePortalTab === 'applications'
                ? 'border-teal-400 text-teal-400'
                : 'border-transparent text-zinc-400 hover:text-white'
            }`}
          >
            <Briefcase className="w-3.5 h-3.5" />
            <span>Applications ({applications.length})</span>
          </button>

          <button
            type="button"
            onClick={() => setActivePortalTab('browse')}
            className={`pb-2.5 px-3 text-xs font-medium border-b-2 transition-all flex items-center gap-2 ${
              activePortalTab === 'browse'
                ? 'border-teal-400 text-teal-400'
                : 'border-transparent text-zinc-400 hover:text-white'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Explore Jobs</span>
          </button>
        </div>

        {/* BROWSE TAB */}
        {activePortalTab === 'browse' && (
          <CandidateJobListing
            onSelectJobForApplication={(job) => setApplyingJob(job)}
          />
        )}

        {/* APPLICATIONS TAB */}
        {activePortalTab === 'applications' && (
          <div className="space-y-8">
            {loading && (
              <div className="py-20 text-center space-y-2">
                <RefreshCw className="w-6 h-6 animate-spin text-teal-400 mx-auto" />
                <p className="text-xs text-zinc-400">Loading your applications...</p>
              </div>
            )}

            {error && (
              <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs">
                {error}
              </div>
            )}

            {!loading && applications.length === 0 && !error && (
              <EmptyState
                icon={Briefcase}
                title="No active applications yet"
                description="Explore open engineering positions configured by hiring teams and submit your application to schedule your AI voice evaluation."
                actionLabel="Explore Open Positions"
                onAction={() => setActivePortalTab('browse')}
              />
            )}

            {!loading && applications.length > 0 && activeJob && (
              <>
                {/* UPCOMING INTERVIEW HERO CARD (with low-opacity dotted-wave background) */}
                <div className="relative overflow-hidden rounded-2xl bg-[#0A0A0B] border border-white/[0.08] p-6 sm:p-8 bg-dots shadow-2xl">
                  <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
                    <div className="space-y-3 max-w-2xl">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[11px] font-mono uppercase tracking-wider text-teal-400">
                          {isInterviewCompleted ? 'Evaluation Complete' : 'Upcoming Interview'}
                        </span>
                        <Badge variant={isInterviewCompleted ? 'emerald' : currentApp?.interview_ready ? 'teal' : 'neutral'}>
                          {isInterviewCompleted
                            ? 'Interview Completed'
                            : currentApp?.interview_ready
                            ? 'Ready to Start'
                            : 'Preparing Interview'}
                        </Badge>
                      </div>

                      <h2 className="text-2xl sm:text-3xl font-display font-bold text-white tracking-tight">
                        {activeJob.job_title}
                      </h2>

                      <p className="text-xs sm:text-sm text-zinc-400 leading-relaxed">
                        {activeJob.department} · {activeJob.workplace_model} · {activeJob.interview_duration_mins} min session
                      </p>

                      {currentApp?.candidate_summary && (
                        <div className="p-3.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-xs text-zinc-300 leading-relaxed mt-2">
                          <strong className="text-teal-300">Session Reflection: </strong>
                          {currentApp.candidate_summary}
                        </div>
                      )}
                    </div>

                    <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 shrink-0">
                      {isInterviewCompleted ? (
                        <div className="inline-flex items-center gap-2 px-5 py-3 rounded-lg bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 text-xs font-semibold">
                          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                          <span>Submitted for Recruiter Review</span>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setPreflightOpen(true)}
                          disabled={!currentApp?.interview_ready}
                          className="inline-flex items-center justify-center gap-2.5 px-7 py-3.5 rounded-lg bg-teal-500 hover:bg-teal-400 text-black font-semibold text-sm shadow-xl shadow-teal-500/20 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-0.5"
                        >
                          <Play className="w-4 h-4 fill-black" />
                          <span>
                            {currentApp?.interview_session_status === 'paused'
                              ? 'Resume Interview'
                              : currentApp?.interview_ready
                              ? 'Start Interview'
                              : 'Preparing Interview...'}
                          </span>
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() => setWithdrawalOpen(true)}
                        className="px-3.5 py-3 rounded-lg text-xs font-medium text-zinc-400 hover:text-rose-400 hover:bg-rose-500/10 border border-transparent hover:border-rose-500/20 transition-colors"
                      >
                        Withdraw
                      </button>
                    </div>
                  </div>
                </div>

                {/* Grid: Application Status Steps + Profile Completeness Card */}
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                  
                  {/* Left (8 cols): Applications List with 4 Status Steps */}
                  <div className="lg:col-span-8 space-y-4">
                    <div className="flex items-center justify-between">
                      <h3 className="text-xs font-mono uppercase tracking-wider text-zinc-400">
                        Active Application Pipeline
                      </h3>
                      {applications.length > 1 && (
                        <div className="flex items-center gap-1.5">
                          {applications.map((app, idx) => (
                            <button
                              key={app.id}
                              onClick={() => setSelectedAppIndex(idx)}
                              className={`px-2.5 py-1 rounded text-xs font-mono transition-colors ${
                                selectedAppIndex === idx
                                  ? 'bg-teal-500 text-black font-semibold'
                                  : 'bg-white/[0.05] text-zinc-400 hover:text-white'
                              }`}
                            >
                              Role {idx + 1}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>

                    {applications.map((app, idx) => {
                      const step = getApplicationStep(app);
                      const isSelected = selectedAppIndex === idx;

                      return (
                        <div
                          key={app.id}
                          onClick={() => setSelectedAppIndex(idx)}
                          className={`p-5 rounded-xl border transition-all cursor-pointer ${
                            isSelected
                              ? 'bg-[#0A0A0B] border-white/[0.16] ring-1 ring-teal-400/20'
                              : 'bg-[#0A0A0B] border-white/[0.08] hover:border-white/[0.12]'
                          }`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                            <div>
                              <h4 className="text-base font-semibold text-white">
                                {app.job?.job_title || 'Software Engineer'}
                              </h4>
                              <p className="text-xs text-zinc-400">
                                {app.job?.department} · Applied on {new Date(app.applied_at || Date.now()).toLocaleDateString()}
                              </p>
                            </div>

                            <Badge variant={step >= 3 ? 'emerald' : step === 2 ? 'teal' : 'neutral'}>
                              {step === 4 ? 'Decision Made' : step === 3 ? 'Under Review' : step === 2 ? 'Interview Stage' : 'Applied'}
                            </Badge>
                          </div>

                          {/* 4 Status Steps (Applied -> Interview -> Under review -> Decision) */}
                          <div className="pt-2">
                            <div className="flex items-center justify-between relative">
                              {STEP_LABELS.map((label, sIdx) => {
                                const stepNum = sIdx + 1;
                                const isPassed = step > stepNum;
                                const isCurrent = step === stepNum;

                                return (
                                  <React.Fragment key={label}>
                                    <div className="flex flex-col items-center z-10">
                                      <div
                                        className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-mono transition-all ${
                                          isPassed
                                            ? 'bg-teal-400 text-black font-bold'
                                            : isCurrent
                                            ? 'bg-teal-500 text-black font-bold ring-4 ring-teal-500/20'
                                            : 'bg-white/[0.08] text-zinc-500'
                                        }`}
                                      >
                                        {isPassed ? <Check className="w-3.5 h-3.5 stroke-[3]" /> : stepNum}
                                      </div>
                                      <span
                                        className={`text-[11px] mt-1.5 transition-colors ${
                                          isCurrent
                                            ? 'font-semibold text-white'
                                            : isPassed
                                            ? 'text-teal-400'
                                            : 'text-zinc-500'
                                        }`}
                                      >
                                        {label}
                                      </span>
                                    </div>

                                    {sIdx < STEP_LABELS.length - 1 && (
                                      <div
                                        className={`flex-1 h-0.5 mx-2 -mt-4 transition-colors ${
                                          step > stepNum ? 'bg-teal-400/60' : 'bg-white/[0.08]'
                                        }`}
                                      />
                                    )}
                                  </React.Fragment>
                                );
                              })}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Right (4 cols): Profile Completeness & Device Readiness */}
                  <div className="lg:col-span-4 space-y-4">
                    <h3 className="text-xs font-mono uppercase tracking-wider text-zinc-400">
                      Profile Readiness
                    </h3>

                    <div className="p-5 rounded-xl bg-[#0A0A0B] border border-white/[0.08] space-y-4">
                      <div className="flex items-center justify-between">
                        <div className="text-xs font-semibold text-white">Profile Completeness</div>
                        <span className="text-xs font-mono text-teal-400">100%</span>
                      </div>

                      <div className="w-full h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                        <div className="h-full bg-teal-400 rounded-full w-full" />
                      </div>

                      <div className="space-y-2 text-xs pt-1">
                        <div className="flex items-center justify-between text-zinc-300">
                          <span className="flex items-center gap-2">
                            <CheckCircle2 className="w-3.5 h-3.5 text-teal-400" />
                            <span>Contact & Profile</span>
                          </span>
                          <span className="text-zinc-500 text-[11px]">Verified</span>
                        </div>

                        <div className="flex items-center justify-between text-zinc-300">
                          <span className="flex items-center gap-2">
                            <CheckCircle2 className="w-3.5 h-3.5 text-teal-400" />
                            <span>Resume Uploaded</span>
                          </span>
                          <span className="text-zinc-500 text-[11px]">Parsed</span>
                        </div>

                        <div className="flex items-center justify-between text-zinc-300">
                          <span className="flex items-center gap-2">
                            <CheckCircle2 className="w-3.5 h-3.5 text-teal-400" />
                            <span>Webcam & Mic Permissions</span>
                          </span>
                          <span className="text-zinc-500 text-[11px]">Ready</span>
                        </div>
                      </div>

                      <div className="pt-2 border-t border-white/[0.06]">
                        <button
                          type="button"
                          onClick={() => setPreflightOpen(true)}
                          disabled={!currentApp?.interview_ready}
                          className="w-full py-2 px-3 rounded-lg bg-white/[0.05] hover:bg-white/[0.1] text-xs font-medium text-zinc-200 transition-colors flex items-center justify-center gap-2 border border-white/[0.08] disabled:opacity-40"
                        >
                          <ShieldCheck className="w-3.5 h-3.5 text-teal-400" />
                          <span>Pre-Flight Diagnostic</span>
                        </button>
                      </div>
                    </div>
                  </div>

                </div>
              </>
            )}
          </div>
        )}
      </main>

      {/* Application Wizard Modal */}
      <ApplicationWizard
        job={applyingJob}
        authUser={authUser}
        isOpen={!!applyingJob}
        onClose={() => setApplyingJob(null)}
        onApplicationSubmitted={handleApplicationSubmitted}
      />

      {/* Pre-Interview PreFlightCheckModal (Untouched props) */}
      <PreFlightCheckModal
        isOpen={preflightOpen}
        onClose={() => setPreflightOpen(false)}
        onProceedToInterview={handleProceedToInterview}
        jobTitle={activeJob?.job_title}
        candidateName={authUser?.full_name}
        isEntering={startingInterview}
      />

      {/* Withdrawal Confirmation Dialog */}
      {withdrawalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="w-full max-w-md p-6 rounded-2xl bg-[#0A0A0B] border border-white/[0.12] space-y-4">
            <h3 className="text-base font-semibold text-white">Withdraw Application?</h3>
            <p className="text-xs text-zinc-400 leading-relaxed">
              Are you sure you want to withdraw your application for{' '}
              <strong className="text-white">{activeJob?.job_title}</strong>? This action will cancel your scheduled interview and remove your dossier from the recruiter's active pipeline.
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setWithdrawalOpen(false)}
                className="px-4 py-2 rounded-lg text-xs font-medium text-zinc-300 bg-white/[0.05] hover:bg-white/[0.1]"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={withdrawing}
                onClick={withdrawApplication}
                className="px-4 py-2 rounded-lg text-xs font-semibold text-white bg-rose-600 hover:bg-rose-500"
              >
                {withdrawing ? 'Withdrawing...' : 'Confirm Withdrawal'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
