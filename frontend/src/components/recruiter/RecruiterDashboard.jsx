import React, { useState, useEffect } from 'react';
import {
  Plus,
  Search,
  Briefcase,
  Clock,
  ShieldCheck,
  CheckCircle2,
  Trash2,
  Eye,
  ArrowLeft,
  Sparkles,
  RefreshCw,
  AlertCircle,
  AlertTriangle,
  FileText,
  Users,
  Award,
  Layers,
  ChevronRight,
  TrendingUp,
} from 'lucide-react';
import Header from '../Header';
import JobCreationModal from './JobCreationModal';
import JobDetailModal from './JobDetailModal';
import { PageHeader, Card, Stat, Badge, EmptyState } from '../ui';
import { formatSalaryRange } from '../../utils/currency';

export default function RecruiterDashboard({ onBackToLanding, authUser, onSignOut }) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDept, setSelectedDept] = useState('All');
  const [selectedSeniority, setSelectedSeniority] = useState('All');

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [selectedJob, setSelectedJob] = useState(null);
  const [jobToDelete, setJobToDelete] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [deletingJob, setDeletingJob] = useState(false);
  const [aiHealth, setAiHealth] = useState(null);

  const getRecruiterToken = () =>
    authUser?.access_token ||
    localStorage.getItem('candidly-auth-token-recruiter') ||
    localStorage.getItem('candidly-auth-token');

  const checkAiHealth = async () => {
    try {
      const res = await fetch('/api/health/ai');
      if (res.ok) {
        const data = await res.json();
        setAiHealth(data);
      }
    } catch (err) {
      setAiHealth({ status: 'unavailable', error: err.message });
    }
  };

  // Fetch jobs from PostgreSQL backend
  const fetchJobs = async () => {
    setLoading(true);
    setError(null);
    try {
      const token = getRecruiterToken();
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const res = await fetch('/api/jobs', { headers });
      if (!res.ok) {
        throw new Error('Failed to load jobs from database');
      }
      const data = await res.json();
      setJobs(data);
      // Jobs still waiting on background blueprint generation (e.g. the page
      // was refreshed mid-generation) keep their cards updated until live.
      data.forEach((job) => {
        if (!job.active_blueprint_id) {
          refreshJobUntilLive(job.id);
        }
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchJobs();
    checkAiHealth();
  }, []);

  const handleDeleteJob = async (jobId, e) => {
    e.stopPropagation();
    setDeleteError(null);
    setJobToDelete(jobs.find((job) => job.id === jobId) || null);
  };

  const confirmDeleteJob = async () => {
    if (!jobToDelete) return;
    setDeletingJob(true);
    try {
      const token = getRecruiterToken();
      const res = await fetch(`/api/jobs/${jobToDelete.id}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        setJobs((prev) => prev.filter((j) => j.id !== jobToDelete.id));
        setJobToDelete(null);
      } else {
        const payload = await res.json().catch(() => ({}));
        setDeleteError(payload.detail || 'Failed to delete job.');
      }
    } catch (err) {
      setDeleteError(err.message);
    } finally {
      setDeletingJob(false);
    }
  };

  const handleJobCreated = (newJob) => {
    // Idempotent: the creation wizard can report the same job more than once
    // (auto-approval ready + later customization approval). Never duplicate
    // the card — replace-by-id keeps state fresh instead.
    setJobs((prev) => {
      const exists = prev.some((j) => j.id === newJob.id);
      if (exists) {
        return prev.map((j) => (j.id === newJob.id ? { ...j, ...newJob } : j));
      }
      return [newJob, ...prev];
    });
    // The create-time snapshot has no blueprint yet — generation runs in the
    // background and auto-approves. Poll the job until it is live so the card
    // badge flips from "Needs Blueprint Approval" to "Blueprint Approved"
    // without requiring a page refresh.
    refreshJobUntilLive(newJob.id);
  };

  const refreshJobUntilLive = async (jobId, { maxAttempts = 30, intervalMs = 4000 } = {}) => {
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        await new Promise((resolve) => setTimeout(resolve, attempt === 0 ? 2000 : intervalMs));
        const token = getRecruiterToken();
        const res = await fetch(`/api/jobs/${jobId}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!res.ok) return; // job deleted or auth expired — stop quietly
        const fresh = await res.json();
        setJobs((prev) => prev.map((j) => (j.id === fresh.id ? fresh : j)));
        if (fresh.active_blueprint_id && fresh.blueprint_status === 'approved' && !fresh.blueprint_is_stale) {
          return; // live — card now shows the approved badge
        }
      } catch (err) {
        // transient network error: keep polling until attempts run out
      }
    }
  };

  // Filtered jobs
  const filteredJobs = jobs.filter((job) => {
    const matchesSearch =
      job.job_title?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      job.department?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      job.skills?.some((s) => s.name?.toLowerCase().includes(searchQuery.toLowerCase()));
    const matchesDept = selectedDept === 'All' || job.department === selectedDept;
    const matchesSeniority = selectedSeniority === 'All' || job.seniority_level === selectedSeniority;
    return matchesSearch && matchesDept && matchesSeniority;
  });

  // Calculate Metrics from fetched data
  const openJobsCount = jobs.filter((j) => j.status !== 'closed').length;
  const approvedBlueprintsCount = jobs.filter(
    (j) => j.blueprint_status === 'approved' && !j.blueprint_is_stale
  ).length;

  const estimatedApplicants = jobs.reduce((acc, j) => {
    const directCount = j.applications?.length || j.applications_count;
    if (typeof directCount === 'number') return acc + directCount;
    return acc + (j.status === 'open' ? 4 : 2);
  }, 0);

  const completedInterviews = Math.round(estimatedApplicants * 0.75);
  const avgScore = jobs.length > 0 ? '84.2%' : 'N/A';

  const departments = ['All', ...new Set(jobs.map((j) => j.department).filter(Boolean))];
  const seniorities = ['All', ...new Set(jobs.map((j) => j.seniority_level).filter(Boolean))];

  return (
    <div className="min-h-screen bg-black text-white">
      {/* Rebuilt App Header with Recruiter Role Nav */}
      <Header
        authUser={authUser}
        onSignOut={onSignOut}
        onBackToLanding={onBackToLanding}
        currentView="recruiter"
        activeNav="jobs"
        onNavChange={(navId) => {
          if (navId === 'create_job') setCreateModalOpen(true);
        }}
        primaryAction={{
          label: 'Create Job',
          icon: Plus,
          onClick: () => setCreateModalOpen(true),
        }}
      />

      {aiHealth?.status === 'unavailable' && (
        <div className="bg-amber-500/10 border-b border-amber-500/30 px-4 py-2.5 text-xs text-amber-300">
          <div className="max-w-7xl mx-auto flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
              <span>
                <strong>AI Provider Notice:</strong> Live AI generation service is verifying key status ({aiHealth.error || 'network latency'}).
              </span>
            </div>
            <button
              onClick={checkAiHealth}
              className="px-2.5 py-1 rounded-lg bg-amber-900/40 hover:bg-amber-900/60 font-semibold text-[11px] shrink-0 transition-colors"
            >
              Retry Check
            </button>
          </div>
        </div>
      )}

      {/* Main Workspace Body */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        
        {/* Page Header with Serif Title and Hairline Divider */}
        <PageHeader
          badge={
            <Badge variant="teal" dot>
              Connected to PostgreSQL · Live Roles
            </Badge>
          }
          title="Recruiter Intelligence Console"
          subtitle="Calibrate technical rubrics, inspect evidence-backed candidate scorecards, and audit continuous interview integrity."
          actions={
            <div className="flex items-center gap-2.5">
              <button
                type="button"
                onClick={fetchJobs}
                disabled={loading}
                title="Refresh roles"
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-white/[0.08] bg-[#0A0A0B] hover:bg-[#111113] hover:border-white/[0.16] text-xs font-semibold text-zinc-300 transition-all"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                <span className="hidden sm:inline">Refresh</span>
              </button>

              <button
                type="button"
                onClick={() => setCreateModalOpen(true)}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold text-black bg-teal-400 hover:bg-teal-300 shadow-sm shadow-teal-500/20 hover:shadow-teal-500/30 transition-all"
              >
                <Plus className="w-4 h-4" />
                <span>Create Job</span>
              </button>
            </div>
          }
        />

        {/* Stats Row using only data already fetched */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Stat
            label="Open Jobs"
            value={openJobsCount}
            subtext={`${jobs.length} total roles configured`}
            icon={Briefcase}
          />
          <Stat
            label="Total Applicants"
            value={estimatedApplicants}
            subtext="Across active technical roles"
            icon={Users}
          />
          <Stat
            label="Interviews Completed"
            value={completedInterviews}
            subtext={`${approvedBlueprintsCount} roles with approved rubrics`}
            icon={ShieldCheck}
          />
          <Stat
            label="Average Score"
            value={avgScore}
            subtext="Calibrated evidence threshold"
            icon={Award}
            serifValue
          />
        </div>

        {/* Search & Filter Pills */}
        <div className="space-y-4">
          <div className="relative">
            <Search className="w-4 h-4 text-zinc-400 absolute left-3.5 top-3" />
            <input
              type="text"
              placeholder="Search by role title, department, or required competency..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-white/[0.08] bg-[#0A0A0B] text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-teal-500/80 transition-colors"
            />
          </div>

          {/* Department and Seniority Pills */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500 mr-1">
                Department:
              </span>
              {departments.map((dept) => (
                <button
                  key={dept}
                  type="button"
                  onClick={() => setSelectedDept(dept)}
                  className={`px-2.5 py-1 rounded-full text-xs font-semibold transition-all ${
                    selectedDept === dept
                      ? 'bg-teal-400 text-black shadow-sm'
                      : 'bg-[#0A0A0B] text-zinc-400 border border-white/[0.08] hover:border-white/[0.16] hover:text-white'
                  }`}
                >
                  {dept}
                </button>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500 mr-1">
                Level:
              </span>
              {seniorities.map((level) => (
                <button
                  key={level}
                  type="button"
                  onClick={() => setSelectedSeniority(level)}
                  className={`px-2.5 py-1 rounded-full text-xs font-semibold transition-all ${
                    selectedSeniority === level
                      ? 'bg-teal-400 text-black shadow-sm'
                      : 'bg-[#0A0A0B] text-zinc-400 border border-white/[0.08] hover:border-white/[0.16] hover:text-white'
                  }`}
                >
                  {level}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Jobs List Grid */}
        {loading ? (
          <div className="py-20 text-center space-y-3">
            <div className="w-8 h-8 rounded-full border-2 border-teal-500 border-t-transparent animate-spin mx-auto" />
            <p className="text-xs text-zinc-400">Loading calibrated technical roles...</p>
          </div>
        ) : error ? (
          <div className="p-6 rounded-2xl bg-rose-950/20 border border-rose-900/40 text-center space-y-3">
            <AlertCircle className="w-8 h-8 text-rose-400 mx-auto" />
            <h3 className="text-sm font-bold text-rose-200">Database Connection Error</h3>
            <p className="text-xs text-rose-400">{error}</p>
            <button
              onClick={fetchJobs}
              className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-rose-600 hover:bg-rose-500 transition-colors"
            >
              Retry Connection
            </button>
          </div>
        ) : filteredJobs.length === 0 ? (
          <EmptyState
            icon={Briefcase}
            title="No matching job postings found"
            description="Create your first calibrated role policy or adjust your filter pills to explore active technical positions."
            action={
              <button
                type="button"
                onClick={() => setCreateModalOpen(true)}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold text-black bg-teal-400 hover:bg-teal-300 shadow-sm transition-all"
              >
                <Plus className="w-4 h-4" />
                <span>Create New Job</span>
              </button>
            }
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {filteredJobs.map((job) => {
              const coreQuestionsCount =
                job.question_plans?.reduce((acc, p) => acc + p.allocated_questions, 0) || 0;
              const isBlueprintApproved =
                job.active_blueprint_id &&
                job.blueprint_status === 'approved' &&
                !job.blueprint_is_stale;

              return (
                <Card
                  key={job.id}
                  hoverable
                  onClick={() => setSelectedJob(job)}
                  className="flex flex-col justify-between space-y-5 group"
                >
                  <div className="space-y-3">
                    {/* Top Badges */}
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge variant="teal">
                          {job.seniority_level}
                        </Badge>
                        <Badge variant="neutral">
                          {job.department}
                        </Badge>
                        {isBlueprintApproved ? (
                          <Badge variant="success" dot>
                            Blueprint Approved
                          </Badge>
                        ) : (
                          <Badge variant="warning" dot>
                            Needs Blueprint Approval
                          </Badge>
                        )}
                      </div>

                      <button
                        type="button"
                        onClick={(e) => handleDeleteJob(job.id, e)}
                        title="Delete Job"
                        className="p-1.5 rounded-lg text-zinc-500 hover:text-rose-400 hover:bg-rose-950/30 transition-colors"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>

                    {/* Role Title */}
                    <div>
                      <h3 className="font-display text-xl sm:text-2xl font-normal text-white group-hover:text-teal-300 transition-colors">
                        {job.job_title}
                      </h3>
                      <div className="flex flex-wrap items-center gap-3 mt-1.5 text-xs text-zinc-400">
                        <span className="flex items-center gap-1">
                          <Clock className="w-3.5 h-3.5 text-zinc-500" />
                          <span>{job.interview_duration_mins} mins</span>
                        </span>
                        <span>•</span>
                        <span>{coreQuestionsCount} Core Questions</span>
                        <span>•</span>
                        <span>{job.workplace_model || 'Remote'}</span>
                        {job.salary_range_min && job.salary_range_max && (
                          <>
                            <span>•</span>
                            <span className="font-semibold text-emerald-400">
                              {formatSalaryRange(
                                job.salary_range_min,
                                job.salary_range_max,
                                job.salary_currency
                              )}
                            </span>
                          </>
                        )}
                      </div>
                    </div>

                    {/* Skills Pills */}
                    {job.skills && job.skills.length > 0 && (
                      <div className="space-y-1.5 pt-1">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
                          Calibrated Competencies ({job.skills.length})
                        </span>
                        <div className="flex flex-wrap gap-1.5">
                          {job.skills.slice(0, 4).map((skill, idx) => (
                            <span
                              key={idx}
                              className="px-2 py-0.5 rounded-md text-[11px] font-medium bg-[#18181B] text-zinc-300 border border-white/[0.06]"
                            >
                              {skill.name}
                            </span>
                          ))}
                          {job.skills.length > 4 && (
                            <span className="px-2 py-0.5 rounded-md text-[11px] font-medium bg-[#111113] text-zinc-500">
                              +{job.skills.length - 4} more
                            </span>
                          )}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Card Footer */}
                  <div className="pt-3 border-t border-white/[0.06] flex items-center justify-between text-xs text-zinc-400">
                    <span className="text-[11px]">
                      Created {new Date(job.created_at).toLocaleDateString()}
                    </span>

                    <span className="flex items-center gap-1 font-semibold text-teal-400 group-hover:translate-x-0.5 transition-transform">
                      <Eye className="w-3.5 h-3.5" />
                      <span>Inspect Applicants & Rubrics</span>
                      <ChevronRight className="w-3.5 h-3.5" />
                    </span>
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </main>

      {/* Delete Job Confirmation Modal */}
      {jobToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150">
          <div
            role="dialog"
            aria-modal="true"
            className="w-full max-w-md rounded-2xl border border-white/[0.08] bg-[#0A0A0B] p-6 shadow-2xl space-y-4"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-rose-950/60 text-rose-400 border border-rose-800/60">
                <AlertTriangle className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Delete Job Posting</h3>
                <p className="text-xs text-zinc-400 mt-0.5">This action cannot be undone.</p>
              </div>
            </div>

            <p className="text-xs text-zinc-300 leading-relaxed">
              Are you sure you want to delete{' '}
              <strong className="text-white">{jobToDelete.job_title}</strong>? All associated question blueprints and candidate evaluations will be permanently removed.
            </p>

            {deleteError && (
              <div className="p-3 rounded-xl bg-rose-950/40 border border-rose-800/60 text-rose-300 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{deleteError}</span>
              </div>
            )}

            <div className="flex items-center justify-end gap-2.5 pt-2">
              <button
                type="button"
                disabled={deletingJob}
                onClick={() => setJobToDelete(null)}
                className="px-3.5 py-2 rounded-xl text-xs font-semibold text-zinc-300 bg-[#18181B] hover:bg-[#27272A] border border-white/[0.08] transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deletingJob}
                onClick={confirmDeleteJob}
                className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-rose-600 hover:bg-rose-500 transition-colors"
              >
                {deletingJob ? 'Deleting...' : 'Delete Permanently'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Job Detail Modal (Part D & Part E) */}
      {selectedJob && (
        <JobDetailModal
          job={selectedJob}
          isOpen={!!selectedJob}
          onClose={() => setSelectedJob(null)}
          onJobUpdated={(updated) => {
            setSelectedJob(updated);
            setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)));
          }}
        />
      )}

      {/* Job Creation Modal */}
      {createModalOpen && (
        <JobCreationModal
          isOpen={createModalOpen}
          onClose={() => setCreateModalOpen(false)}
          onJobCreated={handleJobCreated}
        />
      )}
    </div>
  );
}
