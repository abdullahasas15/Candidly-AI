import React, { useState, useEffect } from 'react';
import {
  Video, Mic, MicOff, Camera, CameraOff, Volume2, ShieldCheck, CheckCircle2, X,
  AlertCircle, ArrowLeft, Play, Sparkles, RefreshCw, Clock, Award,
  CheckCircle, HelpCircle, Layers, FileText, ChevronRight, LogOut, Briefcase,
  Radio, Cpu, MessageSquare, Zap
} from 'lucide-react';
import Logo from '../Logo';
import CandidateJobListing from './CandidateJobListing';
import ApplicationWizard from './ApplicationWizard';
import PreFlightCheckModal from './interview/PreFlightCheckModal';
import LiveInterviewRoom from './interview/LiveInterviewRoom';

export default function CandidateDashboard({ authUser, onBackToLanding, onSignOut }) {
  const [activePortalTab, setActivePortalTab] = useState('applications'); // 'applications' | 'browse'
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

  // Fetch applications for candidate
  const fetchApplications = async () => {
    setLoading(true);
    setError(null);
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
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchApplications();
  }, [authUser]);

  useEffect(() => {
    if (!applications.some((app) => app.interview_generation_status === 'running' || app.interview_generation_status === 'queued')) return undefined;
    const interval = setInterval(fetchApplications, 3000);
    return () => clearInterval(interval);
  }, [applications]);

  useEffect(() => {
    if (applications.length > 0 && selectedAppIndex >= applications.length) {
      setSelectedAppIndex(applications.length - 1);
    }
  }, [applications.length, selectedAppIndex]);

  const currentApp = applications[selectedAppIndex] || applications[0];
  const activeJob = currentApp?.job;

  const handleApplicationSubmitted = (newApp) => {
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
      // The practice-interview endpoint returns the session under `id` (no `session_id`).
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
      // Wiped all candidate records per user specification
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

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-[#0B0F19] text-slate-900 dark:text-white transition-colors">
      
      {/* Candidate Portal Top Navigation */}
      <header className="sticky top-0 z-40 bg-white/85 dark:bg-[#0B0F19]/85 backdrop-blur-xl border-b border-slate-200/80 dark:border-slate-800/80 py-3 px-4 sm:px-6 lg:px-8 transition-colors">
        <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
          
          {/* Left: Brand Identity & Portal Pill */}
          <div className="flex items-center gap-5 sm:gap-6">
            <div className="flex items-center gap-2.5">
              <Logo size={32} className="w-8 h-8 shrink-0" />
              <div className="flex items-center gap-2">
                <span className="font-extrabold text-base tracking-tight text-slate-900 dark:text-white">
                  Candidly<span className="text-indigo-600 dark:text-indigo-400">.AI</span>
                </span>
                <span className="hidden sm:inline-flex items-center gap-1.5 text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-indigo-50 dark:bg-indigo-950/70 text-indigo-700 dark:text-indigo-300 border border-indigo-200/60 dark:border-indigo-800/60">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                  CANDIDATE PORTAL
                </span>
              </div>
            </div>

            {/* Quick Navigation Tabs in Header */}
            <nav className="hidden md:flex items-center gap-1 bg-slate-100/80 dark:bg-slate-900/80 p-1 rounded-xl border border-slate-200/60 dark:border-slate-800/60 text-xs font-semibold">
              <button
                type="button"
                onClick={() => setActivePortalTab('applications')}
                className={`px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 ${
                  activePortalTab === 'applications'
                    ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-300 shadow-sm font-bold'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                }`}
              >
                <Briefcase className="w-3.5 h-3.5" />
                <span>My Applications</span>
                {applications.length > 0 && (
                  <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-indigo-100 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 font-bold">
                    {applications.length}
                  </span>
                )}
              </button>

              <button
                type="button"
                onClick={() => setActivePortalTab('browse')}
                className={`px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 ${
                  activePortalTab === 'browse'
                    ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-300 shadow-sm font-bold'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                }`}
              >
                <Sparkles className="w-3.5 h-3.5 text-amber-500" />
                <span>Explore Jobs</span>
              </button>
            </nav>
          </div>

          {/* Right: User Profile Chip & Actions */}
          <div className="flex items-center gap-2 sm:gap-3">
            {/* User Profile Chip */}
            <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-xl bg-slate-100/80 dark:bg-slate-900/80 border border-slate-200/60 dark:border-slate-800/60 text-xs">
              <div className="w-6 h-6 rounded-lg bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center text-white text-[10px] font-bold shadow-sm">
                {(authUser?.full_name || 'Candidate')
                  .split(' ')
                  .map((n) => n[0])
                  .slice(0, 2)
                  .join('')
                  .toUpperCase()}
              </div>
              <div className="hidden sm:flex flex-col text-left">
                <span className="text-xs font-bold text-slate-800 dark:text-slate-200 leading-tight">
                  {authUser?.full_name || 'Candidate'}
                </span>
                <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium leading-none flex items-center gap-1 mt-0.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block animate-pulse" />
                  Active
                </span>
              </div>
            </div>

            {/* Refresh Button */}
            <button
              type="button"
              onClick={fetchApplications}
              disabled={loading}
              title="Refresh application and interview status"
              className="p-2 rounded-xl text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white bg-slate-100/80 dark:bg-slate-900/80 hover:bg-slate-200 dark:hover:bg-slate-800 border border-slate-200/60 dark:border-slate-800/60 transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>

            {/* Back to Overview */}
            {onBackToLanding && (
              <button
                type="button"
                onClick={onBackToLanding}
                title="Return to main portal overview"
                className="hidden lg:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white bg-slate-100/80 dark:bg-slate-900/80 hover:bg-slate-200 dark:hover:bg-slate-800 border border-slate-200/60 dark:border-slate-800/60 transition-colors"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                <span>Overview</span>
              </button>
            )}

            {/* Sign Out */}
            <button
              type="button"
              onClick={onSignOut}
              title="Sign out of candidate account"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-slate-600 hover:text-rose-600 dark:text-slate-400 dark:hover:text-rose-400 bg-slate-100/80 dark:bg-slate-900/80 hover:bg-rose-50 dark:hover:bg-rose-950/40 border border-slate-200/60 dark:border-slate-800/60 hover:border-rose-300 dark:hover:border-rose-900/60 transition-all"
            >
              <LogOut className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Sign Out</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        
        {/* Welcome Banner */}
        <div className="p-5 sm:p-6 rounded-2xl bg-gradient-to-r from-indigo-900/90 via-slate-900 to-indigo-950 text-white border border-indigo-500/20 shadow-lg relative overflow-hidden">
          <div className="absolute right-0 top-0 w-96 h-96 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
          <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="space-y-2 max-w-2xl">
              <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-indigo-500/20 text-indigo-300 text-xs font-semibold border border-indigo-400/20">
                <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
                <span>{applications.length > 0 ? 'Active Candidate Evaluation' : 'Ready to Discover New Roles'}</span>
              </div>
              <h1 className="text-xl sm:text-2xl font-extrabold tracking-tight">
                Welcome, {authUser?.full_name || 'Candidate'}
              </h1>
              <p className="text-xs sm:text-sm text-indigo-200">
                {authUser?.headline || 'Explore opportunities and showcase your skills through AI voice interviews.'}
              </p>
              <p className="text-xs text-slate-300 pt-1">
                {applications.length > 0
                  ? 'Review the role details, verify your device readiness, and enter your scheduled session.'
                  : 'You have not submitted any applications yet. Browse open positions configured by hiring teams, apply, and complete your evaluation.'}
              </p>
            </div>

            <div className="flex flex-col sm:flex-row items-center gap-3">
              <button
                type="button"
                onClick={handleStartPracticeInterview}
                disabled={startingPractice}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 py-3 rounded-2xl bg-indigo-500/30 hover:bg-indigo-500/50 text-white font-bold text-xs border border-indigo-400/40 shadow-sm transition-all cursor-pointer"
                title="Conduct a 5-minute warm-up interview with the AI interviewer"
              >
                <Sparkles className="w-4 h-4 text-indigo-300" />
                <span>{startingPractice ? 'Starting Warm-up...' : 'Practice Interview (5m Warm-up)'}</span>
              </button>

              {applications.length > 0 ? (
                <span className="text-xs font-semibold text-indigo-200 hidden md:inline">
                  Select an application below.
                </span>
              ) : (
                <button
                  onClick={() => setActivePortalTab('browse')}
                  className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-2xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-sm shadow-lg shadow-indigo-600/30 hover:-translate-y-0.5 transition-all"
                >
                  <Briefcase className="w-4 h-4 fill-white" />
                  <span>Browse Open Positions</span>
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Portal View Tabs */}
        <div className="flex flex-wrap gap-x-5 gap-y-2 border-b border-slate-200 dark:border-slate-800 text-sm font-bold">
          <button
            onClick={() => setActivePortalTab('applications')}
            className={`pb-3 px-1 border-b-2 transition-all flex items-center gap-2 ${
              activePortalTab === 'applications'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Briefcase className="w-4 h-4" />
            <span>Applications ({applications.length})</span>
          </button>

          <button
            onClick={() => setActivePortalTab('browse')}
            className={`pb-3 px-1 border-b-2 transition-all flex items-center gap-2 ${
              activePortalTab === 'browse'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Sparkles className="w-4 h-4" />
            <span>Browse Open Positions</span>
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
          <>
            {/* Loading / Error States */}
            {loading && (
              <div className="py-16 text-center space-y-3">
                <RefreshCw className="w-8 h-8 text-indigo-600 animate-spin mx-auto" />
                <p className="text-sm text-slate-500 dark:text-slate-400">Loading your candidate profile and active applications...</p>
              </div>
            )}

            {error && (
              <div className="p-4 rounded-2xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 text-rose-700 dark:text-rose-300 text-sm flex items-center gap-3">
                <AlertCircle className="w-5 h-5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {/* If multiple applications, allow selecting */}
            {!loading && applications.length > 1 && (
              <div className="flex items-center gap-2 overflow-x-auto pb-1">
                <span className="text-xs font-bold text-slate-400 whitespace-nowrap">Your Roles:</span>
                {applications.map((app, idx) => (
                  <button
                    key={app.id}
                    onClick={() => setSelectedAppIndex(idx)}
                    className={`px-3 py-1.5 rounded-xl text-xs font-bold whitespace-nowrap transition-all flex items-center gap-2 ${
                      selectedAppIndex === idx
                        ? 'bg-indigo-600 text-white shadow-sm'
                        : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-800 hover:border-slate-300'
                    }`}
                  >
                    <span>{app.job?.job_title || `Role ${idx + 1}`}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${selectedAppIndex === idx ? 'bg-indigo-700 text-indigo-100' : 'bg-slate-100 dark:bg-slate-800'}`}>
                      {app.status === 'interview_ready' ? 'Ready' : 'Applied'}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {/* Empty Applications Fallback */}
            {!loading && applications.length === 0 && !error && (
              <div className="p-8 sm:p-12 rounded-3xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-center space-y-4 max-w-lg mx-auto shadow-sm">
                <div className="w-14 h-14 rounded-2xl bg-indigo-50 dark:bg-indigo-950 flex items-center justify-center mx-auto text-indigo-600 dark:text-indigo-400">
                  <Briefcase className="w-7 h-7" />
                </div>
                <div className="space-y-1.5">
                  <h3 className="text-xl font-bold text-slate-900 dark:text-white">No active applications found</h3>
                  <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400">
                    You haven't applied to any job requisitions yet. Explore open roles configured by hiring teams and submit your application to schedule your AI voice interview.
                  </p>
                </div>
                <div className="pt-2 flex items-center justify-center gap-3">
                  <button
                    onClick={() => setActivePortalTab('browse')}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-700 shadow-md shadow-indigo-600/20 transition-all"
                  >
                    <Sparkles className="w-4 h-4" />
                    <span>Explore Open Positions</span>
                  </button>
                  <button
                    onClick={fetchApplications}
                    className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-xs font-bold text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                    <span>Refresh</span>
                  </button>
                </div>
              </div>
            )}

            {/* Active Application Card & Interview Entry */}
            {!loading && activeJob && (
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
                
                {/* Left Column: Application Details & Skills (7 cols) */}
                <div className="lg:col-span-7 space-y-6">
                  <div className="p-6 rounded-3xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm space-y-6">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
                            Target Position
                          </span>
                          <span className="text-[11px] px-2 py-0.5 rounded-md font-bold bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                            {currentApp?.status === 'interview_ready' ? 'Interview Ready' : 'Applied'}
                          </span>
                        </div>
                        <h2 className="text-xl sm:text-2xl font-black text-slate-900 dark:text-white mt-1">
                          {activeJob.job_title}
                        </h2>
                        <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 mt-0.5">
                          {activeJob.department} • {activeJob.seniority_level} • {activeJob.employment_type}
                        </p>
                      </div>

                      <div className="text-right">
                        <div className="text-xs text-slate-400 font-medium">Session Length</div>
                        <div className="text-lg font-black text-slate-900 dark:text-white flex items-center justify-end gap-1">
                          <Clock className="w-4 h-4 text-indigo-500" />
                          <span>{activeJob.interview_duration_mins} mins</span>
                        </div>
                      </div>
                    </div>

                    {/* Job Specs Grid */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                      <div className="p-3 rounded-2xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
                        <div className="text-slate-400">Workplace Model</div>
                        <div className="font-bold text-slate-800 dark:text-slate-200 mt-0.5">{activeJob.workplace_model}</div>
                      </div>
                      <div className="p-3 rounded-2xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
                        <div className="text-slate-400">Experience Bar</div>
                        <div className="font-bold text-slate-800 dark:text-slate-200 mt-0.5">{activeJob.total_experience_years}+ Years</div>
                      </div>
                    </div>

                    {/* Skills needed for the role */}
                    <div className="space-y-3 pt-2">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center justify-between">
                        <span>Skills Needed for This Role ({activeJob.skills?.length || 0})</span>
                      </h3>

                      <div className="space-y-2.5">
                        {activeJob.skills?.map((skill) => (
                          <div
                            key={skill.id}
                            className="p-3.5 rounded-2xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200/70 dark:border-slate-800"
                          >
                            <div className="flex items-center justify-between">
                              <span className="text-xs sm:text-sm font-bold text-slate-900 dark:text-white">
                                {skill.name}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Candidate-Safe Summary Feedback (Part D5) */}
                    {(currentApp?.interview_completed || currentApp?.status === 'interview_completed' || currentApp?.interview_session_status === 'completed') && (
                      <div className="space-y-3 pt-2">
                        <div className="p-4 rounded-2xl bg-indigo-50/70 dark:bg-indigo-950/30 border border-indigo-200/70 dark:border-indigo-900/50 space-y-2">
                          <div className="flex items-center gap-2 text-indigo-700 dark:text-indigo-300 font-bold text-xs">
                            <Sparkles className="w-4 h-4" />
                            <span>Interview Completed · Constructive Reflection</span>
                          </div>
                          {currentApp?.candidate_summary ? (
                            <p className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed">
                              {currentApp.candidate_summary}
                            </p>
                          ) : (
                            <p className="text-xs text-slate-600 dark:text-slate-400">
                              Your interview turns and technical responses are safely stored. The hiring team has received your evaluation dossier.
                            </p>
                          )}
                        </div>
                      </div>
                    )}

                    <div className="flex flex-wrap items-center gap-3 pt-2">
                      {currentApp?.interview_completed || currentApp?.status === 'interview_completed' || currentApp?.interview_session_status === 'completed' ? (
                        <div className="inline-flex items-center gap-2 rounded-xl bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-300 dark:border-emerald-800 px-4 py-3 text-xs font-bold text-emerald-700 dark:text-emerald-300">
                          <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                          <span>Interview Completed · Recruiter Review in Progress</span>
                        </div>
                      ) : (
                        <button
                          onClick={() => setPreflightOpen(true)}
                          disabled={!currentApp?.interview_ready}
                          className={`inline-flex items-center gap-2 rounded-xl px-5 py-3 text-xs font-bold text-white transition-all shadow-md ${
                            currentApp?.interview_ready
                              ? 'bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 shadow-indigo-600/30 cursor-pointer'
                              : 'bg-slate-400 cursor-not-allowed shadow-none'
                          }`}
                        >
                          <Play className="h-3.5 w-3.5 fill-white" />
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
                        onClick={() => setWithdrawalOpen(true)}
                        className="inline-flex items-center gap-2 rounded-xl border border-rose-200 px-4 py-2.5 text-xs font-bold text-rose-600 hover:bg-rose-50 dark:border-rose-900/60 dark:text-rose-400 dark:hover:bg-rose-950/30 transition-colors cursor-pointer"
                      >
                        Withdraw application
                      </button>
                    </div>

                  </div>
                </div>

                {/* Right Column: AI Interview Experience Guide (5 cols) */}
                <div className="lg:col-span-5 space-y-6">
                  <div className="p-6 rounded-3xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm space-y-5 sticky top-20">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-indigo-50 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400">
                          <Radio className="h-4 w-4 animate-pulse" />
                        </div>
                        <h3 className="text-base font-extrabold text-slate-900 dark:text-white">
                          Real-Time Voice Room
                        </h3>
                      </div>
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border border-emerald-200/50 dark:border-emerald-800/50">
                        Enterprise UX
                      </span>
                    </div>

                    <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                      You will participate in a live, bidirectional conversational interview conducted by our AI interviewer with lip-synced visual presence.
                    </p>

                    {/* Feature Highlights */}
                    <div className="space-y-3 text-xs">
                      <div className="flex items-start gap-3 p-3 rounded-2xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800">
                        <div className="p-2 rounded-xl bg-indigo-100 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400 shrink-0">
                          <Cpu className="h-4 w-4" />
                        </div>
                        <div>
                          <div className="font-bold text-slate-900 dark:text-white">Voqalize 2D Talking Head</div>
                          <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                            Speech-correlated viseme lip synchronization with real-time listening & thinking states.
                          </div>
                        </div>
                      </div>

                      <div className="flex items-start gap-3 p-3 rounded-2xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800">
                        <div className="p-2 rounded-xl bg-indigo-100 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400 shrink-0">
                          <Zap className="h-4 w-4" />
                        </div>
                        <div>
                          <div className="font-bold text-slate-900 dark:text-white">Continuous Audio & Barge-In</div>
                          <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                            No manual buttons during the call. Interrupt the AI naturally at any point; speech halts instantly.
                          </div>
                        </div>
                      </div>

                      <div className="flex items-start gap-3 p-3 rounded-2xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800">
                        <div className="p-2 rounded-xl bg-indigo-100 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400 shrink-0">
                          <MessageSquare className="h-4 w-4" />
                        </div>
                        <div>
                          <div className="font-bold text-slate-900 dark:text-white">Adaptive Turn State Machine</div>
                          <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                            Greeting → Self-Intro → Technical Deep Dive with Follow-Ups → Closing & Next Steps.
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Pre-flight CTA Button */}
                    <div className="pt-2">
                      <button
                        onClick={() => setPreflightOpen(true)}
                        disabled={!currentApp?.interview_ready}
                        className="w-full py-3.5 rounded-2xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs shadow-md shadow-indigo-600/30 hover:shadow-indigo-600/40 transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <ShieldCheck className="w-4 h-4" />
                        <span>Launch Pre-Flight & Enter Room</span>
                      </button>
                      <p className="text-[11px] text-center text-slate-400 mt-2">
                        Requires camera, microphone, and a stable internet connection.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </>
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

      {/* Part 1: Pre-Interview Requirements Check Screen */}
      <PreFlightCheckModal
        isOpen={preflightOpen}
        onClose={() => setPreflightOpen(false)}
        onProceedToInterview={handleProceedToInterview}
        jobTitle={activeJob?.job_title}
        candidateName={authUser?.full_name}
        isEntering={startingInterview}
      />

      {/* Part 2: Enterprise Real-Time Live Interview Room */}
      {interviewStarted && interviewSession && (
        <LiveInterviewRoom
          sessionId={interviewSession.id}
          jobTitle={interviewSession?.job_title || activeJob?.job_title || 'Technical Interview'}
          candidateName={authUser?.full_name}
          durationMins={interviewSession?.duration_mins || activeJob?.interview_duration_mins || 20}
          token={localStorage.getItem('candidly-auth-token')}
          onExit={() => {
            setInterviewStarted(false);
            setInterviewSession(null);
            setIsPracticeMode(false);
            setApplications((prev) =>
              prev.map((app) =>
                app.interview_session_id === interviewSession.id || app.id === currentApp?.id
                  ? {
                      ...app,
                      interview_completed: true,
                      status: 'interview_completed',
                      interview_ready: false,
                      interview_session_status: 'completed',
                    }
                  : app
              )
            );
            fetchApplications();
          }}
        />
      )}

      {/* Withdrawal Confirmation Dialog */}
      {withdrawalOpen && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm">
          <div role="dialog" aria-modal="true" className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-700 dark:bg-slate-900">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-bold text-slate-900 dark:text-white">Withdraw application?</h3>
                <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                  All applications, interview transcripts, sessions, and data associated with your candidate profile will be permanently wiped out.
                </p>
                {error && (
                  <div className="mt-3 p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 text-rose-700 dark:text-rose-300 text-xs flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                )}
              </div>
              <button
                onClick={() => setWithdrawalOpen(false)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
                aria-label="Close"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={() => setWithdrawalOpen(false)}
                className="rounded-xl border border-slate-200 px-4 py-2.5 text-xs font-bold text-slate-600 dark:border-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                Keep application
              </button>
              <button
                onClick={withdrawApplication}
                disabled={withdrawing}
                className="rounded-xl bg-rose-600 px-4 py-2.5 text-xs font-bold text-white hover:bg-rose-700 disabled:opacity-60 transition-colors"
              >
                {withdrawing ? 'Withdrawing...' : 'Withdraw application'}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
