import React, { useState, useRef, useEffect } from 'react';
import {
  X, UploadCloud, CheckCircle2, AlertTriangle, ArrowRight, ArrowLeft,
  FileText, Sparkles, Camera, CameraOff, RefreshCw, User, Briefcase,
  DollarSign, ShieldCheck, Trash2, Plus, HelpCircle, Eye, Check,
  GraduationCap, Award, FolderGit2, Code2
} from 'lucide-react';
import { getCurrencySymbol, formatMoney as formatMoneyUtil, formatSalaryRange } from '../../utils/currency';

// Safely extract error message from a fetch response that may not be JSON
async function extractErrorMessage(res) {
  try {
    const text = await res.text();
    try {
      const json = JSON.parse(text);
      return json.detail || json.message || text;
    } catch {
      return text;
    }
  } catch {
    return 'Server error';
  }
}

export default function ApplicationWizard({ job, authUser, isOpen, onClose, onApplicationSubmitted }) {
  if (!isOpen || !job) return null;

  const [currentStep, setCurrentStep] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);

  // Application session state persisted across steps
  const [applicationId, setApplicationId] = useState(null);

  // Step 1: Personal Details
  const [personalDetails, setPersonalDetails] = useState({
    full_name: authUser?.full_name || '',
    email: authUser?.email || '',
    phone: '',
    linkedin_url: '',
    portfolio_url: ''
  });

  // Step 2: File upload & parser status
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [parsingStatus, setParsingStatus] = useState('idle'); // idle | uploading | parsing | done | error
  const [parsedResumeResult, setParsedResumeResult] = useState(null);
  const fileInputRef = useRef(null);

  // Step 3: Editable structured resume data & active subtab
  const [careerTab, setCareerTab] = useState('experience'); // experience | education | certifications | projects | skills
  const [newSkillInput, setNewSkillInput] = useState('');
  const [categorizedSkillInputs, setCategorizedSkillInputs] = useState({});
  const [structuredData, setStructuredData] = useState({
    summary: '',
    work_experience: [],
    education: [],
    certifications: [],
    projects: [],
    skills: [],
    skills_by_category: {
      'Languages': [],
      'Frameworks': [],
      'Databases': [],
      'Cloud & DevOps': [],
      'Tools': []
    },
    contact_info: {},
    total_experience_years: 0.0
  });

  // Step 4: Fit Pitch & Compensation
  const [fitData, setFitData] = useState({
    self_reported_experience_years: 3.0,
    fit_pitch: '',
    expected_salary: job.salary_range_min || 135000,
    expected_salary_currency: job.salary_currency || 'USD'
  });

  // Step 5: Webcam ID Verification
  const [cameraStream, setCameraStream] = useState(null);
  const [liveSnapshot, setLiveSnapshot] = useState(null);
  const [govIdFile, setGovIdFile] = useState(null);
  const [govIdPreview, setGovIdPreview] = useState(null);
  const [cameraError, setCameraError] = useState(null);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);

  // Discrepancy flags received from backend
  const [discrepancyFlags, setDiscrepancyFlags] = useState([]);
  const [submittedSuccessfully, setSubmittedSuccessfully] = useState(false);

  // Clean up camera stream when modal closes or changes
  useEffect(() => {
    return () => {
      if (cameraStream) {
        cameraStream.getTracks().forEach((t) => t.stop());
      }
    };
  }, [cameraStream]);

  // Format currency — delegates to the shared utility for correct symbols
  const formatMoney = (val, curr = 'USD') => {
    return formatMoneyUtil(val, curr);
  };

  // -------------------------------------------------------------
  // STEP 1 -> STEP 2: Create initial Draft Application in Backend
  // -------------------------------------------------------------
  const handleProceedFromStep1 = async (e) => {
    e.preventDefault();
    if (!personalDetails.full_name.trim() || !personalDetails.email.trim()) {
      setErrorMessage('Full name and email are required.');
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);
    try {
      if (!applicationId) {
        const payload = {
          job_id: job.id,
          candidate_id: authUser?.id || null,
          full_name: personalDetails.full_name.trim(),
          email: personalDetails.email.trim(),
          phone: personalDetails.phone.trim() || null,
          linkedin_url: personalDetails.linkedin_url.trim() || null,
          portfolio_url: personalDetails.portfolio_url.trim() || null,
          self_reported_experience_years: parseFloat(fitData.self_reported_experience_years) || 0,
          fit_pitch: fitData.fit_pitch || null,
          expected_salary: parseFloat(fitData.expected_salary) || null,
          expected_salary_currency: fitData.expected_salary_currency || 'USD'
        };

        const token = localStorage.getItem('candidly-auth-token');
        const headers = {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {})
        };

        const res = await fetch('/api/applications', {
          method: 'POST',
          headers,
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          const errMsg = await extractErrorMessage(res);
          throw new Error(errMsg || 'Failed to create application draft');
        }

        const appData = await res.json();
        setApplicationId(appData.id);
      }
      setCurrentStep(2);
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  // -------------------------------------------------------------
  // STEP 2: File Handling & Resume Upload with Real Parsing
  // -------------------------------------------------------------
  const handleFileSelect = (file) => {
    if (!file) return;
    const maxBytes = 10 * 1024 * 1024;
    if (file.size > maxBytes) {
      setErrorMessage(`File is ${(file.size / (1024 * 1024)).toFixed(1)}MB. Maximum permitted size is 10 MB.`);
      return;
    }

    const ext = file.name.split('.').pop().toLowerCase();
    if (!['pdf', 'docx', 'txt'].includes(ext)) {
      setErrorMessage('Only PDF, DOCX, and TXT files are accepted.');
      return;
    }

    setErrorMessage(null);
    setSelectedFile(file);
  };

  const handleUploadAndParseResume = async () => {
    if (!selectedFile || !applicationId) {
      setErrorMessage('Please choose a valid resume file before proceeding.');
      return;
    }

    setParsingStatus('uploading');
    setUploadProgress(20);
    setErrorMessage(null);

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      setUploadProgress(50);
      setParsingStatus('parsing');

      const res = await fetch(`/api/applications/${applicationId}/resume`, {
        method: 'POST',
        body: formData
      });

      if (!res.ok) {
        const errMsg = await extractErrorMessage(res);
        throw new Error(errMsg || 'Resume parsing encountered an error');
      }

      setUploadProgress(100);
      const data = await res.json();
      setParsedResumeResult(data);

      const parsedStruct = data.parsed_structured_data || {};
      setStructuredData({
        summary: parsedStruct.summary || '',
        work_experience: parsedStruct.work_experience || [],
        education: parsedStruct.education || [],
        certifications: parsedStruct.certifications || [],
        projects: parsedStruct.projects || [],
        skills: parsedStruct.skills || [],
        skills_by_category: parsedStruct.skills_by_category || {
          'Languages': [],
          'Frameworks': [],
          'Databases': [],
          'Cloud & DevOps': [],
          'Tools': []
        },
        contact_info: parsedStruct.contact_info || {},
        total_experience_years: parsedStruct.total_experience_years || 0.0
      });

      // Auto-fill personal details if extracted and not yet provided
      if (parsedStruct.contact_info) {
        setPersonalDetails((prev) => ({
          ...prev,
          phone: prev.phone || parsedStruct.contact_info.phone || '',
          linkedin_url: prev.linkedin_url || parsedStruct.contact_info.linkedin || '',
          portfolio_url: prev.portfolio_url || parsedStruct.contact_info.portfolio || parsedStruct.contact_info.github || ''
        }));
      }

      // Auto-fill fit pitch from summary if empty
      if (parsedStruct.summary && !fitData.fit_pitch) {
        setFitData((prev) => ({
          ...prev,
          fit_pitch: parsedStruct.summary
        }));
      }

      // Update fit data with parsed experience default if 0
      if (parsedStruct.total_experience_years) {
        setFitData((prev) => ({
          ...prev,
          self_reported_experience_years: parsedStruct.total_experience_years
        }));
      }

      setDiscrepancyFlags(data.discrepancy_flags || []);
      setParsingStatus('done');
      setCurrentStep(3);
    } catch (err) {
      setParsingStatus('error');
      setErrorMessage(err.message);
    }
  };

  // -------------------------------------------------------------
  // STEP 3: Save Structured Resume Corrections
  // -------------------------------------------------------------
  const handleSaveResumeCorrections = async () => {
    if (!applicationId) return;
    setSubmitting(true);
    setErrorMessage(null);
    try {
      const res = await fetch(`/api/applications/${applicationId}/parsed-resume`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parsed_structured_data: structuredData,
          self_reported_experience_years: fitData.self_reported_experience_years
        })
      });

      if (!res.ok) {
        const errMsg = await extractErrorMessage(res);
        throw new Error(errMsg || 'Failed to save resume corrections');
      }

      const updated = await res.json();
      setDiscrepancyFlags(updated.discrepancy_flags || []);
      setCurrentStep(4);
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  // -------------------------------------------------------------
  // Work Experience Handlers
  // -------------------------------------------------------------
  const handleAddExperience = () => {
    setStructuredData((prev) => ({
      ...prev,
      work_experience: [
        ...prev.work_experience,
        {
          company: '',
          role: '',
          start_date: '2022',
          end_date: 'Present',
          duration_years: 1.0,
          description: '',
          highlights: [],
          technologies: []
        }
      ]
    }));
  };

  const handleRemoveExperience = (idx) => {
    setStructuredData((prev) => ({
      ...prev,
      work_experience: prev.work_experience.filter((_, i) => i !== idx)
    }));
  };

  const handleExperienceChange = (idx, field, val) => {
    setStructuredData((prev) => {
      const updated = [...prev.work_experience];
      updated[idx] = { ...updated[idx], [field]: val };
      return { ...prev, work_experience: updated };
    });
  };

  // -------------------------------------------------------------
  // Education Handlers
  // -------------------------------------------------------------
  const handleAddEducation = () => {
    setStructuredData((prev) => ({
      ...prev,
      education: [
        ...prev.education,
        {
          degree: "Bachelor's Degree",
          institution: '',
          field: 'Computer Science',
          graduation_year: new Date().getFullYear(),
          gpa: '',
          honors: ''
        }
      ]
    }));
  };

  const handleRemoveEducation = (idx) => {
    setStructuredData((prev) => ({
      ...prev,
      education: prev.education.filter((_, i) => i !== idx)
    }));
  };

  const handleEducationChange = (idx, field, val) => {
    setStructuredData((prev) => {
      const updated = [...prev.education];
      updated[idx] = { ...updated[idx], [field]: val };
      return { ...prev, education: updated };
    });
  };

  // -------------------------------------------------------------
  // Certifications Handlers
  // -------------------------------------------------------------
  const handleAddCertification = () => {
    setStructuredData((prev) => ({
      ...prev,
      certifications: [
        ...prev.certifications,
        {
          name: '',
          issuing_org: '',
          issue_year: new Date().getFullYear(),
          credential_id: '',
          url: ''
        }
      ]
    }));
  };

  const handleRemoveCertification = (idx) => {
    setStructuredData((prev) => ({
      ...prev,
      certifications: prev.certifications.filter((_, i) => i !== idx)
    }));
  };

  const handleCertificationChange = (idx, field, val) => {
    setStructuredData((prev) => {
      const updated = [...prev.certifications];
      updated[idx] = { ...updated[idx], [field]: val };
      return { ...prev, certifications: updated };
    });
  };

  // -------------------------------------------------------------
  // Projects Handlers
  // -------------------------------------------------------------
  const handleAddProject = () => {
    setStructuredData((prev) => ({
      ...prev,
      projects: [
        ...prev.projects,
        {
          title: '',
          role: 'Lead Developer',
          technologies: [],
          description: '',
          url: ''
        }
      ]
    }));
  };

  const handleRemoveProject = (idx) => {
    setStructuredData((prev) => ({
      ...prev,
      projects: prev.projects.filter((_, i) => i !== idx)
    }));
  };

  const handleProjectChange = (idx, field, val) => {
    setStructuredData((prev) => {
      const updated = [...prev.projects];
      updated[idx] = { ...updated[idx], [field]: val };
      return { ...prev, projects: updated };
    });
  };

  const handleProjectTechChange = (idx, techString) => {
    const list = techString.split(',').map((s) => s.trim()).filter(Boolean);
    handleProjectChange(idx, 'technologies', list);
  };

  // -------------------------------------------------------------
  // Categorized Skills Handlers
  // -------------------------------------------------------------
  const handleAddSkill = (skillName) => {
    const trimmed = skillName.trim();
    if (!trimmed || structuredData.skills.includes(trimmed)) return;
    setStructuredData((prev) => ({
      ...prev,
      skills: [...prev.skills, trimmed]
    }));
    setNewSkillInput('');
  };

  const handleRemoveSkill = (skillToRemove) => {
    setStructuredData((prev) => ({
      ...prev,
      skills: prev.skills.filter((s) => s !== skillToRemove)
    }));
  };

  const handleAddCategorizedSkill = (category, skillName) => {
    const trimmed = skillName.trim();
    if (!trimmed) return;
    setStructuredData((prev) => {
      const currentCatSkills = prev.skills_by_category?.[category] || [];
      if (currentCatSkills.includes(trimmed)) return prev;
      const updatedCatSkills = [...currentCatSkills, trimmed];
      const updatedAll = prev.skills.includes(trimmed) ? prev.skills : [...prev.skills, trimmed];
      return {
        ...prev,
        skills: updatedAll,
        skills_by_category: {
          ...(prev.skills_by_category || {}),
          [category]: updatedCatSkills
        }
      };
    });
    setCategorizedSkillInputs((prev) => ({ ...prev, [category]: '' }));
  };

  const handleRemoveCategorizedSkill = (category, skillToRemove) => {
    setStructuredData((prev) => {
      const currentCatSkills = prev.skills_by_category?.[category] || [];
      const updatedCatSkills = currentCatSkills.filter((s) => s !== skillToRemove);
      return {
        ...prev,
        skills_by_category: {
          ...(prev.skills_by_category || {}),
          [category]: updatedCatSkills
        }
      };
    });
  };

  // -------------------------------------------------------------
  // STEP 5: Live Webcam Media Stream & Snapshot Capture
  // -------------------------------------------------------------
  const startWebcam = async () => {
    setCameraError(null);
    try {
      if (cameraStream) {
        cameraStream.getTracks().forEach((t) => t.stop());
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
        audio: false
      });
      setCameraStream(stream);
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play();
      }
    } catch (err) {
      setCameraError('Unable to access camera. Please allow camera permissions in your browser.');
    }
  };

  const stopWebcam = () => {
    if (cameraStream) {
      cameraStream.getTracks().forEach((t) => t.stop());
      setCameraStream(null);
    }
  };

  const captureSnapshot = () => {
    if (!videoRef.current || !canvasRef.current) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
    setLiveSnapshot(dataUrl);
    stopWebcam();
  };

  const retakeSnapshot = () => {
    setLiveSnapshot(null);
    startWebcam();
  };

  const handleGovIdSelect = (file) => {
    if (!file) return;
    setGovIdFile(file);
    const reader = new FileReader();
    reader.onload = (e) => setGovIdPreview(e.target.result);
    reader.readAsDataURL(file);
  };

  const handleSaveVerification = async () => {
    if (!liveSnapshot) {
      setErrorMessage('A live webcam photo snapshot is required for identity verification.');
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);
    try {
      const payload = {
        live_photo: liveSnapshot,
        government_id: govIdPreview || null
      };

      const res = await fetch(`/api/applications/${applicationId}/verification`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errMsg = await extractErrorMessage(res);
        throw new Error(errMsg || 'Failed to save identity verification');
      }

      setCurrentStep(6);
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  // -------------------------------------------------------------
  // STEP 6: Final Submission
  // -------------------------------------------------------------
  const handleFinalSubmit = async () => {
    setSubmitting(true);
    setErrorMessage(null);
    try {
      const payload = {
        full_name: personalDetails.full_name,
        email: personalDetails.email,
        phone: personalDetails.phone || null,
        linkedin_url: personalDetails.linkedin_url || null,
        portfolio_url: personalDetails.portfolio_url || null,
        self_reported_experience_years: parseFloat(fitData.self_reported_experience_years) || 0,
        fit_pitch: fitData.fit_pitch || null,
        expected_salary: parseFloat(fitData.expected_salary) || null,
        expected_salary_currency: fitData.expected_salary_currency || 'USD'
      };

      const res = await fetch(`/api/applications/${applicationId}/submit`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errMsg = await extractErrorMessage(res);
        throw new Error(errMsg || 'Failed to finalize application submission');
      }

      const submittedApp = await res.json();
      setSubmittedSuccessfully(true);
      if (onApplicationSubmitted) {
        onApplicationSubmitted(submittedApp);
      }
    } catch (err) {
      setErrorMessage(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const stepsList = [
    { num: 1, label: 'Profile Info' },
    { num: 2, label: 'Resume Ingestion' },
    { num: 3, label: 'Resume Review' },
    { num: 4, label: 'Fit & Compensation' },
    { num: 5, label: 'Live ID Verification' },
    { num: 6, label: 'Review & Submit' }
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
      <div className="relative w-full max-w-4xl max-h-[92vh] flex flex-col rounded-3xl bg-white dark:bg-[#111827] border border-slate-200 dark:border-slate-800 shadow-2xl overflow-hidden">
        
        {/* Top Header */}
        <div className="px-6 py-4 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-600 text-white flex items-center justify-center shadow-md">
              <Briefcase className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base sm:text-lg font-black text-slate-900 dark:text-white">
                  Application: {job.job_title}
                </h2>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border border-emerald-200/60 dark:border-emerald-800">
                  {job.department}
                </span>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Offered: {formatSalaryRange(job.salary_range_min, job.salary_range_max, job.salary_currency)} · {job.interview_duration_mins}m AI Voice Session
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-xl text-slate-400 hover:text-slate-700 dark:hover:text-white bg-slate-100 dark:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Step Progress Bar */}
        {!submittedSuccessfully && (
          <div className="flex overflow-x-auto border-b border-slate-200 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-900/40 px-6 scrollbar-none">
            {stepsList.map((st) => (
              <div
                key={st.num}
                className={`flex items-center gap-2 py-3 px-3 text-xs font-bold whitespace-nowrap border-b-2 transition-all ${
                  currentStep === st.num
                    ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-slate-900/60'
                    : currentStep > st.num
                    ? 'border-emerald-500 text-emerald-600 dark:text-emerald-400'
                    : 'border-transparent text-slate-400'
                }`}
              >
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] ${
                  currentStep === st.num
                    ? 'bg-indigo-600 text-white'
                    : currentStep > st.num
                    ? 'bg-emerald-500 text-white'
                    : 'bg-slate-200 dark:bg-slate-800 text-slate-500'
                }`}>
                  {currentStep > st.num ? <Check className="w-3 h-3" /> : st.num}
                </span>
                <span>{st.label}</span>
              </div>
            ))}
          </div>
        )}

        {/* Error Banner */}
        {errorMessage && (
          <div className="px-6 py-2.5 bg-rose-50 dark:bg-rose-950/50 border-b border-rose-200 dark:border-rose-900/50 flex items-center gap-2 text-xs text-rose-700 dark:text-rose-300 font-semibold">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>{errorMessage}</span>
          </div>
        )}

        {/* Form Body (Scrollable) */}
        <div className="p-6 overflow-y-auto flex-1 text-xs">
          
          {/* ========================================================= */}
          {/* SUCCESS SCREEN */}
          {/* ========================================================= */}
          {submittedSuccessfully ? (
            <div className="py-12 text-center space-y-5 max-w-md mx-auto">
              <div className="w-16 h-16 rounded-3xl bg-emerald-100 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 flex items-center justify-center mx-auto shadow-lg shadow-emerald-500/10">
                <CheckCircle2 className="w-10 h-10" />
              </div>

              <div className="space-y-2">
                <h3 className="text-2xl font-black text-slate-900 dark:text-white">
                  Application Submitted Successfully!
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Your application for <strong className="text-slate-800 dark:text-slate-200">{job.job_title}</strong> has been received and verified.
                </p>
                <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-800 text-[11px] font-mono text-slate-600 dark:text-slate-300">
                  Reference ID: {applicationId}
                </div>
              </div>

              <div className="p-4 rounded-2xl bg-indigo-50 dark:bg-indigo-950/40 border border-indigo-100 dark:border-indigo-900/50 text-left space-y-1.5">
                <div className="font-bold text-indigo-900 dark:text-indigo-200">What Happens Next:</div>
                <p className="text-indigo-700 dark:text-indigo-300 text-[11px]">
                  Your career profile and live ID verification have been calibrated into the recruiter's candidate queue. You can now launch your AI voice evaluation directly from your dashboard.
                </p>
              </div>

              <div className="pt-2 flex justify-center gap-3">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs shadow-md shadow-indigo-600/20 transition-all"
                >
                  Return to Portal
                </button>
              </div>
            </div>
          ) : (
            <>
              {/* ========================================================= */}
              {/* STEP 1: Personal Profile */}
              {/* ========================================================= */}
              {currentStep === 1 && (
                <form onSubmit={handleProceedFromStep1} className="space-y-4">
                  <div className="space-y-1 mb-4">
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                      Step 1: Confirm Your Candidate Profile
                    </h3>
                    <p className="text-slate-500 dark:text-slate-400">
                      Provide your primary contact coordinates for interview scheduling and identity verification.
                    </p>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                        Full Legal Name <span className="text-rose-500">*</span>
                      </label>
                      <input
                        type="text"
                        required
                        placeholder="e.g. Alex Mercer"
                        value={personalDetails.full_name}
                        onChange={(e) => setPersonalDetails({ ...personalDetails, full_name: e.target.value })}
                        className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-indigo-500"
                      />
                    </div>

                    <div>
                      <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                        Email Address <span className="text-rose-500">*</span>
                      </label>
                      <input
                        type="email"
                        required
                        placeholder="e.g. alex@example.com"
                        value={personalDetails.email}
                        onChange={(e) => setPersonalDetails({ ...personalDetails, email: e.target.value })}
                        className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-indigo-500"
                      />
                    </div>

                    <div>
                      <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                        Phone Number
                      </label>
                      <input
                        type="tel"
                        placeholder="e.g. +1 (555) 234-5678"
                        value={personalDetails.phone}
                        onChange={(e) => setPersonalDetails({ ...personalDetails, phone: e.target.value })}
                        className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                      />
                    </div>

                    <div>
                      <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                        LinkedIn Profile URL
                      </label>
                      <input
                        type="url"
                        placeholder="https://linkedin.com/in/username"
                        value={personalDetails.linkedin_url}
                        onChange={(e) => setPersonalDetails({ ...personalDetails, linkedin_url: e.target.value })}
                        className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                      />
                    </div>

                    <div className="sm:col-span-2">
                      <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                        Portfolio / GitHub Profile URL
                      </label>
                      <input
                        type="url"
                        placeholder="https://github.com/username or https://portfolio.dev"
                        value={personalDetails.portfolio_url}
                        onChange={(e) => setPersonalDetails({ ...personalDetails, portfolio_url: e.target.value })}
                        className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                      />
                    </div>
                  </div>

                  <div className="pt-4 border-t border-slate-200 dark:border-slate-800 flex justify-end">
                    <button
                      type="submit"
                      disabled={submitting}
                      className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs shadow-md shadow-indigo-600/20 transition-all"
                    >
                      {submitting ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : null}
                      <span>Continue to Resume Upload</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </form>
              )}

              {/* ========================================================= */}
              {/* STEP 2: Resume Ingestion & Parsing Engine */}
              {/* ========================================================= */}
              {currentStep === 2 && (
                <div className="space-y-5">
                  <div className="space-y-1">
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                      Step 2: Upload Your Resume (PDF, DOCX, TXT)
                    </h3>
                    <p className="text-slate-500 dark:text-slate-400">
                      Our system extracts your work history intervals, academic credentials, and skills. Scanned PDFs automatically invoke local Apple Vision OCR.
                    </p>
                  </div>

                  {/* Dropzone */}
                  <div
                    onClick={() => fileInputRef.current?.click()}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault();
                      if (e.dataTransfer.files?.[0]) {
                        handleFileSelect(e.dataTransfer.files[0]);
                      }
                    }}
                    className={`border-2 border-dashed rounded-3xl p-8 text-center cursor-pointer transition-all ${
                      selectedFile
                        ? 'border-indigo-500 bg-indigo-50/20 dark:bg-indigo-950/20'
                        : 'border-slate-300 dark:border-slate-700 hover:border-indigo-500 dark:hover:border-indigo-400 bg-slate-50 dark:bg-slate-900/50'
                    }`}
                  >
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".pdf,.docx,.txt"
                      className="hidden"
                      onChange={(e) => {
                        if (e.target.files?.[0]) handleFileSelect(e.target.files[0]);
                      }}
                    />

                    <div className="w-14 h-14 rounded-2xl bg-indigo-100 dark:bg-indigo-950/80 text-indigo-600 dark:text-indigo-400 flex items-center justify-center mx-auto mb-3">
                      <UploadCloud className="w-7 h-7" />
                    </div>

                    {selectedFile ? (
                      <div className="space-y-1">
                        <div className="text-sm font-bold text-slate-900 dark:text-white flex items-center justify-center gap-1.5">
                          <FileText className="w-4 h-4 text-indigo-600" />
                          <span>{selectedFile.name}</span>
                        </div>
                        <div className="text-slate-400 text-[11px]">
                          {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB · Click or drag to replace
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-1">
                        <div className="text-sm font-bold text-slate-900 dark:text-white">
                          Click to browse or drag and drop your resume
                        </div>
                        <p className="text-slate-400 text-[11px]">
                          Supported formats: PDF (digital or scanned), DOCX, TXT. Max size 10 MB.
                        </p>
                      </div>
                    )}
                  </div>

                  {/* Parsing progress & status */}
                  {parsingStatus === 'parsing' && (
                    <div className="p-4 rounded-2xl bg-indigo-50 dark:bg-indigo-950/40 border border-indigo-100 dark:border-indigo-900 space-y-2 text-center">
                      <div className="flex items-center justify-center gap-2 font-bold text-indigo-900 dark:text-indigo-200">
                        <RefreshCw className="w-4 h-4 animate-spin text-indigo-600" />
                        <span>Extracting career timeline and running discrepancy checks...</span>
                      </div>
                      <p className="text-[11px] text-indigo-600 dark:text-indigo-400">
                        Computing non-overlapping work intervals and verifying academic threshold compliance.
                      </p>
                    </div>
                  )}

                  <div className="pt-4 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between">
                    <button
                      type="button"
                      onClick={() => setCurrentStep(1)}
                      className="px-4 py-2 rounded-xl text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold"
                    >
                      Back
                    </button>

                    <button
                      type="button"
                      disabled={!selectedFile || parsingStatus === 'parsing'}
                      onClick={handleUploadAndParseResume}
                      className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-bold text-xs shadow-md shadow-indigo-600/20 transition-all"
                    >
                      {parsingStatus === 'parsing' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : null}
                      <span>Upload & Parse Resume</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              )}

              {/* ========================================================= */}
              {/* STEP 3: Structured Career Dossier Multi-Section Editor */}
              {/* ========================================================= */}
              {currentStep === 3 && (
                <div className="space-y-6">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div>
                      <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                        Step 3: Review & Edit Parsed Career Dossier
                      </h3>
                      <p className="text-slate-500 dark:text-slate-400">
                        Information extracted from your resume is pre-populated below. Review and edit any field to ensure maximum signal during your interview.
                      </p>
                    </div>

                    <div className="px-3 py-1.5 rounded-xl bg-indigo-50 dark:bg-indigo-950/60 border border-indigo-200/60 dark:border-indigo-800 text-indigo-700 dark:text-indigo-300 font-bold text-xs flex items-center gap-1.5 self-start sm:self-auto">
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>Timeline: ~{(structuredData.total_experience_years || 0).toFixed(1)} YOE</span>
                    </div>
                  </div>

                  {/* Sub-Navigation Tabs */}
                  <div className="flex flex-wrap gap-1 p-1 rounded-2xl bg-slate-100 dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800">
                    <button
                      type="button"
                      onClick={() => setCareerTab('experience')}
                      className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold transition-all ${
                        careerTab === 'experience'
                          ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-sm'
                          : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                      }`}
                    >
                      <Briefcase className="w-3.5 h-3.5" />
                      <span>Experience ({structuredData.work_experience.length})</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => setCareerTab('education')}
                      className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold transition-all ${
                        careerTab === 'education'
                          ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-sm'
                          : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                      }`}
                    >
                      <GraduationCap className="w-3.5 h-3.5" />
                      <span>Schooling ({structuredData.education.length})</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => setCareerTab('certifications')}
                      className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold transition-all ${
                        careerTab === 'certifications'
                          ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-sm'
                          : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                      }`}
                    >
                      <Award className="w-3.5 h-3.5" />
                      <span>Certifications ({structuredData.certifications.length})</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => setCareerTab('projects')}
                      className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold transition-all ${
                        careerTab === 'projects'
                          ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-sm'
                          : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                      }`}
                    >
                      <FolderGit2 className="w-3.5 h-3.5" />
                      <span>Projects ({structuredData.projects.length})</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => setCareerTab('skills')}
                      className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold transition-all ${
                        careerTab === 'skills'
                          ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-sm'
                          : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                      }`}
                    >
                      <Code2 className="w-3.5 h-3.5" />
                      <span>Categorized Skills ({structuredData.skills.length})</span>
                    </button>
                  </div>

                  {/* TAB 1: WORK EXPERIENCE */}
                  {careerTab === 'experience' && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="font-bold uppercase tracking-wider text-slate-500 text-[11px]">
                          Work Experience History ({structuredData.work_experience.length})
                        </span>
                        <button
                          type="button"
                          onClick={handleAddExperience}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/60 hover:bg-indigo-100"
                        >
                          <Plus className="w-3 h-3" />
                          <span>Add Position</span>
                        </button>
                      </div>

                      {structuredData.work_experience.length === 0 ? (
                        <div className="p-6 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-center text-slate-400 text-xs">
                          No work experience entries recorded. Click "Add Position" to add your work history.
                        </div>
                      ) : (
                        <div className="space-y-3">
                          {structuredData.work_experience.map((exp, idx) => (
                            <div
                              key={idx}
                              className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-3 relative group"
                            >
                              <div className="flex items-center justify-between">
                                <span className="text-[11px] font-bold text-indigo-600 dark:text-indigo-400">
                                  Position #{idx + 1}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => handleRemoveExperience(idx)}
                                  className="p-1 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>

                              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Company / Organization</label>
                                  <input
                                    type="text"
                                    value={exp.company || ''}
                                    onChange={(e) => handleExperienceChange(idx, 'company', e.target.value)}
                                    placeholder="e.g. Stripe, Google, Acme Corp"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Job Title / Role</label>
                                  <input
                                    type="text"
                                    value={exp.role || ''}
                                    onChange={(e) => handleExperienceChange(idx, 'role', e.target.value)}
                                    placeholder="e.g. Senior Software Engineer"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Start Date</label>
                                  <input
                                    type="text"
                                    value={exp.start_date || ''}
                                    onChange={(e) => handleExperienceChange(idx, 'start_date', e.target.value)}
                                    placeholder="e.g. Jan 2021"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">End Date</label>
                                  <input
                                    type="text"
                                    value={exp.end_date || ''}
                                    onChange={(e) => handleExperienceChange(idx, 'end_date', e.target.value)}
                                    placeholder="e.g. Present or Dec 2023"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div className="sm:col-span-2">
                                  <label className="block text-slate-500 font-semibold mb-1">Role Highlights & Summary</label>
                                  <textarea
                                    rows={2}
                                    value={exp.description || (exp.highlights || []).join('; ')}
                                    onChange={(e) => handleExperienceChange(idx, 'description', e.target.value)}
                                    placeholder="Key technical accomplishments, architectural design, team leadership..."
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* TAB 2: SCHOOLING & EDUCATION */}
                  {careerTab === 'education' && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="font-bold uppercase tracking-wider text-slate-500 text-[11px]">
                          Schooling & Academic Degrees ({structuredData.education.length})
                        </span>
                        <button
                          type="button"
                          onClick={handleAddEducation}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/60 hover:bg-indigo-100"
                        >
                          <Plus className="w-3 h-3" />
                          <span>Add Degree</span>
                        </button>
                      </div>

                      {structuredData.education.length === 0 ? (
                        <div className="p-6 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-center text-slate-400 text-xs">
                          No education degrees detected. Click "Add Degree" to specify your academic background.
                        </div>
                      ) : (
                        <div className="space-y-3">
                          {structuredData.education.map((edu, idx) => (
                            <div
                              key={idx}
                              className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-3 relative group"
                            >
                              <div className="flex items-center justify-between">
                                <span className="text-[11px] font-bold text-indigo-600 dark:text-indigo-400">
                                  Degree #{idx + 1}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => handleRemoveEducation(idx)}
                                  className="p-1 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>

                              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Degree Title</label>
                                  <input
                                    type="text"
                                    value={edu.degree || ''}
                                    onChange={(e) => handleEducationChange(idx, 'degree', e.target.value)}
                                    placeholder="e.g. Bachelor of Science, B.Tech, Master of Science"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Institution / University</label>
                                  <input
                                    type="text"
                                    value={edu.institution || ''}
                                    onChange={(e) => handleEducationChange(idx, 'institution', e.target.value)}
                                    placeholder="e.g. Stanford University, MIT, IIT Delhi"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Major / Field of Study</label>
                                  <input
                                    type="text"
                                    value={edu.field || ''}
                                    onChange={(e) => handleEducationChange(idx, 'field', e.target.value)}
                                    placeholder="e.g. Computer Science, Information Systems"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Graduation Year</label>
                                  <input
                                    type="number"
                                    value={edu.graduation_year || ''}
                                    onChange={(e) => handleEducationChange(idx, 'graduation_year', parseInt(e.target.value) || null)}
                                    placeholder="e.g. 2022"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">GPA / CGPA (Optional)</label>
                                  <input
                                    type="text"
                                    value={edu.gpa || ''}
                                    onChange={(e) => handleEducationChange(idx, 'gpa', e.target.value)}
                                    placeholder="e.g. 3.8 / 4.0 or 8.5 / 10"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Honors / Distinctions (Optional)</label>
                                  <input
                                    type="text"
                                    value={edu.honors || ''}
                                    onChange={(e) => handleEducationChange(idx, 'honors', e.target.value)}
                                    placeholder="e.g. Magna Cum Laude, Dean's List"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* TAB 3: CERTIFICATIONS */}
                  {careerTab === 'certifications' && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="font-bold uppercase tracking-wider text-slate-500 text-[11px]">
                          Professional Certifications ({structuredData.certifications.length})
                        </span>
                        <button
                          type="button"
                          onClick={handleAddCertification}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/60 hover:bg-indigo-100"
                        >
                          <Plus className="w-3 h-3" />
                          <span>Add Certification</span>
                        </button>
                      </div>

                      {structuredData.certifications.length === 0 ? (
                        <div className="p-6 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-center text-slate-400 text-xs">
                          No certifications detected. Click "Add Certification" to add your professional credentials.
                        </div>
                      ) : (
                        <div className="space-y-3">
                          {structuredData.certifications.map((cert, idx) => (
                            <div
                              key={idx}
                              className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-3 relative group"
                            >
                              <div className="flex items-center justify-between">
                                <span className="text-[11px] font-bold text-indigo-600 dark:text-indigo-400">
                                  Credential #{idx + 1}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => handleRemoveCertification(idx)}
                                  className="p-1 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>

                              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Certification Name</label>
                                  <input
                                    type="text"
                                    value={cert.name || ''}
                                    onChange={(e) => handleCertificationChange(idx, 'name', e.target.value)}
                                    placeholder="e.g. AWS Solutions Architect Associate"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Issuing Organization</label>
                                  <input
                                    type="text"
                                    value={cert.issuing_org || ''}
                                    onChange={(e) => handleCertificationChange(idx, 'issuing_org', e.target.value)}
                                    placeholder="e.g. Amazon Web Services, Google Cloud, Cisco"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Issue Year</label>
                                  <input
                                    type="number"
                                    value={cert.issue_year || ''}
                                    onChange={(e) => handleCertificationChange(idx, 'issue_year', parseInt(e.target.value) || null)}
                                    placeholder="e.g. 2023"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Credential ID / Verification URL</label>
                                  <input
                                    type="text"
                                    value={cert.credential_id || cert.url || ''}
                                    onChange={(e) => handleCertificationChange(idx, 'credential_id', e.target.value)}
                                    placeholder="e.g. AWS-1092837 or verification URL"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* TAB 4: PROJECTS */}
                  {careerTab === 'projects' && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="font-bold uppercase tracking-wider text-slate-500 text-[11px]">
                          Notable Projects ({structuredData.projects.length})
                        </span>
                        <button
                          type="button"
                          onClick={handleAddProject}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/60 hover:bg-indigo-100"
                        >
                          <Plus className="w-3 h-3" />
                          <span>Add Project</span>
                        </button>
                      </div>

                      {structuredData.projects.length === 0 ? (
                        <div className="p-6 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-center text-slate-400 text-xs">
                          No projects detected. Click "Add Project" to showcase key software or research projects.
                        </div>
                      ) : (
                        <div className="space-y-3">
                          {structuredData.projects.map((proj, idx) => (
                            <div
                              key={idx}
                              className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-3 relative group"
                            >
                              <div className="flex items-center justify-between">
                                <span className="text-[11px] font-bold text-indigo-600 dark:text-indigo-400">
                                  Project #{idx + 1}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => handleRemoveProject(idx)}
                                  className="p-1 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>

                              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Project Title</label>
                                  <input
                                    type="text"
                                    value={proj.title || ''}
                                    onChange={(e) => handleProjectChange(idx, 'title', e.target.value)}
                                    placeholder="e.g. Real-Time Distributed Voice Engine"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Your Role</label>
                                  <input
                                    type="text"
                                    value={proj.role || ''}
                                    onChange={(e) => handleProjectChange(idx, 'role', e.target.value)}
                                    placeholder="e.g. Lead Engineer / Creator"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Technologies Used (comma separated)</label>
                                  <input
                                    type="text"
                                    value={(proj.technologies || []).join(', ')}
                                    onChange={(e) => handleProjectTechChange(idx, e.target.value)}
                                    placeholder="e.g. Python, FastAPI, WebSockets, PostgreSQL, Docker"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div>
                                  <label className="block text-slate-500 font-semibold mb-1">Project / Repository URL</label>
                                  <input
                                    type="text"
                                    value={proj.url || ''}
                                    onChange={(e) => handleProjectChange(idx, 'url', e.target.value)}
                                    placeholder="e.g. https://github.com/user/project"
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>

                                <div className="sm:col-span-2">
                                  <label className="block text-slate-500 font-semibold mb-1">Description & Impact</label>
                                  <textarea
                                    rows={2}
                                    value={proj.description || ''}
                                    onChange={(e) => handleProjectChange(idx, 'description', e.target.value)}
                                    placeholder="Explain the architectural challenge, scale achieved, and key algorithms implemented..."
                                    className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                  />
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* TAB 5: CATEGORIZED SKILLS */}
                  {careerTab === 'skills' && (
                    <div className="space-y-4">
                      <div className="space-y-1">
                        <span className="font-bold uppercase tracking-wider text-slate-500 text-[11px]">
                          Technical Skills Taxonomy By Category
                        </span>
                        <p className="text-slate-400 text-xs">
                          Classifying your skills into categories gives the LLM interviewer clear anchors for architectural and deep-dive technical questions.
                        </p>
                      </div>

                      {['Languages', 'Frameworks', 'Databases', 'Cloud & DevOps', 'Tools'].map((cat) => {
                        const catSkills = structuredData.skills_by_category?.[cat] || [];
                        return (
                          <div key={cat} className="p-3.5 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-2">
                            <div className="flex items-center justify-between text-xs font-bold text-slate-700 dark:text-slate-300">
                              <span>{cat} ({catSkills.length})</span>
                              <div className="flex items-center gap-1.5">
                                <input
                                  type="text"
                                  value={categorizedSkillInputs[cat] || ''}
                                  onChange={(e) => setCategorizedSkillInputs({ ...categorizedSkillInputs, [cat]: e.target.value })}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                      e.preventDefault();
                                      handleAddCategorizedSkill(cat, categorizedSkillInputs[cat] || '');
                                    }
                                  }}
                                  placeholder={`Add to ${cat}...`}
                                  className="px-2.5 py-1 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                                />
                                <button
                                  type="button"
                                  onClick={() => handleAddCategorizedSkill(cat, categorizedSkillInputs[cat] || '')}
                                  className="px-2 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-[11px]"
                                >
                                  Add
                                </button>
                              </div>
                            </div>

                            <div className="flex flex-wrap gap-1.5 min-h-[32px] items-center">
                              {catSkills.length === 0 ? (
                                <span className="text-slate-400 text-xs italic">No {cat.toLowerCase()} added yet.</span>
                              ) : (
                                catSkills.map((s, sIdx) => (
                                  <span
                                    key={sIdx}
                                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 font-semibold text-xs"
                                  >
                                    <span>{s}</span>
                                    <button
                                      type="button"
                                      onClick={() => handleRemoveCategorizedSkill(cat, s)}
                                      className="text-slate-400 hover:text-rose-500"
                                    >
                                      <X className="w-3 h-3" />
                                    </button>
                                  </span>
                                ))
                              )}
                            </div>
                          </div>
                        );
                      })}

                      {/* General Flat Skills */}
                      <div className="pt-2 border-t border-slate-200 dark:border-slate-800 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="font-bold uppercase tracking-wider text-slate-500 text-[11px]">
                            All Detected Skills ({structuredData.skills.length})
                          </span>
                          <div className="flex items-center gap-1.5">
                            <input
                              type="text"
                              value={newSkillInput}
                              onChange={(e) => setNewSkillInput(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault();
                                  handleAddSkill(newSkillInput);
                                }
                              }}
                              placeholder="Add general skill..."
                              className="px-2.5 py-1 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                            />
                            <button
                              type="button"
                              onClick={() => handleAddSkill(newSkillInput)}
                              className="px-2 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-[11px]"
                            >
                              Add
                            </button>
                          </div>
                        </div>

                        <div className="flex flex-wrap gap-1.5 p-3 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
                          {structuredData.skills.map((skill, sIdx) => (
                            <span
                              key={sIdx}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 font-semibold text-xs"
                            >
                              <span>{skill}</span>
                              <button
                                type="button"
                                onClick={() => handleRemoveSkill(skill)}
                                className="text-slate-400 hover:text-rose-500"
                              >
                                <X className="w-3 h-3" />
                              </button>
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Navigation Buttons for Step 3 */}
                  <div className="pt-4 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between">
                    <button
                      type="button"
                      onClick={() => setCurrentStep(2)}
                      className="px-4 py-2 rounded-xl text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold text-xs"
                    >
                      Back to Upload
                    </button>

                    <button
                      type="button"
                      disabled={submitting}
                      onClick={handleSaveResumeCorrections}
                      className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs shadow-md shadow-indigo-600/20 transition-all"
                    >
                      {submitting ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : null}
                      <span>Save & Continue to Compensation</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              )}

              {/* ========================================================= */}
              {/* STEP 4: Fit Pitch & Compensation Expectations */}
              {/* ========================================================= */}
              {currentStep === 4 && (
                <div className="space-y-6">
                  <div className="space-y-1">
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                      Step 4: Role Fit Pitch & Compensation Expectations
                    </h3>
                    <p className="text-slate-500 dark:text-slate-400">
                      State your total years of experience, why you are a fit, and your desired compensation.
                    </p>
                  </div>

                  {/* Compensation benchmark card */}
                  <div className="p-4 rounded-2xl bg-gradient-to-r from-emerald-500/10 via-indigo-500/10 to-transparent border border-emerald-500/20 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div>
                      <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Role Compensation Budget</div>
                      <div className="text-base font-black text-emerald-700 dark:text-emerald-300 mt-0.5">
                        {job.salary_range_min ? `${formatMoney(job.salary_range_min, job.salary_currency)} - ${formatMoney(job.salary_range_max, job.salary_currency)}` : 'Competitive'}
                      </div>
                    </div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      Required Experience: <strong className="text-slate-800 dark:text-slate-200">{job.total_experience_years}+ Years</strong>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                        Self-Reported Experience (Years) <span className="text-rose-500">*</span>
                      </label>
                      <input
                        type="number"
                        step="0.5"
                        min="0"
                        max="50"
                        value={fitData.self_reported_experience_years}
                        onChange={(e) => setFitData({ ...fitData, self_reported_experience_years: parseFloat(e.target.value) || 0 })}
                        className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                      />
                      <span className="text-[11px] text-slate-400 mt-1 block">
                        Resume derived timeline: ~{structuredData.total_experience_years.toFixed(1)} years.
                      </span>
                    </div>

                    <div>
                      <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                        Expected Annual Salary
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="number"
                          step="1000"
                          placeholder="e.g. 150000"
                          value={fitData.expected_salary}
                          onChange={(e) => setFitData({ ...fitData, expected_salary: parseFloat(e.target.value) || 0 })}
                          className="flex-1 px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                        />
                        <select
                          value={fitData.expected_salary_currency}
                          onChange={(e) => setFitData({ ...fitData, expected_salary_currency: e.target.value })}
                          className="px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm font-semibold"
                        >
                          <option value="USD">USD</option>
                          <option value="EUR">EUR</option>
                          <option value="GBP">GBP</option>
                          <option value="CAD">CAD</option>
                          <option value="AUD">AUD</option>
                          <option value="INR">INR</option>
                        </select>
                      </div>
                    </div>

                    <div className="sm:col-span-2">
                      <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                        Why are you a fit for this role? <span className="text-slate-400 font-normal">(Fit Pitch)</span>
                      </label>
                      <textarea
                        rows={4}
                        placeholder="Briefly highlight your relevant engineering background, architectural designs you have built, or distributed systems experience..."
                        value={fitData.fit_pitch}
                        onChange={(e) => setFitData({ ...fitData, fit_pitch: e.target.value })}
                        className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-indigo-500"
                      />
                    </div>
                  </div>

                  <div className="pt-4 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between">
                    <button
                      type="button"
                      onClick={() => setCurrentStep(3)}
                      className="px-4 py-2 rounded-xl text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold"
                    >
                      Back
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setCurrentStep(5);
                        startWebcam();
                      }}
                      className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs shadow-md shadow-indigo-600/20 transition-all"
                    >
                      <span>Continue to Live ID Verification</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              )}

              {/* ========================================================= */}
              {/* STEP 5: Live Webcam ID Verification */}
              {/* ========================================================= */}
              {currentStep === 5 && (
                <div className="space-y-6">
                  <div className="space-y-1">
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                      Step 5: Live Identity Verification & Proctoring Baseline
                    </h3>
                    <p className="text-slate-500 dark:text-slate-400">
                      Take a real-time webcam photo snapshot to establish your biometric interview baseline.
                    </p>
                  </div>

                  {cameraError && (
                    <div className="p-3.5 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900 text-amber-800 dark:text-amber-200 text-xs flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 shrink-0" />
                      <span>{cameraError}</span>
                    </div>
                  )}

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* Live Webcam Box */}
                    <div className="space-y-3">
                      <div className="text-xs font-bold text-slate-700 dark:text-slate-300 flex items-center justify-between">
                        <span>Webcam Snapshot</span>
                        {liveSnapshot && (
                          <span className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            Captured
                          </span>
                        )}
                      </div>

                      <div className="relative aspect-video rounded-2xl bg-slate-950 overflow-hidden flex items-center justify-center border border-slate-800">
                        {liveSnapshot ? (
                          <img
                            src={liveSnapshot}
                            alt="Live snapshot preview"
                            className="w-full h-full object-cover"
                          />
                        ) : (
                          <video
                            ref={videoRef}
                            autoPlay
                            playsInline
                            muted
                            className="w-full h-full object-cover"
                          />
                        )}

                        <canvas ref={canvasRef} className="hidden" />
                      </div>

                      <div className="flex gap-2">
                        {liveSnapshot ? (
                          <button
                            type="button"
                            onClick={retakeSnapshot}
                            className="flex-1 py-2 px-3 rounded-xl border border-slate-300 dark:border-slate-700 text-xs font-bold text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
                          >
                            Retake Photo
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={captureSnapshot}
                            className="flex-1 py-2.5 px-3 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold shadow-md shadow-indigo-600/20 flex items-center justify-center gap-2"
                          >
                            <Camera className="w-4 h-4" />
                            <span>Capture Photo Snapshot</span>
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Government ID Document (Optional) */}
                    <div className="space-y-3">
                      <div className="text-xs font-bold text-slate-700 dark:text-slate-300 flex items-center justify-between">
                        <span>Government ID (Optional)</span>
                        <span className="text-[10px] text-slate-400 font-normal">Passport / Driver's License</span>
                      </div>

                      <div className="aspect-video rounded-2xl border-2 border-dashed border-slate-300 dark:border-slate-700 flex flex-col items-center justify-center p-4 text-center bg-slate-50 dark:bg-slate-900/40 relative overflow-hidden">
                        {govIdPreview ? (
                          <img src={govIdPreview} alt="Gov ID preview" className="w-full h-full object-contain" />
                        ) : (
                          <div className="space-y-2">
                            <ShieldCheck className="w-8 h-8 text-slate-400 mx-auto" />
                            <div className="text-[11px] text-slate-500">
                              Upload a photo of your ID for accelerated verification
                            </div>
                            <label className="inline-block px-3 py-1.5 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-xs font-bold text-indigo-600 dark:text-indigo-400 cursor-pointer hover:bg-slate-50">
                              <span>Choose ID File</span>
                              <input
                                type="file"
                                accept="image/*,.pdf"
                                className="hidden"
                                onChange={(e) => {
                                  if (e.target.files?.[0]) handleGovIdSelect(e.target.files[0]);
                                }}
                              />
                            </label>
                          </div>
                        )}
                      </div>

                      {govIdPreview && (
                        <button
                          type="button"
                          onClick={() => {
                            setGovIdFile(null);
                            setGovIdPreview(null);
                          }}
                          className="w-full py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-[11px] text-slate-500 hover:text-rose-600"
                        >
                          Remove ID Document
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="pt-4 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between">
                    <button
                      type="button"
                      onClick={() => {
                        stopWebcam();
                        setCurrentStep(4);
                      }}
                      className="px-4 py-2 rounded-xl text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold"
                    >
                      Back
                    </button>

                    <button
                      type="button"
                      disabled={!liveSnapshot || submitting}
                      onClick={handleSaveVerification}
                      className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-bold text-xs shadow-md shadow-indigo-600/20 transition-all"
                    >
                      {submitting ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : null}
                      <span>Save & Final Review</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              )}

              {/* ========================================================= */}
              {/* STEP 6: Final Review & Confirmation */}
              {/* ========================================================= */}
              {currentStep === 6 && (
                <div className="space-y-6">
                  <div className="space-y-1">
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                      Step 6: Review & Confirm Application Submission
                    </h3>
                    <p className="text-slate-500 dark:text-slate-400">
                      Verify your application summary before confirming your entry into the candidate queue.
                    </p>
                  </div>

                  {/* Summary Cards */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-2">
                      <div className="text-[11px] font-bold uppercase text-slate-400">Candidate</div>
                      <div className="font-bold text-slate-900 dark:text-white text-sm">{personalDetails.full_name}</div>
                      <div className="text-slate-500 text-[11px]">{personalDetails.email}</div>
                      {personalDetails.phone && <div className="text-slate-500 text-[11px]">{personalDetails.phone}</div>}
                    </div>

                    <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-2">
                      <div className="text-[11px] font-bold uppercase text-slate-400">Experience & Pitch</div>
                      <div className="text-slate-800 dark:text-slate-200 font-bold">
                        Stated: {fitData.self_reported_experience_years} YOE
                      </div>
                      <div className="text-slate-500 text-[11px]">
                        Resume Timeline: ~{structuredData.total_experience_years.toFixed(1)} YOE
                      </div>
                      <div className="text-emerald-600 dark:text-emerald-400 font-bold text-[11px]">
                        Expected: {formatMoney(fitData.expected_salary, fitData.expected_salary_currency)}
                      </div>
                    </div>

                    <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-2 flex flex-col items-center justify-center text-center">
                      <div className="text-[11px] font-bold uppercase text-slate-400">Identity Baseline</div>
                      {liveSnapshot ? (
                        <div className="w-16 h-16 rounded-xl overflow-hidden border border-emerald-500/50 shadow-sm">
                          <img src={liveSnapshot} alt="Snapshot preview" className="w-full h-full object-cover" />
                        </div>
                      ) : (
                        <span className="text-amber-500 font-semibold">Missing snapshot</span>
                      )}
                      <span className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400">Webcam Verified</span>
                    </div>
                  </div>

                  {/* Discrepancy Warnings (if any) */}
                  {discrepancyFlags && discrepancyFlags.length > 0 && (
                    <div className="p-4 rounded-2xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900/60 space-y-2">
                      <div className="flex items-center gap-2 text-xs font-bold text-amber-800 dark:text-amber-200">
                        <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
                        <span>Automated Consistency Notice ({discrepancyFlags.length})</span>
                      </div>
                      <ul className="text-[11px] text-amber-700 dark:text-amber-300 space-y-1 list-disc list-inside">
                        {discrepancyFlags.map((flag, fIdx) => (
                          <li key={fIdx}>{flag.flag_reason}</li>
                        ))}
                      </ul>
                      <p className="text-[10px] text-slate-500 pt-1">
                        Note: Flags are informational to ensure fair evaluation and will be reviewed by the hiring lead.
                      </p>
                    </div>
                  )}

                  {/* Pitch preview */}
                  {fitData.fit_pitch && (
                    <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <div className="font-bold text-slate-500 uppercase text-[10px]">Your Fit Pitch</div>
                      <p className="text-slate-700 dark:text-slate-300 text-xs italic">
                        "{fitData.fit_pitch}"
                      </p>
                    </div>
                  )}

                  {/* Career Credentials Overview */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                    <div className="p-3.5 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1">
                      <div className="flex items-center gap-1 text-[10px] font-bold uppercase text-slate-400">
                        <GraduationCap className="w-3.5 h-3.5 text-indigo-500" />
                        <span>Education ({structuredData.education.length})</span>
                      </div>
                      {structuredData.education.length === 0 ? (
                        <div className="text-slate-400 text-[11px]">None listed</div>
                      ) : (
                        structuredData.education.slice(0, 2).map((edu, idx) => (
                          <div key={idx} className="font-semibold text-slate-800 dark:text-slate-200 truncate text-[11px]">
                            {edu.degree} · <span className="text-slate-500">{edu.institution}</span>
                          </div>
                        ))
                      )}
                    </div>

                    <div className="p-3.5 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1">
                      <div className="flex items-center gap-1 text-[10px] font-bold uppercase text-slate-400">
                        <FolderGit2 className="w-3.5 h-3.5 text-indigo-500" />
                        <span>Key Projects ({structuredData.projects.length})</span>
                      </div>
                      {structuredData.projects.length === 0 ? (
                        <div className="text-slate-400 text-[11px]">None listed</div>
                      ) : (
                        structuredData.projects.slice(0, 2).map((proj, idx) => (
                          <div key={idx} className="font-semibold text-slate-800 dark:text-slate-200 truncate text-[11px]">
                            {proj.title} <span className="text-slate-500 text-[10px]">({(proj.technologies || []).slice(0, 2).join(', ')})</span>
                          </div>
                        ))
                      )}
                    </div>

                    <div className="p-3.5 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1">
                      <div className="flex items-center gap-1 text-[10px] font-bold uppercase text-slate-400">
                        <Award className="w-3.5 h-3.5 text-indigo-500" />
                        <span>Certifications ({structuredData.certifications.length})</span>
                      </div>
                      {structuredData.certifications.length === 0 ? (
                        <div className="text-slate-400 text-[11px]">None listed</div>
                      ) : (
                        structuredData.certifications.slice(0, 2).map((c, idx) => (
                          <div key={idx} className="font-semibold text-slate-800 dark:text-slate-200 truncate text-[11px]">
                            {c.name} · <span className="text-slate-500">{c.issuing_org}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  <div className="pt-4 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between">
                    <button
                      type="button"
                      onClick={() => setCurrentStep(5)}
                      className="px-4 py-2 rounded-xl text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold"
                    >
                      Back
                    </button>

                    <button
                      type="button"
                      disabled={submitting}
                      onClick={handleFinalSubmit}
                      className="inline-flex items-center gap-2 px-8 py-3 rounded-2xl bg-emerald-600 hover:bg-emerald-700 text-white font-extrabold text-sm shadow-lg shadow-emerald-600/20 hover:-translate-y-0.5 transition-all"
                    >
                      {submitting ? <RefreshCw className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                      <span>Confirm & Submit Application</span>
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

        </div>

      </div>
    </div>
  );
}

