import React, { useState, useEffect } from 'react';
import {
  Video, Mic, MicOff, Camera, CameraOff, Volume2, ShieldCheck, CheckCircle2,
  AlertCircle, ArrowLeft, Play, Sparkles, RefreshCw, Clock, Award,
  CheckCircle, HelpCircle, Layers, FileText, ChevronRight, LogOut, Briefcase
} from 'lucide-react';
import Logo from '../Logo';
import CandidateJobListing from './CandidateJobListing';
import ApplicationWizard from './ApplicationWizard';

export default function CandidateDashboard({ authUser, onBackToLanding, onSignOut }) {
  const [activePortalTab, setActivePortalTab] = useState('applications'); // 'applications' | 'browse'
  const [applyingJob, setApplyingJob] = useState(null);
  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Pre-flight check states
  const [cameraActive, setCameraActive] = useState(false);
  const [micActive, setMicActive] = useState(false);
  const [audioLevel, setAudioLevel] = useState(42);
  const [activeChecklist, setActiveChecklist] = useState({
    micChecked: false,
    cameraChecked: false,
    networkChecked: true,
    roomQuiet: true
  });
  const [interviewStarted, setInterviewStarted] = useState(false);

  // Fetch applications for candidate
  const fetchApplications = async () => {
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem('candidly-auth-token');
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

  // Audio level simulator when mic is active
  useEffect(() => {
    let interval;
    if (micActive) {
      interval = setInterval(() => {
        setAudioLevel(Math.floor(25 + Math.random() * 65));
      }, 150);
    } else {
      setAudioLevel(0);
    }
    return () => clearInterval(interval);
  }, [micActive]);

  const toggleCamera = () => {
    setCameraActive((prev) => {
      const next = !prev;
      if (next) {
        setActiveChecklist((c) => ({ ...c, cameraChecked: true }));
      }
      return next;
    });
  };

  const toggleMic = () => {
    setMicActive((prev) => {
      const next = !prev;
      if (next) {
        setActiveChecklist((c) => ({ ...c, micChecked: true }));
      }
      return next;
    });
  };

  const [selectedAppIndex, setSelectedAppIndex] = useState(0);
  const currentApp = applications[selectedAppIndex] || applications[0];
  const activeJob = currentApp?.job;

  const handleApplicationSubmitted = (newApp) => {
    fetchApplications();
    setActivePortalTab('applications');
    setApplyingJob(null);
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-[#0B0F19] text-slate-900 dark:text-white transition-colors">
      
      {/* Candidate Portal Top Navigation */}
      <header className="sticky top-0 z-40 bg-white/90 dark:bg-[#0B0F19]/90 backdrop-blur-md border-b border-slate-200/80 dark:border-slate-800/80 py-3.5 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={onBackToLanding}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>Back to Overview</span>
            </button>

            <div className="h-5 w-[1px] bg-slate-200 dark:border-slate-800 hidden sm:block" />

            <div className="flex items-center gap-2.5">
              <Logo size={32} className="w-8 h-8" />
              <div className="flex items-center gap-1.5">
                <span className="font-extrabold text-base tracking-tight text-slate-900 dark:text-white">
                  Candidly<span className="text-indigo-600 dark:text-indigo-400">.AI</span>
                </span>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border border-emerald-200/60 dark:border-emerald-800/60">
                  CANDIDATE PORTAL
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden md:flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 mr-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>Signed in as <strong className="text-slate-800 dark:text-slate-200">{authUser?.full_name || 'Candidate'}</strong></span>
            </div>

            <button
              onClick={fetchApplications}
              disabled={loading}
              title="Refresh Application Status"
              className="p-2 rounded-xl text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>

            <button
              onClick={onSignOut}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 dark:hover:bg-rose-900/60 border border-rose-200/60 dark:border-rose-800/60 transition-colors"
            >
              <LogOut className="w-3.5 h-3.5" />
              <span>Sign Out</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        
        {/* Welcome Banner */}
        <div className="p-6 sm:p-8 rounded-3xl bg-gradient-to-r from-indigo-900/90 via-slate-900 to-indigo-950 text-white border border-indigo-500/20 shadow-xl relative overflow-hidden">
          <div className="absolute right-0 top-0 w-96 h-96 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
          <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="space-y-2 max-w-2xl">
              <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-indigo-500/20 text-indigo-300 text-xs font-semibold border border-indigo-400/20">
                <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
                <span>{applications.length > 0 ? 'Active Candidate Evaluation' : 'Ready to Discover New Roles'}</span>
              </div>
              <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight">
                Welcome, {authUser?.full_name || 'Candidate'}
              </h1>
              <p className="text-xs sm:text-sm text-indigo-200">
                {authUser?.headline || 'Explore opportunities and showcase your skills through AI voice interviews.'}
              </p>
              <p className="text-xs text-slate-300 pt-1">
                {applications.length > 0
                  ? 'Your AI-guided voice interview is calibrated against clear rubric standards. Review role details, verify readiness, and enter your session.'
                  : 'You have not submitted any applications yet. Browse open positions configured by hiring teams, apply, and complete your evaluation.'}
              </p>
            </div>

            <div className="flex flex-col sm:flex-row items-center gap-3">
              {applications.length > 0 ? (
                <button
                  onClick={() => setInterviewStarted(true)}
                  className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-2xl bg-indigo-500 hover:bg-indigo-400 text-white font-bold text-sm shadow-lg shadow-indigo-500/30 hover:-translate-y-0.5 transition-all"
                >
                  <Play className="w-4 h-4 fill-white" />
                  <span>Enter AI Voice Interview</span>
                </button>
              ) : (
                <button
                  onClick={() => setActivePortalTab('browse')}
                  className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-2xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-sm shadow-lg shadow-indigo-600/30 hover:-translate-y-0.5 transition-all"
                >
                  <Sparkles className="w-4 h-4 fill-white" />
                  <span>Browse Open Positions</span>
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Portal View Tabs */}
        <div className="flex border-b border-slate-200 dark:border-slate-800 space-x-6 text-sm font-bold">
          <button
            onClick={() => setActivePortalTab('applications')}
            className={`pb-3 px-1 border-b-2 transition-all flex items-center gap-2 ${
              activePortalTab === 'applications'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Briefcase className="w-4 h-4" />
            <span>My Applications & Interviews ({applications.length})</span>
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

        {/* Active Application Card & Hardware Pre-Flight */}
        {!loading && activeJob && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
            
            {/* Left Column: Application Details & Rubric Blueprint (7 cols) */}
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
                  <div className="p-3 rounded-2xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
                    <div className="text-slate-400">Integrity Tier</div>
                    <div className="font-bold text-slate-800 dark:text-slate-200 mt-0.5">{activeJob.integrity_policy_tier}</div>
                  </div>
                  <div className="p-3 rounded-2xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
                    <div className="text-slate-400">Pacing Profile</div>
                    <div className="font-bold text-slate-800 dark:text-slate-200 mt-0.5">{activeJob.pacing_strictness}</div>
                  </div>
                </div>

                {/* Evaluated Skills & Target Rubrics */}
                <div className="space-y-3 pt-2">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center justify-between">
                    <span>What You'll Be Evaluated On ({activeJob.skills?.length || 0} Core Dimensions)</span>
                    <span className="text-[10px] text-indigo-500 font-semibold">Calibrated Rubrics L1-L5</span>
                  </h3>

                  <div className="space-y-2.5">
                    {activeJob.skills?.map((skill) => (
                      <div
                        key={skill.id}
                        className="p-3.5 rounded-2xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200/70 dark:border-slate-800 space-y-2"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className={`text-[10px] font-black px-2 py-0.5 rounded-md ${
                              skill.priority_tier === 'P0'
                                ? 'bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-800'
                                : 'bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800'
                            }`}>
                              {skill.priority_tier}
                            </span>
                            <span className="text-xs sm:text-sm font-bold text-slate-900 dark:text-white">
                              {skill.name}
                            </span>
                          </div>
                          <span className="text-xs font-mono font-bold text-indigo-600 dark:text-indigo-400">
                            {skill.weight_percentage}% weight
                          </span>
                        </div>

                        {/* Benchmark rubric highlight */}
                        <div className="text-[11px] text-slate-500 dark:text-slate-400 bg-white dark:bg-slate-900/80 p-2.5 rounded-xl border border-slate-100 dark:border-slate-800/80">
                          <strong className="text-slate-700 dark:text-slate-200">Target Standard (L3-L4):</strong>{' '}
                          {skill.rubric_l3 || skill.rubric_l4 || 'Demonstrates clean production reasoning, optimal space/time bounds, and explicit architectural trade-offs.'}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Question Allocation Overview */}
                {activeJob.question_plans && activeJob.question_plans.length > 0 && (
                  <div className="p-4 rounded-2xl bg-indigo-50/50 dark:bg-indigo-950/30 border border-indigo-100 dark:border-indigo-900/50 space-y-2">
                    <div className="flex items-center justify-between text-xs font-bold text-indigo-900 dark:text-indigo-200">
                      <span>Mathematical Interview Budget</span>
                      <span>~2.0 min per cycle</span>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 text-[11px]">
                      {activeJob.question_plans.map((p) => (
                        <div key={p.id} className="bg-white dark:bg-slate-900 p-2 rounded-xl border border-indigo-100/60 dark:border-indigo-900/40">
                          <div className="font-semibold text-slate-800 dark:text-slate-200 truncate">{p.skill_name}</div>
                          <div className="text-indigo-600 dark:text-indigo-400 font-bold">{p.allocated_questions} questions ({p.time_allocation_minutes}m)</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Right Column: Interactive Pre-Flight Hardware Check (5 cols) */}
            <div className="lg:col-span-5 space-y-6">
              <div className="p-6 rounded-3xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm space-y-6 sticky top-20">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                    <h3 className="text-base font-extrabold text-slate-900 dark:text-white">
                      Device Pre-Flight Check
                    </h3>
                  </div>
                  <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300">
                    Step 1 of 2
                  </span>
                </div>

                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Verify your camera, microphone, and audio loopback before entering the real-time AI session.
                </p>

                {/* Camera Preview Box */}
                <div className="space-y-3">
                  <div className="relative aspect-video rounded-2xl bg-slate-950 overflow-hidden flex items-center justify-center border border-slate-800">
                    {cameraActive ? (
                      <div className="w-full h-full relative flex flex-col items-center justify-center bg-slate-900 text-slate-400">
                        {/* Simulated active feed */}
                        <div className="w-20 h-20 rounded-full border-2 border-indigo-500 border-dashed animate-spin-slow flex items-center justify-center">
                          <Camera className="w-8 h-8 text-indigo-400" />
                        </div>
                        <span className="text-xs font-semibold text-emerald-400 mt-2 flex items-center gap-1.5">
                          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                          HD Video Stream Connected (1080p)
                        </span>
                        <div className="absolute bottom-2 left-2 text-[10px] font-mono bg-black/60 px-2 py-0.5 rounded text-white">
                          CANDIDATE: {authUser?.full_name || 'Alex Mercer'}
                        </div>
                      </div>
                    ) : (
                      <div className="text-center p-4 space-y-2">
                        <CameraOff className="w-10 h-10 text-slate-600 mx-auto" />
                        <div className="text-xs text-slate-400">Camera preview is inactive</div>
                      </div>
                    )}

                    <div className="absolute top-2 right-2">
                      <button
                        onClick={toggleCamera}
                        className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all flex items-center gap-1.5 ${
                          cameraActive
                            ? 'bg-rose-600 hover:bg-rose-700 text-white'
                            : 'bg-indigo-600 hover:bg-indigo-700 text-white'
                        }`}
                      >
                        {cameraActive ? <CameraOff className="w-3.5 h-3.5" /> : <Camera className="w-3.5 h-3.5" />}
                        <span>{cameraActive ? 'Turn Off Camera' : 'Test Camera'}</span>
                      </button>
                    </div>
                  </div>
                </div>

                {/* Microphone Level & Audio Test */}
                <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200/70 dark:border-slate-800 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Volume2 className="w-4 h-4 text-indigo-500" />
                      <span className="text-xs font-bold text-slate-800 dark:text-slate-200">Microphone Input Gauge</span>
                    </div>
                    <button
                      onClick={toggleMic}
                      className={`text-xs font-bold px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1 ${
                        micActive
                          ? 'bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300'
                          : 'bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300'
                      }`}
                    >
                      {micActive ? <Mic className="w-3.5 h-3.5" /> : <MicOff className="w-3.5 h-3.5" />}
                      <span>{micActive ? 'Mic Active' : 'Start Mic Test'}</span>
                    </button>
                  </div>

                  {/* Visual volume bar */}
                  <div className="space-y-1">
                    <div className="h-2.5 w-full bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden flex">
                      <div
                        className={`h-full transition-all duration-150 rounded-full ${
                          audioLevel > 70 ? 'bg-amber-500' : 'bg-emerald-500'
                        }`}
                        style={{ width: `${micActive ? audioLevel : 0}%` }}
                      />
                    </div>
                    <div className="flex justify-between text-[10px] text-slate-400 font-mono">
                      <span>Muted</span>
                      <span>Optimal Voice Band</span>
                      <span>Clipping</span>
                    </div>
                  </div>
                </div>

                {/* Pre-flight Checklist */}
                <div className="space-y-2">
                  <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                    Readiness Checklist
                  </div>

                  <div className="space-y-2 text-xs">
                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800/80">
                      <span className="text-slate-700 dark:text-slate-300">Camera & Lighting Verified</span>
                      {cameraActive ? (
                        <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                      ) : (
                        <span className="text-[10px] font-bold text-amber-500">Pending test</span>
                      )}
                    </div>

                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800/80">
                      <span className="text-slate-700 dark:text-slate-300">Microphone Audio Sensitivity</span>
                      {micActive ? (
                        <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                      ) : (
                        <span className="text-[10px] font-bold text-amber-500">Pending test</span>
                      )}
                    </div>

                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800/80">
                      <span className="text-slate-700 dark:text-slate-300">AI Voice Socket Latency</span>
                      <span className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400">12ms (Optimal)</span>
                    </div>
                  </div>
                </div>

                {/* Final Enter Interview Button */}
                <button
                  onClick={() => setInterviewStarted(true)}
                  className="w-full py-3.5 rounded-2xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-sm shadow-md shadow-indigo-600/30 hover:shadow-indigo-600/40 hover:-translate-y-0.5 transition-all flex items-center justify-center gap-2"
                >
                  <Play className="w-4 h-4 fill-white" />
                  <span>Launch Live AI Interview</span>
                </button>
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

      {/* Live Interview Session Modal / Simulation Drawer */}
      {interviewStarted && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4">
          <div className="w-full max-w-2xl bg-white dark:bg-slate-900 rounded-3xl p-6 sm:p-8 shadow-2xl border border-slate-200 dark:border-slate-800 space-y-6 text-center">
            <div className="w-16 h-16 rounded-full bg-indigo-100 dark:bg-indigo-950 flex items-center justify-center mx-auto text-indigo-600 dark:text-indigo-400">
              <Sparkles className="w-8 h-8 animate-pulse" />
            </div>

            <div className="space-y-2">
              <h3 className="text-2xl font-black text-slate-900 dark:text-white">
                AI Voice Interview Room Calibrated
              </h3>
              <p className="text-sm text-slate-500 dark:text-slate-400 max-w-md mx-auto">
                The autonomous AI interviewer is queued with {activeJob?.skills?.length || 4} rubric dimensions for{' '}
                <strong className="text-slate-800 dark:text-slate-200">{activeJob?.job_title}</strong>.
              </p>
            </div>

            <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-800 text-left text-xs space-y-2">
              <div className="font-bold text-slate-700 dark:text-slate-300">Live Session Rules:</div>
              <ul className="space-y-1 text-slate-500 dark:text-slate-400 list-disc list-inside">
                <li>Speak naturally; the AI adapts pacing and probes deeper based on your answers.</li>
                <li>You have {activeJob?.interview_duration_mins || 20} minutes with grace extension permitted.</li>
                <li>Proctoring integrity checks run continuously in the background.</li>
              </ul>
            </div>

            <div className="flex items-center justify-center gap-3 pt-2">
              <button
                onClick={() => setInterviewStarted(false)}
                className="px-5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 text-xs font-bold text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                Return to Portal
              </button>
              <button
                onClick={() => alert("The real-time Gemini Live audio streaming engine will be linked in the next phase!")}
                className="px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold shadow-md shadow-indigo-600/30 transition-all"
              >
                Connect to AI Audio Room
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

