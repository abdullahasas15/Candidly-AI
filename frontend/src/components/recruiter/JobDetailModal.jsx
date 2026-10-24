import React, { useState, useEffect } from 'react';
import {
  X, Award, Clock, ShieldCheck, CheckCircle2, ChevronRight, Layers,
  FileText, AlertCircle, Users, DollarSign, AlertTriangle, Eye, ArrowRight,
  RefreshCw, Check, Sparkles, Filter, Calendar
} from 'lucide-react';
import ApplicantDetailModal from './ApplicantDetailModal';
import { Badge, Card } from '../ui';
import { formatMoney } from '../../utils/currency';

const BlueprintReviewEditor = React.lazy(() => import('./BlueprintReviewEditor'));

export default function JobDetailModal({ job, isOpen, onClose, onJobUpdated }) {
  if (!isOpen || !job) return null;

  const [activeTab, setActiveTab] = useState('overview'); // 'overview' | 'blueprint' | 'applicants'
  const [applicants, setApplicants] = useState([]);
  const [loadingApplicants, setLoadingApplicants] = useState(false);
  const [selectedApplicant, setSelectedApplicant] = useState(null);
  const [sortBy, setSortBy] = useState('score_desc');
  const [filterVerdict, setFilterVerdict] = useState('all');

  const fetchApplicants = async () => {
    if (!job?.id) return;
    setLoadingApplicants(true);
    try {
      const token = localStorage.getItem('candidly-auth-token');
      const res = await fetch(`/api/jobs/${job.id}/applications`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data = await res.json();
        setApplicants(data);
      }
    } catch (err) {
      console.error('Error fetching job applications:', err);
    } finally {
      setLoadingApplicants(false);
    }
  };

  useEffect(() => {
    fetchApplicants();
  }, [job?.id]);

  const handleApplicantUpdated = (updatedApp) => {
    setApplicants((prev) =>
      prev.map((app) => (app.id === updatedApp.id ? updatedApp : app))
    );
  };

  const sortedApplicants = [...applicants]
    .filter((app) => {
      if (filterVerdict !== 'all') {
        const v = app.evaluation?.verdict || '';
        if (filterVerdict === 'HIRE' && (!v.includes('HIRE') || v.includes('NO'))) return false;
        if (filterVerdict === 'BORDERLINE' && v !== 'BORDERLINE') return false;
        if (filterVerdict === 'NO_HIRE' && !v.includes('NO')) return false;
      }
      return true;
    })
    .sort((a, b) => {
      if (sortBy === 'score_desc') {
        const sa = a.evaluation?.overall_score ?? -1;
        const sb = b.evaluation?.overall_score ?? -1;
        return sb - sa;
      }
      return new Date(b.applied_at) - new Date(a.applied_at);
    });

  // Circular score ring component
  const ScoreRing = ({ score }) => {
    const hasScore = score !== undefined && score !== null;
    const val = hasScore ? Math.round(score) : 0;
    const strokeDash = 2 * Math.PI * 18;
    const strokeOffset = strokeDash - (strokeDash * val) / 100;
    const colorClass =
      val >= 80 ? 'text-teal-400 stroke-teal-400' : val >= 60 ? 'text-amber-400 stroke-amber-400' : 'text-rose-400 stroke-rose-400';

    return (
      <div className="relative flex h-12 w-12 shrink-0 items-center justify-center">
        <svg className="h-12 w-12 -rotate-90 transform" viewBox="0 0 44 44">
          <circle
            cx="22"
            cy="22"
            r="18"
            className="stroke-white/[0.08]"
            strokeWidth="3.5"
            fill="transparent"
          />
          {hasScore && (
            <circle
              cx="22"
              cy="22"
              r="18"
              className={colorClass}
              strokeWidth="3.5"
              strokeDasharray={strokeDash}
              strokeDashoffset={strokeOffset}
              strokeLinecap="round"
              fill="transparent"
            />
          )}
        </svg>
        <span className="absolute font-mono text-[11px] font-bold text-white">
          {hasScore ? val : '—'}
        </span>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-md animate-in fade-in duration-150">
      <div className="relative w-full max-w-5xl max-h-[92vh] flex flex-col rounded-3xl bg-[#0A0A0B] border border-white/[0.08] shadow-2xl overflow-hidden">
        
        {/* Modal Header */}
        <div className="p-6 border-b border-white/[0.08] bg-[#0A0A0B] flex items-start justify-between gap-4">
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="teal">{job.seniority_level}</Badge>
              <Badge variant="neutral">{job.department}</Badge>
              <Badge variant="outline">{job.workplace_model || 'Remote'}</Badge>
              {job.salary_range_min && (
                <span className="text-xs font-semibold text-emerald-400 flex items-center gap-1">
                  <DollarSign className="w-3 h-3" />
                  <span>
                    {formatMoney(job.salary_range_min, job.salary_currency)} - {formatMoney(job.salary_range_max, job.salary_currency)}
                  </span>
                </span>
              )}
            </div>
            
            <h2 className="font-display text-2xl sm:text-3xl font-normal text-white tracking-tight">
              {job.job_title}
            </h2>

            <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-400">
              <span className="flex items-center gap-1">
                <Clock className="w-3.5 h-3.5 text-zinc-500" />
                <span>{job.interview_duration_mins} mins</span>
              </span>
              <span>•</span>
              <span>Integrity: Tier {job.integrity_policy_tier}</span>
              <span>•</span>
              <span className="text-teal-400 font-semibold">
                {applicants.length} Total Applicants
              </span>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-xl text-zinc-400 hover:text-white bg-[#18181B] border border-white/[0.08] hover:border-white/[0.16] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 3 Main Tabs: Overview / Blueprint / Applicants */}
        <div className="flex border-b border-white/[0.08] px-6 bg-[#000000]/40 text-xs font-bold">
          <button
            type="button"
            onClick={() => setActiveTab('overview')}
            className={`py-3.5 px-4 border-b-2 transition-all flex items-center gap-2 ${
              activeTab === 'overview'
                ? 'border-teal-400 text-teal-300'
                : 'border-transparent text-zinc-400 hover:text-white'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Overview</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('blueprint')}
            className={`py-3.5 px-4 border-b-2 transition-all flex items-center gap-2 ${
              activeTab === 'blueprint'
                ? 'border-teal-400 text-teal-300'
                : 'border-transparent text-zinc-400 hover:text-white'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Blueprint & Rubric</span>
            {job.blueprint_status === 'approved' && (
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            )}
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('applicants')}
            className={`py-3.5 px-4 border-b-2 transition-all flex items-center gap-2 ${
              activeTab === 'applicants'
                ? 'border-teal-400 text-teal-300'
                : 'border-transparent text-zinc-400 hover:text-white'
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            <span>Applicants ({applicants.length})</span>
          </button>
        </div>

        {/* Tab Content Body */}
        <div className="p-6 overflow-y-auto flex-1 text-xs space-y-6">
          
          {/* TAB 1: OVERVIEW */}
          {activeTab === 'overview' && (
            <div className="space-y-6">
              <div className="rounded-2xl border border-white/[0.08] bg-[#111113] p-5 space-y-3">
                <h3 className="font-display text-lg font-normal text-white">
                  Role Description & Scope
                </h3>
                <p className="text-zinc-300 leading-relaxed text-xs whitespace-pre-line">
                  {job.job_description || 'No job description provided for this role.'}
                </p>
              </div>

              {/* Competencies Grid */}
              <div className="space-y-3">
                <h4 className="font-bold text-xs uppercase tracking-wider text-zinc-400">
                  Target Competencies & Calibrated Rubrics
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {(job.skills || []).map((skill, sIdx) => (
                    <div
                      key={sIdx}
                      className="rounded-xl border border-white/[0.06] bg-[#111113] p-3.5 space-y-1.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-white text-xs">{skill.name}</span>
                        <Badge
                          variant={skill.priority_tier === 'P0' ? 'error' : 'teal'}
                          size="sm"
                        >
                          {skill.priority_tier || 'P1'}
                        </Badge>
                      </div>
                      <p className="text-[11px] text-zinc-400 leading-relaxed line-clamp-2">
                        {skill.description || 'Core technical capability evaluation.'}
                      </p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Parameters Breakdown */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
                <div className="rounded-xl border border-white/[0.06] bg-[#111113] p-3">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
                    Duration
                  </div>
                  <div className="mt-1 font-semibold text-white">
                    {job.interview_duration_mins} Minutes
                  </div>
                </div>

                <div className="rounded-xl border border-white/[0.06] bg-[#111113] p-3">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
                    Interviewer Tone
                  </div>
                  <div className="mt-1 font-semibold text-white capitalize">
                    {job.interviewer_tone || 'Professional'}
                  </div>
                </div>

                <div className="rounded-xl border border-white/[0.06] bg-[#111113] p-3">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
                    Follow-Up Depth
                  </div>
                  <div className="mt-1 font-semibold text-white">
                    Max L{job.max_followup_depth || 3} Probing
                  </div>
                </div>

                <div className="rounded-xl border border-white/[0.06] bg-[#111113] p-3">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
                    Pacing Strictness
                  </div>
                  <div className="mt-1 font-semibold text-white capitalize">
                    {job.pacing_strictness || 'Adaptive'}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: BLUEPRINT */}
          {activeTab === 'blueprint' && (
            <div className="space-y-4">
              <React.Suspense
                fallback={
                  <div className="p-12 text-center text-teal-400 font-semibold space-y-2">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto text-teal-400" />
                    <p className="text-xs text-zinc-400">Loading Blueprint Editor...</p>
                  </div>
                }
              >
                <BlueprintReviewEditor
                  job={job}
                  jobId={job.id}
                  onApproved={(approvedBp) => {
                    if (onJobUpdated) onJobUpdated({ ...job, blueprint_status: 'approved', active_blueprint_id: approvedBp?.id });
                  }}
                  onBlueprintApproved={(approvedBp) => {
                    if (onJobUpdated) onJobUpdated({ ...job, blueprint_status: 'approved', active_blueprint_id: approvedBp?.id });
                  }}
                />
              </React.Suspense>
            </div>
          )}

          {/* TAB 3: APPLICANTS RANKED LIST */}
          {activeTab === 'applicants' && (
            <div className="space-y-4">
              {/* Filter & Sort Bar */}
              <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-2xl border border-white/[0.08] bg-[#111113] text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
                    Sort:
                  </span>
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value)}
                    className="rounded-lg border border-white/[0.08] bg-[#18181B] px-2.5 py-1 text-white font-semibold focus:outline-none"
                  >
                    <option value="score_desc">Ranked by Evidence Score</option>
                    <option value="date_desc">Application Date (Newest)</option>
                  </select>
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
                    Verdict:
                  </span>
                  <select
                    value={filterVerdict}
                    onChange={(e) => setFilterVerdict(e.target.value)}
                    className="rounded-lg border border-white/[0.08] bg-[#18181B] px-2.5 py-1 text-white font-semibold focus:outline-none"
                  >
                    <option value="all">All Verdicts</option>
                    <option value="HIRE">Hire Recommended</option>
                    <option value="BORDERLINE">Borderline</option>
                    <option value="NO_HIRE">No Hire</option>
                  </select>
                </div>
              </div>

              {/* Applicants Ranked List */}
              {loadingApplicants ? (
                <div className="py-16 text-center space-y-2">
                  <RefreshCw className="w-5 h-5 animate-spin text-teal-400 mx-auto" />
                  <p className="text-zinc-400">Loading applicant pipeline...</p>
                </div>
              ) : sortedApplicants.length === 0 ? (
                <div className="p-10 rounded-2xl border border-white/[0.08] bg-[#111113] text-center space-y-2">
                  <Users className="w-7 h-7 text-zinc-500 mx-auto" />
                  <p className="font-semibold text-white">No applicants found</p>
                  <p className="text-zinc-500 text-xs">
                    Candidate applications submitted for this role will appear ranked by score here.
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  {sortedApplicants.map((app, rankIdx) => {
                    const score = app.evaluation?.overall_score;
                    const verdict = app.evaluation?.verdict;
                    const statusVariant =
                      app.status === 'hired'
                        ? 'success'
                        : app.status === 'rejected'
                        ? 'error'
                        : app.status === 'interviewed'
                        ? 'teal'
                        : 'neutral';

                    return (
                      <div
                        key={app.id}
                        onClick={() => setSelectedApplicant(app)}
                        className="group flex items-center justify-between gap-4 p-4 rounded-2xl border border-white/[0.06] bg-[#111113] hover:border-white/[0.16] hover:bg-[#18181B] transition-all cursor-pointer"
                      >
                        {/* Left: Rank & Candidate Details */}
                        <div className="flex items-center gap-4 min-w-0">
                          <span className="font-mono text-sm font-bold text-zinc-500 w-6 text-center">
                            #{rankIdx + 1}
                          </span>

                          <ScoreRing score={score} />

                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <h4 className="font-bold text-sm text-white group-hover:text-teal-300 transition-colors truncate">
                                {app.full_name}
                              </h4>
                              {verdict && (
                                <Badge
                                  size="sm"
                                  variant={
                                    verdict.includes('HIRE') && !verdict.includes('NO')
                                      ? 'success'
                                      : verdict === 'BORDERLINE'
                                      ? 'warning'
                                      : 'error'
                                  }
                                >
                                  {verdict.replace(/_/g, ' ')}
                                </Badge>
                              )}
                            </div>
                            <p className="text-xs text-zinc-400 truncate">{app.email}</p>
                            <div className="flex items-center gap-2 mt-1 text-[11px] text-zinc-500">
                              <span className="flex items-center gap-1">
                                <Calendar className="w-3 h-3" />
                                <span>{new Date(app.applied_at).toLocaleDateString()}</span>
                              </span>
                              {app.interview_duration && (
                                <>
                                  <span>•</span>
                                  <span>{app.interview_duration}</span>
                                </>
                              )}
                            </div>
                          </div>
                        </div>

                        {/* Right: Status & Action Button */}
                        <div className="flex items-center gap-3 shrink-0">
                          <Badge variant={statusVariant} size="sm">
                            {app.status?.replace(/_/g, ' ') || 'Submitted'}
                          </Badge>

                          <button
                            type="button"
                            className="p-2 rounded-xl text-teal-400 hover:text-white bg-teal-950/40 border border-teal-800/60 group-hover:bg-teal-400 group-hover:text-black transition-all"
                            aria-label="Inspect Scorecard"
                          >
                            <ChevronRight className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Applicant Detail Modal (Scorecard view) */}
      {selectedApplicant && (
        <ApplicantDetailModal
          application={selectedApplicant}
          isOpen={!!selectedApplicant}
          onClose={() => setSelectedApplicant(null)}
          onApplicationUpdated={handleApplicantUpdated}
        />
      )}
    </div>
  );
}
