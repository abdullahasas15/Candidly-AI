import React, { useState, useEffect } from 'react';
import {
  Search, Briefcase, Clock, MapPin, DollarSign, Award, Layers,
  ChevronRight, ArrowRight, ShieldCheck, CheckCircle2, Sparkles,
  X, Filter, Building2, BookOpen
} from 'lucide-react';

export default function CandidateJobListing({ onSelectJobForApplication }) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDept, setSelectedDept] = useState('All');
  const [selectedWorkplace, setSelectedWorkplace] = useState('All');
  const [selectedSeniority, setSelectedSeniority] = useState('All');

  // Modal for inspecting full role details before applying
  const [inspectingJob, setInspectingJob] = useState(null);

  const fetchJobs = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/jobs');
      if (!res.ok) throw new Error('Failed to retrieve open positions');
      const data = await res.json();
      // Only show active jobs to candidates
      const activeJobs = data.filter((j) => (j.status || 'active').toLowerCase() === 'active');
      setJobs(activeJobs);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchJobs();
  }, []);

  const formatSalary = (min, max, currency = 'USD') => {
    if (!min && !max) return 'Competitive compensation';
    const currSymbol = currency === 'USD' || currency === 'CAD' || currency === 'AUD' || currency === 'SGD' ? '$'
      : currency === 'EUR' ? '€'
      : currency === 'GBP' ? '£'
      : currency === 'INR' ? '₹'
      : `${currency} `;

    if (min && max) {
      return `${currSymbol}${Number(min).toLocaleString()} - ${currSymbol}${Number(max).toLocaleString()} ${currency}`;
    }
    if (min) return `From ${currSymbol}${Number(min).toLocaleString()} ${currency}`;
    return `Up to ${currSymbol}${Number(max).toLocaleString()} ${currency}`;
  };

  // Filtered jobs
  const departments = ['All', ...new Set(jobs.map((j) => j.department).filter(Boolean))];
  const workplaces = ['All', 'Remote', 'Hybrid', 'On-site'];
  const seniorities = ['All', ...new Set(jobs.map((j) => j.seniority_level).filter(Boolean))];

  const filteredJobs = jobs.filter((job) => {
    const query = searchQuery.toLowerCase();
    const matchesSearch =
      job.job_title.toLowerCase().includes(query) ||
      job.department.toLowerCase().includes(query) ||
      job.skills?.some((s) => s.name.toLowerCase().includes(query));

    const matchesDept = selectedDept === 'All' || job.department === selectedDept;
    const matchesWorkplace = selectedWorkplace === 'All' || job.workplace_model === selectedWorkplace;
    const matchesSeniority = selectedSeniority === 'All' || job.seniority_level === selectedSeniority;

    return matchesSearch && matchesDept && matchesWorkplace && matchesSeniority;
  });

  return (
    <div className="space-y-6">
      
      {/* Header Strip */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 border border-indigo-200/60 dark:border-indigo-800 mb-1.5">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Open Verified Positions</span>
          </div>
          <h2 className="text-xl sm:text-2xl font-black text-slate-900 dark:text-white tracking-tight">
            Explore Open Engineering Positions
          </h2>
          <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400">
            Every position features calibrated 5-tier rubrics, transparent salary bands, and AI voice interviews.
          </p>
        </div>

        <div className="text-xs font-semibold px-3 py-1.5 rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 self-start sm:self-auto">
          {filteredJobs.length} {filteredJobs.length === 1 ? 'Role' : 'Roles'} Available
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm flex flex-col md:flex-row items-center gap-3">
        <div className="relative flex-1 w-full">
          <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-3" />
          <input
            type="text"
            placeholder="Search by role title, department, or technical skill..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
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
            value={selectedWorkplace}
            onChange={(e) => setSelectedWorkplace(e.target.value)}
            className="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs font-semibold text-slate-700 dark:text-slate-300"
          >
            {workplaces.map((w) => (
              <option key={w} value={w}>Location: {w}</option>
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

      {/* Roles Grid */}
      {loading ? (
        <div className="py-20 text-center space-y-3">
          <div className="w-8 h-8 rounded-full border-2 border-indigo-600 border-t-transparent animate-spin mx-auto" />
          <p className="text-xs text-slate-500 dark:text-slate-400">Loading open roles from database...</p>
        </div>
      ) : error ? (
        <div className="p-6 rounded-2xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 text-center space-y-3">
          <p className="text-xs font-bold text-rose-700 dark:text-rose-300">{error}</p>
          <button
            onClick={fetchJobs}
            className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-rose-600 hover:bg-rose-700"
          >
            Retry
          </button>
        </div>
      ) : filteredJobs.length === 0 ? (
        <div className="p-12 rounded-3xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-center space-y-3">
          <Briefcase className="w-8 h-8 text-slate-400 mx-auto" />
          <h3 className="text-sm font-bold text-slate-900 dark:text-white">No active roles match your filters</h3>
          <p className="text-xs text-slate-500">Try adjusting your keywords or clearing the department filters.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {filteredJobs.map((job) => (
            <div
              key={job.id}
              className="p-6 rounded-3xl bg-white dark:bg-[#111827] border border-slate-200 dark:border-slate-800 hover:border-indigo-500/60 dark:hover:border-indigo-500/60 shadow-sm hover:shadow-xl transition-all flex flex-col justify-between space-y-5"
            >
              <div className="space-y-3">
                {/* Badges */}
                <div className="flex items-center justify-between">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 border border-indigo-200/60 dark:border-indigo-800">
                      {job.seniority_level}
                    </span>
                    <span className="px-2 py-0.5 rounded-md text-[11px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                      {job.department}
                    </span>
                    <span className="px-2 py-0.5 rounded-md text-[11px] font-medium bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300">
                      {job.workplace_model}
                    </span>
                  </div>

                  <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                    {job.interview_duration_mins}m Session
                  </span>
                </div>

                {/* Title */}
                <h3 className="text-lg font-bold text-slate-900 dark:text-white">
                  {job.job_title}
                </h3>

                {/* Compensation Banner */}
                <div className="p-3 rounded-2xl bg-gradient-to-r from-emerald-500/10 via-indigo-500/10 to-transparent border border-emerald-500/20 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <DollarSign className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                    <div>
                      <div className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Offered Salary Band</div>
                      <div className="text-xs font-black text-emerald-700 dark:text-emerald-300">
                        {formatSalary(job.salary_range_min, job.salary_range_max, job.salary_currency)}
                      </div>
                    </div>
                  </div>
                  <div className="text-[10px] font-medium text-slate-500 dark:text-slate-400 text-right">
                    {job.total_experience_years}+ YOE Bar
                  </div>
                </div>

                {/* Location string */}
                {job.permitted_locations && job.permitted_locations.length > 0 && (
                  <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                    <MapPin className="w-3.5 h-3.5 text-indigo-500 shrink-0" />
                    <span className="truncate">{job.permitted_locations.join(' · ')}</span>
                  </div>
                )}

                {/* Skills strip */}
                <div className="space-y-1 pt-2 border-t border-slate-100 dark:border-slate-800">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    Evaluated Competencies ({job.skills?.length || 0})
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {job.skills?.slice(0, 4).map((s, idx) => (
                      <span
                        key={idx}
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded-md ${
                          s.priority_tier === 'P0'
                            ? 'bg-rose-50 dark:bg-rose-950/60 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900'
                            : 'bg-slate-50 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700'
                        }`}
                      >
                        {s.name} ({s.weight_percentage}%)
                      </span>
                    ))}
                    {(job.skills?.length || 0) > 4 && (
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-500">
                        +{job.skills.length - 4} more
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setInspectingJob(job)}
                  className="flex-1 py-2.5 px-3 rounded-xl border border-slate-200 dark:border-slate-700 text-xs font-bold text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
                >
                  View Role Details
                </button>
                <button
                  type="button"
                  onClick={() => onSelectJobForApplication(job)}
                  className="flex-1 py-2.5 px-3 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold shadow-md shadow-indigo-600/20 hover:-translate-y-0.5 transition-all flex items-center justify-center gap-1.5"
                >
                  <span>Apply Now</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Role Details Modal */}
      {inspectingJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-slate-950/75 backdrop-blur-sm animate-fadeIn">
          <div className="relative w-full max-w-4xl max-h-[90vh] flex flex-col rounded-3xl bg-white dark:bg-[#111827] border border-slate-200 dark:border-slate-800 shadow-2xl overflow-hidden">
            
            {/* Modal Header */}
            <div className="p-6 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 flex items-start justify-between">
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800">
                    {inspectingJob.seniority_level}
                  </span>
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-200/70 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
                    {inspectingJob.department}
                  </span>
                  <span className="px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300">
                    {inspectingJob.workplace_model} · {inspectingJob.employment_type}
                  </span>
                </div>
                <h3 className="text-2xl font-black text-slate-900 dark:text-white">
                  {inspectingJob.job_title}
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {inspectingJob.interview_duration_mins} Minutes AI Voice Evaluation · {inspectingJob.pacing_strictness} Pacing · {inspectingJob.integrity_policy_tier} Proctoring
                </p>
              </div>

              <button
                onClick={() => setInspectingJob(null)}
                className="p-2 rounded-xl text-slate-400 hover:text-slate-700 dark:hover:text-white bg-slate-100 dark:bg-slate-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Scrollable Content */}
            <div className="p-6 overflow-y-auto flex-1 space-y-6 text-xs">
              
              {/* Compensation Callout */}
              <div className="p-4 rounded-2xl bg-gradient-to-r from-emerald-500/10 via-indigo-500/10 to-slate-100 dark:to-slate-800 border border-emerald-500/30 flex items-center justify-between">
                <div>
                  <div className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Target Compensation</div>
                  <div className="text-lg font-black text-emerald-700 dark:text-emerald-300 mt-0.5">
                    {formatSalary(inspectingJob.salary_range_min, inspectingJob.salary_range_max, inspectingJob.salary_currency)}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Required Experience</div>
                  <div className="text-sm font-bold text-slate-800 dark:text-slate-200 mt-0.5">
                    {inspectingJob.total_experience_years}+ Years Total ({inspectingJob.domain_experience_years} Years Domain)
                  </div>
                </div>
              </div>

              {/* Education & Academic Criteria */}
              <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-3">
                <div className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white">
                  <BookOpen className="w-4 h-4 text-indigo-600" />
                  <span>Academic & Degree Requirements</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <div>
                    <span className="text-slate-400 block">Minimum Degree:</span>
                    <strong className="text-slate-800 dark:text-slate-200">{inspectingJob.min_degree_level}</strong>
                    <div className="text-[11px] text-indigo-600 dark:text-indigo-400 mt-0.5">
                      Enforcement: {inspectingJob.degree_enforcement_type}
                    </div>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Accepted Fields of Study:</span>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {inspectingJob.accepted_majors?.map((major, idx) => (
                        <span key={idx} className="px-2 py-0.5 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 font-medium">
                          {major}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Evaluated Competencies & 5-Level Rubrics */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white">
                    <Layers className="w-4 h-4 text-indigo-600" />
                    <span>Calibrated Competency Dimensions</span>
                  </div>
                  <span className="text-[11px] font-semibold text-slate-400">Targeting L3 (Proficient) Baseline</span>
                </div>

                <div className="space-y-3">
                  {inspectingJob.skills?.map((skill, idx) => (
                    <div
                      key={idx}
                      className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className={`text-[10px] font-black px-2 py-0.5 rounded ${
                            skill.priority_tier === 'P0'
                              ? 'bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300'
                              : 'bg-indigo-100 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                          }`}>
                            {skill.priority_tier} {skill.priority_tier === 'P0' ? 'Mandatory' : 'Core'}
                          </span>
                          <span className="font-bold text-slate-900 dark:text-white text-sm">{skill.name}</span>
                          <span className="text-slate-400">({skill.category})</span>
                        </div>
                        <span className="font-mono font-bold text-indigo-600 dark:text-indigo-400">{skill.weight_percentage}%</span>
                      </div>

                      {/* L3 Rubric Highlight */}
                      <div className="p-2.5 rounded-xl bg-white dark:bg-slate-800/80 border border-slate-100 dark:border-slate-700 text-[11px]">
                        <span className="font-bold text-slate-700 dark:text-slate-200 block mb-0.5">Benchmark Expectation (L3):</span>
                        <p className="text-slate-600 dark:text-slate-300">{skill.rubric_l3 || 'Demonstrates clean production reasoning with optimal space/time bounds.'}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="p-4 bg-slate-50 dark:bg-slate-900 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between">
              <button
                type="button"
                onClick={() => setInspectingJob(null)}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                Close
              </button>
              <button
                type="button"
                onClick={() => {
                  const target = inspectingJob;
                  setInspectingJob(null);
                  onSelectJobForApplication(target);
                }}
                className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs shadow-md shadow-indigo-600/20 transition-all"
              >
                <span>Proceed to Apply</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>

          </div>
        </div>
      )}

    </div>
  );
}

