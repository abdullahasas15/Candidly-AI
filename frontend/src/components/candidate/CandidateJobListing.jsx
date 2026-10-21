import React, { useState, useEffect } from 'react';
import {
  Search, Briefcase, Clock, MapPin, DollarSign, Award, Layers,
  ChevronRight, ArrowRight, ShieldCheck, CheckCircle2, Sparkles,
  X, Filter, Building2, BookOpen
} from 'lucide-react';
import { formatSalaryRange } from '../../utils/currency';
import { Badge } from '../ui';

const SENIORITY_MAP = {
  entry: 'Entry-Level (L2-L3)',
  mid: 'Mid-Level (L3-L4)',
  senior: 'Senior (L4-L5)',
  lead: 'Lead / Principal (L5+)',
};

const formatSeniority = (val) => {
  if (!val) return 'Mid-Level';
  const lower = val.toLowerCase().trim();
  return SENIORITY_MAP[lower] || val;
};

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
          <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-mono text-teal-400 bg-teal-500/10 border border-teal-500/20 mb-2">
            <Sparkles className="w-3 h-3" />
            <span>Open Engineering Roles</span>
          </div>
          <h2 className="text-xl sm:text-2xl font-bold font-display text-white tracking-tight">
            Explore Open Engineering Positions
          </h2>
          <p className="text-xs sm:text-sm text-zinc-400 mt-0.5">
            Review calibrated competencies, role expectations, and compensation bands.
          </p>
        </div>

        <div className="text-xs font-mono px-3 py-1.5 rounded-lg bg-[#111113] border border-white/[0.08] text-zinc-300 self-start sm:self-auto">
          {filteredJobs.length} {filteredJobs.length === 1 ? 'Role' : 'Roles'} Available
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="p-4 rounded-xl bg-[#0A0A0B] border border-white/[0.08] flex flex-col md:flex-row items-center gap-3">
        <div className="relative flex-1 w-full">
          <Search className="w-4 h-4 text-zinc-500 absolute left-3 top-2.5" />
          <input
            type="text"
            placeholder="Search by role title, department, or technical skill..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 rounded-lg border border-white/[0.12] bg-[#111113] text-xs text-white placeholder:text-zinc-500 focus:outline-none focus:border-teal-400"
          />
        </div>

        {/* Filter Pills */}
        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
          <select
            value={selectedDept}
            onChange={(e) => setSelectedDept(e.target.value)}
            className="px-3 py-1.5 rounded-lg border border-white/[0.12] bg-[#111113] text-xs font-medium text-zinc-300 focus:outline-none focus:border-teal-400"
          >
            {departments.map((d) => (
              <option key={d} value={d}>Dept: {d}</option>
            ))}
          </select>

          <select
            value={selectedWorkplace}
            onChange={(e) => setSelectedWorkplace(e.target.value)}
            className="px-3 py-1.5 rounded-lg border border-white/[0.12] bg-[#111113] text-xs font-medium text-zinc-300 focus:outline-none focus:border-teal-400"
          >
            {workplaces.map((w) => (
              <option key={w} value={w}>Location: {w}</option>
            ))}
          </select>

          <select
            value={selectedSeniority}
            onChange={(e) => setSelectedSeniority(e.target.value)}
            className="px-3 py-1.5 rounded-lg border border-white/[0.12] bg-[#111113] text-xs font-medium text-zinc-300 focus:outline-none focus:border-teal-400"
          >
            {seniorities.map((s) => (
              <option key={s} value={s}>Level: {s}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Clean Roles Grid */}
      {loading ? (
        <div className="py-20 text-center space-y-2">
          <div className="w-6 h-6 rounded-full border-2 border-teal-400 border-t-transparent animate-spin mx-auto" />
          <p className="text-xs text-zinc-400">Loading open positions...</p>
        </div>
      ) : error ? (
        <div className="p-6 rounded-xl bg-rose-500/10 border border-rose-500/20 text-center space-y-3">
          <p className="text-xs font-medium text-rose-300">{error}</p>
          <button
            onClick={fetchJobs}
            className="px-4 py-1.5 rounded-lg text-xs font-semibold text-black bg-teal-500 hover:bg-teal-400"
          >
            Retry
          </button>
        </div>
      ) : filteredJobs.length === 0 ? (
        <div className="p-12 rounded-xl bg-[#0A0A0B] border border-white/[0.08] text-center space-y-3">
          <Briefcase className="w-8 h-8 text-zinc-600 mx-auto" />
          <h3 className="text-sm font-semibold text-white">No active roles match your filters</h3>
          <p className="text-xs text-zinc-500">Try adjusting your keywords or clearing the department filters.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {filteredJobs.map((job) => (
            <div
              key={job.id}
              className="p-6 rounded-xl bg-[#0A0A0B] border border-white/[0.08] hover:border-white/[0.16] shadow-sm transition-all flex flex-col justify-between space-y-5 group"
            >
              <div className="space-y-3">
                {/* Badges: Seniority & Salary */}
                <div className="flex items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {/* Seniority Badge */}
                    <span className="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-white/[0.05] text-zinc-300 border border-white/[0.08]">
                      {formatSeniority(job.seniority_level)}
                    </span>

                    {/* Workplace Badge */}
                    <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-white/[0.03] text-zinc-400 border border-white/[0.06]">
                      {job.workplace_model}
                    </span>

                    <span className="px-2 py-0.5 rounded text-[11px] font-medium text-zinc-400">
                      {job.department}
                    </span>
                  </div>

                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/[0.05] text-zinc-400 border border-white/[0.06]">
                    {job.interview_duration_mins}m Session
                  </span>
                </div>

                {/* Job Title */}
                <h3 className="text-lg font-bold text-white group-hover:text-teal-400 transition-colors">
                  {job.job_title}
                </h3>

                {/* Salary Badge Banner */}
                <div className="p-3 rounded-lg bg-[#111113] border border-white/[0.06] flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <DollarSign className="w-4 h-4 text-emerald-400" />
                    <div>
                      <div className="text-[10px] uppercase font-mono text-zinc-500 tracking-wider">Salary Band</div>
                      <div className="text-xs font-semibold text-emerald-400">
                        {formatSalaryRange(job.salary_range_min, job.salary_range_max, job.salary_currency)}
                      </div>
                    </div>
                  </div>
                  <div className="text-[11px] font-mono text-zinc-400 text-right">
                    {job.total_experience_years}+ yrs YOE
                  </div>
                </div>

                {/* Locations */}
                {job.permitted_locations && job.permitted_locations.length > 0 && (
                  <div className="flex items-center gap-1.5 text-xs text-zinc-400">
                    <MapPin className="w-3.5 h-3.5 text-teal-400 shrink-0" />
                    <span className="truncate">{job.permitted_locations.join(' · ')}</span>
                  </div>
                )}

                {/* Skills tags */}
                <div className="space-y-1.5 pt-2 border-t border-white/[0.06]">
                  <div className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">
                    Required Competencies ({job.skills?.length || 0})
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {job.skills?.slice(0, 4).map((s, idx) => (
                      <span
                        key={idx}
                        className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/[0.03] text-zinc-300 border border-white/[0.06]"
                      >
                        {s.name}
                      </span>
                    ))}
                    {(job.skills?.length || 0) > 4 && (
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/[0.03] text-zinc-500 border border-white/[0.06]">
                        +{job.skills.length - 4} more
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="pt-3 border-t border-white/[0.06] flex items-center gap-2.5">
                <button
                  type="button"
                  onClick={() => setInspectingJob(job)}
                  className="flex-1 py-2 px-3 rounded-lg border border-white/[0.12] text-xs font-medium text-zinc-300 hover:text-white hover:bg-white/[0.05] transition-colors"
                >
                  Role Details
                </button>
                {job.accepts_applications ? (
                  <button
                    type="button"
                    onClick={() => onSelectJobForApplication(job)}
                    className="flex-1 py-2 px-3 rounded-lg bg-teal-500 hover:bg-teal-400 text-black text-xs font-semibold transition-all flex items-center justify-center gap-1.5 cursor-pointer shadow-sm"
                  >
                    <span>Apply Now</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled
                    title="This position is not accepting applications yet."
                    className="flex-1 py-2 px-3 rounded-lg bg-white/[0.05] text-zinc-500 text-xs font-medium cursor-not-allowed flex items-center justify-center gap-1.5 border border-white/[0.06]"
                  >
                    <Clock className="w-3.5 h-3.5" />
                    <span>Applications Pending</span>
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Role Details Modal */}
      {inspectingJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-sm animate-fadeIn">
          <div className="relative w-full max-w-4xl max-h-[90vh] flex flex-col rounded-2xl bg-[#0A0A0B] border border-white/[0.08] shadow-2xl overflow-hidden">
            
            {/* Modal Header */}
            <div className="p-6 bg-[#0A0A0B] border-b border-white/[0.08] flex items-start justify-between">
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-white/[0.05] text-zinc-300 border border-white/[0.08]">
                    {formatSeniority(inspectingJob.seniority_level)}
                  </span>
                  <span className="px-2 py-0.5 rounded text-xs font-medium bg-white/[0.03] text-zinc-400 border border-white/[0.06]">
                    {inspectingJob.department}
                  </span>
                  <span className="px-2 py-0.5 rounded text-xs font-medium bg-white/[0.03] text-zinc-400">
                    {inspectingJob.workplace_model} · {inspectingJob.employment_type}
                  </span>
                </div>
                <h3 className="text-2xl font-bold font-display text-white mt-1">
                  {inspectingJob.job_title}
                </h3>
                <p className="text-xs font-mono text-zinc-400">
                  {inspectingJob.interview_duration_mins} minute voice evaluation
                </p>
              </div>

              <button
                onClick={() => setInspectingJob(null)}
                className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/[0.05] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Scrollable Content */}
            <div className="p-6 overflow-y-auto flex-1 space-y-6 text-xs">
              
              {/* Compensation Callout */}
              <div className="p-4 rounded-xl bg-[#111113] border border-white/[0.08] flex items-center justify-between">
                <div>
                  <div className="text-[10px] font-mono text-zinc-500 uppercase tracking-wider">Target Compensation</div>
                  <div className="text-base font-semibold text-emerald-400 mt-0.5">
                    {formatSalaryRange(inspectingJob.salary_range_min, inspectingJob.salary_range_max, inspectingJob.salary_currency)}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] font-mono text-zinc-500 uppercase tracking-wider">Required Experience</div>
                  <div className="text-xs font-medium text-zinc-200 mt-0.5">
                    {inspectingJob.total_experience_years}+ Years Total
                  </div>
                </div>
              </div>

              {/* Description */}
              <div className="p-5 rounded-xl bg-[#111113] border border-white/[0.08] space-y-2.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-wider text-zinc-400">
                    <Briefcase className="w-3.5 h-3.5 text-teal-400" />
                    <span>Role Overview & Expectations</span>
                  </div>
                </div>
                {inspectingJob.job_description && inspectingJob.job_description !== 'N/A' ? (
                  <div className="text-zinc-300 whitespace-pre-line leading-relaxed text-xs">
                    {inspectingJob.job_description}
                  </div>
                ) : (
                  <p className="text-zinc-500 italic text-xs">
                    No custom narrative job description provided. Please review the competencies, academic criteria, and interview duration benchmarks below.
                  </p>
                )}
              </div>

              {/* Education */}
              <div className="p-4 rounded-xl bg-[#111113] border border-white/[0.08] space-y-3">
                <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-wider text-zinc-400">
                  <BookOpen className="w-3.5 h-3.5 text-teal-400" />
                  <span>Academic & Degree Criteria</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <div>
                    <span className="text-zinc-500 block">Minimum Degree:</span>
                    <strong className="text-zinc-200">{inspectingJob.min_degree_level}</strong>
                  </div>
                  <div>
                    <span className="text-zinc-500 block">Accepted Fields of Study:</span>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {inspectingJob.accepted_majors?.map((major, idx) => (
                        <span key={idx} className="px-2 py-0.5 rounded bg-black/40 border border-white/[0.08] text-zinc-300 font-mono text-[10px]">
                          {major}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Skills */}
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-wider text-zinc-400">
                  <Layers className="w-3.5 h-3.5 text-teal-400" />
                  <span>Assessed Skills</span>
                </div>

                <div className="space-y-2">
                  {inspectingJob.skills?.map((skill, idx) => (
                    <div
                      key={idx}
                      className="p-3 rounded-lg bg-[#111113] border border-white/[0.08] flex items-center justify-between"
                    >
                      <span className="font-semibold text-white text-xs">{skill.name}</span>
                      <span className="text-zinc-500 text-[11px] font-mono">{skill.category}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="p-4 bg-[#0A0A0B] border-t border-white/[0.08] flex items-center justify-between">
              <button
                type="button"
                onClick={() => setInspectingJob(null)}
                className="px-4 py-1.5 rounded-lg text-xs font-medium text-zinc-400 hover:text-white bg-white/[0.05] border border-white/[0.08]"
              >
                Close
              </button>
              {inspectingJob.accepts_applications ? (
                <button
                  type="button"
                  onClick={() => {
                    const target = inspectingJob;
                    setInspectingJob(null);
                    onSelectJobForApplication(target);
                  }}
                  className="inline-flex items-center gap-2 px-5 py-2 rounded-lg bg-teal-500 hover:bg-teal-400 text-black font-semibold text-xs shadow-md transition-all cursor-pointer"
                >
                  <span>Proceed to Apply</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              ) : (
                <button
                  type="button"
                  disabled
                  className="inline-flex items-center gap-2 px-4 py-1.5 rounded-lg bg-white/[0.05] text-zinc-500 font-medium text-xs cursor-not-allowed border border-white/[0.06]"
                >
                  <Clock className="w-3.5 h-3.5" />
                  <span>Applications Pending</span>
                </button>
              )}
            </div>

          </div>
        </div>
      )}

    </div>
  );
}
