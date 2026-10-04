import React, { useState, useEffect } from 'react';
import {
  X, Award, Clock, ShieldCheck, CheckCircle2, ChevronRight, Layers,
  FileText, AlertCircle, Users, DollarSign, AlertTriangle, Eye, ArrowRight,
  RefreshCw, Check
} from 'lucide-react';
import ApplicantDetailModal from './ApplicantDetailModal';
import { formatMoney } from '../../utils/currency';

export default function JobDetailModal({ job, isOpen, onClose }) {
  if (!isOpen || !job) return null;

  const [activeTab, setActiveTab] = useState('applicants');
  const [applicants, setApplicants] = useState([]);
  const [loadingApplicants, setLoadingApplicants] = useState(false);
  const [selectedApplicant, setSelectedApplicant] = useState(null);

  const fetchApplicants = async () => {
    if (!job?.id) return;
    setLoadingApplicants(true);
    try {
      const token = localStorage.getItem('candidly-auth-token');
      const res = await fetch(`/api/jobs/${job.id}/applications`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
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

  const getStatusBadge = (status) => {
    switch (status) {
      case 'ready_for_interview':
        return 'bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800';
      case 'under_review':
        return 'bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800';
      case 'interviewed':
        return 'bg-purple-50 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-800';
      case 'hired':
        return 'bg-teal-50 dark:bg-teal-950 text-teal-700 dark:text-teal-300 border-teal-200 dark:border-teal-800';
      case 'rejected':
        return 'bg-rose-50 dark:bg-rose-950 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800';
      default:
        return 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700';
    }
  };

  const unresolvedFlagsCount = applicants.reduce((acc, app) => {
    return acc + (app.discrepancy_flags?.filter((f) => !f.reviewed_by_recruiter).length || 0);
  }, 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-slate-950/70 backdrop-blur-sm animate-fadeIn">
      <div className="relative w-full max-w-5xl max-h-[92vh] flex flex-col rounded-3xl bg-white dark:bg-[#111827] border border-slate-200 dark:border-slate-800 shadow-2xl overflow-hidden">
        
        {/* Header */}
        <div className="p-6 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 flex items-start justify-between">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-indigo-50 dark:bg-indigo-950/80 text-indigo-700 dark:text-indigo-300 border border-indigo-200/60 dark:border-indigo-800">
                {job.seniority_level}
              </span>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
                {job.department}
              </span>
              <span className="px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300">
                {job.workplace_model} · {job.employment_type}
              </span>
              {job.salary_range_min && (
                <span className="px-2 py-0.5 rounded-md text-xs font-bold bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 flex items-center gap-1">
                  <DollarSign className="w-3 h-3" />
                  <span>{formatMoney(job.salary_range_min, job.salary_currency)} - {formatMoney(job.salary_range_max, job.salary_currency)}</span>
                </span>
              )}
            </div>
            <h2 className="text-2xl font-extrabold text-slate-900 dark:text-white tracking-tight">
              {job.job_title}
            </h2>
            <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
              <span className="flex items-center gap-1">
                <Clock className="w-3.5 h-3.5 text-indigo-500" />
                Duration: {job.interview_duration_mins} mins
              </span>
              <span>•</span>
              <span className="flex items-center gap-1">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
                Integrity Tier: {job.integrity_policy_tier}
              </span>
              <span>•</span>
              <span>Pacing: {job.pacing_strictness}</span>
              <span>•</span>
              <span className="font-semibold text-indigo-600 dark:text-indigo-400">
                {applicants.length} Total Applicants
              </span>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-xl text-slate-400 hover:text-slate-700 dark:hover:text-white bg-slate-100 dark:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex overflow-x-auto border-b border-slate-200 dark:border-slate-800 px-6 bg-slate-50/50 dark:bg-slate-900/40 text-xs font-bold scrollbar-none">
          <button
            onClick={() => setActiveTab('applicants')}
            className={`py-3 px-4 border-b-2 transition-all flex items-center gap-1.5 whitespace-nowrap ${
              activeTab === 'applicants'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-slate-900/60'
                : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            <span>Applicants ({applicants.length})</span>
            {unresolvedFlagsCount > 0 && (
              <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
            )}
          </button>

          <button
            onClick={() => setActiveTab('skills')}
            className={`py-3 px-4 border-b-2 transition-all whitespace-nowrap ${
              activeTab === 'skills'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-slate-900/60'
                : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            Competencies & Rubrics ({job.skills?.length || 0})
          </button>

          <button
            onClick={() => setActiveTab('plan')}
            className={`py-3 px-4 border-b-2 transition-all whitespace-nowrap ${
              activeTab === 'plan'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-slate-900/60'
                : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            Mathematical Plan ({job.question_plans?.length || 0})
          </button>

          <button
            onClick={() => setActiveTab('criteria')}
            className={`py-3 px-4 border-b-2 transition-all whitespace-nowrap ${
              activeTab === 'criteria'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-slate-900/60'
                : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            Academic & Experience Criteria
          </button>

          <button
            onClick={() => setActiveTab('custom')}
            className={`py-3 px-4 border-b-2 transition-all whitespace-nowrap ${
              activeTab === 'custom'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-slate-900/60'
                : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            Custom Questions ({job.custom_questions?.length || 0})
          </button>
        </div>

        {/* Tab Content Body (Scrollable) */}
        <div className="p-6 overflow-y-auto flex-1 space-y-6 text-xs">
          
          {/* TAB: APPLICANTS PIPELINE */}
          {activeTab === 'applicants' && (
            <div className="space-y-4">
              
              {/* Summary Stats Strip */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="p-3.5 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-0.5">
                  <div className="text-slate-400 text-[10px] uppercase font-bold">Total Applicants</div>
                  <div className="text-xl font-black text-slate-900 dark:text-white">{applicants.length}</div>
                </div>

                <div className="p-3.5 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-0.5">
                  <div className="text-slate-400 text-[10px] uppercase font-bold">Ready for Interview</div>
                  <div className="text-xl font-black text-emerald-600 dark:text-emerald-400">
                    {applicants.filter((a) => a.status === 'ready_for_interview').length}
                  </div>
                </div>

                <div className="p-3.5 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-0.5">
                  <div className="text-slate-400 text-[10px] uppercase font-bold">Under Review</div>
                  <div className="text-xl font-black text-indigo-600 dark:text-indigo-400">
                    {applicants.filter((a) => a.status === 'under_review' || a.status === 'submitted').length}
                  </div>
                </div>

                <div className="p-3.5 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-0.5">
                  <div className="text-slate-400 text-[10px] uppercase font-bold">Unreviewed Flags</div>
                  <div className="text-xl font-black text-amber-600 dark:text-amber-400">
                    {unresolvedFlagsCount}
                  </div>
                </div>
              </div>

              {/* Applicants Table */}
              {loadingApplicants ? (
                <div className="py-16 text-center space-y-2">
                  <RefreshCw className="w-6 h-6 animate-spin text-indigo-600 mx-auto" />
                  <p className="text-slate-400">Querying applicants for this position...</p>
                </div>
              ) : applicants.length === 0 ? (
                <div className="p-12 rounded-3xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-center space-y-2">
                  <Users className="w-8 h-8 text-slate-400 mx-auto" />
                  <h4 className="font-bold text-slate-900 dark:text-white text-sm">No applications submitted yet</h4>
                  <p className="text-slate-400 text-xs">
                    Candidates who apply via the candidate portal will appear here with automated discrepancy checks and live ID baseline photos.
                  </p>
                </div>
              ) : (
                <div className="rounded-2xl border border-slate-200 dark:border-slate-800 overflow-hidden bg-white dark:bg-slate-900">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-800/40 text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                        <th className="py-3 px-4">Candidate</th>
                        <th className="py-3 px-4">Experience Stated / Derived</th>
                        <th className="py-3 px-4">Expected Compensation</th>
                        <th className="py-3 px-4">Status</th>
                        <th className="py-3 px-4">Discrepancy Check</th>
                        <th className="py-3 px-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                      {applicants.map((app) => {
                        const parsedExp = app.resume?.parsed_structured_data?.total_experience_years || 0.0;
                        const hasUnresolvedFlags = app.discrepancy_flags?.some((f) => !f.reviewed_by_recruiter);
                        const hasAnyFlags = (app.discrepancy_flags?.length || 0) > 0;

                        return (
                          <tr
                            key={app.id}
                            className="hover:bg-slate-50/80 dark:hover:bg-slate-800/40 transition-colors"
                          >
                            <td className="py-3.5 px-4">
                              <div className="font-bold text-slate-900 dark:text-white text-xs">{app.full_name}</div>
                              <div className="text-[11px] text-slate-400">{app.email}</div>
                              <div className="text-[10px] text-slate-400 mt-0.5">Applied {new Date(app.applied_at).toLocaleDateString()}</div>
                            </td>

                            <td className="py-3.5 px-4 font-mono text-[11px]">
                              <div>
                                <strong className="text-slate-800 dark:text-slate-200">{app.self_reported_experience_years} yrs</strong> stated
                              </div>
                              <div className="text-slate-400">
                                ~{parsedExp.toFixed(1)} yrs resume
                              </div>
                            </td>

                            <td className="py-3.5 px-4 font-mono text-[11px]">
                              <span className="font-semibold text-emerald-600 dark:text-emerald-400">
                                {formatMoney(app.expected_salary, app.expected_salary_currency)}
                              </span>
                            </td>

                            <td className="py-3.5 px-4">
                              <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold border capitalize ${getStatusBadge(app.status)}`}>
                                {app.status.replace(/_/g, ' ')}
                              </span>
                            </td>

                            <td className="py-3.5 px-4">
                              {hasAnyFlags ? (
                                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold border ${
                                  hasUnresolvedFlags
                                    ? 'bg-amber-50 dark:bg-amber-950/80 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800'
                                    : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700'
                                }`}>
                                  <AlertTriangle className="w-3 h-3 text-amber-500" />
                                  <span>{app.discrepancy_flags.length} {hasUnresolvedFlags ? 'Pending Review' : 'Reviewed'}</span>
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold">
                                  <Check className="w-3 h-3" />
                                  <span>Verified Match</span>
                                </span>
                              )}
                            </td>

                            <td className="py-3.5 px-4 text-right">
                              <button
                                type="button"
                                onClick={() => setSelectedApplicant(app)}
                                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-950/60 dark:hover:bg-indigo-900/60 text-indigo-700 dark:text-indigo-300 text-xs font-bold transition-colors"
                              >
                                <Eye className="w-3.5 h-3.5" />
                                <span>Inspect Dossier</span>
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

            </div>
          )}

          {/* TAB 1: Competencies & Rubrics */}
          {activeTab === 'skills' && (
            <div className="space-y-6">
              {job.skills?.map((skill, idx) => (
                <div
                  key={idx}
                  className="p-5 rounded-2xl bg-slate-50 dark:bg-slate-900/60 border border-slate-200/80 dark:border-slate-800 space-y-4"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-200/60 dark:border-slate-800">
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                        skill.priority_tier === 'P0'
                          ? 'bg-rose-100 dark:bg-rose-950/80 text-rose-700 dark:text-rose-300'
                          : 'bg-indigo-100 dark:bg-indigo-950/80 text-indigo-700 dark:text-indigo-300'
                      }`}>
                        {skill.priority_tier} {skill.priority_tier === 'P0' ? 'Mandatory' : 'Core'}
                      </span>
                      <h4 className="text-base font-bold text-slate-900 dark:text-white">
                        {skill.name}
                      </h4>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        ({skill.category})
                      </span>
                    </div>
                    <div className="text-xs font-bold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/60 px-2.5 py-1 rounded-lg border border-indigo-100 dark:border-indigo-900/50">
                      Weight: {skill.weight_percentage}%
                    </div>
                  </div>

                  {/* 5-Level Behavioral Rubrics */}
                  <div className="grid grid-cols-1 gap-2.5 text-xs">
                    <div className="p-2.5 rounded-lg bg-rose-50/50 dark:bg-rose-950/20 border border-rose-100 dark:border-rose-900/30">
                      <strong className="text-rose-700 dark:text-rose-400 block mb-0.5">L1 (Incompetent / Novice):</strong>
                      <span className="text-slate-700 dark:text-slate-300">{skill.rubric_l1 || 'Fails to understand core concepts; proposes broken solutions.'}</span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-amber-50/50 dark:bg-amber-950/20 border border-amber-100 dark:border-amber-900/30">
                      <strong className="text-amber-700 dark:text-amber-400 block mb-0.5">L2 (Developing / Basic):</strong>
                      <span className="text-slate-700 dark:text-slate-300">{skill.rubric_l2 || 'Names technologies but struggles with failure modes and implementation mechanics.'}</span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-blue-50/50 dark:bg-blue-950/20 border border-blue-100 dark:border-blue-900/30">
                      <strong className="text-blue-700 dark:text-blue-400 block mb-0.5">L3 (Proficient / Target Baseline):</strong>
                      <span className="text-slate-700 dark:text-slate-300">{skill.rubric_l3 || 'Clean, workable production-grade answer with sound architectural reasoning.'}</span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-indigo-50/50 dark:bg-indigo-950/20 border border-indigo-100 dark:border-indigo-900/30">
                      <strong className="text-indigo-700 dark:text-indigo-400 block mb-0.5">L4 (Advanced / Strong):</strong>
                      <span className="text-slate-700 dark:text-slate-300">{skill.rubric_l4 || 'Proactively identifies edge cases, distributed failures, and optimization trade-offs.'}</span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-emerald-50/50 dark:bg-emerald-950/20 border border-emerald-100 dark:border-emerald-900/30">
                      <strong className="text-emerald-700 dark:text-emerald-400 block mb-0.5">L5 (Expert / Exceptional):</strong>
                      <span className="text-slate-700 dark:text-slate-300">{skill.rubric_l5 || 'Deep systems-level mastery; evaluates engine internals, cost vs SLAs, and hardware bounds.'}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* TAB 2: Question Plan */}
          {activeTab === 'plan' && (
            <div className="space-y-4">
              <div className="p-4 rounded-xl bg-indigo-50 dark:bg-indigo-950/40 border border-indigo-100 dark:border-indigo-900 text-xs text-indigo-900 dark:text-indigo-200 flex items-center justify-between">
                <div>
                  <span className="font-bold">Total Budget: {job.interview_duration_mins} Minutes</span>
                  <span className="mx-2">•</span>
                  <span>Operational Overhead: 3.5m</span>
                  <span className="mx-2">•</span>
                  <span>Active Eval Time: {job.interview_duration_mins - 3.5}m</span>
                </div>
                <div className="font-extrabold text-sm text-indigo-600 dark:text-indigo-400">
                  {job.question_plans?.reduce((acc, p) => acc + p.allocated_questions, 0) || 0} Core Questions Allocated
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {job.question_plans?.map((plan, idx) => (
                  <div
                    key={idx}
                    className="p-4 rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-slate-800 dark:text-slate-200 truncate max-w-[200px]">
                        {plan.skill_name}
                      </span>
                      <span className="text-xs font-extrabold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/70 px-2 py-0.5 rounded">
                        {plan.allocated_questions} Questions
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 pt-1 border-t border-slate-100 dark:border-slate-800">
                      <span>Time Allocated: ~{plan.time_allocation_minutes} mins</span>
                      <span>Target: {plan.target_rubric_tier}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* TAB 3: Academic & Experience Criteria */}
          {activeTab === 'criteria' && (
            <div className="space-y-6 text-xs">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1.5">
                  <div className="font-bold text-slate-500 uppercase tracking-wider">Minimum Degree</div>
                  <div className="text-sm font-extrabold text-slate-900 dark:text-white">{job.min_degree_level}</div>
                  <div className="text-slate-500">Enforcement: <span className="font-semibold text-indigo-600 dark:text-indigo-400">{job.degree_enforcement_type}</span></div>
                </div>

                <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1.5">
                  <div className="font-bold text-slate-500 uppercase tracking-wider">Experience Thresholds</div>
                  <div className="text-sm font-extrabold text-slate-900 dark:text-white">
                    {job.total_experience_years} Years Total ({job.domain_experience_years} Years Domain)
                  </div>
                  <div className="text-slate-500">
                    Leadership / Mentorship: <span className="font-semibold">{job.leadership_required ? 'Required (Scenario Question Allocated)' : 'Not Mandatory'}</span>
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1.5 sm:col-span-2">
                  <div className="font-bold text-slate-500 uppercase tracking-wider">Accepted Fields of Study (Majors)</div>
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {job.accepted_majors?.map((major, idx) => (
                      <span key={idx} className="px-2.5 py-1 rounded-md bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 font-medium">
                        {major}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 4: Custom Questions */}
          {activeTab === 'custom' && (
            <div className="space-y-4">
              {job.custom_questions?.length > 0 ? (
                job.custom_questions.map((q, idx) => (
                  <div
                    key={idx}
                    className="p-4 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-2 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-indigo-600 dark:text-indigo-400">{q.priority_tier} Priority</span>
                      <span className="text-slate-500">{q.difficulty_level} · {q.category}</span>
                    </div>
                    <p className="text-sm font-semibold text-slate-900 dark:text-white">
                      “{q.question_text}”
                    </p>
                    <div className="pt-2 border-t border-slate-200/60 dark:border-slate-800">
                      <div className="font-bold text-slate-600 dark:text-slate-400 mb-1">Expected Key Points:</div>
                      <ul className="list-disc pl-4 space-y-1 text-slate-700 dark:text-slate-300">
                        {q.expected_key_points?.map((pt, pIdx) => (
                          <li key={pIdx}>{pt}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-center py-8 text-xs text-slate-500">
                  No custom questions specified. System utilizes standard calibrated question plan.
                </div>
              )}
            </div>
          )}

        </div>

        {/* Footer */}
        <div className="p-4 bg-slate-50 dark:bg-slate-900 border-t border-slate-200 dark:border-slate-800 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 rounded-xl text-xs font-semibold text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-slate-100"
          >
            Close
          </button>
        </div>

      </div>

      {/* Deep Applicant Inspection Drawer / Modal */}
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
