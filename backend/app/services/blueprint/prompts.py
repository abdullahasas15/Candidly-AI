"""Prompts and prompt templates for Job Interview Blueprint generation and repair."""

import json
from typing import Dict, Any, List, Optional
from backend.app.services.blueprint.seniority_config import get_seniority_profile


def build_welcome_script(job_title: str, duration_mins: int) -> str:
    return (
        f"Hello, and welcome to your technical interview for the {job_title} role. "
        f"Over the next {duration_mins} minutes, we will walk through your background and "
        "explore technical architecture, trade-offs, and practical engineering challenges. "
        "Take your time when answering, and when you are ready, let's begin."
    )


def build_closing_script(job_title: str) -> str:
    return (
        "Thank you for sharing your experience and technical perspective with me today. "
        f"That concludes our interview for {job_title}. Our recruiting team will review "
        "the session transcript and be in touch regarding next steps. Have a wonderful rest of your day!"
    )


SUGGEST_SKILLS_SYSTEM_PROMPT = """You are Candidly's Talent Architecture Lead.
Your task is to analyze a job title, seniority level, and job description, and propose 3 to 4 calibrated evaluation competencies with 5-level behavioral rubrics (L1-L5).

MANDATORY RULES:
1. SPECIFIC COMPETENCY NAMES: Never use generic/vague skill names like "projects", "work", "general", "experience", "coding", or "skills". Use precise technical or domain titles (e.g. "Distributed Data Processing", "API Design & Resiliency", "Production Troubleshooting & Latency").
2. BALANCED CATEGORIES: Include Core Technical, Domain & Architectural, Tooling & Frameworks, and Soft & Cultural.
3. PRIORITY TIERS: Exactly one or two P0 (Mandatory) skills. The others must be P1 (Core) or P2 (Secondary).
4. WEIGHTS: Integer percentages summing to EXACTLY 100%. P0 skills must have the highest weights.
5. 5-LEVEL RUBRICS (L1 to L5):
   - L1: Anti-patterns, lack of fundamentals.
   - L2: Developing / surface knowledge without deep failure awareness.
   - L3: Baseline proficient / production competence.
   - L4: Advanced architecture, trade-offs, and edge case resilience.
   - L5: Principal-level mastery, internal engine trade-offs, hardware bounds, cost vs SLAs.
"""

SKILL_SECTION_SYSTEM_PROMPT = """You are Candidly's Principal Technical Interview Architect.
Your task is to produce a rigorous, voice-optimized interview blueprint section for a single competency.

CRITICAL VOICE & QUALITY RULES (MANDATORY):
1. LENGTH: Every question and probe MUST be concise. Target under 35 words. HARD CEILING is 45 words.
2. ONE QUESTION PER TURN: Exactly ONE question mark (?) per question or probe. Never ask compound multi-part questions (e.g. "Tell me about X and how did you scale it?").
3. NO CODING ALOUD: Never ask the candidate to write code, type syntax, or recite code line by line. Focus on architecture, data structures, trade-offs, debugging, and operational behaviors.
4. SENIORITY-CALIBRATED STYLE:
   - Entry: Anchor MUST be a verbal problem-solving prompt or hypothetical scenario (e.g. "Suppose you receive a stream of ...; talk me through how you would..."). ZERO assumption of prior production experience. Do NOT ask "Walk me through a project where you in production...". Anchor Alt MUST be a simpler, more concrete version of the exact same scenario to assist a candidate who is stuck or says they have no experience.
   - Mid / Senior: Anchor is experience-based ("Walk me through a system or project where you..."). Anchor Alt is a hypothetical version if the candidate lacks direct experience with that specific scenario ("Suppose you were asked to design... how would you approach...?").
   - Lead: System boundaries, SLA vs infrastructure cost balance, incident leadership, and engineering standards.
5. ZERO EXPECTATION LEAKAGE: Never mention the rubric solution, buzzword, or desired technique in the question.
   - WRONG: "How did you use idempotency keys to avoid duplicate charges?" (Leaks the answer).
   - RIGHT: "Walk me through how you handled the payment service receiving the same charge request twice during a network retry."
6. RELEVANCE: Every expectation, question, and probe MUST strictly belong to the specified competency. NEVER introduce unrelated domain concepts (e.g. do NOT ask database SQL questions under an AI Engineering competency).
7. ANCHOR & ANCHOR_ALT:
   - For Entry level: Anchor is verbal problem-solving (hypothetical). Anchor Alt is a SIMPLER, MORE CONCRETE fallback version of the same scenario.
   - For Mid / Senior / Lead: Anchor is experience-based. Anchor Alt is a hypothetical version.
8. SELF-CONTAINED ESCALATION:
   - Escalation questions must be completely self-contained. Do NOT use dangling references like "in that project", "your database", or "those trade-offs" unless qualified by an explicit premise or gating condition.
9. PROBE TRIGGER & TECHNIQUE RULES:
   - Every probe MUST have a clear trigger_condition and target_expectation_indices.
   - A probe MUST NOT name a specific solution technique unless its trigger condition indicates the candidate already brought it up!
10. SPOKEN CONVERSATIONAL ENGLISH: No code blocks, markdown formatting, bullet points, asterisks, or quotes in question text.
11. CAPACITY LIMITS:
   - Core expectations: maximum 3 items.
   - Stretch expectations: maximum 2 items.
   - Total expectations: between 2 and 5 items.
12. NO PLACEHOLDERS OR READY-MADE QUESTIONS:
   - Every question must be generated from the job description, competency rubric, and seniority level.
   - Never emit generic placeholder questions that ask generally how someone handles challenges in a skill.
   - Never repeat the same probe wording with minor punctuation changes.
   - The anchor, anchor_alt, escalation, and at least 3 probes must all be present and distinct.
13. JOB DESCRIPTION GROUNDING:
   - Use the concrete systems, responsibilities, technologies, and constraints named in the job description.
   - Do not copy role-template expectation text verbatim; adapt it to the actual JD and rubric.
"""


def _competency_scenario_guidance(comp_name: str, comp_desc: str, rubric_summary: str) -> str:
    """Return a concrete scenario type for the competency without writing the question.

    This prevents the model from reusing one generic stream-processing scenario
    for every skill. The guidance describes the situation the question must
    exercise; the actual wording still comes from the JD and rubric.
    """
    text = f"{comp_name} {comp_desc} {rubric_summary}".lower()

    if any(term in text for term in ("debug", "testing", "test suite", "flaky", "quality assurance", "qa ")):
        return (
            "Present a failing or unreliable software behavior: for example, a service returns stale data after "
            "a deploy, a test passes locally but fails in CI, or a production bug appears under load. Ask how the "
            "candidate would isolate the cause, choose evidence, and validate a fix. The anchor_alt should ask what "
            "they would test or which checks they would use; never ask them to write code or tests."
        )
    if any(term in text for term in ("data structure", "algorithm", "problem solving", "complexity", "big-o")):
        return (
            "Present a concrete data-processing problem from the JD: records must be deduplicated, filtered, ranked, "
            "grouped, or processed under memory/time limits. Ask for the structure choice, complexity trade-offs, and "
            "how edge cases such as duplicates, missing values, or unbounded input affect the solution."
        )
    if any(term in text for term in ("concurrency", "thread", "process", "operating system", "synchronization", "tcp", "udp")):
        return (
            "Present a concurrency or OS-level behavior: two threads update shared state, a service becomes unresponsive "
            "under load, or a process/thread choice must be justified. Ask about synchronization, race conditions, "
            "deadlock symptoms, or the relevant protocol behavior rather than a generic data-stream question."
        )
    if any(term in text for term in ("database", "sql", "postgres", "query", "schema", "index")):
        return (
            "Present a data-store problem from the JD: a query slows down at scale, a schema or index choice is "
            "ambiguous, or consistency must be maintained during a migration. Ask for the diagnostic approach and "
            "the trade-offs between correctness, latency, and write cost."
        )
    if any(term in text for term in ("machine learning", " ml ", "artificial intelligence", " ai ", "llm", "inference", "model evaluation")):
        return (
            "Present an ML or AI behavior from the JD: retrieval quality degrades, a model overfits, evaluation results "
            "disagree with production, or inference latency exceeds the budget. Ask how the candidate would diagnose it "
            "and which metrics or experiments they would trust."
        )
    if any(term in text for term in ("api", "backend", "microservice", "rest", "event stream", "distributed")):
        return (
            "Present an API or backend failure mode from the JD: a client breaks after an API change, retries or timeouts "
            "cause duplicate work, or an event pipeline drops or reorders messages. Ask for the design or debugging "
            "approach and the trade-offs between compatibility, reliability, and latency."
        )
    if any(term in text for term in ("security", "authentication", "authorization", "owasp", "vulnerability")):
        return (
            "Present a concrete security concern from the JD, such as an authentication bypass, an over-permissive API, or "
            "untrusted input reaching a sensitive operation. Ask how the candidate would reason about the threat and the fix."
        )
    return (
        "Use a concrete system, failure, or artifact named in the job description or rubric. Ask for the candidate's "
        "approach, trade-offs, and how they would validate the result; do not ask a generic definition question."
    )


def build_skill_section_user_prompt(
    job_title: str,
    seniority_level: str,
    skill_info: Dict[str, Any],
    job_description: Optional[str] = None,
    recommended_expectations: int = 3,
) -> str:
    seniority_profile = get_seniority_profile(seniority_level)
    core_levels = ", ".join(seniority_profile["core_levels"])
    stretch_levels = ", ".join(seniority_profile["stretch_levels"])
    style_guide = seniority_profile["question_style_instructions"]

    rubrics = skill_info.get("rubrics", {})
    rubric_summary = "\n".join(
        f"  - {lvl.upper()}: {rubrics.get(lvl)}"
        for lvl in ["l2", "l3", "l4", "l5"]
        if rubrics.get(lvl)
    )
    if not rubric_summary:
        rubric_summary = f"  - L3: Proficient application of {skill_info.get('name')}\n  - L4: Advanced architecture and edge-case handling\n  - L5: Expert leadership, performance tuning, and failure mode design"

    expectation_bank = skill_info.get("expectation_bank", {})
    bank_lines = []
    if expectation_bank:
        for lvl in seniority_profile["core_levels"] + seniority_profile["stretch_levels"]:
            items = expectation_bank.get(lvl, [])
            for it in items[:2]:
                bank_lines.append(f"  - [{lvl}]: {it}")
    bank_summary = "\n".join(bank_lines) if bank_lines else "None provided (derive from rubrics)."

    jd_context = (
        f"\nJob Description & Target Stack (PRIMARY SOURCE OF TRUTH):\n{job_description[:6000]}\n"
        if job_description and job_description != "N/A"
        else ""
    )

    comp_name = skill_info.get('skill_name') or skill_info.get('name') or 'Technical Competency'
    comp_desc = skill_info.get('description') or f"Technical evaluation of {comp_name}"
    scenario_guidance = _competency_scenario_guidance(comp_name, comp_desc, rubric_summary)

    if seniority_profile['key'] == 'entry':
        anchor_instructions = """2. Anchor Question (kind='anchor'):
   - Verbal problem-solving or hypothetical scenario answerable with ZERO prior work experience.
   - The scenario MUST come from the Competency-Specific Scenario Guidance below. Do NOT default to a generic data-stream question when the competency is debugging, testing, APIs, databases, or another domain.
   - Never ask "Walk me through a project where you in production...".
   - Under 35 words. Exactly 1 question mark. Does NOT leak expected answers or ask to write code.
3. Anchor Alt Question (kind='anchor_alt'):
   - A SIMPLER, MORE CONCRETE stepping stone of that SAME competency-specific scenario, NOT a different trivial problem.
   - Used when the candidate is stuck, overwhelmed, or unsure where to start.
   - Trigger condition MUST be: "Candidate is stuck or unsure where to start".
   - Under 35 words. Exactly 1 question mark. Never ask the candidate to write code or tests."""
        escalation_instructions = """4. Escalation Question (kind='escalation'):
   - Follow-up scenario if candidate thoroughly solves the anchor.
   - For Entry: MUST escalate on depth, scale, or trade-offs within the SAME competency, NEVER low-level CPU cache misses, cache-line layout, lock-free primitives, or distributed consensus.
   - MUST be self-contained: avoid dangling references ("in that system", "your database") unless gated by a condition.
   - Under 35 words. Exactly 1 question mark."""
    else:
        anchor_instructions = """2. Anchor Question (kind='anchor'):
   - Primary experience-based scenario ("Walk me through a project or system where you..."), tied directly to the Competency-Specific Scenario Guidance and the job description.
   - Do NOT default to a generic data-stream question when the competency is debugging, testing, APIs, databases, or another domain.
   - Under 35 words. Exactly 1 question mark. Does NOT leak expected answers or ask to write code.
3. Anchor Alt Question (kind='anchor_alt'):
   - Hypothetical version if candidate lacks direct production experience with this competency-specific scenario.
   - Trigger condition MUST be: "Candidate indicates no direct experience with this scenario".
   - Under 35 words. Exactly 1 question mark. Never ask the candidate to write code or tests."""
        escalation_instructions = """4. Escalation Question (kind='escalation'):
   - Follow-up scenario if candidate thoroughly solves the anchor.
   - Escalates to higher scale, edge failure modes, concurrency, or operational trade-offs within the SAME competency.
   - MUST be self-contained: avoid dangling references ("in that system", "your database") unless gated by a condition.
   - Under 35 words. Exactly 1 question mark."""

    return f"""Role: {job_title}
Seniority Level: {seniority_profile['display_name']} ({seniority_level})
Competency to Assess: {comp_name}
Category: {skill_info.get('category', 'Core Technical')}
Competency Description: {comp_desc}
Priority Tier: {skill_info.get('priority', skill_info.get('priority_tier', 'P0'))}
Allocated Minutes: {skill_info.get('allocated_minutes', 4.0)}m
Target Core Levels: {core_levels} | Stretch Levels: {stretch_levels}
Question Style Guidance: {style_guide}
{jd_context}
Job Rubric Anchors for this Competency:
{rubric_summary}

Competency-Specific Scenario Guidance (use this scenario type; write your own question):
{scenario_guidance}

Calibration Reference Only (do NOT copy these verbatim; the JD and rubric are authoritative):
{bank_summary}

Requirements for this section:
1. Expectations (generate 2 to 5 items total: at most 3 'core', at most 2 'stretch'):
   - 'core' expectations must map to {core_levels}.
   - 'stretch' expectations must map to {stretch_levels}.
   - Must strictly assess '{skill_info.get('name') or comp_name}'. Zero irrelevant domain leakage.
   - Derive them from the job description responsibilities, the rubric anchors, and the seniority level.
{anchor_instructions}
{escalation_instructions}
5. Probes (generate 3 to 5 items, kind='probe'):
   - Each probe MUST have a clear 'trigger_condition' and 'target_expectation_indices' (0-based list).
   - A probe MUST NOT name a target technique unless the trigger condition says the candidate already mentioned it.
   - Under 35 words. Exactly 1 question mark.

QUALITY BAR:
- The anchor, anchor alt, escalation, and probes must be distinct and specific to this job description.
- NEVER return generic placeholders or repeated probe questions across slots.
- Do not copy role-template examples verbatim; tailor every question to the actual JD.

Return ONLY one valid JSON object with exactly these top-level keys:
{{
  "skill_name": "{comp_name}",
  "expectations": [
    {{"expectation_text": "...", "source_rubric_level": "L3", "importance": "core"}},
    {{"expectation_text": "...", "source_rubric_level": "L4", "importance": "stretch"}}
  ],
  "anchor_question": {{"question_role": "anchor", "question_text": "...", "trigger_condition": null, "target_expectation_indices": [0]}},
  "anchor_alt_question": {{"question_role": "anchor_alt", "question_text": "...", "trigger_condition": "...", "target_expectation_indices": [0]}},
  "escalation_question": {{"question_role": "escalation", "question_text": "...", "trigger_condition": "...", "target_expectation_indices": [0]}},
  "probes": [
    {{"question_role": "probe", "question_text": "...", "trigger_condition": "...", "target_expectation_indices": [0, 1]}},
    {{"question_role": "probe", "question_text": "...", "trigger_condition": "...", "target_expectation_indices": [1]}},
    {{"question_role": "probe", "question_text": "...", "trigger_condition": "...", "target_expectation_indices": [0]}}
  ]
}}

All four question groups (anchor, anchor_alt, escalation, probes) are mandatory.
"""


def build_repair_user_prompt(
    original_draft: Dict[str, Any],
    validation_errors: List[str],
) -> str:
    return f"""The previous interview blueprint section for '{original_draft.get('skill_name')}' failed automated validation with the following errors:

{chr(10).join(f"- {err}" for err in validation_errors)}

Previous Output:
{json.dumps(original_draft, indent=2)}

Please revise the section to fix ALL listed errors:
- Return the complete section with every required key: skill_name, expectations, anchor_question, anchor_alt_question, escalation_question, and probes.
- Return 3 to 5 distinct probes with trigger_condition and target_expectation_indices.
- Ensure EVERY question and probe has length under 35 words (never > 45 words).
- Ensure EVERY question and probe contains EXACTLY ONE question mark (?).
- Ensure an 'anchor_alt_question' is included for hypothetical scenarios.
- Ensure escalations are self-contained without unresolved pronouns.
- Ensure probes do not leak techniques unless mentioned in their trigger conditions.
- For technique-leakage errors, do NOT keep a tool or technique name in a probe unless its trigger explicitly says the candidate already mentioned that exact technique. Prefer removing tool names (for example, "flame graphs", "APM", "STAR") from the probe and asking what evidence or approach the candidate would use instead.
- Ensure core expectations <= 3 and stretch expectations <= 2.
- If the candidate draft used 'description', 'level', or 'stretch', convert them to 'expectation_text', 'source_rubric_level', and 'importance'.
- Do NOT insert generic placeholder questions. Every question must be specific to the job description and competency.
- Remove all markdown formatting or code syntax.

Return the complete revised JSON strictly matching the canonical schema.
"""
