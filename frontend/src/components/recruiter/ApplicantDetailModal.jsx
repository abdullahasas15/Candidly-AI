import React, { useState } from 'react';
import {
  X, CheckCircle2, AlertTriangle, Clock, ShieldCheck, Download,
  ExternalLink, Mail, Phone, Calendar, DollarSign, Award, Briefcase,
  Layers, Check, ChevronRight, UserCheck, RefreshCw, FileText,
  Sparkles, Code, FolderGit2, GraduationCap
} from 'lucide-react';
import { getCurrencySymbol, formatMoney as formatMoneyUtil } from '../../utils/currency';

export default function ApplicantDetailModal({
  application,
  isOpen,
  onClose,
  onApplicationUpdated
}) {
  if (!isOpen || !application) return null;

  const [currentApp, setCurrentApp] = useState(application);
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [togglingFlagId, setTogglingFlagId] = useState(null);

  const statusOptions = [
    { value: 'submitted', label: 'Submitted' },
    { value: 'under_review', label: 'Under Review' },
    { value: 'ready_for_interview', label: 'Ready for Interview' },
    { value: 'interviewed', label: 'Interviewed' },
    { value: 'rejected', label: 'Rejected' },
    { value: 'hired', label: 'Hired' }
  ];

  const handleStatusChange = async (newStatus) => {
    setUpdatingStatus(true);
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
      alert('Error: ' + err.message);
    } finally {
      setUpdatingStatus(false);
    }
  };

  const handleToggleFlag = async (flagId) => {
    setTogglingFlagId(flagId);
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
      alert('Error: ' + err.message);
    } finally {
      setTogglingFlagId(null);
    }
  };

  const formatMoney = (val, curr = 'USD') => {
    return formatMoneyUtil(val, curr);
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

        {/* Scrollable Body */}
        <div className="p-6 overflow-y-auto space-y-6 flex-1 text-xs">
          
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
                  <div className="text-emerald-600 dark:text-emerald-400 font-bold text-xs flex items-center gap-1.5">
                    <span className="font-extrabold text-xs">{getCurrencySymbol(currentApp.expected_salary_currency)}</span>
                    <span>Expected: {formatMoney(currentApp.expected_salary, currentApp.expected_salary_currency)}</span>
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

                {/* Webcam Snapshot Display */}
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

                {/* Government ID if available */}
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

            {/* Academic Credentials & Schooling */}
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
                      <div className="flex flex-wrap gap-2 pt-1">
                        {edu.graduation_year && (
                          <span className="text-[10px] px-2 py-0.5 rounded bg-indigo-50 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400 font-bold border border-indigo-200 dark:border-indigo-800">
                            Class of {edu.graduation_year}
                          </span>
                        )}
                        {edu.gpa && (
                          <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 font-bold border border-emerald-200 dark:border-emerald-800">
                            GPA: {edu.gpa}
                          </span>
                        )}
                        {edu.honors && (
                          <span className="text-[10px] px-2 py-0.5 rounded bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400 font-bold border border-amber-200 dark:border-amber-800">
                            {edu.honors}
                          </span>
                        )}
                      </div>
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
                      <div className="flex items-center justify-between gap-2">
                        <div className="font-bold text-slate-900 dark:text-white text-sm">{proj.title}</div>
                        {proj.role && (
                          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-semibold">
                            {proj.role}
                          </span>
                        )}
                      </div>
                      {proj.description && (
                        <p className="text-slate-600 dark:text-slate-300 text-xs">
                          {proj.description}
                        </p>
                      )}
                      {proj.technologies && proj.technologies.length > 0 && (
                        <div className="flex flex-wrap gap-1 pt-1">
                          {proj.technologies.map((t, tIdx) => (
                            <span key={tIdx} className="px-2 py-0.5 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 text-[10px] font-semibold">
                              {t}
                            </span>
                          ))}
                        </div>
                      )}
                      {proj.url && (
                        <div className="pt-1">
                          <a
                            href={proj.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-xs text-indigo-600 dark:text-indigo-400 font-semibold hover:underline flex items-center gap-1"
                          >
                            <span>Repository / Demo</span>
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Professional Certifications */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
                  <Award className="w-4 h-4 text-indigo-600" />
                  <span>Certifications & Accreditations</span>
                </h3>
                <span className="text-xs font-bold text-indigo-600 dark:text-indigo-400">
                  {certs.length} Credentials
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {certs.length === 0 ? (
                  <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900 text-slate-400">
                    No certifications detected.
                  </div>
                ) : (
                  certs.map((c, idx) => (
                    <div
                      key={idx}
                      className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1"
                    >
                      <div className="font-bold text-slate-900 dark:text-white text-sm">{c.name}</div>
                      <div className="text-slate-600 dark:text-slate-300 font-semibold">{c.issuing_org}</div>
                      <div className="flex flex-wrap gap-2 text-[10px] pt-1">
                        {c.issue_year && <span className="text-slate-500 font-bold">Issued: {c.issue_year}</span>}
                        {c.credential_id && <span className="font-mono text-slate-400">ID: {c.credential_id}</span>}
                      </div>
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
                  <span>Technical Skills & Categorization ({skills.length})</span>
                </h3>
              </div>

              {Object.keys(categorizedSkills).length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {Object.entries(categorizedSkills).map(([cat, list]) => list && list.length > 0 && (
                    <div key={cat} className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <span className="font-bold text-slate-700 dark:text-slate-300 text-xs">{cat}</span>
                      <div className="flex flex-wrap gap-1">
                        {list.map((item, i) => (
                          <span key={i} className="px-2 py-0.5 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 text-[10px] font-semibold">
                            {item}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}

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

