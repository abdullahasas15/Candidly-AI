# CANDIDLY AI VOICE INTERVIEW PLATFORM
## Comprehensive System Architecture, Codebase Inventory & Technical Dossier

---

### Executive Summary

**Candidly** is an enterprise-grade autonomous AI voice interview platform designed for hiring technical talent (Software Development Engineers, AI/ML Engineers, Data Engineers, DevOps/SREs). It replaces static screening forms and robotic video questionnaires with a fluid, human-like voice conversational interview.

The platform conducts end-to-end technical interviews using calibrated **L1–L5 behavioral rubrics**, enforces proctoring and identity baselines, performs automated resume discrepancy analysis, captures streaming candidate speech with low latency, and delivers comprehensive post-interview scorecards with quote-backed evidence.

---

## 1. High-Level Architecture & Technology Stack

```
+--------------------------------------------------------------------------------------------------+
|                                    CANDIDLY PLATFORM ARCHITECTURE                                 |
+--------------------------------------------------------------------------------------------------+

  [ CANDIDATE / RECRUITER BROWSER ]
       |                   ^
       | React 19 + Vite   | WebRTC Audio/Video Tracks + DataChannel (RTVI Events)
       v                   v
+--------------------------------------------------------------------------------------------------+
| FASTAPI BACKEND RUNTIME (Python 3.11+)                                                           |
|                                                                                                  |
|   +------------------------------------+      +----------------------------------------------+   |
|   | REST API & Management Endpoints    |      | Live Interview Orchestration                 |   |
|   |  - Auth (/api/auth)                |      |  - LiveInterviewManager (Singleton)          |   |
|   |  - Jobs & Rubrics (/api/jobs)      |      |  - SmallWebRTCConnection (aiortc)            |   |
|   |  - Applications (/api/applications)|      |  - Pipecat Audio Pipeline                    |   |
|   |  - Blueprints (/api/blueprints)    |      |  - SimpleInterviewCoordinator (Scripted)     |   |
|   |  - STT Status & Pre-flight         |      |  - InterviewCoordinatorProcessor (Adaptive)  |   |
|   +------------------------------------+      +----------------------------------------------+   |
|                     |                                                |                           |
|                     v                                                v                           |
|   +------------------------------------+      +----------------------------------------------+   |
|   | Database Layer (PostgreSQL)        |      | Voice Audio Stack                            |   |
|   |  - SQLAlchemy 2.0 (Asyncpg)        |      |  - VAD: Silero VAD (ONNX)                    |   |
|   |  - Alembic Migrations (7 versions) |      |  - STT: Deepgram Nova-3 / Apple / MLX        |   |
|   |  - Binary PDF/Image Bytea Storage  |      |  - TTS: Deepgram Aura / Kokoro-82M (MLX)     |   |
|   +------------------------------------+      +----------------------------------------------+   |
|                     |                                                |                           |
|                     v                                                v                           |
|   +------------------------------------+      +----------------------------------------------+   |
|   | LLM Intelligence & Scoring Engine  |      | Monitoring & Integrity                       |   |
|   |  - Google Gemini 3.5 Flash / Lite  |      |  - Acoustic Echo Gate                        |   |
|   |  - 3-Key Automatic Rotation Pool   |      |  - Session Trace Timeline (timeline.jsonl)   |   |
|   |  - OpenRouter / NVIDIA NIM Fallback|      |  - Event-Loop Lag Monitoring (<5ms p95)      |   |
|   +------------------------------------+      +----------------------------------------------+   |
+--------------------------------------------------------------------------------------------------+
```

### Core Technologies
- **Backend**: Python 3.11+ / 3.13, FastAPI, Uvicorn, Pydantic v2.
- **Data Layer**: PostgreSQL, asyncpg, SQLAlchemy 2.0 (async ORM), Alembic migrations.
- **Frontend**: React 19, Vite, Tailwind CSS, Lucide Icons, Pipecat Client SDK (`@pipecat-ai/client-js`), WebRTC.
- **Audio & Voice Pipeline**: Pipecat AI framework (`SmallWebRTCTransport`), Silero VAD (ONNX), Deepgram WebSocket Streaming STT (Nova-3) & TTS (Aura), Apple Native SpeechAnalyzer helper (`native/apple_stt`), MLX local inference (Parakeet TDT 0.6B, Kokoro-82M).
- **LLM Reasoning**: Google Gemini API (`gemini-3.5-flash`, `gemini-3.5-flash-lite`) with 3-key failover pool, OpenRouter / NVIDIA NIM failover.

---

## 2. Complete End-to-End System Workflows

### 2.1. Recruiter Job Creation & Blueprint Materialization
1. **Job Definition**: Recruiter fills job metadata (title, department, seniority level, salary, education requirements, interview policy).
2. **Role Templates**: Recruiter can select pre-calibrated role templates (`sde`, `ai_engineer`, `data_engineer`, `devops`).
3. **Calibrated Rubrics (L1–L5)**: 3–5 core skills with weights summing to 100%, each mapped to detailed behavioral anchors:
   - **L1 (Novice)**: Superficial knowledge, anti-patterns.
   - **L2 (Developing)**: Basic textbook implementation, lacks nuance.
   - **L3 (Proficient)**: Target production baseline, handles standard edge cases.
   - **L4 (Advanced)**: Deep architectural understanding, scaling trade-offs.
   - **L5 (Expert)**: Industry-leading, novel designs, systems-level optimization.
4. **Blueprint Generation**: LLM generates an auditable, idempotent `InterviewBlueprint` dividing interview duration into fixed sections: Welcome/Agenda, Self-Intro, Per-Skill Deep Dives (Anchor Question, Escalation Question, Anchor-Alt for "no experience"), Candidate Q&A, and Closing.

### 2.2. Candidate Application & Identity Verification
1. **Job Exploration**: Candidate browses public job listings.
2. **Multi-Step Application Wizard**:
   - Contact information & self-reported experience.
   - Resume upload (PDF/DOCX/TXT). The file is stored as raw binary in PostgreSQL (`candidate_resumes.file_data`).
   - Automated Parsing: Text extracted via `pdfplumber` (with Apple Vision OCR fallback) and structured into education, work experience, projects, and skills.
   - Discrepancy Detection: Automatic flagging of discrepancies (e.g., self-reported 5 years experience vs. resume showing 2.5 years).
   - Webcam Baseline Capture: Live snapshot taken for proctoring verification (`candidate_id_verification`).
3. **Background Materialization**: Application submission automatically triggers question plan materialization, binding the job blueprint with candidate resume context.

### 2.3. Pre-Flight Check & Room Entry
1. **Device Verification**: Candidate tests microphone, camera, and speakers.
2. **Network & WebRTC Probe**: Verifies ICE connection and RTT latency.
3. **STT Speech Check**: Transcribes a spoken calibration sentence to verify microphone quality and provider readiness before room entry is permitted.

### 2.4. Live Voice Interview Runtime
1. **WebRTC Negotiation**: Browser establishes peer connection to FastAPI backend via Pipecat's `SmallWebRTCTransport`.
2. **Deterministic Scripted Flow (Simple Mode - R3.5 Default)**:
   - **Welcome Agenda**: AI interviewer speaks greeting, AI disclosure, duration, integrity notice, and agenda in one smooth utterance, concluding with "Ready to begin?".
   - **Ready Gate**: AI waits for candidate acknowledgment ("ready", "yes", "let's go") or button press before starting questions.
   - **Self-Intro**: AI asks candidate to introduce background and projects.
   - **Skill Deep Dives**: AI asks Anchor question. Candidate answers. If candidate indicates no experience, AI dynamically pivots to `anchor_alt`. If answer is solid, AI advances to `escalation`.
   - **Candidate Q&A & Closing**: Candidate can ask questions; AI delivers closing remarks.
3. **Turn-Taking & Commit Mechanics**:
   - First-one-wins commit: UI button ("I'm done answering"), verbal commit phrase ("that's my answer"), or silence auto-commit (2.5s post-speech silence).
   - Echo-gating prevents bot voice from transcribing itself.

### 2.5. Post-Interview Evaluation & Scoring
1. **Transcription Ledger**: All turns persisted in `interview_transcript_turns`.
2. **LLM Evaluation Judge**: Evaluates answers against L1–L5 rubrics using Gemini Flash.
3. **Scorecard**: Overall score (0–100), hire recommendation (Strong Hire, Hire, Lean Hire, No Hire), rubric level per skill, verified verbatim quotes, strengths, and concerns.

---

## 3. Database Architecture & Relational Schema (SQLAlchemy)

All models inherit from `backend.app.database.Base` and are mapped to PostgreSQL via asyncpg:

### 3.1. User & Identity
- **`User` (`users`)**:
  - `id`: UUID (PK).
  - `email`: String (Unique, Indexed).
  - `password_hash`: String (bcrypt hash).
  - `full_name`: String.
  - `role`: `'recruiter'` | `'candidate'`.
  - `company_name`: String (for recruiters).
  - `headline`: String (for candidates).
  - `auth_provider`: `'local'` | `'google'`.

### 3.2. Job Specifications & Role Templates
- **`RoleTemplate` (`role_templates`)**:
  - `role_key`: Unique key (`'sde'`, `'ai_engineer'`, `'data_engineer'`, `'devops'`).
  - `display_name`, `description`, `version`, `default_duration_mins`.
  - `skills`: JSON (default skill list with L1–L5 rubrics).
  - `seniority_profiles`: JSON (seniority calibration profiles).
- **`JobPosting` (`job_postings`)**:
  - `id`: UUID (PK).
  - `job_title`, `department`, `job_description`, `seniority_level` (`entry`, `mid`, `senior`, `lead`).
  - `employment_type`, `workplace_model`, `permitted_locations`.
  - Academic criteria: `min_degree_level`, `degree_enforcement_type`, `accepted_majors`, `min_cgpa`, `grad_year_start/end`.
  - Experience criteria: `total_experience_years`, `domain_experience_years`, `leadership_required`.
  - Interview policy: `interview_duration_mins` (15–60m), `allow_grace_extension` (+5m), `max_followup_depth`, `pacing_strictness`, `interviewer_tone`, `integrity_policy_tier`.
  - Compensation: `salary_range_min`, `salary_range_max`, `salary_currency`.
  - Foreign keys: `recruiter_id` -> `users.id`, `role_template_id` -> `role_templates.id`, `active_blueprint_id` -> `interview_blueprints.id`.
- **`JobSkill` (`job_skills`)**:
  - `job_id`: FK -> `job_postings.id`.
  - `name`, `category` (`Core Technical`, `Tooling`, `Architecture`, `Soft & Cultural`).
  - `priority_tier` (`P0 Mandatory`, `P1 High`, `P2 Bonus`).
  - `weight_percentage`: Float (skills sum to 100.0%).
  - Behavioral rubrics: `rubric_l1`, `rubric_l2`, `rubric_l3`, `rubric_l4`, `rubric_l5`.
- **`JobCertification` (`job_certifications`)** & **`JobCustomQuestion` (`job_custom_questions`)**.

### 3.3. Interview Blueprints
- **`InterviewBlueprint` (`interview_blueprints`)**:
  - `job_id`: FK -> `job_postings.id`.
  - `version`, `status` (`draft`, `approved`, `archived`), `total_duration_mins`, `active_skill_mins`, `fixed_overhead_mins`.
  - `input_hash`: SHA256 of job requirements for idempotency.
  - `generation_provider`, `generation_model`, `generation_latency_ms`.
- **`BlueprintSection` (`blueprint_sections`)**:
  - `blueprint_id`: FK -> `interview_blueprints.id`.
  - `order_index`: Integer.
  - `section_type`: `'welcome'`, `'intro'`, `'skill'`, `'candidate_qa'`, `'closing'`.
  - `allocated_minutes`, `target_rubric_tier`.
- **`BlueprintExpectation` (`blueprint_expectations`)**:
  - Expected knowledge points mapped from L3/L4/L5 rubrics.
- **`BlueprintQuestion` (`blueprint_questions`)**:
  - `question_role`: `'anchor'`, `'escalation'`, `'anchor_alt'`, `'probe'`, `'intro_hook'`.
  - `question_text`, `trigger_condition`, `target_expectation_ids`.

### 3.4. Candidate Applications & Dossiers
- **`JobApplication` (`job_applications`)**:
  - `job_id`: FK -> `job_postings.id`, `candidate_id`: FK -> `users.id`.
  - Candidate contact details, LinkedIn URL, portfolio URL, self-reported experience, fit pitch, salary expectations.
  - Status: `'submitted'`, `'ready_for_interview'`, `'interviewed'`, `'rejected'`, `'hired'`.
  - Recruiter decision: `'strong_hire'`, `'hire'`, `'lean_hire'`, `'no_hire'`, `'hold'`.
- **`CandidateResume` (`candidate_resumes`)**:
  - `application_id`: FK -> `job_applications.id`.
  - `file_data`: LargeBinary (`BYTEA` in Postgres) storing raw PDF/DOCX bytes.
  - `file_base64`: Base64 string for Gemini API payload.
  - `parsed_text`, `parsed_structured_data` (JSON), `ocr_used`, `parsing_status`.
- **`ResumeDiscrepancyFlag` (`resume_discrepancy_flags`)**:
  - `field_name`, `candidate_stated_value`, `resume_derived_value`, `flag_reason`.
- **`CandidateIdVerification` (`candidate_id_verification`)**:
  - Webcam snapshot base64 image, verification status.
- **`CandidatePersonalization` (`candidate_personalizations`)**:
  - Resume-grounded hooks, project deep-dive questions, and claims to verify.

### 3.5. Live Interview Sessions & Transcripts
- **`InterviewSession` (`interview_sessions`)**:
  - `id`: UUID (PK).
  - `application_id`: FK -> `job_applications.id`, `job_id`: FK -> `job_postings.id`.
  - `status`: `'scheduled'`, `'preflight'`, `'in_progress'`, `'completed'`, `'cancelled'`.
  - `current_phase`: `'greeting'`, `'self_intro'`, `'deep_dive'`, `'closing'`, `'completed'`.
  - `current_question_index`, `follow_up_count_in_current`.
  - `runtime_state`: JSON (progress tracking).
  - `started_at`, `completed_at`.
- **`InterviewQuestion` (`interview_questions`)**:
  - Materialized instance of a blueprint question for this candidate session.
- **`InterviewTranscriptTurn` (`interview_transcript_turns`)**:
  - `session_id`: FK -> `interview_sessions.id`.
  - `question_id`: FK -> `interview_questions.id`.
  - `turn_type`: `'greeting'`, `'self_intro_prompt'`, `'main_question'`, `'candidate_answer'`, `'follow_up'`, `'closing'`.
  - `speaker`: `'ai'` | `'candidate'`.
  - `text`: Spoken text content.
  - Metrics: `stt_final_ms`, `llm_ttft_ms`, `tts_first_audio_ms`, `total_response_ms`, `provider`, `model_name`.
  - `sequence_number`: Monotonically increasing turn sequence.
- **`SessionExpectationCoverage` (`session_expectation_coverage`)**:
  - Real-time quote tracking showing candidate evidence for rubric expectations.

### 3.6. Evaluation & Scoring
- **`InterviewEvaluation` (`interview_evaluations`)**:
  - Overall score (0–100), verdict (`strong_hire`, `hire`, `lean_hire`, `no_hire`), summary, strengths, concerns.
- **`InterviewSkillScore` (`interview_skill_scores`)**:
  - Per-skill rubric level (`L1`–`L5` or `NOT_ASSESSED`), numeric score, rationale, verified evidence quotes.
- **`InterviewIntegrityEvent` (`interview_integrity_events`)**:
  - Proctoring logs: window blur, tab switch, face missing, multiple faces.
- **`InterviewFeedback` (`interview_feedback`)**:
  - Candidate post-interview rating and feedback comments.

---

## 4. Complete File-by-File Inventory

### 4.1. Root Files
- **`CLAUDE.md`**: Project instructions, guidelines, branch standards, command reference, and test execution procedures.
- **`requirements.txt`**: Core Python dependencies (FastAPI, Uvicorn, SQLAlchemy, asyncpg, Alembic, Pydantic, google-genai, deepgram-sdk, etc.).
- **`requirements-voice-macos.txt`**: macOS voice stack dependencies (Pipecat, mlx-audio, parakeet-mlx, aiortc).
- **`alembic.ini`**: Alembic migration environment configuration.

### 4.2. Database & Migrations (`alembic/`)
- **`alembic/env.py`**: Async migration runner loading `Base.metadata` and connecting via `DATABASE_URL`.
- **`alembic/versions/20261005_interview_generation_runtime.py`**: Initial schema for users, jobs, skills, applications, sessions, turns, evaluations.
- **`alembic/versions/20261013_blueprint_r2_enhancements.py`**: Added blueprint metadata, input hash, generation latency.
- **`alembic/versions/20261013_job_interview_blueprints.py`**: Introduced `interview_blueprints`, sections, expectations, and questions.
- **`alembic/versions/20261013_live_interview_and_evaluation.py`**: Schema updates for live WebRTC session tracking and scoring rubrics.
- **`alembic/versions/20261013_role_templates_and_blueprint_quality.py`**: Added `role_templates` table and calibrated seeds.
- **`alembic/versions/20261014_candidate_personalization_and_coverage.py`**: Added `candidate_personalizations` and `session_expectation_coverage`.
- **`alembic/versions/20261014_provider_routing_and_runtime_state.py`**: Added multi-provider STT/LLM routing fields and runtime state.

### 4.3. Backend Core (`backend/app/`)
- **`backend/__init__.py` & `backend/app/__init__.py`**: Module packages.
- **`backend/app/database.py`**: Database setup (`AsyncSessionLocal`, `engine`, `Base`, `get_db` dependency).
- **`backend/app/models.py`**: Complete SQLAlchemy ORM definitions for all 22 database tables.
- **`backend/app/schemas.py`**: Pydantic v2 validation models for request/response bodies across all APIs.
- **`backend/app/budgeting.py`**: Question budgeting logic allocating interview time to skills based on weights and priorities.
- **`backend/app/seed.py`**: Database seeding script populating initial role templates and recruiter accounts.
- **`backend/app/main.py`**: Central FastAPI application:
  - Application lifecycle (startup/shutdown, voice model pre-warming).
  - Auth routes (`/api/auth/signup`, `/api/auth/login`, `/api/auth/me`).
  - Job management routes (`/api/jobs`, `/api/jobs/{id}`, public redacted endpoints).
  - Role templates (`/api/role-templates`).
  - Candidate application routes (`/api/applications`, resume upload, PDF streaming, ID verification).
  - Interview blueprint routes (`/api/jobs/{id}/blueprint`, review, edit, approve).
  - Live session routes (`/api/interview-sessions/{id}/connect`, `/api/interview-sessions/{id}/patch`, `/api/interview-sessions/{id}/commit-turn`, `/api/interview-sessions/{id}/repeat-question`).
  - Preflight & STT readiness (`/api/stt/status`, `/api/stt/preflight-check`).
  - Evaluation & reporting endpoints (`/api/interview-sessions/{id}/evaluation`).

### 4.4. Backend Services (`backend/app/services/`)
- **`backend/app/services/auth.py`**: JWT token creation, password hashing (bcrypt), and current user dependency extraction.
- **`backend/app/services/llm_router.py`**: Multi-provider LLM client with automatic key rotation across 3 Gemini API keys, with fallback to OpenRouter and NVIDIA NIM.
- **`backend/app/services/resume_parser.py`**: Multi-format resume extraction (PDF via `pdfplumber` + Apple OCR fallback, DOCX via `python-docx`, TXT), section segmentation, structured information extraction, and discrepancy auditing.

#### Role Templates (`backend/app/services/role_templates/`)
- **`loader.py`**: Loads JSON template files into the database.
- **`sde.v1.json`**: Software Development Engineer template with L1–L5 rubrics for Data Structures, System Design, Concurrency, and Clean Code.
- **`ai_engineer.v1.json`**: AI Engineer template covering Deep Learning, LLM Architecture, Fine-Tuning, and MLOps.
- **`data_engineer.v1.json`**: Data Engineer template covering Distributed Computing, Data Modeling, ETL, and Streaming.
- **`devops.v1.json`**: DevOps/SRE template covering CI/CD, Kubernetes, Observability, and Infrastructure as Code.

#### Blueprint Engine (`backend/app/services/blueprint/`)
- **`contracts.py`**: Pydantic dataclasses for blueprint sections, questions, and expectations.
- **`generator.py`**: Orchestrates LLM prompt construction, structured output parsing, and validation.
- **`persistence.py`**: Saves generated blueprints into database tables.
- **`prompts.py`**: System and user prompts for blueprint generation.
- **`seniority_config.py`**: Seniority adjustments (Entry, Mid, Senior, Lead) defining pacing, question depths, and rubric targets.
- **`validator.py`**: Enforces strict structural rules (time budgets, verbal-only phrasing, forbidden code questions, rubric alignment).

#### Question Generation (`backend/app/services/question_generation/`)
- **`contracts.py`**: Data transfer contracts for question generation.
- **`persistence.py`**: Persists materialized question plans to `interview_questions`.
- **`prompt_builder.py`**: Assembles prompts combining job requirements, rubrics, and candidate resume text.
- **`provider.py`**: Gemini API integration with structured JSON schema responses.
- **`snapshot.py`**: Computes input hash snapshots for idempotency.
- **`validator.py`**: Validates question quality, relevance, and formatting.

#### Live Interview Runtime (`backend/app/services/interview/`)
- **`live_session.py`**:
  - `LiveInterviewManager`: Process-wide singleton managing active interview sessions.
  - `LiveInterviewRunner`: WebRTC session runner setting up SmallWebRTC transport, RTVI event handlers, and coordinators.
  - `InterviewCoordinatorProcessor`: Adaptive mode coordinator (LLM-in-the-loop with Gemini Flash-Lite).
- **`simple_session.py`**:
  - `SimpleInterviewCoordinator`: R3.5 default deterministic scripted state machine (`ASKING` -> `LISTENING` -> `COMMITTED`) with zero LLM calls in the live audio loop.
  - Handles ready-gate, welcome agenda, skill transitions, "no experience" branching, silence auto-commit, repeating questions, and transcript persistence.
- **`voice_pipeline.py`**:
  - Builds Pipecat pipeline components (`PipelineRunner`, `PipelineTask`).
  - Warm singletons for Silero VAD, Parakeet STT, Kokoro TTS.
  - `CandidlyDeepgramSTTService`: Deepgram Nova-3 real-time WebSocket streaming STT.
  - `CandidlyDeepgramTTSService`: Deepgram Aura real-time WebSocket TTS.
  - Acoustic echo suppression gate.
- **`stt_provider.py`**:
  - Pluggable STT provider resolution (`deepgram`, `apple_speechanalyzer`, `apple_sfspeech`, `local_two_lane`).
  - `AppleSpeechProcess`: Subprocess supervisor for native macOS speech helper.
  - `stitch_sliding_text()`: Algorithm for merging sliding volatile STT transcript windows.
  - Offline transcription utilities for pre-flight testing and review.
- **`personalization.py`**: Generates resume-grounded intro hooks and technical probes.
- **`plan_materializer.py`**: Binds job blueprints to interview questions.
- **`followup_policy.py`**: Rules for follow-up depth and neutral verbal bridges.
- **`state_machine.py`**: Enums and models for interview phases, turn types, and pacing control.
- **`trace.py`**: Low-overhead structured event logger emitting `timeline.jsonl` per session.
- **`turn_evaluator.py`**: Post-interview evaluation engine invoking Gemini judge to generate scorecard and rubric scores.

### 4.5. Native Modules (`native/`)
- **`native/apple_stt/Package.swift`**: Swift Package Manager manifest for macOS speech recognizer.
- **`native/apple_stt/Sources/apple_stt/main.swift`**: Swift CLI tool wrapping Apple's `SpeechAnalyzer` (macOS 26+) and `SFSpeechRecognizer` (macOS 13+), streaming PCM audio via stdin and outputting JSON lines partial/final events to stdout.

### 4.6. Frontend Application (`frontend/`)
- **`frontend/package.json`**: Dependencies (`react`, `react-dom`, `@pipecat-ai/client-js`, `lucide-react`, `tailwindcss`, `vite`).
- **`frontend/vite.config.js`**: Vite configuration with proxy to FastAPI backend (`/api` -> `http://localhost:8000`).
- **`frontend/tailwind.config.js`**: Design system tokens, typography, and color palette.
- **`frontend/src/main.jsx`**: React root mounting `App.jsx`.
- **`frontend/src/App.jsx`**: Main client-side router and state manager handling role views (Candidate vs. Recruiter) and modals.
- **`frontend/src/index.css`**: Tailwind directives and custom animation styles (orb pulse, speaking waves).
- **`frontend/src/utils/currency.js`**: International currency formatting utilities ($ USD, ₹ INR, € EUR, £ GBP).

#### Landing & Shared Components (`frontend/src/components/`)
- **`Header.jsx`**: Global navbar with auth controls and role switcher.
- **`Footer.jsx`**: Platform footer.
- **`Hero.jsx`**: Marketing hero with interactive CTA.
- **`StatsStrip.jsx`**: Social proof and metrics strip.
- **`WhatWeOffer.jsx`**: Feature comparison showcase.
- **`HowWeEvaluate.jsx`**: Explanation of L1–L5 rubric evaluation.
- **`ProctoringIntegrity.jsx`**: Security, privacy, and anti-cheating overview.
- **`PersonaTabs.jsx`**: Recruiter vs. Candidate value proposition tabs.
- **`DemoModal.jsx`**: Interactive preview modal.
- **`Logo.jsx`**: Candidly brand SVG logo.
- **`auth/AuthModal.jsx`**: Login and signup modal with JWT token persistence.

#### Recruiter Experience (`frontend/src/components/recruiter/`)
- **`RecruiterDashboard.jsx`**: Overview of posted jobs, applicant pipelines, and interview completions.
- **`JobCreationModal.jsx`**: 6-step job wizard with role template selection, salary criteria, education requirements, and L1–L5 rubric editor.
- **`JobDetailModal.jsx`**: Detailed view of job posting and applicant list.
- **`ApplicantDetailModal.jsx`**: Full candidate dossier showing resume PDF viewer, parsed data, discrepancy flags, proctoring baseline, interview transcript, and evaluation scorecard.
- **`BlueprintReviewEditor.jsx`**: Interactive editor to inspect, customize, and approve job interview blueprints.

#### Candidate Experience (`frontend/src/components/candidate/`)
- **`CandidateDashboard.jsx`**: Candidate home showing applications and upcoming interview sessions.
- **`CandidateJobListing.jsx`**: Job board with public, redacted job descriptions.
- **`ApplicationWizard.jsx`**: Multi-step application submission, resume upload, discrepancy review, and webcam verification.
- **`interview/PreFlightCheckModal.jsx`**: Diagnostic modal verifying camera, microphone, WebRTC connectivity, and STT readiness.
- **`interview/LiveInterviewRoom.jsx`**: The live interview room:
  - Dual-pane layout: AI interviewer orb and state pill (left) | Candidate video, live audio visualizer, and streaming transcript (right).
  - WebRTC connection handling via `@pipecat-ai/client-js`.
  - Bot state visualization (`Listening`, `Thinking`, `Speaking`, `Finishing`).
  - Candidate controls: Mute/Unmute, "I'm done answering" commit button, "Repeat question", and End Interview.
  - Collapsible transcript drawer.

### 4.7. Scripts & Tooling (`scripts/`)
- **`scripts/start_servers.sh` & `scripts/stop_servers.sh`**: Start/stop FastAPI and Vite dev servers.
- **`scripts/db.sh`**: Database helper script for migrations and psql access.
- **`scripts/build_apple_stt.sh`**: Compiles native Swift speech helper.
- **`scripts/verify_r3_5.py`**: Test suite with 49 automated checks verifying R3.5 simple mode state transitions, DB persistence, and zero live LLM calls.
- **`scripts/test_question_generation_pipeline.py`**: Verifies question generation and rubric materialization.
- **`scripts/test_application_flow.py`**: Tests candidate application submission and resume parsing.
- **`scripts/test_auth_and_application_flow.py`**: End-to-end auth and application flow test.
- **`scripts/benchmark_voice_latency.py` & `scripts/benchmark_r3_1_latency.py`**: Benchmarks STT TTFT, LLM latency, and TTS first-audio latency.
- **`scripts/drive_provider_stt.py`**: Benchmarks STT providers against recorded audio samples.
- **`scripts/build_stt_review.py` & `scripts/analyze_captured_audio.py`**: Analyzes recorded audio files and generates HTML accuracy reports (`review/stt_review.html`).
- **`scripts/wipe_database.py`**: Clean database wipe and reset utility.

---

## 5. Voice Pipeline Deep Dive & Audio Topology

The live voice runtime uses **Pipecat 1.12.0** with a custom frame-processing pipeline:

```
[Candidate Microphone]
       |
       v (WebRTC Track - 16kHz PCM16)
[SmallWebRTCTransport.Input]
       |
       +---> [SileroVADAnalyzer] ---> Emits UserStartedSpeakingFrame / UserStoppedSpeakingFrame
       |
       +---> [STT Service (Deepgram Nova-3 / Apple / MLX)]
       |           |
       |           +---> InterimTranscriptionFrame (Live streaming partial words)
       |           +---> TranscriptionFrame (Finalized segment)
       |
       v
[Coordinator Processor (SimpleInterviewCoordinator)]
       |
       | (State Machine: ASKING -> LISTENING -> COMMITTED)
       |
       v
[TTS Service (Deepgram Aura / Kokoro-82M)]
       |
       v (TTSAudioRawFrame)
[SmallWebRTCTransport.Output]
       |
       v (WebRTC Track)
[Candidate Headphones/Speakers]
```

### 5.1. Audio Pipeline Components
1. **Transport**: `SmallWebRTCTransport` (aiortc) handles WebRTC audio ingest and playback over an RTCPeerConnection, alongside a DataChannel for bidirectional RTVI JSON messages.
2. **VAD (Voice Activity Detection)**: `SileroVADAnalyzer` (ONNX) tuned for interview speech with a 500ms speech start threshold and a 2.5s speech stop threshold.
3. **STT Providers**:
   - **Deepgram Cloud (Nova-3)**: Streaming WebSocket client (`wss://api.deepgram.com`) configured with `smart_format=True`, `punctuate=True`, and `interim_results=True`.
   - **Apple Speech (macOS Native)**: Swift helper using macOS `SpeechAnalyzer` (macOS 26+) or `SFSpeechRecognizer` (macOS 13+), feeding raw PCM16 over stdin.
   - **Local MLX Two-Lane**: In-process Parakeet TDT 0.6B (streaming lane) + Whisper Large v3 Turbo (accuracy lane).
4. **TTS Providers**:
   - **Deepgram Aura**: Real-time cloud WebSocket TTS with voices like `aura-asteria-en`. First-audio latency ~150–250ms.
   - **Kokoro-82M (MLX)**: In-process neural TTS running on Apple Silicon unified memory with a pre-synthesized static phrase cache.
5. **Echo Suppression**: Mutes microphone input during bot speech to eliminate acoustic echo feedback loops when the candidate is not wearing headphones.

---

## 6. Interview State Machines & Orchestration

The platform supports two orchestration modes:

### 6.1. Simple Mode (`INTERVIEW_MODE=simple`, R3.5 Default)
Designed for predictable, deterministic interviews with **zero live LLM latency**:
- **Scripted State Machine**:
  - `ASKING`: Bot is actively speaking a scripted question via TTS. Microphones are echo-gated.
  - `LISTENING`: Candidate is speaking. Words stream to the UI in real time.
  - `COMMITTED`: Candidate's answer is captured. Bot speaks a brief bridge (e.g., "Got it.") and moves to the next question.
- **Rule-Based Conversational Flow**:
  1. *Welcome*: AI disclosure, duration, monitoring notice, and agenda merged into one utterance.
  2. *Ready Gate*: Waits for candidate confirmation before proceeding.
  3. *Self-Intro*: Asks candidate to introduce themselves.
  4. *Per-Skill Steps*:
     - Asks `anchor` question.
     - If candidate says "no experience" (regex-detected), swaps to `anchor_alt` and skips escalation.
     - If answer is <4 words, prompts "Could you say a bit more?" (maximum once per skill).
     - Otherwise asks `escalation` question.
  5. *Candidate Q&A*: Invites questions from the candidate.
  6. *Closing*: Concluding remarks and next steps.
- **Turn Commit Triggers (First wins)**:
  - Candidate clicks "I'm done answering".
  - Candidate speaks an explicit commit phrase ("that's my answer", "I'm done").
  - `AUTO_COMMIT_SILENCE` (2.5s of uninterrupted silence after speaking).

### 6.2. Adaptive Mode (`INTERVIEW_MODE=adaptive`, R3.4c)
- Uses Gemini 3.5 Flash-Lite in the live audio loop.
- Dynamically decides whether to ask a clarifying follow-up, probe deeper, or advance to the next skill based on candidate answer completeness.
- Uses dynamic token scaling and neutral verbal bridges (<=5 words, no praise like "Great job!").

---

## 7. Forensic Root-Cause Analysis of Recent Live Test Failures

During the live test on MacBook M2 Air with Deepgram STT/TTS, the user experienced four critical failures. Here are the exact architectural root causes:

### 7.1. Failure 1: Voice Clipping & Biting at Start of Bot Speech
- **Symptom**: When the AI interviewer began speaking, the first syllable was swallowed or cut off.
- **Root Cause**:
  - In `LiveInterviewRoom.jsx`, the candidate's browser WebRTC audio element was initialized without pre-buffering or was momentarily paused while handling autoplay policies.
  - Concurrently, Deepgram Aura WebSocket sends initial audio packets in very small byte buffers (sub-20ms chunks) without a jitter buffer, causing browser WebRTC audio underflow during the first 100ms of playback.

### 7.2. Failure 2: Premature Ready-Gate Trigger
- **Symptom**: The AI interviewer asked "Ready to begin?", and before the candidate could speak, the platform immediately jumped into asking the background question.
- **Root Cause**:
  - Background noise or room breath was transcribed by Deepgram as a single short token (e.g., `"Donate."` or `"Yeah."`).
  - In `simple_session.py`, `_READY_ACK_RE` matched `"yeah"` inside the stitched string, or the VAD user-stopped event fired an auto-commit that satisfied the ready gate without a positive speech confirmation threshold.

### 7.3. Failure 3: Transcript Stuttering & Duplicate Word Repetitions
- **Symptom**: Transcribed text duplicated multiple times: *"BTEC BTEC in CBIT, Hyderabad BTEC in CBIT Hyderabad... And And I'm I have... Rack Chat Rack chatbot..."*
- **Root Cause (Triple-Dispatch Bug)**:
  - In `voice_pipeline.py` (`CandidlyDeepgramSTTService`):
    - `_on_message` called `super()._on_message(message)`, which pushed a `TranscriptionFrame` downstream into Pipecat.
    - Inside `_on_message`, it ALSO called `self._on_stt_final_chunk(transcript)`.
    - Downstream in `simple_session.py`, `SimpleInterviewCoordinator.process_frame()` intercepted the `TranscriptionFrame` and called `self.record_stt_final_chunk(text)` a SECOND time.
    - Both paths called `stitch_sliding_text()`.
    - Furthermore, `_on_message` in `CandidlyDeepgramSTTService` called `stitch_sliding_text()` on every interim partial as well as finals.
    - Because Deepgram interim partials are cumulative prefix strings, running sliding-window suffix stitching on every partial and duplicate final repeatedly appended overlapping words, causing exponential word repetition.

### 7.4. Failure 4: Turn Commit Freeze on "Finishing your answer..."
- **Symptom**: After the candidate finished speaking their background, the UI showed "Finishing your answer..." and froze permanently. The interview never moved to the next question.
- **Root Cause (Race Condition & Incomplete State Transition)**:
  - In `simple_session.py`, `_auto_commit_after_silence()` executed:
    ```python
    if self.state == self.ST_LISTENING and not self._speech_active:
        await self._emit("interview-bot-state", {"state": "finishing", "commit_reason": "silence"})
    if (
        time.monotonic() - self._last_activity_monotonic >= wait - 0.35
        and self.state == self.ST_LISTENING
        and not self._speech_active
    ):
        await self.commit_turn(reason="silence")
    ```
  - `_emit("interview-bot-state", {"state": "finishing"})` was broadcast to the frontend UI *before* the activity condition check.
  - While the timer was waiting, a duplicate late STT chunk arrived, updating `self._last_activity_monotonic = time.monotonic()`.
  - When the timeout loop finished, `time.monotonic() - self._last_activity_monotonic` was only ~0.2s, so the condition `0.2 >= 2.15` evaluated to **FALSE**!
  - As a result, `commit_turn()` was **never invoked**!
  - The UI remained stuck displaying "Finishing your answer...", with the commit button disabled, while the coordinator loop became dormant.

---

## 8. Strategic Architectural Recommendations for Claude

When designing the next-generation architecture for Candidly, the following structural improvements should be prioritized:

### 8.1. Clean Pipeline Decoupling (Separation of Concerns)
- **Eliminate Dual-Path Callbacks**: STT services in Pipecat should **only** push standard Pipecat frames (`InterimTranscriptionFrame`, `TranscriptionFrame`) downstream. Remove custom side-channel callbacks (`_on_stt_final_chunk`, `_on_stt_interim`) to guarantee that every transcript segment is processed exactly once.
- **Standardized Text Accumulator**: Replace sliding-window string stitching with an ID-based or sequence-based transcript accumulator:
  - Deepgram emits stable sequence metadata (`message.channel.alternatives[0].words`).
  - Maintain a clean array of finalized word objects `[{word, start, end, confidence}]` and a separate single transient string for interim partials.

### 8.2. Atomic Turn Commit State Machine
- **State Transition Atomicity**: The state transition to `FINISHING` must be atomic with the commit execution. Never emit a UI state update until the lock is acquired and the commit operation is actively executing.
- **Bounded Flush with Fallback**: Never block indefinitely on WebSocket `send_finalize`. Use `asyncio.wait_for()` with a 400ms timeout; if finalize does not return within the budget, commit the latest accumulated text immediately without stalling the interview.

### 8.3. Robust Ready-Gate & Noise Filtering
- **Intent Recognition Gate**: Do not rely on loose regex matching on single tokens. The ready-gate should require:
  - Either an explicit button click ("I'm ready"), OR
  - High-confidence multi-word intent ("I am ready", "let's begin") with a minimum duration of 500ms of voiced audio.
- **Ambient Noise Rejector**: Discard transcripts with low confidence (<0.65) or duration under 300ms during gate checks.

### 8.4. Unified Audio Transport & Cloud-First Modular Architecture
- **WebRTC Transport Stability**: Implement a lightweight jitter buffer (60–100ms) on the client side before feeding received audio tracks to the HTML5 audio element to completely eliminate initial speech clipping.
- **Provider Abstraction Layer**: Cleanly isolate Cloud (Deepgram Nova-3 + Aura) and Local (Apple/MLX) behind a unified interface `VoicePipelineProvider` with zero platform-specific monkey patching in coordinator logic.
