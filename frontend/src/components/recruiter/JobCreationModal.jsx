import React, { useState, useMemo } from 'react';
import {
  X, Plus, Trash2, CheckCircle2, AlertTriangle, Clock, ShieldCheck,
  Award, BookOpen, Briefcase, Settings2, HelpCircle, Layers, Sparkles, ArrowRight
} from 'lucide-react';

export default function JobCreationModal({ isOpen, onClose, onJobCreated }) {
  if (!isOpen) return null;

  const [activeStep, setActiveStep] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  // Form State
  const [formData, setFormData] = useState({
    // 1. Role Metadata
    job_title: '',
    department: '',
    job_description: '',
    seniority_level: 'Mid-Level (L4)',
    employment_type: 'Full-Time',
    workplace_model: 'Remote',
    permitted_locations_str: 'Global Remote, United States, India',
    salary_range_min: 130000,
    salary_range_max: 175000,
    salary_currency: 'USD',

    // 2. Academic Metrics
    min_degree_level: "Bachelor's Degree (B.S. / B.E. / B.Tech)",
    degree_enforcement_type: 'Equivalent Professional Experience Allowed',
    accepted_majors_str: 'Computer Science, Software Engineering, Information Technology, Electrical Engineering',
    min_cgpa: '3.0 / 4.0',
    cgpa_strict_filter: false,
    grad_year_start: '',
    grad_year_end: '',

    // 3. Experience Metrics
    total_experience_years: 3.0,
    domain_experience_years: 2.0,
    leadership_required: false,

    // 4. Certifications
    certifications: [
      { name: 'AWS Certified Solutions Architect', issuing_org: 'Amazon Web Services', priority_tier: 'P1', verification_required: true }
    ],

    // 5. Skills & Rubrics
    skills: [
      {
        name: 'Data Structures & Algorithms',
        category: 'Core Technical',
        priority_tier: 'P0',
        weight_percentage: 35,
        rubric_l1: 'Fails basic algorithmic analysis; uses O(N^2) loops where O(N) is trivial.',
        rubric_l2: 'Understands basic syntax and hash tables but cannot optimize auxiliary space.',
        rubric_l3: 'Clean production-grade solution with verified optimal time/space complexity.',
        rubric_l4: 'Addresses memory locality, amortized runtime, and cache friendliness proactively.',
        rubric_l5: 'Deep low-level hardware cache hierarchy analysis and lock-free algorithmic primitives.'
      },
      {
        name: 'System Design & Scalability',
        category: 'Domain & Architectural',
        priority_tier: 'P0',
        weight_percentage: 30,
        rubric_l1: 'Proposes single-server monoliths; ignores caching and database replication.',
        rubric_l2: 'Mentions caching but cannot explain cache invalidation or replication lag trade-offs.',
        rubric_l3: 'Designs functional distributed system with load balancers, Redis, and read-replicas.',
        rubric_l4: 'Addresses distributed consensus, circuit breakers, idempotency, and backpressure.',
        rubric_l5: 'Deep trade-offs on engine internals (LSM vs B-Tree, Paxos vs Raft) and cost vs SLAs.'
      },
      {
        name: 'Database Architecture & Indexing',
        category: 'Tooling & Frameworks',
        priority_tier: 'P1',
        weight_percentage: 20,
        rubric_l1: 'Lacks understanding of indexing internals; queries unindexed large tables.',
        rubric_l2: 'Understands primary keys but cannot diagnose composite index order or lock contention.',
        rubric_l3: 'Configures appropriate indexes (B-Tree, Hash); balances normalized vs denormalized schemas.',
        rubric_l4: 'Analyzes transaction isolation levels (MVCC, phantom reads, and sharding keys).',
        rubric_l5: 'Designs distributed-SQL layers with multi-region quorum reads and conflict-free types.'
      },
      {
        name: 'Technical Communication',
        category: 'Soft & Cultural',
        priority_tier: 'P1',
        weight_percentage: 15,
        rubric_l1: 'Disorganized thought process; unable to articulate reasons for technical choices.',
        rubric_l2: 'Explains decisions when prompted but struggles to proactively frame trade-offs.',
        rubric_l3: 'Communicates with structured clarity (top-down articulation) before solving.',
        rubric_l4: 'Articulates nuanced trade-offs clearly; proactively invites architecture critique.',
        rubric_l5: 'Exemplary leadership presence; explains complex concepts with razor-sharp brevity.'
      }
    ],

    // 6. Interview Policy
    interview_duration_mins: 20,
    allow_grace_extension: true,
    max_followup_depth: 1,
    pacing_strictness: 'Balanced',
    interviewer_tone: 'Direct, technical, tech-lead caliber; probes for architectural trade-offs; warm but concise.',
    integrity_policy_tier: 'Moderate',

    // 7. Custom Questions
    custom_questions: [
      {
        question_text: 'Explain how you design a rate limiter handling 100k RPS with low latency.',
        category: 'Domain & Architectural',
        difficulty_level: 'Mid-Senior',
        expected_key_points_str: 'Proposes Redis sliding window or token bucket\nAddresses race conditions via Lua scripts\nHandles cluster failover and HTTP 429 backoff',
        priority_tier: 'P0'
      }
    ]
  });

  // Calculate sum of skill weights
  const totalWeight = useMemo(() => {
    return formData.skills.reduce((sum, s) => sum + (parseFloat(s.weight_percentage) || 0), 0);
  }, [formData.skills]);

  // Live Mathematical Question Budget Calculation (Part 2)
  const questionBudget = useMemo(() => {
    const duration = parseInt(formData.interview_duration_mins, 10) || 20;
    const overhead = duration <= 15 ? 3.0 : duration <= 20 ? 3.5 : duration <= 30 ? 4.0 : duration <= 45 ? 5.0 : 6.0;
    const activeEvalTime = Math.max(2.0, duration - overhead);
    const totalCoreQuestions = Math.round(activeEvalTime / 2.0);

    // Calculate allocation
    let totalAssigned = 0;
    const items = formData.skills.map((s) => {
      const weight = parseFloat(s.weight_percentage) || 0;
      const rawQuota = (totalCoreQuestions * weight) / 100.0;
      let baseInt = Math.floor(rawQuota);
      if (s.priority_tier === 'P0' && baseInt < 1 && totalCoreQuestions > 0) {
        baseInt = 1;
      }
      const remainder = rawQuota - Math.floor(rawQuota);
      totalAssigned += baseInt;
      return {
        name: s.name || 'Untitled Skill',
        priority: s.priority_tier,
        weight,
        allocated: baseInt,
        remainder
      };
    });

    const leftover = totalCoreQuestions - totalAssigned;
    if (leftover > 0 && items.length > 0) {
      items.sort((a, b) => b.remainder - a.remainder);
      for (let i = 0; i < leftover; i++) {
        items[i % items.length].allocated += 1;
      }
    }

    return {
      duration,
      overhead,
      activeEvalTime,
      totalCoreQuestions,
      items
    };
  }, [formData.interview_duration_mins, formData.skills]);

  // Handlers for Skills
  const handleAddSkill = () => {
    setFormData((prev) => ({
      ...prev,
      skills: [
        ...prev.skills,
        {
          name: '',
          category: 'Core Technical',
          priority_tier: 'P1',
          weight_percentage: 10,
          rubric_l1: '',
          rubric_l2: '',
          rubric_l3: '',
          rubric_l4: '',
          rubric_l5: ''
        }
      ]
    }));
  };

  const handleUpdateSkill = (index, field, value) => {
    setFormData((prev) => {
      const updated = [...prev.skills];
      updated[index] = { ...updated[index], [field]: value };
      return { ...prev, skills: updated };
    });
  };

  const handleRemoveSkill = (index) => {
    setFormData((prev) => ({
      ...prev,
      skills: prev.skills.filter((_, i) => i !== index)
    }));
  };

  // Handlers for Certifications
  const handleAddCert = () => {
    setFormData((prev) => ({
      ...prev,
      certifications: [
        ...prev.certifications,
        { name: '', issuing_org: '', priority_tier: 'P1', verification_required: false }
      ]
    }));
  };

  const handleUpdateCert = (index, field, value) => {
    setFormData((prev) => {
      const updated = [...prev.certifications];
      updated[index] = { ...updated[index], [field]: value };
      return { ...prev, certifications: updated };
    });
  };

  const handleRemoveCert = (index) => {
    setFormData((prev) => ({
      ...prev,
      certifications: prev.certifications.filter((_, i) => i !== index)
    }));
  };

  // Handlers for Custom Questions
  const handleAddQuestion = () => {
    setFormData((prev) => ({
      ...prev,
      custom_questions: [
        ...prev.custom_questions,
        {
          question_text: '',
          category: 'Core Technical',
          difficulty_level: 'Mid-Senior',
          expected_key_points_str: '',
          priority_tier: 'P0'
        }
      ]
    }));
  };

  const handleUpdateQuestion = (index, field, value) => {
    setFormData((prev) => {
      const updated = [...prev.custom_questions];
      updated[index] = { ...updated[index], [field]: value };
      return { ...prev, custom_questions: updated };
    });
  };

  const handleRemoveQuestion = (index) => {
    setFormData((prev) => ({
      ...prev,
      custom_questions: prev.custom_questions.filter((_, i) => i !== index)
    }));
  };

  // Form Submit
  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrorMsg(null);

    if (!formData.job_title.trim() || !formData.department.trim()) {
      setErrorMsg('Please enter both Job Title and Department.');
      setActiveStep(1);
      return;
    }

    if (Math.round(totalWeight) !== 100) {
      setErrorMsg(`Skill weightages must equal exactly 100%. Current sum is ${totalWeight}%.`);
      setActiveStep(4);
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        job_title: formData.job_title.trim(),
        department: formData.department.trim(),
        job_description: formData.job_description.trim() || 'N/A',
        seniority_level: formData.seniority_level,
        employment_type: formData.employment_type,
        workplace_model: formData.workplace_model,
        permitted_locations: formData.permitted_locations_str.split(',').map((s) => s.trim()).filter(Boolean),
        min_degree_level: formData.min_degree_level,
        degree_enforcement_type: formData.degree_enforcement_type,
        accepted_majors: formData.accepted_majors_str.split(',').map((s) => s.trim()).filter(Boolean),
        min_cgpa: formData.min_cgpa,
        cgpa_strict_filter: formData.cgpa_strict_filter,
        grad_year_start: formData.grad_year_start ? parseInt(formData.grad_year_start, 10) : null,
        grad_year_end: formData.grad_year_end ? parseInt(formData.grad_year_end, 10) : null,
        total_experience_years: parseFloat(formData.total_experience_years) || 0,
        domain_experience_years: parseFloat(formData.domain_experience_years) || 0,
        leadership_required: formData.leadership_required,
        interview_duration_mins: parseInt(formData.interview_duration_mins, 10),
        allow_grace_extension: formData.allow_grace_extension,
        max_followup_depth: parseInt(formData.max_followup_depth, 10),
        pacing_strictness: formData.pacing_strictness,
        interviewer_tone: formData.interviewer_tone,
        integrity_policy_tier: formData.integrity_policy_tier,
        salary_range_min: formData.salary_range_min ? parseFloat(formData.salary_range_min) : null,
        salary_range_max: formData.salary_range_max ? parseFloat(formData.salary_range_max) : null,
        salary_currency: formData.salary_currency || 'USD',
        skills: formData.skills.map((s) => ({
          name: s.name.trim(),
          category: s.category,
          priority_tier: s.priority_tier,
          weight_percentage: parseFloat(s.weight_percentage),
          rubric_l1: s.rubric_l1,
          rubric_l2: s.rubric_l2,
          rubric_l3: s.rubric_l3,
          rubric_l4: s.rubric_l4,
          rubric_l5: s.rubric_l5
        })),
        certifications: formData.certifications.map((c) => ({
          name: c.name.trim(),
          issuing_org: c.issuing_org.trim(),
          priority_tier: c.priority_tier,
          verification_required: c.verification_required
        })),
        custom_questions: formData.custom_questions.map((q) => ({
          question_text: q.question_text.trim(),
          category: q.category,
          difficulty_level: q.difficulty_level,
          expected_key_points: q.expected_key_points_str.split('\n').map((k) => k.trim()).filter(Boolean),
          priority_tier: q.priority_tier
        }))
      };

      const token = localStorage.getItem('candidly-auth-token');
      const headers = {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {})
      };

      const res = await fetch('/api/jobs', {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to create job posting');
      }

      const created = await res.json();
      onJobCreated(created);
      onClose();
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const steps = [
    { num: 1, label: 'Role Metadata', icon: Briefcase },
    { num: 2, label: 'Academic Criteria', icon: BookOpen },
    { num: 3, label: 'Experience & Certs', icon: Award },
    { num: 4, label: 'Skills & 5-Level Rubrics', icon: Layers },
    { num: 5, label: 'AI Interviewer Policy', icon: Settings2 },
    { num: 6, label: 'Custom Questions & Budget', icon: HelpCircle }
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-slate-950/75 backdrop-blur-sm animate-fadeIn">
      <div className="relative w-full max-w-5xl max-h-[92vh] flex flex-col rounded-3xl bg-white dark:bg-[#111827] border border-slate-200 dark:border-slate-800 shadow-2xl overflow-hidden">
        
        {/* Header */}
        <div className="px-6 py-4 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-600 text-white flex items-center justify-center shadow-md">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-xl font-extrabold text-slate-900 dark:text-white tracking-tight">
                Configure New Autonomous Role Policy
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Calibrates interview persona, 5-level rubrics, and the real-time question planner.
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

        {/* Step Navigation Bar */}
        <div className="flex overflow-x-auto border-b border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-900/50 px-6 scrollbar-none">
          {steps.map((step) => {
            const Icon = step.icon;
            const isActive = activeStep === step.num;
            return (
              <button
                key={step.num}
                type="button"
                onClick={() => setActiveStep(step.num)}
                className={`flex items-center gap-2 py-3.5 px-4 text-xs font-bold border-b-2 whitespace-nowrap transition-all ${
                  isActive
                    ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400 bg-white dark:bg-slate-900/70'
                    : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-white'
                }`}
              >
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] ${
                  isActive
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-200 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                }`}>
                  {step.num}
                </span>
                <span>{step.label}</span>
              </button>
            );
          })}
        </div>

        {/* Error Banner */}
        {errorMsg && (
          <div className="px-6 py-2.5 bg-rose-50 dark:bg-rose-950/50 border-b border-rose-200 dark:border-rose-900/50 flex items-center gap-2 text-xs text-rose-700 dark:text-rose-300 font-semibold">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Modal Scrollable Form Body */}
        <form onSubmit={handleSubmit} className="p-6 overflow-y-auto flex-1 space-y-6">
          
          {/* STEP 1: Role Identity & Metadata */}
          {activeStep === 1 && (
            <div className="space-y-4 text-xs">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Job Title <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Senior Distributed Systems Engineer"
                    value={formData.job_title}
                    onChange={(e) => setFormData({ ...formData, job_title: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-indigo-500"
                  />
                  <span className="text-[11px] text-slate-400 mt-1 block">Injected into the AI interviewer persona prompt.</span>
                </div>

                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Department / Business Unit <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Core Platform Infrastructure, Payments"
                    value={formData.department}
                    onChange={(e) => setFormData({ ...formData, department: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-indigo-500"
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Job Description
                  </label>
                  <textarea
                    rows={5}
                    placeholder="Describe the role, key responsibilities, required qualifications, and preferred qualifications."
                    value={formData.job_description}
                    onChange={(e) => setFormData({ ...formData, job_description: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm focus:ring-2 focus:ring-indigo-500 resize-y"
                  />
                  <span className="text-[11px] text-slate-400 mt-1 block">
                    Shown to candidates as the role overview and used as context for the AI interviewer.
                  </span>
                </div>

                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Seniority Level
                  </label>
                  <select
                    value={formData.seniority_level}
                    onChange={(e) => setFormData({ ...formData, seniority_level: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  >
                    <option>Intern</option>
                    <option>Entry-Level (L3)</option>
                    <option>Mid-Level (L4)</option>
                    <option>Senior (L5)</option>
                    <option>Lead / Principal</option>
                  </select>
                  <span className="text-[11px] text-slate-400 mt-1 block">Dictates foundational question difficulty and rubric strictness.</span>
                </div>

                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Employment Type
                  </label>
                  <select
                    value={formData.employment_type}
                    onChange={(e) => setFormData({ ...formData, employment_type: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  >
                    <option>Full-Time</option>
                    <option>Part-Time</option>
                    <option>Contract</option>
                    <option>Internship</option>
                  </select>
                </div>

                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Workplace Model
                  </label>
                  <select
                    value={formData.workplace_model}
                    onChange={(e) => setFormData({ ...formData, workplace_model: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  >
                    <option>Remote</option>
                    <option>Hybrid</option>
                    <option>On-site</option>
                  </select>
                </div>

                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Permitted Locations / Timezones
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. United States, Canada, India, Global Remote"
                    value={formData.permitted_locations_str}
                    onChange={(e) => setFormData({ ...formData, permitted_locations_str: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  />
                  <span className="text-[11px] text-slate-400 mt-1 block">Comma-separated list of approved regions.</span>
                </div>
              </div>

              {/* Compensation & Salary Band Section */}
              <div className="pt-4 border-t border-slate-200 dark:border-slate-800">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h4 className="font-bold text-slate-900 dark:text-white text-sm">Compensation & Salary Band</h4>
                    <p className="text-[11px] text-slate-400">Target annual compensation range displayed to prospective applicants.</p>
                  </div>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 border border-emerald-200/60 dark:border-emerald-800">
                    Transparent Pay Policy
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div>
                    <label className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                      Min Annual Salary
                    </label>
                    <input
                      type="number"
                      step="1000"
                      placeholder="e.g. 130000"
                      value={formData.salary_range_min || ''}
                      onChange={(e) => setFormData({ ...formData, salary_range_min: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                    />
                  </div>

                  <div>
                    <label className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                      Max Annual Salary
                    </label>
                    <input
                      type="number"
                      step="1000"
                      placeholder="e.g. 175000"
                      value={formData.salary_range_max || ''}
                      onChange={(e) => setFormData({ ...formData, salary_range_max: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                    />
                  </div>

                  <div>
                    <label className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                      Currency
                    </label>
                    <select
                      value={formData.salary_currency}
                      onChange={(e) => setFormData({ ...formData, salary_currency: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                    >
                      <option value="USD">USD ($)</option>
                      <option value="EUR">EUR (€)</option>
                      <option value="GBP">GBP (£)</option>
                      <option value="CAD">CAD ($)</option>
                      <option value="AUD">AUD ($)</option>
                      <option value="INR">INR (₹)</option>
                      <option value="SGD">SGD ($)</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* STEP 2: Academic & Educational Criteria */}
          {activeStep === 2 && (
            <div className="space-y-4 text-xs">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Minimum Degree Level Required
                  </label>
                  <select
                    value={formData.min_degree_level}
                    onChange={(e) => setFormData({ ...formData, min_degree_level: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  >
                    <option>High School Diploma / GED</option>
                    <option>Associate Degree</option>
                    <option>Bachelor's Degree (B.S. / B.E. / B.Tech)</option>
                    <option>Master's Degree (M.S. / M.E. / M.Tech)</option>
                    <option>Doctorate (Ph.D.)</option>
                  </select>
                </div>

                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Degree Requirement Enforcement Type
                  </label>
                  <select
                    value={formData.degree_enforcement_type}
                    onChange={(e) => setFormData({ ...formData, degree_enforcement_type: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  >
                    <option>Mandatory (Hard Knockout)</option>
                    <option>Preferred (Bonus Score)</option>
                    <option>Equivalent Professional Experience Allowed</option>
                  </select>
                  <span className="text-[11px] text-slate-400 mt-1 block">Equivalent experience waives degree if candidate has +2 yrs per missing tier.</span>
                </div>

                <div className="md:col-span-2">
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Accepted Fields of Study (Majors)
                  </label>
                  <input
                    type="text"
                    value={formData.accepted_majors_str}
                    onChange={(e) => setFormData({ ...formData, accepted_majors_str: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  />
                  <span className="text-[11px] text-slate-400 mt-1 block">Comma-separated majors matched semantically against candidate transcripts.</span>
                </div>

                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Minimum Academic Performance (CGPA / GPA)
                  </label>
                  <input
                    type="text"
                    value={formData.min_cgpa}
                    onChange={(e) => setFormData({ ...formData, min_cgpa: e.target.value })}
                    placeholder="e.g. 3.0 / 4.0 or 7.0 / 10.0"
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  />
                </div>

                <div className="flex items-center gap-3 pt-6">
                  <input
                    type="checkbox"
                    id="cgpa_strict"
                    checked={formData.cgpa_strict_filter}
                    onChange={(e) => setFormData({ ...formData, cgpa_strict_filter: e.target.checked })}
                    className="w-4 h-4 text-indigo-600 rounded"
                  />
                  <label htmlFor="cgpa_strict" className="text-slate-700 dark:text-slate-300 font-semibold cursor-pointer">
                    Enforce CGPA as strict knockout filter (rather than tiebreaker)
                  </label>
                </div>

                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Graduation Year Start (Optional)
                  </label>
                  <input
                    type="number"
                    placeholder="e.g. 2021"
                    value={formData.grad_year_start}
                    onChange={(e) => setFormData({ ...formData, grad_year_start: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  />
                </div>

                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Graduation Year End (Optional)
                  </label>
                  <input
                    type="number"
                    placeholder="e.g. 2025"
                    value={formData.grad_year_end}
                    onChange={(e) => setFormData({ ...formData, grad_year_end: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  />
                </div>
              </div>
            </div>
          )}

          {/* STEP 3: Experience & Certifications Matrix */}
          {activeStep === 3 && (
            <div className="space-y-6 text-xs">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Total Professional Experience (Years)
                  </label>
                  <input
                    type="number"
                    step="0.5"
                    value={formData.total_experience_years}
                    onChange={(e) => setFormData({ ...formData, total_experience_years: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  />
                </div>

                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Role-Specific / Domain Experience (Years)
                  </label>
                  <input
                    type="number"
                    step="0.5"
                    value={formData.domain_experience_years}
                    onChange={(e) => setFormData({ ...formData, domain_experience_years: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  />
                </div>

                <div className="md:col-span-2 flex items-center gap-3 p-3.5 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
                  <input
                    type="checkbox"
                    id="leadership"
                    checked={formData.leadership_required}
                    onChange={(e) => setFormData({ ...formData, leadership_required: e.target.checked })}
                    className="w-4 h-4 text-indigo-600 rounded"
                  />
                  <div>
                    <label htmlFor="leadership" className="font-bold text-slate-900 dark:text-white cursor-pointer block">
                      Leadership & Project Ownership Required
                    </label>
                    <span className="text-[11px] text-slate-500 dark:text-slate-400">
                      When enabled, the AI automatically allocates at least one scenario-based behavioral ownership question.
                    </span>
                  </div>
                </div>
              </div>

              {/* Certifications Matrix */}
              <div className="space-y-3 pt-4 border-t border-slate-200 dark:border-slate-800">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                      Professional Certifications & Accreditations Matrix
                    </h3>
                    <p className="text-[11px] text-slate-500">
                      P0 Mandatory (license to practice), P1 Highly Preferred (triggers verification question), P2 Bonus.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={handleAddCert}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800 hover:bg-indigo-100"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Add Certification</span>
                  </button>
                </div>

                <div className="space-y-2.5">
                  {formData.certifications.map((c, idx) => (
                    <div
                      key={idx}
                      className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 grid grid-cols-1 sm:grid-cols-12 gap-3 items-center"
                    >
                      <div className="sm:col-span-4">
                        <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Certification Name</label>
                        <input
                          type="text"
                          placeholder="e.g. AWS Solutions Architect Professional"
                          value={c.name}
                          onChange={(e) => handleUpdateCert(idx, 'name', e.target.value)}
                          className="w-full px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs"
                        />
                      </div>
                      <div className="sm:col-span-3">
                        <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Issuing Body</label>
                        <input
                          type="text"
                          placeholder="e.g. AWS, CNCF"
                          value={c.issuing_org}
                          onChange={(e) => handleUpdateCert(idx, 'issuing_org', e.target.value)}
                          className="w-full px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs"
                        />
                      </div>
                      <div className="sm:col-span-2">
                        <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Priority</label>
                        <select
                          value={c.priority_tier}
                          onChange={(e) => handleUpdateCert(idx, 'priority_tier', e.target.value)}
                          className="w-full px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs"
                        >
                          <option>P0</option>
                          <option>P1</option>
                          <option>P2</option>
                        </select>
                      </div>
                      <div className="sm:col-span-2 flex items-center gap-1.5 pt-3 sm:pt-0">
                        <input
                          type="checkbox"
                          id={`cert_v_${idx}`}
                          checked={c.verification_required}
                          onChange={(e) => handleUpdateCert(idx, 'verification_required', e.target.checked)}
                          className="w-3.5 h-3.5 text-indigo-600 rounded"
                        />
                        <label htmlFor={`cert_v_${idx}`} className="text-[11px] text-slate-600 dark:text-slate-400 cursor-pointer">
                          Verify ID
                        </label>
                      </div>
                      <div className="sm:col-span-1 flex justify-end">
                        <button
                          type="button"
                          onClick={() => handleRemoveCert(idx)}
                          className="p-1.5 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/50 rounded-lg"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* STEP 4: Skills Taxonomy & 5-Level Rubrics */}
          {activeStep === 4 && (
            <div className="space-y-6 text-xs">
              
              {/* Weightage Validation Progress Bar */}
              <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-slate-800 dark:text-slate-200">
                      Total Competency Weightage
                    </span>
                    {Math.round(totalWeight) === 100 ? (
                      <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-bold">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Exactly 100% Calibrated
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400 font-bold">
                        <AlertTriangle className="w-3.5 h-3.5" /> Must equal 100% (Current: {totalWeight}%)
                      </span>
                    )}
                  </div>
                  <span className="font-mono font-black text-sm text-indigo-600 dark:text-indigo-400">
                    {totalWeight}% / 100%
                  </span>
                </div>

                <div className="h-2.5 w-full bg-slate-200 dark:bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all duration-300 ${
                      Math.round(totalWeight) === 100
                        ? 'bg-emerald-500'
                        : totalWeight > 100
                        ? 'bg-rose-500'
                        : 'bg-indigo-600'
                    }`}
                    style={{ width: `${Math.min(100, totalWeight)}%` }}
                  />
                </div>
              </div>

              {/* Skills List */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                    Configured Competencies & 5-Level Rubric Anchors
                  </h3>
                  <button
                    type="button"
                    onClick={handleAddSkill}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800 hover:bg-indigo-100"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Add Skill</span>
                  </button>
                </div>

                {formData.skills.map((skill, idx) => (
                  <div
                    key={idx}
                    className="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm space-y-4"
                  >
                    <div className="grid grid-cols-1 sm:grid-cols-12 gap-3 items-center">
                      <div className="sm:col-span-5">
                        <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Skill Name</label>
                        <input
                          type="text"
                          placeholder="e.g. Distributed System Design"
                          value={skill.name}
                          onChange={(e) => handleUpdateSkill(idx, 'name', e.target.value)}
                          className="w-full px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs font-semibold"
                        />
                      </div>

                      <div className="sm:col-span-3">
                        <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Category</label>
                        <select
                          value={skill.category}
                          onChange={(e) => handleUpdateSkill(idx, 'category', e.target.value)}
                          className="w-full px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs"
                        >
                          <option>Core Technical</option>
                          <option>Tooling & Frameworks</option>
                          <option>Domain & Architectural</option>
                          <option>Soft & Cultural</option>
                        </select>
                      </div>

                      <div className="sm:col-span-2">
                        <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Priority</label>
                        <select
                          value={skill.priority_tier}
                          onChange={(e) => handleUpdateSkill(idx, 'priority_tier', e.target.value)}
                          className="w-full px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs"
                        >
                          <option value="P0">P0 (Mandatory)</option>
                          <option value="P1">P1 (Core)</option>
                          <option value="P2">P2 (Secondary)</option>
                        </select>
                      </div>

                      <div className="sm:col-span-1">
                        <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Weight %</label>
                        <input
                          type="number"
                          value={skill.weight_percentage}
                          onChange={(e) => handleUpdateSkill(idx, 'weight_percentage', e.target.value)}
                          className="w-full px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs font-bold"
                        />
                      </div>

                      <div className="sm:col-span-1 flex justify-end">
                        <button
                          type="button"
                          onClick={() => handleRemoveSkill(idx)}
                          className="p-1.5 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/50 rounded-lg"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>

                    {/* 5-Level Rubrics Expandable */}
                    <div className="space-y-2 pt-2 border-t border-slate-100 dark:border-slate-800">
                      <div className="text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        5-Level Behavioral Rubrics (L1–L5)
                      </div>
                      <div className="grid grid-cols-1 gap-2">
                        <input
                          type="text"
                          placeholder="L1 (Incompetent): Fails basic fundamentals; proposes broken anti-patterns."
                          value={skill.rubric_l1}
                          onChange={(e) => handleUpdateSkill(idx, 'rubric_l1', e.target.value)}
                          className="w-full px-2.5 py-1.5 rounded-lg border border-rose-200/80 dark:border-rose-900/50 bg-rose-50/40 dark:bg-rose-950/10 text-xs"
                        />
                        <input
                          type="text"
                          placeholder="L2 (Developing): Knows surface theory, names tools, but cannot explain internals or failure modes."
                          value={skill.rubric_l2}
                          onChange={(e) => handleUpdateSkill(idx, 'rubric_l2', e.target.value)}
                          className="w-full px-2.5 py-1.5 rounded-lg border border-amber-200/80 dark:border-amber-900/50 bg-amber-50/40 dark:bg-amber-950/10 text-xs"
                        />
                        <input
                          type="text"
                          placeholder="L3 (Proficient / Baseline): Delivers clean, production-grade answer with sound reasoning."
                          value={skill.rubric_l3}
                          onChange={(e) => handleUpdateSkill(idx, 'rubric_l3', e.target.value)}
                          className="w-full px-2.5 py-1.5 rounded-lg border border-blue-200/80 dark:border-blue-900/50 bg-blue-50/40 dark:bg-blue-950/10 text-xs"
                        />
                        <input
                          type="text"
                          placeholder="L4 (Advanced): Proactively identifies edge cases, distributed failure scenarios, and latency bottlenecks."
                          value={skill.rubric_l4}
                          onChange={(e) => handleUpdateSkill(idx, 'rubric_l4', e.target.value)}
                          className="w-full px-2.5 py-1.5 rounded-lg border border-indigo-200/80 dark:border-indigo-900/50 bg-indigo-50/40 dark:bg-indigo-950/10 text-xs"
                        />
                        <input
                          type="text"
                          placeholder="L5 (Expert): Demonstrates systems-level mastery; low-level engine internals, cost vs SLAs, hardware constraints."
                          value={skill.rubric_l5}
                          onChange={(e) => handleUpdateSkill(idx, 'rubric_l5', e.target.value)}
                          className="w-full px-2.5 py-1.5 rounded-lg border border-emerald-200/80 dark:border-emerald-900/50 bg-emerald-50/40 dark:bg-emerald-950/10 text-xs"
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* STEP 5: AI Interviewer Policy & Pacing */}
          {activeStep === 5 && (
            <div className="space-y-4 text-xs">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Interview Duration
                  </label>
                  <select
                    value={formData.interview_duration_mins}
                    onChange={(e) => setFormData({ ...formData, interview_duration_mins: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm font-semibold"
                  >
                    <option value={15}>15 Minutes (~6 Core Questions)</option>
                    <option value={20}>20 Minutes (~8 Core Questions)</option>
                    <option value={30}>30 Minutes (~13 Core Questions)</option>
                    <option value={45}>45 Minutes (~20 Core Questions)</option>
                    <option value={60}>60 Minutes (~27 Core Questions)</option>
                  </select>
                </div>

                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Max Follow-Up Depth per Core Question
                  </label>
                  <select
                    value={formData.max_followup_depth}
                    onChange={(e) => setFormData({ ...formData, max_followup_depth: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  >
                    <option value={1}>1 Follow-up (Recommended standard)</option>
                    <option value={2}>2 Follow-ups (Deep architectural probe)</option>
                  </select>
                </div>

                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Pacing Strictness
                  </label>
                  <select
                    value={formData.pacing_strictness}
                    onChange={(e) => setFormData({ ...formData, pacing_strictness: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  >
                    <option>Relaxed (Allows candidate to elaborate freely)</option>
                    <option>Balanced (Gently keeps candidate on track)</option>
                    <option>Aggressive (Interjects if answers exceed 90s)</option>
                  </select>
                </div>

                <div>
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Integrity Policy Tier
                  </label>
                  <select
                    value={formData.integrity_policy_tier}
                    onChange={(e) => setFormData({ ...formData, integrity_policy_tier: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  >
                    <option>Basic (Presence & tab tracking)</option>
                    <option>Moderate (Multiple faces & gaze tracking)</option>
                    <option>Strict (Full acoustic & unauthorized device detection)</option>
                  </select>
                </div>

                <div className="md:col-span-2 flex items-center gap-3 p-3.5 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
                  <input
                    type="checkbox"
                    id="grace"
                    checked={formData.allow_grace_extension}
                    onChange={(e) => setFormData({ ...formData, allow_grace_extension: e.target.checked })}
                    className="w-4 h-4 text-indigo-600 rounded"
                  />
                  <div>
                    <label htmlFor="grace" className="font-bold text-slate-900 dark:text-white cursor-pointer block">
                      Enable Optional +5 Minute Grace Period Extension
                    </label>
                    <span className="text-[11px] text-slate-500 dark:text-slate-400">
                      Prompts candidate at T-1 minute if in the middle of a high-value technical explanation.
                    </span>
                  </div>
                </div>

                <div className="md:col-span-2">
                  <label className="block font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Interviewer Conversational Tone & Persona
                  </label>
                  <textarea
                    rows={2}
                    value={formData.interviewer_tone}
                    onChange={(e) => setFormData({ ...formData, interviewer_tone: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white text-sm"
                  />
                </div>
              </div>
            </div>
          )}

          {/* STEP 6: Custom Questions & Live Mathematical Question Budget */}
          {activeStep === 6 && (
            <div className="space-y-6 text-xs">
              
              {/* Real-time Question Budget Mathematics Card */}
              <div className="p-5 rounded-2xl bg-indigo-50/70 dark:bg-indigo-950/40 border border-indigo-200 dark:border-indigo-900/60 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-extrabold text-indigo-950 dark:text-indigo-100 flex items-center gap-2">
                      <Clock className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                      Live Mathematical Question Budget (Part 2 Formula)
                    </h3>
                    <p className="text-[11px] text-indigo-800/80 dark:text-indigo-300/80">
                      Duration: {questionBudget.duration}m · Overhead: {questionBudget.overhead}m · Active Eval Time: {questionBudget.activeEvalTime}m
                    </p>
                  </div>
                  <div className="px-3 py-1.5 rounded-xl bg-white dark:bg-slate-900 border border-indigo-200 dark:border-indigo-800 text-indigo-600 dark:text-indigo-400 font-extrabold text-sm shadow-sm">
                    {questionBudget.totalCoreQuestions} Core Questions Planned
                  </div>
                </div>

                {/* Skill Allocation Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                  {questionBudget.items.map((item, idx) => (
                    <div
                      key={idx}
                      className="p-3 rounded-xl bg-white dark:bg-slate-900 border border-indigo-100 dark:border-indigo-900 shadow-sm space-y-1"
                    >
                      <div className="flex items-center justify-between font-bold text-slate-800 dark:text-slate-200">
                        <span className="truncate max-w-[120px]">{item.name}</span>
                        <span className="text-indigo-600 dark:text-indigo-400">{item.allocated} Qs</span>
                      </div>
                      <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400">
                        <span>Weight: {item.weight}%</span>
                        <span>~{(item.allocated * 2.0).toFixed(1)} mins</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Custom Questions Section */}
              <div className="space-y-4 pt-2">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                      Custom Scenario Questions (Optional)
                    </h3>
                    <p className="text-[11px] text-slate-500">
                      Define specific questions with objective Expected Key Points for the real-time turn evaluator.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={handleAddQuestion}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800 hover:bg-indigo-100"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Add Question</span>
                  </button>
                </div>

                {formData.custom_questions.map((q, idx) => (
                  <div
                    key={idx}
                    className="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm space-y-3"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-slate-700 dark:text-slate-300">Custom Question #{idx + 1}</span>
                        <select
                          value={q.priority_tier}
                          onChange={(e) => handleUpdateQuestion(idx, 'priority_tier', e.target.value)}
                          className="px-2 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-[11px]"
                        >
                          <option>P0</option>
                          <option>P1</option>
                          <option>P2</option>
                        </select>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleRemoveQuestion(idx)}
                        className="p-1.5 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/50 rounded-lg"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>

                    <textarea
                      rows={2}
                      placeholder="e.g. How do you design an idempotent payment processing consumer?"
                      value={q.question_text}
                      onChange={(e) => handleUpdateQuestion(idx, 'question_text', e.target.value)}
                      className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs"
                    />

                    <div>
                      <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">
                        Expected Key Points (1 per line)
                      </label>
                      <textarea
                        rows={2}
                        placeholder="Mentions idempotency key persistence&#10;Addresses distributed locking via Redis&#10;Handles network timeouts gracefully"
                        value={q.expected_key_points_str}
                        onChange={(e) => handleUpdateQuestion(idx, 'expected_key_points_str', e.target.value)}
                        className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs font-mono"
                      />
                    </div>
                  </div>
                ))}
              </div>

            </div>
          )}

          {/* Footer Controls */}
          <div className="pt-6 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2.5 rounded-xl text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              Cancel
            </button>

            <div className="flex items-center gap-3">
              {activeStep > 1 && (
                <button
                  type="button"
                  onClick={() => setActiveStep((prev) => prev - 1)}
                  className="px-4 py-2.5 rounded-xl text-xs font-semibold text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200"
                >
                  Previous
                </button>
              )}

              {activeStep < 6 ? (
                <button
                  type="button"
                  onClick={() => setActiveStep((prev) => prev + 1)}
                  className="flex items-center gap-1.5 px-5 py-2.5 rounded-xl text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-700 shadow-sm"
                >
                  <span>Next Step</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={submitting}
                  className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 shadow-md transition-all disabled:opacity-50"
                >
                  <CheckCircle2 className="w-4 h-4" />
                  <span>{submitting ? 'Saving to Database...' : 'Deploy Calibrated Job'}</span>
                </button>
              )}
            </div>
          </div>

        </form>

      </div>
    </div>
  );
}
