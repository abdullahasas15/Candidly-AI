import React, { useState, useEffect } from 'react';
import {
  Plus, Search, Filter, Briefcase, Clock, ShieldCheck, CheckCircle2,
  Trash2, Eye, ArrowLeft, Sparkles, RefreshCw, AlertCircle, FileText, LogOut
} from 'lucide-react';
import Logo from '../Logo';
import JobCreationModal from './JobCreationModal';
import JobDetailModal from './JobDetailModal';
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

  // Fetch jobs from PostgreSQL backend
  const fetchJobs = async () => {
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem('candidly-auth-token');
      const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
      const res = await fetch('/api/jobs', { headers });
      if (!res.ok) {
        throw new Error('Failed to load jobs from database');
      }
      const data = await res.json();
      setJobs(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchJobs();
  }, []);

  const handleDeleteJob = async (jobId, e) => {
    e.stopPropagation();
    if (!window.confirm('Are you sure you want to delete this job posting?')) return;
    try {
      const token = localStorage.getItem('candidly-auth-token');
      const res = await fetch(`/api/jobs/${jobId}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      if (res.ok) {
        setJobs((prev) => prev.filter((j) => j.id !== jobId));
      }
    } catch (err) {
      alert('Failed to delete job: ' + err.message);
    }
  };

  const handleJobCreated = (newJob) => {
    setJobs((prev) => [newJob, ...prev]);
  };

  // Filtered jobs
  const filteredJobs = jobs.filter((job) => {
    const matchesSearch =
      job.job_title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      job.department.toLowerCase().includes(searchQuery.toLowerCase()) ||
      job.skills?.some((s) => s.name.toLowerCase().includes(searchQuery.toLowerCase()));
    const matchesDept = selectedDept === 'All' || job.department === selectedDept;
    const matchesSeniority = selectedSeniority === 'All' || job.seniority_level === selectedSeniority;
    return matchesSearch && matchesDept && matchesSeniority;
  });

  // Calculate Summary Metrics
  const totalQuestionsCapacity = jobs.reduce((acc, j) => {
    return acc + (j.question_plans?.reduce((pAcc, p) => pAcc + p.allocated_questions, 0) || 0);
  }, 0);

  const totalP0Skills = jobs.reduce((acc, j) => {
    return acc + (j.skills?.filter((s) => s.priority_tier === 'P0').length || 0);
  }, 0);

  const departments = ['All', ...new Set(jobs.map((j) => j.department).filter(Boolean))];
  const seniorities = ['All', ...new Set(jobs.map((j) => j.seniority_level).filter(Boolean))];

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-[#0B0F19] text-slate-900 dark:text-white transition-colors">
      
      {/* Top Navigation Bar */}
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
              <div className="flex flex-col">
                <div className="flex items-center gap-1.5">
                  <span className="font-extrabold text-base tracking-tight text-slate-900 dark:text-white">
                    Candidly<span className="text-indigo-600 dark:text-indigo-400">.AI</span>
                  </span>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 border border-indigo-200/60 dark:border-indigo-800/60">
                    RECRUITER WORKSPACE
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {authUser && (
              <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-100 dark:bg-slate-800 text-xs font-semibold">
                <span className="w-2 h-2 rounded-full bg-indigo-500" />
                <span className="text-slate-800 dark:text-slate-200">{authUser.full_name}</span>
                {authUser.company_name && (
                  <span className="text-[10px] text-slate-500 font-normal">({authUser.company_name})</span>
                )}
              </div>
            )}

            <button
              onClick={fetchJobs}
              disabled={loading}
              title="Refresh Jobs"
              className="p-2 rounded-xl text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>

            <button
              onClick={() => setCreateModalOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-700 shadow-md shadow-indigo-600/20 hover:-translate-y-0.5 transition-all"
            >
              <Plus className="w-4 h-4" />
              <span>Create New Role</span>
            </button>

            {onSignOut && (
              <button
                onClick={onSignOut}
                title="Sign Out"
                className="p-2 rounded-xl text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors"
              >
                <LogOut className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Main Workspace Body */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        
        {/* Workspace Title & Greeting */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-slate-900 dark:text-white">
              Recruiter Intelligence Console
            </h1>
            <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 mt-1">
              Active roles connected to local PostgreSQL database (<code className="font-mono text-indigo-600 dark:text-indigo-400">Candidly AI</code>).
            </p>
          </div>

          {/* Quick Database Status Pill */}
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-200/70 dark:border-emerald-800 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span>PostgreSQL: Connected (localhost:5432)</span>
          </div>
        </div>

        {/* 4 Stat Overview Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm space-y-1">
            <div className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              Active Job Postings
            </div>
            <div className="text-2xl sm:text-3xl font-black text-slate-900 dark:text-white">
              {jobs.length}
            </div>
            <div className="text-[11px] text-slate-500">Autonomous roles deployed</div>
          </div>

          <div className="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm space-y-1">
            <div className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              Core Questions Planned
            </div>
            <div className="text-2xl sm:text-3xl font-black text-indigo-600 dark:text-indigo-400">
              {totalQuestionsCapacity}
            </div>
            <div className="text-[11px] text-slate-500">Allocated via Part 2 math</div>
          </div>

          <div className="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm space-y-1">
            <div className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              P0 Mandatory Competencies
            </div>
            <div className="text-2xl sm:text-3xl font-black text-rose-600 dark:text-rose-400">
              {totalP0Skills}
            </div>
            <div className="text-[11px] text-slate-500">Guaranteed question coverage</div>
          </div>

          <div className="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm space-y-1">
            <div className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              Avg Session Duration
            </div>
            <div className="text-2xl sm:text-3xl font-black text-emerald-600 dark:text-emerald-400">
              {jobs.length > 0 ? Math.round(jobs.reduce((a, b) => a + b.interview_duration_mins, 0) / jobs.length) : 20}m
            </div>
            <div className="text-[11px] text-slate-500">Fixed 3.5m overhead applied</div>
          </div>
        </div>

        {/* Filter & Search Bar */}
        <div className="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm flex flex-col md:flex-row items-center gap-3">
          <div className="relative flex-1 w-full">
            <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-3" />
            <input
              type="text"
              placeholder="Search by role title, department, or required skill..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div className="flex items-center gap-2 w-full md:w-auto">
            <select
              value={selectedDept}
              onChange={(e) => setSelectedDept(e.target.value)}
              className="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-300"
            >
              {departments.map((d) => (
                <option key={d} value={d}>Dept: {d}</option>
              ))}
            </select>

            <select
              value={selectedSeniority}
              onChange={(e) => setSelectedSeniority(e.target.value)}
              className="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-300"
            >
              {seniorities.map((s) => (
                <option key={s} value={s}>Level: {s}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Jobs List Grid */}
        {loading ? (
          <div className="py-20 text-center space-y-3">
            <div className="w-8 h-8 rounded-full border-2 border-indigo-600 border-t-transparent animate-spin mx-auto" />
            <p className="text-xs text-slate-500">Querying PostgreSQL database...</p>
          </div>
        ) : error ? (
          <div className="p-6 rounded-2xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 text-center space-y-3">
            <AlertCircle className="w-8 h-8 text-rose-500 mx-auto" />
            <h3 className="text-sm font-bold text-rose-800 dark:text-rose-200">Database Connection Error</h3>
            <p className="text-xs text-rose-600 dark:text-rose-300">{error}</p>
            <button
              onClick={fetchJobs}
              className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-rose-600 hover:bg-rose-700"
            >
              Retry Connection
            </button>
          </div>
        ) : filteredJobs.length === 0 ? (
          <div className="p-12 rounded-3xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-center space-y-4">
            <div className="w-14 h-14 rounded-2xl bg-indigo-50 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400 flex items-center justify-center mx-auto">
              <Briefcase className="w-7 h-7" />
            </div>
            <h3 className="text-base font-bold text-slate-900 dark:text-white">
              No matching job postings found
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 max-w-sm mx-auto">
              Create your first calibrated role policy to start conducting autonomous, evidence-backed interviews.
            </p>
            <button
              onClick={() => setCreateModalOpen(true)}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-700 shadow-sm"
            >
              <Plus className="w-4 h-4" />
              <span>Create New Job</span>
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {filteredJobs.map((job) => {
              const coreQuestionsCount = job.question_plans?.reduce((acc, p) => acc + p.allocated_questions, 0) || 0;
              return (
                <div
                  key={job.id}
                  onClick={() => setSelectedJob(job)}
                  className="group p-6 rounded-3xl bg-white dark:bg-[#111827] border border-slate-200 dark:border-slate-800 hover:border-indigo-500/60 dark:hover:border-indigo-500/60 transition-all duration-200 shadow-sm hover:shadow-xl hover:-translate-y-1 cursor-pointer flex flex-col justify-between space-y-5"
                >
                  <div className="space-y-3">
                    {/* Top Badges */}
                    <div className="flex items-center justify-between">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 border border-indigo-200/60 dark:border-indigo-800">
                          {job.seniority_level}
                        </span>
                        <span className="px-2 py-0.5 rounded-md text-[11px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                          {job.department}
                        </span>
                      </div>

                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={(e) => handleDeleteJob(job.id, e)}
                          title="Delete Job"
                          className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/50 transition-colors"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>

                    {/* Job Title */}
                    <h3 className="text-lg font-bold text-slate-900 dark:text-white group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors">
                      {job.job_title}
                    </h3>

                    {/* Metadata strip */}
                    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
                      <span className="flex items-center gap-1 font-semibold text-slate-700 dark:text-slate-300">
                        <Clock className="w-3.5 h-3.5 text-indigo-500" />
                        {job.interview_duration_mins} mins
                      </span>
                      <span>•</span>
                      <span className="font-semibold text-indigo-600 dark:text-indigo-400">
                        {coreQuestionsCount} Core Questions
                      </span>
                      <span>•</span>
                      <span>{job.workplace_model}</span>
                      {job.salary_range_min && (
                        <>
                          <span>•</span>
                          <span className="font-semibold text-emerald-600 dark:text-emerald-400">
                            {formatSalaryRange(job.salary_range_min, job.salary_range_max, job.salary_currency)}
                          </span>
                        </>
                      )}
                    </div>

                    {/* Skills & Weight breakdown */}
                    <div className="space-y-1.5 pt-2 border-t border-slate-100 dark:border-slate-800">
                      <div className="flex items-center justify-between text-[11px] font-bold text-slate-400 uppercase">
                        <span>Calibrated Competencies</span>
                        <span>{job.skills?.length || 0} Total</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {job.skills?.slice(0, 4).map((s, sIdx) => (
                          <span
                            key={sIdx}
                            className={`px-2 py-0.5 rounded-md text-[10px] font-semibold flex items-center gap-1 ${
                              s.priority_tier === 'P0'
                                ? 'bg-rose-50 dark:bg-rose-950/60 text-rose-700 dark:text-rose-300 border border-rose-200/60 dark:border-rose-900'
                                : 'bg-slate-50 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700'
                            }`}
                          >
                            <span>{s.name}</span>
                            <span className="font-bold opacity-70">({s.weight_percentage}%)</span>
                          </span>
                        ))}
                        {job.skills?.length > 4 && (
                          <span className="px-2 py-0.5 rounded-md text-[10px] bg-slate-100 dark:bg-slate-800 text-slate-500">
                            +{job.skills.length - 4} more
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Card Bottom Bar */}
                  <div className="pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs">
                    <span className="text-[11px] text-slate-400">
                      Created {new Date(job.created_at).toLocaleDateString()}
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedJob(job);
                      }}
                      className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 font-bold hover:bg-indigo-100 transition-colors"
                    >
                      <Eye className="w-3.5 h-3.5" />
                      <span>Inspect Applicants & Rubrics</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

      </main>

      {/* Modals */}
      <JobCreationModal
        isOpen={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        onJobCreated={handleJobCreated}
      />

      <JobDetailModal
        job={selectedJob}
        isOpen={!!selectedJob}
        onClose={() => setSelectedJob(null)}
      />

    </div>
  );
}
