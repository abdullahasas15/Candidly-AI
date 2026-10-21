import React, { useState, useEffect, useMemo } from 'react';
import {
  X, Plus, Trash2, CheckCircle2, AlertTriangle, Clock, ShieldCheck,
  Award, BookOpen, Briefcase, Settings2, HelpCircle, Layers, Sparkles,
  ArrowRight, RefreshCw, Cpu, Database, Server, Terminal, ChevronDown, ChevronUp
} from 'lucide-react';

const BlueprintReviewEditor = React.lazy(() => import('./BlueprintReviewEditor'));

const VAGUE_SKILL_NAMES = new Set([
  'projects', 'project', 'work', 'general', 'misc', 'miscellaneous',
  'responsibilities', 'experience', 'tasks', 'duties'
]);

const SENIORITY_OPTIONS = [
  { value: 'entry', label: 'Entry-Level (L2-L3)', shortLabel: 'Entry' },
  { value: 'mid', label: 'Mid-Level (L3-L4)', shortLabel: 'Mid' },
  { value: 'senior', label: 'Senior (L4-L5)', shortLabel: 'Senior' },
  { value: 'lead', label: 'Lead / Principal (L5+)', shortLabel: 'Lead' },
];

const TEMPLATE_CARD_META = {
  sde: {
    icon: Terminal,
    color: 'from-blue-600 to-indigo-600',
    tag: 'Core Engineering',
  },
  ai_engineer: {
    icon: Cpu,
    color: 'from-purple-600 to-pink-600',
    tag: 'GenAI & Applied ML',
  },
  devops: {
    icon: Server,
    color: 'from-amber-600 to-orange-600',
    tag: 'Cloud & Infrastructure',
  },
  data_engineer: {
    icon: Database,
    color: 'from-emerald-600 to-teal-600',
    tag: 'Pipelines & Warehousing',
  },
};

const ROLE_DETAILS = {
  sde: {
    department: 'Core Platform & Infrastructure',
    accepted_majors_str: 'Computer Science, Software Engineering, Computer Engineering, Electrical Engineering, Mathematics',
    getSalary: (sen) => {
      switch (sen) {
        case 'entry': return { min: 105000, max: 140000 };
        case 'senior': return { min: 180000, max: 235000 };
        case 'lead': return { min: 230000, max: 295000 };
        case 'mid':
        default: return { min: 140000, max: 185000 };
      }
    },
    getYoe: (sen) => {
      switch (sen) {
        case 'entry': return { total: 1.0, domain: 1.0, grad_start: 2022, grad_end: 2026, leadership: false };
        case 'senior': return { total: 6.0, domain: 5.0, grad_start: 2012, grad_end: 2020, leadership: true };
        case 'lead': return { total: 9.0, domain: 7.0, grad_start: 2008, grad_end: 2017, leadership: true };
        case 'mid':
        default: return { total: 3.5, domain: 2.5, grad_start: 2018, grad_end: 2023, leadership: false };
      }
    },
    getDescription: (sen) => {
      const levelLabel = sen === 'entry' ? 'Entry-Level' : sen === 'senior' ? 'Senior' : sen === 'lead' ? 'Staff / Lead' : 'Mid-Level';
      return `### Role Overview & Mission
We are seeking a high-caliber ${levelLabel} Software Development Engineer (SDE) to join our Core Platform team. In this role, you will design, build, and maintain high-throughput backend microservices, resilient event streaming pipelines, and clean API contracts supporting millions of daily active users.

### Key Responsibilities
- Architect, implement, and maintain reliable, scalable backend services and REST/gRPC endpoints with strict latency SLAs.
- Optimize algorithmic complexity, database indexing, and memory allocation patterns for performance-critical hot paths.
- Write robust, automated test suites (unit, integration, and chaos testing) to guarantee backward compatibility and zero downtime deployments.
- Collaborate with cross-functional product, infrastructure, and security teams to translate system requirements into clean, decoupled architectures.
- Participate in peer design reviews, observability monitoring (metrics, tracing, logs), and blameless post-mortem investigations.

### Technical Requirements & Qualifications
- Solid foundation in Computer Science fundamentals: data structures, algorithmic complexity (Big-O), concurrency, and memory management.
- Demonstrated hands-on proficiency in modern backend languages such as Go, Python, Java, Rust, or TypeScript/Node.js.
- Strong practical knowledge of relational (PostgreSQL, MySQL) and NoSQL (Redis, DynamoDB) datastores, caching strategies, and transaction isolation levels.
- Familiarity with containerized workflows (Docker, Kubernetes) and CI/CD automated deployment pipelines.
- Excellent verbal and written technical communication skills, with an emphasis on system trade-off analysis.

### Technology Stack
- Languages: Go, Python, Java, TypeScript
- Storage: PostgreSQL, Redis, Apache Kafka
- Infrastructure: AWS / GCP, Docker, Kubernetes, Terraform, Datadog`;
    },
    getScreeningQuestions: (sen) => [
      {
        question_text: 'Describe a complex technical challenge or distributed systems issue you investigated and resolved. Walk us through how you identified the bottleneck, the trade-offs you evaluated, and how you verified the fix.',
        category: 'Core Technical',
        difficulty_level: sen === 'entry' ? 'Entry' : sen === 'senior' || sen === 'lead' ? 'Senior' : 'Mid',
        expected_key_points_str: 'Systematically isolates root cause using metrics, traces, or profiling\nExplains trade-offs between computational complexity and memory usage\nVerifies resolution with rigorous benchmark testing or automated regression suites',
        priority_tier: 'P0',
        question_type: 'textarea',
        is_required: true,
      }
    ]
  },

  ai_engineer: {
    department: 'Applied AI & Intelligent Systems',
    accepted_majors_str: 'Computer Science, Artificial Intelligence, Data Science, Computational Linguistics, Statistics, Robotics',
    getSalary: (sen) => {
      switch (sen) {
        case 'entry': return { min: 115000, max: 155000 };
        case 'senior': return { min: 195000, max: 260000 };
        case 'lead': return { min: 250000, max: 330000 };
        case 'mid':
        default: return { min: 155000, max: 205000 };
      }
    },
    getYoe: (sen) => {
      switch (sen) {
        case 'entry': return { total: 1.0, domain: 1.0, grad_start: 2022, grad_end: 2026, leadership: false };
        case 'senior': return { total: 6.0, domain: 5.0, grad_start: 2012, grad_end: 2020, leadership: true };
        case 'lead': return { total: 9.0, domain: 7.0, grad_start: 2008, grad_end: 2017, leadership: true };
        case 'mid':
        default: return { total: 3.5, domain: 2.5, grad_start: 2018, grad_end: 2023, leadership: false };
      }
    },
    getDescription: (sen) => {
      const levelLabel = sen === 'entry' ? 'Entry-Level' : sen === 'senior' ? 'Senior' : sen === 'lead' ? 'Staff / Lead' : 'Mid-Level';
      return `### Role Overview & Mission
We are hiring a talented ${levelLabel} AI Engineer specializing in Generative AI, Large Language Models (LLMs), and agentic workflows. You will design, build, and deploy production-grade AI applications, advanced Retrieval-Augmented Generation (RAG) architectures, and real-time multimodal inference pipelines.

### Key Responsibilities
- Architect and operationalize high-accuracy RAG pipelines using semantic chunking, dense vector retrieval, and cross-encoder reranking.
- Implement robust tool-calling agent frameworks with deterministic structured JSON schemas and safety guardrails.
- Build systematic evaluation benchmarks (Ragas, TruLens, DeepEval) tracking faithfulness, answer relevancy, and hallucination rates.
- Optimize LLM inference latency and token economics through prompt compression, semantic caching, and speculative decoding.
- Integrate real-time audio and speech pipelines with WebRTC/WebSocket streaming interfaces.

### Technical Requirements & Qualifications
- Proven hands-on experience developing applications with state-of-the-art foundation models (Gemini, Claude, GPT-4, Llama).
- Deep understanding of vector database index topologies (HNSW, IVFFlat) and hybrid search (BM25 + dense embeddings).
- Proficiency in Python, modern async frameworks (FastAPI, AsyncIO), and AI orchestration tools (LangChain, LlamaIndex, LiteLLM).
- Experience designing automated evaluation harnesses and prompt red-teaming for security (prompt injection, jailbreaking).
- Familiarity with fine-tuning techniques (LoRA, QLoRA) and model quantization (GGUF, AWQ, vLLM).

### Technology Stack
- AI Frameworks: Google GenAI SDK, OpenAI SDK, LangChain, vLLM
- Vector Datastores: Pinecone, Qdrant, Chroma, pgvector
- Backend & Cloud: Python (FastAPI), Redis, Docker, GCP Vertex AI / AWS Bedrock`;
    },
    getScreeningQuestions: (sen) => [
      {
        question_text: 'Walk through an end-to-end RAG or LLM agent pipeline you built for production. How did you handle document chunking, hallucination detection, retrieval evaluation, and inference latency optimization?',
        category: 'Core Technical',
        difficulty_level: sen === 'entry' ? 'Entry' : sen === 'senior' || sen === 'lead' ? 'Senior' : 'Mid',
        expected_key_points_str: 'Explains chunking trade-offs and semantic vector search\nDetails automated evaluation metrics for hallucination and retrieval recall\nDemonstrates caching, prompt optimization, or streaming latency controls',
        priority_tier: 'P0',
        question_type: 'textarea',
        is_required: true,
      }
    ]
  },

  data_engineer: {
    department: 'Data Platform & Analytics',
    accepted_majors_str: 'Computer Science, Data Science, Information Systems, Software Engineering, Applied Mathematics',
    getSalary: (sen) => {
      switch (sen) {
        case 'entry': return { min: 100000, max: 135000 };
        case 'senior': return { min: 175000, max: 230000 };
        case 'lead': return { min: 225000, max: 290000 };
        case 'mid':
        default: return { min: 135000, max: 180000 };
      }
    },
    getYoe: (sen) => {
      switch (sen) {
        case 'entry': return { total: 1.0, domain: 1.0, grad_start: 2022, grad_end: 2026, leadership: false };
        case 'senior': return { total: 6.0, domain: 5.0, grad_start: 2012, grad_end: 2020, leadership: true };
        case 'lead': return { total: 9.0, domain: 7.0, grad_start: 2008, grad_end: 2017, leadership: true };
        case 'mid':
        default: return { total: 3.5, domain: 2.5, grad_start: 2018, grad_end: 2023, leadership: false };
      }
    },
    getDescription: (sen) => {
      const levelLabel = sen === 'entry' ? 'Entry-Level' : sen === 'senior' ? 'Senior' : sen === 'lead' ? 'Staff / Lead' : 'Mid-Level';
      return `### Role Overview & Mission
We are seeking a driven ${levelLabel} Data Engineer to architect, build, and maintain enterprise-scale data pipelines, lakehouse architectures, and real-time streaming infrastructure powering critical business intelligence and machine learning models.

### Key Responsibilities
- Architect robust batch and real-time event streaming pipelines handling terabytes of structured and unstructured data daily.
- Model scalable data warehouses and lakehouses adhering to Kimball dimensional modeling, medallion architecture, and data mesh principles.
- Enforce automated data quality validation (Great Expectations, dbt tests) and schema evolution guardrails.
- Optimize BigQuery / Snowflake / Spark query performance, partition pruning, and cluster sizing to minimize compute spend.
- Collaborate with data scientists and analytics engineers to deliver production-ready feature stores and clean data marts.

### Technical Requirements & Qualifications
- Advanced proficiency in SQL and Python for data transformation, ingestion, and distributed computing (PySpark, DuckDB).
- Hands-on experience with modern workflow orchestration frameworks (Airflow, Prefect, Dagster).
- Practical knowledge of modern cloud data warehouses (BigQuery, Snowflake, Databricks) and open table formats (Apache Iceberg, Delta Lake).
- Strong understanding of streaming technologies such as Apache Kafka, Pulsar, or AWS Kinesis.
- Demonstrated experience implementing CI/CD testing for data pipelines using dbt or Dataform.

### Technology Stack
- Orchestration & Transformation: Apache Airflow, dbt, Apache Spark
- Storage & Warehouse: Google BigQuery, Snowflake, Apache Iceberg, PostgreSQL
- Streaming: Apache Kafka, Debezium (CDC)
- Languages: Python, SQL, Scala`;
    },
    getScreeningQuestions: (sen) => [
      {
        question_text: 'Describe an end-to-end data pipeline you architected for batch or streaming data. How did you handle schema drift, backpressure, idempotency, and late-arriving records?',
        category: 'Core Technical',
        difficulty_level: sen === 'entry' ? 'Entry' : sen === 'senior' || sen === 'lead' ? 'Senior' : 'Mid',
        expected_key_points_str: 'Explains exactly-once or at-least-once delivery semantics and idempotency\nDescribes schema validation and handling of malformed records via dead-letter queues\nAnalyzes partitioning, clustering, and compute resource cost optimization',
        priority_tier: 'P0',
        question_type: 'textarea',
        is_required: true,
      }
    ]
  },

  devops: {
    department: 'Cloud Infrastructure & SRE',
    accepted_majors_str: 'Computer Science, Computer Systems Engineering, Information Technology, Cybersecurity, Cloud Computing',
    getSalary: (sen) => {
      switch (sen) {
        case 'entry': return { min: 105000, max: 140000 };
        case 'senior': return { min: 180000, max: 235000 };
        case 'lead': return { min: 230000, max: 295000 };
        case 'mid':
        default: return { min: 140000, max: 185000 };
      }
    },
    getYoe: (sen) => {
      switch (sen) {
        case 'entry': return { total: 1.0, domain: 1.0, grad_start: 2022, grad_end: 2026, leadership: false };
        case 'senior': return { total: 6.0, domain: 5.0, grad_start: 2012, grad_end: 2020, leadership: true };
        case 'lead': return { total: 9.0, domain: 7.0, grad_start: 2008, grad_end: 2017, leadership: true };
        case 'mid':
        default: return { total: 3.5, domain: 2.5, grad_start: 2018, grad_end: 2023, leadership: false };
      }
    },
    getDescription: (sen) => {
      const levelLabel = sen === 'entry' ? 'Entry-Level' : sen === 'senior' ? 'Senior' : sen === 'lead' ? 'Staff / Lead' : 'Mid-Level';
      return `### Role Overview & Mission
We are looking for an experienced ${levelLabel} DevOps & Site Reliability Engineer (SRE) to manage our mission-critical multi-region cloud infrastructure, ensure 99.99% system availability, and accelerate developer velocity with automated CI/CD tooling.

### Key Responsibilities
- Architect, provision, and maintain resilient multi-cluster Kubernetes environments and cloud resources using Terraform (Infrastructure-as-Code).
- Design and automate robust CI/CD pipelines (GitHub Actions, ArgoCD) supporting progressive canary deployments and instant automated rollbacks.
- Establish comprehensive observability stacks (Prometheus, Grafana, OpenTelemetry, Datadog) with actionable SLI/SLO dashboards.
- Lead incident response, on-call operational escalations, and blameless post-mortems to eliminate single points of failure.
- Implement security best practices, secrets management (Vault, AWS Secrets Manager), and zero-trust IAM policies.

### Technical Requirements & Qualifications
- Extensive practical experience running production container workloads on Kubernetes (EKS, GKE) and Docker.
- Strong scripting and automation skills in Python, Go, or Bash.
- Deep expertise in Infrastructure as Code (Terraform, Pulumi) and GitOps deployment workflows (ArgoCD, Flux).
- Thorough understanding of networking protocols (TCP/IP, DNS, TLS, HTTP/2, gRPC, VPC peering) and load balancing.
- Proven track record defining and managing Service Level Objectives (SLOs) and Error Budgets.

### Technology Stack
- Orchestration: Kubernetes, Docker, Helm, ArgoCD
- Cloud & IaC: AWS, Google Cloud, Terraform
- Observability: Prometheus, Grafana, OpenTelemetry, Datadog
- CI/CD: GitHub Actions, GitLab CI`;
    },
    getScreeningQuestions: (sen) => [
      {
        question_text: 'Describe a severe production infrastructure outage or latency spike you diagnosed and resolved under pressure. What observability signals did you follow, what was the root cause, and what permanent guardrails did you implement?',
        category: 'Core Technical',
        difficulty_level: sen === 'entry' ? 'Entry' : sen === 'senior' || sen === 'lead' ? 'Senior' : 'Mid',
        expected_key_points_str: 'Systematically tracks logs, APM traces, and infrastructure metrics to isolate bottleneck\nExecutes swift, safe mitigation (rollback, traffic shedding, scaling) while keeping stakeholders informed\nImplements automated architectural guardrails or chaos testing to prevent regression',
        priority_tier: 'P0',
        question_type: 'textarea',
        is_required: true,
      }
    ]
  }
};

export default function JobCreationModal({ isOpen, onClose, onJobCreated }) {
  if (!isOpen) return null;

  const [activeStep, setActiveStep] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [createdJob, setCreatedJob] = useState(null);
  const [blueprintApproved, setBlueprintApproved] = useState(false);

  // Role Templates State
  const [roleTemplates, setRoleTemplates] = useState([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [hasCustomizedSkills, setHasCustomizedSkills] = useState(false);
  const [pendingTemplateChange, setPendingTemplateChange] = useState(null);
  const [expandedSkillIdx, setExpandedSkillIdx] = useState(0);

  // Form State initialized with SDE Entry Defaults
  const [formData, setFormData] = useState({
    // Role Template Metadata
    role_key: 'sde',
    role_template_id: null,
    role_template_version: null,

    // 1. Role Metadata
    job_title: 'Software Development Engineer (SDE) (Entry)',
    department: 'Core Platform & Infrastructure',
    job_description: ROLE_DETAILS.sde.getDescription('entry'),
    seniority_level: 'entry',
    employment_type: 'Full-Time',
    workplace_model: 'Remote',
    permitted_locations_str: 'Global Remote, United States, Canada, United Kingdom, India',
    salary_range_min: 105000,
    salary_range_max: 140000,
    salary_currency: 'USD',

    // 2. Academic & Experience Thresholds
    min_degree_level: "Bachelor's Degree (B.S. / B.E. / B.Tech)",
    degree_enforcement_type: 'Equivalent Professional Experience Allowed',
    accepted_majors_str: ROLE_DETAILS.sde.accepted_majors_str,
    min_cgpa: '3.0 / 4.0',
    cgpa_strict_filter: false,
    grad_year_start: 2022,
    grad_year_end: 2026,
    total_experience_years: 1.0,
    domain_experience_years: 1.0,
    leadership_required: false,

    // Certifications
    certifications: [
      { name: 'AWS Certified Solutions Architect - Associate', issuing_org: 'Amazon Web Services', priority_tier: 'P1', verification_required: false },
      { name: 'Google Cloud Associate Cloud Engineer', issuing_org: 'Google Cloud', priority_tier: 'P2', verification_required: false }
    ],

    // 3. Competencies & Rubrics
    skills: [],

    // 4. Interview Policy
    interview_duration_mins: 30,
    allow_grace_extension: true,
    max_followup_depth: 1,
    pacing_strictness: 'Balanced',
    interviewer_tone: 'Direct, technical, tech-lead caliber; probes for architectural trade-offs; warm but concise.',
    integrity_policy_tier: 'Moderate',

    // 5. Custom Screening Questions
    custom_questions: ROLE_DETAILS.sde.getScreeningQuestions('entry')
  });

  // Fetch Role Templates on mount
  useEffect(() => {
    let isMounted = true;
    async function loadTemplates() {
      setLoadingTemplates(true);
      try {
        const token = localStorage.getItem('candidly-auth-token');
        const headers = token ? { Authorization: `Bearer ${token}` } : {};
        const res = await fetch('/api/role-templates', { headers });
        if (res.ok) {
          const data = await res.json();
          if (isMounted) {
            setRoleTemplates(data);
            const sdeTpl = data.find(t => t.role_key === 'sde') || data[0];
            if (sdeTpl && (!formData.role_template_id || formData.role_key === 'sde')) {
              applyRoleTemplate(sdeTpl, formData.seniority_level || 'entry');
            }
          }
        }
      } catch (err) {
        console.error('Failed to load role templates:', err);
      } finally {
        if (isMounted) setLoadingTemplates(false);
      }
    }
    loadTemplates();
    return () => { isMounted = false; };
  }, []);

  // Helper to extract skills and rubrics from template for given seniority
  const extractSkillsForTemplate = (template, seniority) => {
    if (!template || !template.skills) return [];
    const sNorm = (seniority || 'mid').toLowerCase().trim();
    let seniorityKey = 'mid';
    if (sNorm.includes('entry') || sNorm.includes('intern') || sNorm.includes('junior')) {
      seniorityKey = 'entry';
    } else if (sNorm.includes('lead') || sNorm.includes('staff') || sNorm.includes('principal')) {
      seniorityKey = 'lead';
    } else if (sNorm.includes('senior') || sNorm.includes('sr')) {
      seniorityKey = 'senior';
    } else {
      seniorityKey = 'mid';
    }

    const profiles = template.seniority_profiles || {};
    const profile = profiles[seniorityKey] || profiles['mid'] || profiles['entry'] || {};
    const allSkills = template.skills || [];
    const result = [];

    allSkills.forEach((def) => {
      const skey = def.key || def.skill_key;
      const cfg = profile[skey];
      // Filter out explicitly excluded skills
      if (cfg && cfg.included === false) return;
      if (!cfg && Object.keys(profile).length > 0) return;

      result.push({
        template_skill_key: skey,
        name: def.name || skey,
        category: def.category || 'Core Technical',
        priority_tier: cfg?.tier || cfg?.priority_tier || 'P1',
        weight_percentage: parseFloat(cfg?.weight ?? cfg?.weight_percentage ?? 20),
        target_level_min: cfg?.target_level_min || 'L2',
        target_level_max: cfg?.target_level_max || 'L4',
        source: 'template',
        description: def.description || '',
        rubric_l1: def.rubric_l1 || '',
        rubric_l2: def.rubric_l2 || '',
        rubric_l3: def.rubric_l3 || '',
        rubric_l4: def.rubric_l4 || '',
        rubric_l5: def.rubric_l5 || '',
      });
    });

    if (result.length === 0 && allSkills.length > 0) {
      const defaultWeight = Math.round(100 / allSkills.length);
      allSkills.forEach((def) => {
        const skey = def.key || def.skill_key;
        result.push({
          template_skill_key: skey,
          name: def.name || skey,
          category: def.category || 'Core Technical',
          priority_tier: 'P1',
          weight_percentage: defaultWeight,
          target_level_min: 'L2',
          target_level_max: 'L4',
          source: 'template',
          description: def.description || '',
          rubric_l1: def.rubric_l1 || '',
          rubric_l2: def.rubric_l2 || '',
          rubric_l3: def.rubric_l3 || '',
          rubric_l4: def.rubric_l4 || '',
          rubric_l5: def.rubric_l5 || '',
        });
      });
    }

    return result;
  };

  // Apply Role Template to formData
  const applyRoleTemplate = (template, seniority = formData.seniority_level) => {
    if (!template) {
      setFormData(prev => ({
        ...prev,
        role_key: 'custom',
        role_template_id: null,
        role_template_version: null,
      }));
      return;
    }

    const shortSen = SENIORITY_OPTIONS.find(o => o.value === seniority)?.shortLabel || 'Mid';
    const computedTitle = `${template.display_name} (${shortSen})`;
    const skills = extractSkillsForTemplate(template, seniority);

    const certs = (template.suggested_certifications || []).map(c => ({
      name: c.name || '',
      issuing_org: c.issuing_org || '',
      priority_tier: c.priority_tier || 'P1',
      verification_required: !!c.verification_required,
    }));

    const details = ROLE_DETAILS[template.role_key] || {
      department: 'Engineering',
      accepted_majors_str: 'Computer Science, Software Engineering, Information Technology, Electrical Engineering',
      getSalary: () => ({ min: 120000, max: 160000 }),
      getYoe: () => ({ total: 2.0, domain: 2.0, grad_start: 2020, grad_end: 2026, leadership: false }),
      getDescription: () => template.description || 'Full-stack software development and platform engineering.',
      getScreeningQuestions: () => ([{
        question_text: 'Describe a complex technical challenge you solved and how you arrived at the solution.',
        category: 'Core Technical',
        difficulty_level: 'Mid',
        expected_key_points_str: 'Identifies root cause systematically\nExplains trade-offs considered\nVerifies resolution with metrics or tests',
        priority_tier: 'P0',
        question_type: 'textarea',
        is_required: true,
      }])
    };

    const salary = details.getSalary(seniority);
    const yoe = details.getYoe(seniority);
    const desc = details.getDescription(seniority);
    const screening = details.getScreeningQuestions(seniority);

    setFormData(prev => ({
      ...prev,
      role_key: template.role_key,
      role_template_id: template.id,
      role_template_version: template.version,
      job_title: computedTitle,
      department: details.department,
      job_description: desc,
      seniority_level: seniority,
      employment_type: 'Full-Time',
      workplace_model: 'Remote',
      permitted_locations_str: 'Global Remote, United States, Canada, United Kingdom, India',
      salary_range_min: salary.min,
      salary_range_max: salary.max,
      salary_currency: 'USD',

      min_degree_level: "Bachelor's Degree (B.S. / B.E. / B.Tech)",
      degree_enforcement_type: 'Equivalent Professional Experience Allowed',
      accepted_majors_str: details.accepted_majors_str,
      min_cgpa: '3.0 / 4.0',
      cgpa_strict_filter: false,
      grad_year_start: yoe.grad_start || '',
      grad_year_end: yoe.grad_end || '',
      total_experience_years: yoe.total,
      domain_experience_years: yoe.domain,
      leadership_required: yoe.leadership,

      certifications: certs,
      skills,

      interview_duration_mins: template.default_duration_mins || 30,
      interviewer_tone: template.default_interviewer_tone || prev.interviewer_tone,
      pacing_strictness: template.default_pacing || 'Balanced',
      allow_grace_extension: true,
      max_followup_depth: seniority === 'entry' ? 1 : 2,
      integrity_policy_tier: 'Moderate',

      custom_questions: screening,
    }));
    setHasCustomizedSkills(false);
  };

  // Handle switching template with confirmation if skills were edited
  const handleSelectTemplate = (template) => {
    if (hasCustomizedSkills && formData.skills.length > 0) {
      setPendingTemplateChange({ template, seniority: formData.seniority_level });
      return;
    }
    applyRoleTemplate(template, formData.seniority_level);
  };

  // Handle switching seniority with confirmation if skills were edited
  const handleSelectSeniority = (newSeniority) => {
    if (hasCustomizedSkills && formData.skills.length > 0) {
      const currentTpl = roleTemplates.find(t => t.role_key === formData.role_key);
      setPendingTemplateChange({ template: currentTpl, seniority: newSeniority });
      return;
    }
    const currentTpl = roleTemplates.find(t => t.role_key === formData.role_key);
    if (currentTpl) {
      applyRoleTemplate(currentTpl, newSeniority);
    } else {
      setFormData(prev => ({ ...prev, seniority_level: newSeniority }));
    }
  };

  const confirmPendingChange = () => {
    if (pendingTemplateChange) {
      applyRoleTemplate(pendingTemplateChange.template, pendingTemplateChange.seniority);
      setPendingTemplateChange(null);
    }
  };

  // Title vs Seniority Mismatch Warning
  const titleMismatchWarning = useMemo(() => {
    const titleLower = (formData.job_title || '').toLowerCase();
    const sen = formData.seniority_level;
    const isEntryWord = /\b(intern|junior|entry|associate|l2|l3|sde\s*1|sde-1|engineer\s*1|engineer-1)\b/i.test(titleLower);
    const isSeniorWord = /\b(senior|sr|lead|staff|principal|director|l5|l6|sde\s*3|sde-3)\b/i.test(titleLower);

    if (isEntryWord && (sen === 'mid' || sen === 'senior' || sen === 'lead')) {
      return `Job title indicates an entry/junior role, but Seniority is calibrated to "${sen.toUpperCase()}". Please verify this is intentional.`;
    }
    if (isSeniorWord && sen === 'entry') {
      return `Job title indicates a senior or lead role, but Seniority is calibrated to "ENTRY". Please verify this is intentional.`;
    }
    return null;
  }, [formData.job_title, formData.seniority_level]);

  // Calculate sum of skill weights
  const totalWeight = useMemo(() => {
    return formData.skills.reduce((sum, s) => sum + (parseFloat(s.weight_percentage) || 0), 0);
  }, [formData.skills]);

  // Duration Fit Markers
  const durationFitInfo = useMemo(() => {
    const duration = parseInt(formData.interview_duration_mins, 10) || 20;
    const overhead = duration <= 15 ? 3.0 : duration <= 20 ? 3.5 : duration <= 30 ? 4.0 : duration <= 45 ? 5.0 : 6.0;
    const activeEvalTime = Math.max(2.0, duration - overhead);
    // 2.0 min per expectation
    const coreCapacity = Math.round(activeEvalTime / 2.0);

    return {
      duration,
      activeEvalTime,
      coreCapacity,
    };
  }, [formData.interview_duration_mins]);

  // Handlers for Skills
  const handleAddSkill = () => {
    setHasCustomizedSkills(true);
    setFormData((prev) => ({
      ...prev,
      skills: [
        ...prev.skills,
        {
          name: '',
          category: 'Core Technical',
          priority_tier: 'P1',
          weight_percentage: 10,
          source: 'recruiter',
          rubric_l1: '',
          rubric_l2: '',
          rubric_l3: '',
          rubric_l4: '',
          rubric_l5: ''
        }
      ]
    }));
    setExpandedSkillIdx(formData.skills.length);
  };

  const handleUpdateSkill = (index, field, value) => {
    setHasCustomizedSkills(true);
    setFormData((prev) => {
      const updated = [...prev.skills];
      updated[index] = { ...updated[index], [field]: value };
      return { ...prev, skills: updated };
    });
  };

  const handleRemoveSkill = (index) => {
    setHasCustomizedSkills(true);
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

  // Handlers for Custom Screening Questions
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
          priority_tier: 'P0',
          question_type: 'text',
          is_required: true,
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

  // Form Submit / Create Job Draft
  const handleSubmit = async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    setErrorMsg(null);

    if (createdJob) {
      setActiveStep(6);
      return createdJob;
    }

    if (!formData.job_title.trim() || !formData.department.trim()) {
      setErrorMsg('Please enter both Job Title and Department.');
      setActiveStep(1);
      return null;
    }

    if (Math.round(totalWeight) !== 100) {
      setErrorMsg(`Competency weightages must equal exactly 100%. Current sum is ${Math.round(totalWeight)}%.`);
      setActiveStep(3);
      return null;
    }

    // Check for vague skills
    for (const s of formData.skills) {
      if (VAGUE_SKILL_NAMES.has(s.name.trim().toLowerCase())) {
        setErrorMsg(`Competency name "${s.name}" is too vague. Please rename it (e.g. "Practical Software Projects").`);
        setActiveStep(3);
        return null;
      }
    }

    setSubmitting(true);
    try {
      const payload = {
        role_key: formData.role_key || 'custom',
        role_template_id: formData.role_template_id,
        role_template_version: formData.role_template_version,
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
          template_skill_key: s.template_skill_key,
          target_level_min: s.target_level_min,
          target_level_max: s.target_level_max,
          source: s.source || 'recruiter',
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
          expected_key_points: (q.expected_key_points_str || '').split('\n').map((k) => k.trim()).filter(Boolean),
          priority_tier: q.priority_tier,
          question_type: q.question_type || 'text',
          is_required: q.is_required !== false,
          options: q.options || [],
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
      setCreatedJob(created);
      setActiveStep(6);
      return created;
    } catch (err) {
      setErrorMsg(err.message);
      return null;
    } finally {
      setSubmitting(false);
    }
  };

  const steps = [
    { num: 1, label: 'Role & Template', icon: Briefcase },
    { num: 2, label: 'Thresholds & Certs', icon: BookOpen },
    { num: 3, label: 'Competencies & Rubrics', icon: Layers },
    { num: 4, label: 'Interviewer Policy', icon: Settings2 },
    { num: 5, label: 'Screening Questions', icon: HelpCircle },
    { num: 6, label: 'Interview Blueprint', icon: Sparkles }
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-slate-950/75 backdrop-blur-sm animate-fadeIn">
      <div className="relative w-full max-w-5xl max-h-[92vh] flex flex-col rounded-3xl bg-[#0A0A0B] border border-white/[0.08] shadow-2xl overflow-hidden">
        
        {/* Header */}
        <div className="px-6 py-4 bg-[#111113] border-b border-white/[0.08] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-teal-500 text-black text-white flex items-center justify-center shadow-md">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-xl font-extrabold text-white tracking-tight">
                Configure Autonomous Job & Interview Blueprint
              </h2>
              <p className="text-xs text-zinc-400">
                Ground interview delivery in calibrated role templates, seniority-tuned rubrics, and predictable budgeting.
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-xl text-slate-400 hover:text-slate-700 dark:hover:text-white bg-[#18181B] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Step Navigation Bar */}
        <div className="border-b border-white/[0.08] bg-[#0A0A0B] p-2 sm:px-6">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-1.5">
            {steps.map((step) => {
              const Icon = step.icon;
              const isActive = activeStep === step.num;
              const isPast = activeStep > step.num;
              return (
                <button
                  key={step.num}
                  type="button"
                  onClick={() => setActiveStep(step.num)}
                  className={`flex items-center gap-2 py-2 px-2.5 rounded-xl text-xs font-semibold transition-all text-left ${
                    isActive
                      ? 'bg-teal-500 text-black text-white shadow-sm ring-1 ring-teal-400'
                      : isPast
                      ? 'bg-emerald-50/70 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200/50 dark:border-emerald-800/40 hover:bg-emerald-100/60'
                      : 'text-zinc-400 hover:bg-slate-100 dark:hover:bg-slate-800/60'
                  }`}
                >
                  <span className={`w-5 h-5 rounded-lg flex items-center justify-center text-[10px] font-bold flex-shrink-0 ${
                    isActive
                      ? 'bg-white/20 text-white'
                      : isPast
                      ? 'bg-emerald-600 text-white'
                      : 'bg-slate-200 dark:bg-slate-800 text-zinc-400'
                  }`}>
                    {isPast ? <CheckCircle2 className="w-3 h-3" /> : step.num}
                  </span>
                  <span className="truncate">{step.label}</span>
                </button>
              );
            })}
          </div>
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
          
          {/* STEP 1: Role Identity & Template Picker */}
          {activeStep === 1 && (
            <div className="space-y-6 text-xs">
              
              {/* Template Picker Cards */}
              <div>
                <label className="block font-bold text-white text-sm mb-2">
                  Select Calibrated Role Template
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
                  {roleTemplates.map((tpl) => {
                    const meta = TEMPLATE_CARD_META[tpl.role_key] || {
                      icon: Terminal,
                      color: 'from-blue-600 to-indigo-600',
                      tag: 'Standard Role'
                    };
                    const Icon = meta.icon;
                    const isSelected = formData.role_key === tpl.role_key;

                    return (
                      <div
                        key={tpl.role_key}
                        onClick={() => handleSelectTemplate(tpl)}
                        className={`p-4 rounded-2xl border cursor-pointer transition-all flex flex-col justify-between ${
                          isSelected
                            ? 'border-teal-400 bg-teal-500/10 ring-2 ring-teal-400/30'
                            : 'border-white/[0.08] bg-[#111113] hover:border-slate-300 dark:hover:border-slate-700'
                        }`}
                      >
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <div className={`w-8 h-8 rounded-lg bg-gradient-to-br ${meta.color} text-white flex items-center justify-center shadow-sm`}>
                              <Icon className="w-4 h-4" />
                            </div>
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[#18181B] text-zinc-400">
                              {meta.tag}
                            </span>
                          </div>
                          <h4 className="font-bold text-white text-xs">
                            {tpl.display_name}
                          </h4>
                          <p className="text-[11px] text-slate-500 line-clamp-2">
                            {tpl.description}
                          </p>
                        </div>
                        <div className="mt-3 pt-2 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-[10px] text-slate-400">
                          <span>{tpl.skills?.length || 5} Competencies</span>
                          {isSelected && (
                            <span className="text-teal-400 font-bold flex items-center gap-1">
                              <CheckCircle2 className="w-3.5 h-3.5" /> Selected
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}

                  {/* Custom Role Option */}
                  <div
                    onClick={() => handleSelectTemplate(null)}
                    className={`p-4 rounded-2xl border cursor-pointer transition-all flex flex-col justify-between ${
                      formData.role_key === 'custom'
                        ? 'border-teal-400 bg-teal-500/10 ring-2 ring-teal-400/30'
                        : 'border-white/[0.08] bg-[#111113] hover:border-slate-300 dark:hover:border-slate-700'
                    }`}
                  >
                    <div className="space-y-2">
                      <div className="w-8 h-8 rounded-lg bg-slate-700 text-white flex items-center justify-center">
                        <Plus className="w-4 h-4" />
                      </div>
                      <h4 className="font-bold text-white text-xs">
                        Custom Role
                      </h4>
                      <p className="text-[11px] text-slate-500 line-clamp-2">
                        Build specialized competencies and rubric tiers from scratch.
                      </p>
                    </div>
                    <div className="mt-3 pt-2 border-t border-slate-100 dark:border-slate-800 text-[10px] text-slate-400">
                      {formData.role_key === 'custom' ? (
                        <span className="text-teal-400 font-bold flex items-center gap-1">
                          <CheckCircle2 className="w-3.5 h-3.5" /> Selected
                        </span>
                      ) : (
                        <span>Recruiter-defined</span>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* Seniority Level Picker */}
              <div>
                <label className="block font-bold text-white mb-1.5">
                  Target Seniority Level
                </label>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                  {SENIORITY_OPTIONS.map((opt) => {
                    const isSelected = formData.seniority_level === opt.value;
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => handleSelectSeniority(opt.value)}
                        className={`py-2 px-3 rounded-xl border text-left transition-all ${
                          isSelected
                            ? 'border-teal-400 bg-teal-500/10 text-teal-300 font-bold shadow-sm'
                            : 'border-white/[0.08] bg-[#0A0A0B] text-zinc-300 hover:border-slate-300'
                        }`}
                      >
                        <div className="text-xs">{opt.label}</div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Title Mismatch Warning Banner */}
              {titleMismatchWarning && (
                <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/60 flex items-start gap-2.5 text-amber-800 dark:text-amber-200">
                  <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
                  <div className="text-[11px]">
                    <span className="font-bold">Seniority Calibration Notice: </span>
                    {titleMismatchWarning}
                  </div>
                </div>
              )}

              {/* Basic Fields */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block font-bold text-zinc-300 mb-1">
                    Job Title <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Software Development Engineer (Entry)"
                    value={formData.job_title}
                    onChange={(e) => setFormData({ ...formData, job_title: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm focus:ring-2 focus:ring-teal-400"
                  />
                  <span className="text-[11px] text-slate-400 mt-1 block">Injected into the AI interviewer persona prompt.</span>
                </div>

                <div>
                  <label className="block font-bold text-zinc-300 mb-1">
                    Department / Business Unit <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Core Platform Infrastructure, Payments"
                    value={formData.department}
                    onChange={(e) => setFormData({ ...formData, department: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm focus:ring-2 focus:ring-teal-400"
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="block font-bold text-zinc-300 mb-1">
                    Job Description
                  </label>
                  <textarea
                    rows={7}
                    placeholder="Describe role mission, team responsibilities, and expected competencies."
                    value={formData.job_description}
                    onChange={(e) => setFormData({ ...formData, job_description: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm focus:ring-2 focus:ring-teal-400 resize-y font-mono text-xs leading-relaxed"
                  />
                  <span className="text-[11px] text-slate-400 mt-1 block">
                    Pre-populated with calibrated role mission, responsibilities, qualifications, and technology stack. Fully editable.
                  </span>
                </div>

                <div>
                  <label className="block font-bold text-zinc-300 mb-1">
                    Employment Type
                  </label>
                  <select
                    value={formData.employment_type}
                    onChange={(e) => setFormData({ ...formData, employment_type: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                  >
                    <option>Full-Time</option>
                    <option>Part-Time</option>
                    <option>Contract</option>
                    <option>Internship</option>
                  </select>
                </div>

                <div>
                  <label className="block font-bold text-zinc-300 mb-1">
                    Workplace Model
                  </label>
                  <select
                    value={formData.workplace_model}
                    onChange={(e) => setFormData({ ...formData, workplace_model: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                  >
                    <option>Remote</option>
                    <option>Hybrid</option>
                    <option>On-site</option>
                  </select>
                </div>

                <div className="md:col-span-2">
                  <label className="block font-bold text-zinc-300 mb-1">
                    Permitted Locations / Timezones
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Global Remote, United States, India"
                    value={formData.permitted_locations_str}
                    onChange={(e) => setFormData({ ...formData, permitted_locations_str: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                  />
                  <span className="text-[11px] text-slate-400 mt-1 block">Comma-separated list of approved regions.</span>
                </div>
              </div>

              {/* Compensation & Salary Band */}
              <div className="pt-4 border-t border-white/[0.08]">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h4 className="font-bold text-white text-sm">Target Annual Compensation Band</h4>
                    <p className="text-[11px] text-slate-400">Displayed transparently to prospective candidates.</p>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div>
                    <label className="block font-semibold text-zinc-300 mb-1">
                      Min Annual Salary
                    </label>
                    <input
                      type="number"
                      step="1000"
                      value={formData.salary_range_min || ''}
                      onChange={(e) => setFormData({ ...formData, salary_range_min: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                    />
                  </div>

                  <div>
                    <label className="block font-semibold text-zinc-300 mb-1">
                      Max Annual Salary
                    </label>
                    <input
                      type="number"
                      step="1000"
                      value={formData.salary_range_max || ''}
                      onChange={(e) => setFormData({ ...formData, salary_range_max: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                    />
                  </div>

                  <div>
                    <label className="block font-semibold text-zinc-300 mb-1">
                      Currency
                    </label>
                    <select
                      value={formData.salary_currency}
                      onChange={(e) => setFormData({ ...formData, salary_currency: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                    >
                      <option value="USD">USD ($)</option>
                      <option value="EUR">EUR (€)</option>
                      <option value="GBP">GBP (£)</option>
                      <option value="INR">INR (₹)</option>
                      <option value="CAD">CAD ($)</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* STEP 2: Candidate Thresholds & Certifications */}
          {activeStep === 2 && (
            <div className="space-y-6 text-xs">
              
              {/* Academic Thresholds */}
              <div>
                <h3 className="text-sm font-bold text-white mb-2">
                  Academic & Educational Criteria
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block font-bold text-zinc-300 mb-1">
                      Minimum Degree Level Required
                    </label>
                    <select
                      value={formData.min_degree_level}
                      onChange={(e) => setFormData({ ...formData, min_degree_level: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                    >
                      <option>High School Diploma / GED</option>
                      <option>Associate Degree</option>
                      <option>Bachelor's Degree (B.S. / B.E. / B.Tech)</option>
                      <option>Master's Degree (M.S. / M.E. / M.Tech)</option>
                      <option>Doctorate (Ph.D.)</option>
                    </select>
                  </div>

                  <div>
                    <label className="block font-bold text-zinc-300 mb-1">
                      Degree Requirement Enforcement Type
                    </label>
                    <select
                      value={formData.degree_enforcement_type}
                      onChange={(e) => setFormData({ ...formData, degree_enforcement_type: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                    >
                      <option>Mandatory (Hard Knockout)</option>
                      <option>Preferred (Bonus Score)</option>
                      <option>Equivalent Professional Experience Allowed</option>
                    </select>
                  </div>

                  <div className="md:col-span-2">
                    <label className="block font-bold text-zinc-300 mb-1">
                      Accepted Fields of Study (Majors)
                    </label>
                    <input
                      type="text"
                      value={formData.accepted_majors_str}
                      onChange={(e) => setFormData({ ...formData, accepted_majors_str: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                    />
                    <span className="text-[11px] text-slate-400 mt-1 block">Comma-separated majors matched semantically against candidate transcripts.</span>
                  </div>

                  <div>
                    <label className="block font-bold text-zinc-300 mb-1">
                      Minimum CGPA / GPA Threshold
                    </label>
                    <input
                      type="text"
                      value={formData.min_cgpa}
                      onChange={(e) => setFormData({ ...formData, min_cgpa: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                    />
                  </div>

                  <div className="flex items-center gap-3 pt-6">
                    <input
                      type="checkbox"
                      id="cgpa_strict"
                      checked={formData.cgpa_strict_filter}
                      onChange={(e) => setFormData({ ...formData, cgpa_strict_filter: e.target.checked })}
                      className="w-4 h-4 text-teal-400 rounded"
                    />
                    <label htmlFor="cgpa_strict" className="text-zinc-300 font-semibold cursor-pointer">
                      Enforce CGPA as strict knockout filter
                    </label>
                  </div>

                  <div>
                    <label className="block font-bold text-zinc-300 mb-1">
                      Graduation Year (Earliest)
                    </label>
                    <input
                      type="number"
                      placeholder="e.g. 2020"
                      value={formData.grad_year_start}
                      onChange={(e) => setFormData({ ...formData, grad_year_start: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                    />
                    <span className="text-[11px] text-slate-400 mt-1 block">Earliest eligible cohort graduation year.</span>
                  </div>

                  <div>
                    <label className="block font-bold text-zinc-300 mb-1">
                      Graduation Year (Latest)
                    </label>
                    <input
                      type="number"
                      placeholder="e.g. 2026"
                      value={formData.grad_year_end}
                      onChange={(e) => setFormData({ ...formData, grad_year_end: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                    />
                    <span className="text-[11px] text-slate-400 mt-1 block">Latest eligible cohort graduation year.</span>
                  </div>
                </div>
              </div>

              {/* Professional Experience Metrics */}
              <div className="pt-4 border-t border-white/[0.08]">
                <h3 className="text-sm font-bold text-white mb-2">
                  Experience Metrics
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block font-bold text-zinc-300 mb-1">
                      Total Experience (Years)
                    </label>
                    <input
                      type="number"
                      step="0.5"
                      value={formData.total_experience_years}
                      onChange={(e) => setFormData({ ...formData, total_experience_years: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                    />
                  </div>

                  <div>
                    <label className="block font-bold text-zinc-300 mb-1">
                      Domain / Role Experience (Years)
                    </label>
                    <input
                      type="number"
                      step="0.5"
                      value={formData.domain_experience_years}
                      onChange={(e) => setFormData({ ...formData, domain_experience_years: e.target.value })}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                    />
                  </div>

                  <div className="md:col-span-2 flex items-center gap-3 p-3.5 rounded-xl bg-[#111113] border border-white/[0.08]">
                    <input
                      type="checkbox"
                      id="leadership"
                      checked={formData.leadership_required}
                      onChange={(e) => setFormData({ ...formData, leadership_required: e.target.checked })}
                      className="w-4 h-4 text-teal-400 rounded"
                    />
                    <div>
                      <label htmlFor="leadership" className="font-bold text-white cursor-pointer block">
                        Leadership & Project Ownership Required
                      </label>
                      <span className="text-[11px] text-zinc-400">
                        Allocates behavioral scenario probe on system ownership and stakeholder alignment.
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Certifications Matrix */}
              <div className="pt-4 border-t border-white/[0.08] space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-white">
                      Suggested Certifications & Accreditations
                    </h3>
                    <p className="text-[11px] text-slate-500">
                      Prefilled from the selected role template. P0 = mandatory, P1 = preferred, P2 = bonus.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={handleAddCert}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-teal-500/10 text-teal-300 border border-teal-500/20 hover:bg-indigo-100"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Add Certification</span>
                  </button>
                </div>

                {formData.certifications.length === 0 ? (
                  <div className="p-4 rounded-xl border border-dashed border-slate-300 dark:border-slate-800 text-center text-slate-400">
                    No certifications added. Click "Add Certification" if this role requires specific credentials.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {formData.certifications.map((c, idx) => (
                      <div
                        key={idx}
                        className="p-3 rounded-xl bg-[#111113]/60 border border-white/[0.08] grid grid-cols-1 sm:grid-cols-12 gap-3 items-center"
                      >
                        <div className="sm:col-span-4">
                          <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Certification Name</label>
                          <input
                            type="text"
                            value={c.name}
                            onChange={(e) => handleUpdateCert(idx, 'name', e.target.value)}
                            className="w-full px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs"
                          />
                        </div>
                        <div className="sm:col-span-3">
                          <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Issuing Body</label>
                          <input
                            type="text"
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
                            className="w-3.5 h-3.5 text-teal-400 rounded"
                          />
                          <label htmlFor={`cert_v_${idx}`} className="text-[11px] text-zinc-400 cursor-pointer">
                            Verify Credential
                          </label>
                        </div>
                        <div className="sm:col-span-1 flex justify-end">
                          <button
                            type="button"
                            onClick={() => handleRemoveCert(idx)}
                            className="p-1.5 rounded-lg text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/50"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* STEP 3: Competencies & 5-Level Rubrics */}
          {activeStep === 3 && (
            <div className="space-y-6 text-xs">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-bold text-white">
                    Role Competencies & 5-Level Behavioral Rubrics
                  </h3>
                  <p className="text-[11px] text-slate-500">
                    Weights must sum to exactly 100%. Budgeting assigns ~2m per primary expectation.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleAddSkill}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-teal-500/10 text-teal-300 border border-teal-500/20 hover:bg-indigo-100"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Add Competency</span>
                  </button>
                </div>
              </div>

              {/* Weight & Duration Fit Summary Bar */}
              <div className="p-3.5 rounded-2xl bg-[#111113]/60 border border-white/[0.08] flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-zinc-300">Total Weight:</span>
                  <span className={`px-2.5 py-0.5 rounded-full font-bold text-xs ${
                    Math.round(totalWeight) === 100
                      ? 'bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 border border-emerald-300'
                      : 'bg-rose-50 dark:bg-rose-950 text-rose-700 dark:text-rose-300 border border-rose-300'
                  }`}>
                    {Math.round(totalWeight)}% / 100%
                  </span>
                </div>
                <div className="text-[11px] text-slate-500">
                  <span>Interview Duration: <strong>{durationFitInfo.duration}m</strong> (~{durationFitInfo.coreCapacity} core competencies covered live)</span>
                </div>
              </div>

              {/* Skills List */}
              <div className="space-y-3">
                {formData.skills.map((skill, idx) => {
                  const isVague = VAGUE_SKILL_NAMES.has((skill.name || '').trim().toLowerCase());
                  const isExpanded = expandedSkillIdx === idx;
                  const isP0 = skill.priority_tier === 'P0';

                  return (
                    <div
                      key={idx}
                      className={`rounded-2xl border transition-all ${
                        isExpanded
                          ? 'border-teal-400/50 bg-[#0A0A0B]/70 shadow-md'
                          : 'border-white/[0.08] bg-slate-50/50 dark:bg-slate-900/30'
                      }`}
                    >
                      {/* Skill Header */}
                      <div className="p-3.5 flex flex-wrap items-center justify-between gap-3">
                        <div className="flex items-center gap-2 flex-1 min-w-[200px]">
                          <span className={`w-6 h-6 rounded-lg flex items-center justify-center font-bold text-xs ${
                            isP0 ? 'bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300' : 'bg-slate-200 dark:bg-slate-800 text-zinc-400'
                          }`}>
                            {skill.priority_tier}
                          </span>
                          <input
                            type="text"
                            value={skill.name}
                            placeholder="Competency name (e.g. Core CS Fundamentals)"
                            onChange={(e) => handleUpdateSkill(idx, 'name', e.target.value)}
                            className="font-bold text-white bg-transparent border-b border-transparent hover:border-slate-300 focus:border-teal-400 text-sm focus:outline-none flex-1"
                          />
                        </div>

                        {/* Badges & Meta */}
                        <div className="flex items-center gap-2">
                          {/* Duration fit marker */}
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                            isP0
                              ? 'bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 border border-emerald-200'
                              : 'bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400 border border-blue-200'
                          }`}>
                            {isP0 ? 'Primary Core (~2m/exp)' : 'Secondary (~2m/exp)'}
                          </span>

                          {/* Source */}
                          {skill.source && (
                            <span className="text-[10px] px-2 py-0.5 rounded bg-[#18181B] text-slate-500">
                              {skill.source}
                            </span>
                          )}

                          {/* Weight */}
                          <div className="flex items-center gap-1">
                            <input
                              type="number"
                              min="1"
                              max="100"
                              value={skill.weight_percentage}
                              onChange={(e) => handleUpdateSkill(idx, 'weight_percentage', e.target.value)}
                              className="w-14 px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-center font-bold text-xs"
                            />
                            <span className="text-slate-400">%</span>
                          </div>

                          {/* Expand/Collapse Toggle */}
                          <button
                            type="button"
                            onClick={() => setExpandedSkillIdx(isExpanded ? null : idx)}
                            className="p-1 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-800 text-slate-500"
                          >
                            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                          </button>

                          {/* Delete */}
                          <button
                            type="button"
                            onClick={() => handleRemoveSkill(idx)}
                            className="p-1 rounded-lg hover:bg-rose-50 dark:hover:bg-rose-950 text-rose-500"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>

                      {/* Vague Warning */}
                      {isVague && (
                        <div className="mx-3.5 mb-2 p-2 rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-200 text-amber-800 dark:text-amber-300 text-[11px] flex items-center gap-1.5">
                          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                          <span>Vague competency name detected. Please be specific (e.g. "Practical Software Projects").</span>
                        </div>
                      )}

                      {/* Expanded Rubrics Editor */}
                      {isExpanded && (
                        <div className="p-3.5 pt-0 border-t border-slate-100 dark:border-slate-800 space-y-2 mt-2">
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-2">
                            <div>
                              <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Category</label>
                              <select
                                value={skill.category}
                                onChange={(e) => handleUpdateSkill(idx, 'category', e.target.value)}
                                className="w-full px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs"
                              >
                                <option>Core Technical</option>
                                <option>Domain & Architectural</option>
                                <option>Tooling & Frameworks</option>
                                <option>Soft & Cultural</option>
                              </select>
                            </div>
                            <div>
                              <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Priority Tier</label>
                              <select
                                value={skill.priority_tier}
                                onChange={(e) => handleUpdateSkill(idx, 'priority_tier', e.target.value)}
                                className="w-full px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs"
                              >
                                <option>P0</option>
                                <option>P1</option>
                                <option>P2</option>
                              </select>
                            </div>
                          </div>

                          {/* 5-Level Rubrics */}
                          <div className="space-y-1.5">
                            <span className="text-[10px] font-bold text-slate-400 uppercase">Observable 5-Level Rubric Tiers</span>
                            {[
                              { key: 'rubric_l1', label: 'L1 Novice', color: 'text-rose-500' },
                              { key: 'rubric_l2', label: 'L2 Developing', color: 'text-amber-500' },
                              { key: 'rubric_l3', label: 'L3 Competent', color: 'text-blue-500' },
                              { key: 'rubric_l4', label: 'L4 Advanced', color: 'text-indigo-500' },
                              { key: 'rubric_l5', label: 'L5 Expert', color: 'text-emerald-500' },
                            ].map((lvl) => (
                              <div key={lvl.key} className="flex items-start gap-2">
                                <span className={`w-20 font-bold text-[10px] mt-1.5 ${lvl.color}`}>{lvl.label}</span>
                                <input
                                  type="text"
                                  value={skill[lvl.key] || ''}
                                  placeholder={`Behavioral indicators for ${lvl.label}...`}
                                  onChange={(e) => handleUpdateSkill(idx, lvl.key, e.target.value)}
                                  className="flex-1 px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs"
                                />
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* STEP 4: AI Interviewer Policy & Pacing */}
          {activeStep === 4 && (
            <div className="space-y-4 text-xs">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block font-bold text-zinc-300 mb-1">
                    Interview Session Duration
                  </label>
                  <select
                    value={formData.interview_duration_mins}
                    onChange={(e) => setFormData({ ...formData, interview_duration_mins: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm font-semibold"
                  >
                    <option value={15}>15 Minutes (~5-6 Expectations)</option>
                    <option value={20}>20 Minutes (~7-8 Expectations)</option>
                    <option value={30}>30 Minutes (~12-13 Expectations)</option>
                    <option value={45}>45 Minutes (~18-20 Expectations)</option>
                    <option value={60}>60 Minutes (~25-27 Expectations)</option>
                  </select>
                </div>

                <div>
                  <label className="block font-bold text-zinc-300 mb-1">
                    Max Follow-Up Depth per Core Question
                  </label>
                  <select
                    value={formData.max_followup_depth}
                    onChange={(e) => setFormData({ ...formData, max_followup_depth: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                  >
                    <option value={1}>1 Follow-up (Standard)</option>
                    <option value={2}>2 Follow-ups (Deep probe)</option>
                  </select>
                </div>

                <div>
                  <label className="block font-bold text-zinc-300 mb-1">
                    Pacing Strictness
                  </label>
                  <select
                    value={formData.pacing_strictness}
                    onChange={(e) => setFormData({ ...formData, pacing_strictness: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                  >
                    <option>Relaxed (Allows candidate to elaborate freely)</option>
                    <option>Balanced (Gently keeps candidate on track)</option>
                    <option>Aggressive (Interjects if answers exceed 90s)</option>
                  </select>
                </div>

                <div>
                  <label className="block font-bold text-zinc-300 mb-1">
                    Integrity Policy Tier
                  </label>
                  <select
                    value={formData.integrity_policy_tier}
                    onChange={(e) => setFormData({ ...formData, integrity_policy_tier: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                  >
                    <option>Basic (Presence & tab tracking)</option>
                    <option>Moderate (Multiple faces & gaze tracking)</option>
                    <option>Strict (Full acoustic & unauthorized device detection)</option>
                  </select>
                </div>

                <div className="md:col-span-2 flex items-center gap-3 p-3.5 rounded-xl bg-[#111113] border border-white/[0.08]">
                  <input
                    type="checkbox"
                    id="grace"
                    checked={formData.allow_grace_extension}
                    onChange={(e) => setFormData({ ...formData, allow_grace_extension: e.target.checked })}
                    className="w-4 h-4 text-teal-400 rounded"
                  />
                  <div>
                    <label htmlFor="grace" className="font-bold text-white cursor-pointer block">
                      Enable Optional +5 Minute Grace Period Extension
                    </label>
                    <span className="text-[11px] text-zinc-400">
                      Offers candidate extra time if answering a deep architectural question at session close.
                    </span>
                  </div>
                </div>

                <div className="md:col-span-2">
                  <label className="block font-bold text-zinc-300 mb-1">
                    Interviewer Conversational Tone & Persona Prompt
                  </label>
                  <textarea
                    rows={2}
                    value={formData.interviewer_tone}
                    onChange={(e) => setFormData({ ...formData, interviewer_tone: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-[#111113] text-white text-sm"
                  />
                </div>
              </div>
            </div>
          )}

          {/* STEP 5: Application Screening Questions */}
          {activeStep === 5 && (
            <div className="space-y-4 text-xs">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-bold text-white">
                    Application Screening Questions (Optional)
                  </h3>
                  <p className="text-[11px] text-slate-500">
                    Questions answered by candidate during job application before interview scheduling.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleAddQuestion}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-teal-500/10 text-teal-300 border border-teal-500/20 hover:bg-indigo-100"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>Add Question</span>
                </button>
              </div>

              {formData.custom_questions.length === 0 ? (
                <div className="p-6 rounded-2xl border border-dashed border-slate-300 dark:border-slate-800 text-center text-slate-400">
                  No screening questions added. Candidates will proceed directly from resume upload to interview scheduling.
                </div>
              ) : (
                <div className="space-y-3">
                  {formData.custom_questions.map((q, idx) => (
                    <div
                      key={idx}
                      className="p-4 rounded-2xl bg-[#111113]/60 border border-white/[0.08] space-y-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1">
                          <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">
                            Question Prompt
                          </label>
                          <input
                            type="text"
                            value={q.question_text}
                            onChange={(e) => handleUpdateQuestion(idx, 'question_text', e.target.value)}
                            placeholder="e.g. Describe a high-scale architecture project you designed..."
                            className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-medium"
                          />
                        </div>
                        <button
                          type="button"
                          onClick={() => handleRemoveQuestion(idx)}
                          className="p-2 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950 rounded-xl"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div>
                          <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Type</label>
                          <select
                            value={q.question_type || 'textarea'}
                            onChange={(e) => handleUpdateQuestion(idx, 'question_type', e.target.value)}
                            className="w-full px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs"
                          >
                            <option value="textarea">Paragraph / Essay</option>
                            <option value="text">Single Line Text</option>
                            <option value="yes_no">Yes / No Binary</option>
                            <option value="single_choice">Single Choice</option>
                          </select>
                        </div>
                        <div>
                          <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Difficulty</label>
                          <select
                            value={q.difficulty_level}
                            onChange={(e) => handleUpdateQuestion(idx, 'difficulty_level', e.target.value)}
                            className="w-full px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs"
                          >
                            <option>Junior</option>
                            <option>Mid-Senior</option>
                            <option>Staff / Principal</option>
                          </select>
                        </div>
                        <div className="flex items-center gap-2 pt-4">
                          <input
                            type="checkbox"
                            id={`q_req_${idx}`}
                            checked={q.is_required !== false}
                            onChange={(e) => handleUpdateQuestion(idx, 'is_required', e.target.checked)}
                            className="w-4 h-4 text-teal-400 rounded"
                          />
                          <label htmlFor={`q_req_${idx}`} className="text-zinc-300 font-semibold cursor-pointer">
                            Required to submit
                          </label>
                        </div>
                      </div>

                      <div>
                        <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">
                          Expected Key Points (one per line)
                        </label>
                        <textarea
                          rows={2}
                          value={q.expected_key_points_str || ''}
                          onChange={(e) => handleUpdateQuestion(idx, 'expected_key_points_str', e.target.value)}
                          placeholder="Points to evaluate in candidate answer..."
                          className="w-full px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs"
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* STEP 6: Interview Blueprint & Review Editor */}
          {activeStep === 6 && (
            <div className="space-y-6 text-xs">
              {!createdJob ? (
                <div className="p-8 text-center space-y-5 bg-[#111113]/60 rounded-3xl border border-white/[0.08]">
                  <div className="w-14 h-14 rounded-2xl bg-teal-500/10 text-teal-400 flex items-center justify-center mx-auto shadow-sm">
                    <Sparkles className="w-7 h-7" />
                  </div>
                  <div className="max-w-md mx-auto space-y-1">
                    <h3 className="text-base font-extrabold text-white">
                      Synthesize Role Interview Blueprint
                    </h3>
                    <p className="text-xs text-zinc-400">
                      Save calibrated role parameters to synthesize anchor questions, escalation challenges, probes, and live time budgeting.
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={submitting}
                    onClick={handleSubmit}
                    className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-teal-500 hover:bg-teal-400 text-black font-semibold font-bold text-xs shadow-md shadow-indigo-600/20 hover:-translate-y-0.5 transition-all disabled:opacity-50"
                  >
                    {submitting ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        <span>Saving Job & Opening Blueprint...</span>
                      </>
                    ) : (
                      <>
                        <Sparkles className="w-4 h-4" />
                        <span>Save Role & Generate Blueprint</span>
                      </>
                    )}
                  </button>
                </div>
              ) : (
                <React.Suspense
                  fallback={
                    <div className="p-12 text-center text-teal-400 font-semibold space-y-2">
                      <RefreshCw className="w-6 h-6 animate-spin mx-auto text-teal-400" />
                      <p className="text-xs text-zinc-400">Loading Blueprint Editor...</p>
                    </div>
                  }
                >
                  <BlueprintReviewEditor
                    job={createdJob}
                    onApproved={(approvedBp) => {
                      setBlueprintApproved(true);
                      onJobCreated(createdJob);
                    }}
                  />
                </React.Suspense>
              )}
            </div>
          )}

          {/* Footer Controls */}
          <div className="pt-6 border-t border-white/[0.08] flex items-center justify-between">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2.5 rounded-xl text-xs font-semibold text-zinc-400 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              Cancel
            </button>

            <div className="flex items-center gap-3">
              {activeStep > 1 && (
                <button
                  type="button"
                  onClick={() => setActiveStep((prev) => prev - 1)}
                  className="px-4 py-2.5 rounded-xl text-xs font-semibold text-zinc-300 bg-[#18181B] hover:bg-slate-200"
                >
                  Previous
                </button>
              )}

              {activeStep < 5 ? (
                <button
                  type="button"
                  onClick={() => setActiveStep((prev) => prev + 1)}
                  className="flex items-center gap-1.5 px-5 py-2.5 rounded-xl text-xs font-bold text-white bg-teal-500 text-black hover:bg-indigo-700 shadow-sm"
                >
                  <span>Next Step</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              ) : activeStep === 5 ? (
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => {
                    if (createdJob) {
                      setActiveStep(6);
                    } else {
                      handleSubmit();
                    }
                  }}
                  className="flex items-center gap-1.5 px-6 py-2.5 rounded-xl text-xs font-bold text-white bg-teal-500 text-black hover:bg-indigo-700 shadow-md shadow-indigo-600/20"
                >
                  {submitting ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Saving Role...</span>
                    </>
                  ) : (
                    <>
                      <span>Proceed to Blueprint</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </>
                  )}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    if (createdJob) onJobCreated(createdJob);
                    onClose();
                  }}
                  className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-xs font-bold text-white bg-slate-900 hover:bg-slate-800 dark:bg-slate-800 dark:hover:bg-slate-700 shadow-md transition-all"
                >
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  <span>Done / Close</span>
                </button>
              )}
            </div>
          </div>

        </form>

      </div>

      {/* Confirmation Modal when changing template or seniority after custom edits */}
      {pendingTemplateChange && (
        <div className="fixed inset-0 z-60 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
          <div className="bg-[#0A0A0B] rounded-3xl p-6 max-w-md w-full border border-white/[0.08] shadow-2xl space-y-4">
            <div className="w-12 h-12 rounded-2xl bg-amber-50 dark:bg-amber-950/60 text-amber-600 flex items-center justify-center">
              <AlertTriangle className="w-6 h-6" />
            </div>
            <div>
              <h3 className="font-extrabold text-base text-white">
                Reset Role Competencies?
              </h3>
              <p className="text-xs text-slate-500 mt-1">
                You have custom edits to the competencies or rubrics. Switching the role template or seniority will reset them to the calibrated template defaults.
              </p>
            </div>
            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setPendingTemplateChange(null)}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-zinc-400 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                Keep Current Edits
              </button>
              <button
                type="button"
                onClick={confirmPendingChange}
                className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 shadow-md"
              >
                Reset to Template
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
