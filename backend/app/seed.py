from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.app.models import JobPosting, JobSkill, JobCertification, JobCustomQuestion, JobQuestionPlan, User, CandidateApplication
from backend.app.budgeting import calculate_question_budget

DEFAULT_JOB_DATA = {
    "job_title": "Senior Distributed Systems Engineer",
    "department": "Core Platform Infrastructure",
    "seniority_level": "Mid-Level (L4)",
    "employment_type": "Full-Time",
    "workplace_model": "Hybrid",
    "permitted_locations": ["United States", "Canada", "Remote (EST/PST)"],
    "min_degree_level": "Bachelor's Degree (B.S. / B.E. / B.Tech)",
    "degree_enforcement_type": "Equivalent Professional Experience Allowed",
    "accepted_majors": ["Computer Science", "Software Engineering", "Electrical & Computer Engineering"],
    "min_cgpa": "3.2 / 4.0",
    "cgpa_strict_filter": False,
    "grad_year_start": 2018,
    "grad_year_end": 2023,
    "total_experience_years": 4.0,
    "domain_experience_years": 2.5,
    "leadership_required": True,
    "interview_duration_mins": 20,
    "allow_grace_extension": True,
    "max_followup_depth": 1,
    "pacing_strictness": "Balanced",
    "interviewer_tone": "Direct, technical, tech-lead caliber; probes for architectural trade-offs; warm but concise.",
    "integrity_policy_tier": "Moderate",
    "salary_range_min": 145000.0,
    "salary_range_max": 185000.0,
    "salary_currency": "USD",
    "skills": [
        {
            "name": "Data Structures & Algorithms (DSA)",
            "category": "Core Technical",
            "priority_tier": "P0",
            "weight_percentage": 35.0,
            "rubric_l1": "Fails basic algorithmic analysis; uses O(N^2) loops where O(N) is trivial; struggles with pointer manipulation or recursion.",
            "rubric_l2": "Solves simple cases but struggles with edge bounds; understands standard hash tables but cannot optimize auxiliary space complexity.",
            "rubric_l3": "Produces clean, production-grade solutions with verified optimal time/space complexity; writes correct boundary conditions.",
            "rubric_l4": "Proactively addresses memory locality, amortized runtime analysis, cache friendliness, and concurrency-safe data structures.",
            "rubric_l5": "Explains hardware cache hierarchy impact (L1/L2 miss rates), SIMD vectorization potential, and lock-free algorithmic primitives."
        },
        {
            "name": "System Design & Scalability",
            "category": "Domain & Architectural",
            "priority_tier": "P0",
            "weight_percentage": 30.0,
            "rubric_l1": "Proposes monolithic single-server solutions; completely ignores caching, load balancers, and database bottlenecks.",
            "rubric_l2": "Mentions caching and microservices but cannot explain cache invalidation strategies or database replication lag trade-offs.",
            "rubric_l3": "Designs functional distributed system with load balancers, Redis caching, and relational read-replicas with valid justification.",
            "rubric_l4": "Proactively addresses distributed consensus, circuit breakers, idempotency keys, backpressure, and graceful degradation.",
            "rubric_l5": "Evaluates deep engine trade-offs (e.g. LSM-tree vs B-Tree, Paxos vs Raft), network partition survivability, and financial cloud cost vs SLAs."
        },
        {
            "name": "Database Architecture & Consistency",
            "category": "Tooling & Frameworks",
            "priority_tier": "P1",
            "weight_percentage": 20.0,
            "rubric_l1": "Lacks understanding of indexing internals; proposes querying unindexed large tables; ignores ACID guarantees.",
            "rubric_l2": "Understands primary/foreign keys and basic indexing, but cannot diagnose lock contention or explain composite index column ordering.",
            "rubric_l3": "Configures appropriate indexes (B-Tree, Hash, GIN); designs normalized vs denormalized schemas aligned with query patterns.",
            "rubric_l4": "Analyzes transaction isolation levels (Read Committed vs Serializable), phantom reads, multi-version concurrency control (MVCC), and sharding keys.",
            "rubric_l5": "Architects globally distributed distributed-SQL layers with multi-region quorum reads and conflict-free replicated data types (CRDTs)."
        },
        {
            "name": "Technical Communication & Trade-offs",
            "category": "Soft & Cultural",
            "priority_tier": "P1",
            "weight_percentage": 15.0,
            "rubric_l1": "Disorganized thought process; rambles defensively; unable to articulate reasons behind technical choices.",
            "rubric_l2": "Explains decisions when prompted but struggles to proactively frame architectural trade-offs to non-technical stakeholders.",
            "rubric_l3": "Communicates with structured clarity (top-down articulation); clarifies ambiguities before jumping into solution designs.",
            "rubric_l4": "Articulates nuanced trade-offs clearly; acknowledges limitations of proposed designs and invites architectural critique.",
            "rubric_l5": "Exemplary engineering leadership presence; explains complex distributed trade-offs with razor-sharp brevity and poise."
        }
    ],
    "certifications": [
        {
            "name": "AWS Certified Solutions Architect - Professional",
            "issuing_org": "Amazon Web Services",
            "priority_tier": "P1",
            "verification_required": True
        },
        {
            "name": "Certified Kubernetes Administrator (CKA)",
            "issuing_org": "Cloud Native Computing Foundation (CNCF)",
            "priority_tier": "P2",
            "verification_required": False
        }
    ],
    "custom_questions": [
        {
            "question_text": "Describe how you would design a multi-tenant rate limiter serving 100,000 requests per second with strict latency budgets under 5ms.",
            "category": "Domain & Architectural",
            "difficulty_level": "Senior (L5)",
            "expected_key_points": [
                "Proposes sliding window log or token bucket algorithm in Redis",
                "Addresses race conditions using Redis Lua scripts or atomic increments",
                "Implements local in-memory tiering to reduce Redis round-trips",
                "Handles Redis cluster failover and graceful throttling response (HTTP 429)"
            ],
            "priority_tier": "P0"
        }
    ]
}

async def seed_initial_job_if_empty(session: AsyncSession):
    stmt = select(JobPosting)
    result = await session.execute(stmt)
    existing = result.scalars().first()
    if existing:
        if existing.salary_range_min is None:
            existing.salary_range_min = DEFAULT_JOB_DATA["salary_range_min"]
            existing.salary_range_max = DEFAULT_JOB_DATA["salary_range_max"]
            existing.salary_currency = DEFAULT_JOB_DATA["salary_currency"]
            await session.commit()
        return existing

    # Create job posting
    job = JobPosting(
        job_title=DEFAULT_JOB_DATA["job_title"],
        department=DEFAULT_JOB_DATA["department"],
        seniority_level=DEFAULT_JOB_DATA["seniority_level"],
        employment_type=DEFAULT_JOB_DATA["employment_type"],
        workplace_model=DEFAULT_JOB_DATA["workplace_model"],
        permitted_locations=DEFAULT_JOB_DATA["permitted_locations"],
        min_degree_level=DEFAULT_JOB_DATA["min_degree_level"],
        degree_enforcement_type=DEFAULT_JOB_DATA["degree_enforcement_type"],
        accepted_majors=DEFAULT_JOB_DATA["accepted_majors"],
        min_cgpa=DEFAULT_JOB_DATA["min_cgpa"],
        cgpa_strict_filter=DEFAULT_JOB_DATA["cgpa_strict_filter"],
        grad_year_start=DEFAULT_JOB_DATA["grad_year_start"],
        grad_year_end=DEFAULT_JOB_DATA["grad_year_end"],
        total_experience_years=DEFAULT_JOB_DATA["total_experience_years"],
        domain_experience_years=DEFAULT_JOB_DATA["domain_experience_years"],
        leadership_required=DEFAULT_JOB_DATA["leadership_required"],
        interview_duration_mins=DEFAULT_JOB_DATA["interview_duration_mins"],
        allow_grace_extension=DEFAULT_JOB_DATA["allow_grace_extension"],
        max_followup_depth=DEFAULT_JOB_DATA["max_followup_depth"],
        pacing_strictness=DEFAULT_JOB_DATA["pacing_strictness"],
        interviewer_tone=DEFAULT_JOB_DATA["interviewer_tone"],
        integrity_policy_tier=DEFAULT_JOB_DATA["integrity_policy_tier"],
        salary_range_min=DEFAULT_JOB_DATA["salary_range_min"],
        salary_range_max=DEFAULT_JOB_DATA["salary_range_max"],
        salary_currency=DEFAULT_JOB_DATA["salary_currency"],
        status="active"
    )
    session.add(job)
    await session.flush()

    # Add Skills
    for s in DEFAULT_JOB_DATA["skills"]:
        skill = JobSkill(
            job_id=job.id,
            name=s["name"],
            category=s["category"],
            priority_tier=s["priority_tier"],
            weight_percentage=s["weight_percentage"],
            rubric_l1=s.get("rubric_l1"),
            rubric_l2=s.get("rubric_l2"),
            rubric_l3=s.get("rubric_l3"),
            rubric_l4=s.get("rubric_l4"),
            rubric_l5=s.get("rubric_l5"),
        )
        session.add(skill)

    # Add Certifications
    for c in DEFAULT_JOB_DATA["certifications"]:
        cert = JobCertification(
            job_id=job.id,
            name=c["name"],
            issuing_org=c["issuing_org"],
            priority_tier=c["priority_tier"],
            verification_required=c["verification_required"]
        )
        session.add(cert)

    # Add Custom Questions
    for q in DEFAULT_JOB_DATA["custom_questions"]:
        question = JobCustomQuestion(
            job_id=job.id,
            question_text=q["question_text"],
            category=q["category"],
            difficulty_level=q["difficulty_level"],
            expected_key_points=q["expected_key_points"],
            priority_tier=q["priority_tier"]
        )
        session.add(question)

    # Calculate and store question plan
    budget = calculate_question_budget(DEFAULT_JOB_DATA["interview_duration_mins"], DEFAULT_JOB_DATA["skills"])
    for alloc in budget["allocations"]:
        plan = JobQuestionPlan(
            job_id=job.id,
            skill_name=alloc["skill_name"],
            skill_priority=alloc["skill_priority"],
            allocated_questions=alloc["allocated_questions"],
            time_allocation_minutes=alloc["time_allocation_minutes"],
            weight_percentage=alloc["weight_percentage"],
            target_rubric_tier=alloc["target_rubric_tier"]
        )
        session.add(plan)

    await session.commit()
    return job


async def seed_initial_users_if_empty(session: AsyncSession):
    stmt = select(User)
    result = await session.execute(stmt)
    existing = result.scalars().first()
    if existing:
        return

    # Seed Default Recruiter
    recruiter = User(
        email="recruiter@candidly.ai",
        password_hash="12qw",
        full_name="Jane Doe",
        role="recruiter",
        company_name="Acme Engineering Labs"
    )
    session.add(recruiter)

    # Seed Default Candidate
    candidate = User(
        email="candidate@candidly.ai",
        password_hash="12qw",
        full_name="Alex Mercer",
        role="candidate",
        headline="Senior Distributed Systems & Cloud Engineer (4 YOE)"
    )
    session.add(candidate)
    await session.flush()

    # Link candidate application to the first available job
    job_stmt = select(JobPosting)
    job_result = await session.execute(job_stmt)
    job = job_result.scalars().first()
    if job:
        app = CandidateApplication(
            user_id=candidate.id,
            job_id=job.id,
            status="interview_ready",
            fit_score=None
        )
        session.add(app)

    await session.commit()


