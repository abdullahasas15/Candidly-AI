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
"""


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
            for it in items[:3]:
                bank_lines.append(f"  - [{lvl}]: {it}")
    bank_summary = "\n".join(bank_lines) if bank_lines else "None provided (derive from rubrics)."

    jd_context = f"\nTarget Job Stack & Context:\n{job_description[:600]}\n" if job_description and job_description != "N/A" else ""

    comp_name = skill_info.get('skill_name') or skill_info.get('name') or 'Technical Competency'
    comp_desc = skill_info.get('description') or f"Technical evaluation of {comp_name}"

    if seniority_profile['key'] == 'entry':
        anchor_instructions = """2. Anchor Question (kind='anchor'):
   - Verbal problem-solving or hypothetical scenario answerable with ZERO prior work experience (e.g. "Suppose you receive a stream of ...; talk me through the data structures and complexity trade-offs you would consider.").
   - Never ask "Walk me through a project where you in production...".
   - Under 35 words. Exactly 1 question mark. Does NOT leak expected answers or ask to write code.
3. Anchor Alt Question (kind='anchor_alt'):
   - A SIMPLER, MORE CONCRETE stepping stone of that SAME scenario (e.g. "Start simple: how would you count how often each error code appears?"), NOT a different trivial problem.
   - Used when the candidate is stuck, overwhelmed, or unsure where to start.
   - Trigger condition MUST be: "Candidate is stuck or unsure where to start".
   - Under 35 words. Exactly 1 question mark."""
        escalation_instructions = """4. Escalation Question (kind='escalation'):
   - Follow-up scenario if candidate thoroughly solves the anchor.
   - For Entry: MUST escalate on algorithmic depth or trade-offs (e.g. space vs time constraints, streaming windowing, or handling unexpected data skews), NEVER low-level CPU cache misses, cache-line layout, lock-free primitives, or distributed consensus.
   - MUST be self-contained: avoid dangling references ("in that system", "your database") unless gated by a condition.
   - Under 35 words. Exactly 1 question mark."""
    else:
        anchor_instructions = """2. Anchor Question (kind='anchor'):
   - Primary experience-based scenario ("Walk me through a project or system where you...").
   - Under 35 words. Exactly 1 question mark. Does NOT leak expected answers or ask to write code.
3. Anchor Alt Question (kind='anchor_alt'):
   - Hypothetical version if candidate lacks direct production experience with this scenario (e.g. "Suppose you were asked to design... how would you approach...?").
   - Trigger condition MUST be: "Candidate indicates no direct experience with this scenario".
   - Under 35 words. Exactly 1 question mark."""
        escalation_instructions = """4. Escalation Question (kind='escalation'):
   - Follow-up scenario if candidate thoroughly solves the anchor.
   - Escalates to higher scale, edge failure modes, distributed concurrency, or operational trade-offs.
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

Role Template Expectation Bank (Use as primary base and tailor to JD stack):
{bank_summary}

Requirements for this section:
1. Expectations (generate 2 to 4 items total: at most 3 'core', at most 2 'stretch'):
   - 'core' expectations must map to {core_levels}.
   - 'stretch' expectations must map to {stretch_levels}.
   - Must strictly assess '{skill_info.get('name')}'. Zero irrelevant domain leakage.
{anchor_instructions}
{escalation_instructions}
5. Probes (generate 3 to 5 items, kind='probe'):
   - Each probe MUST have a clear 'trigger_condition' and 'target_expectation_indices' (0-based list).
   - A probe MUST NOT name a target technique unless the trigger condition says the candidate already mentioned it.
   - Under 35 words. Exactly 1 question mark.

Return ONLY valid JSON strictly matching the SkillSectionContent schema.
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
- Ensure EVERY question and probe has length under 35 words (never > 45 words).
- Ensure EVERY question and probe contains EXACTLY ONE question mark (?).
- Ensure an 'anchor_alt_question' is included for hypothetical scenarios.
- Ensure escalations are self-contained without unresolved pronouns.
- Ensure probes do not leak techniques unless mentioned in their trigger conditions.
- Ensure core expectations <= 3 and stretch expectations <= 2.
- Remove all markdown formatting or code syntax.

Return the complete revised JSON strictly matching the schema.
"""
