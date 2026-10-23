"""Plan Schema and Deterministic Skeleton Builder for Candidly Live Interviewer.

Defines the contract for the pre-interview script plan and creates deterministic
PlanSkeleton objects without LLM arithmetic.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator

from backend.app.services.interview_v2.context_hydrator import HydratedInterviewContext


def clean_role_title_for_speech(role: Optional[str]) -> str:
    """Normalize role titles for spoken text so hyphens/dashes are never spoken as 'minus'."""
    if not role:
        return "Software Engineer"
    cleaned = str(role)
    cleaned = re.sub(r"\s*[\-–—_]+\s*", " ", cleaned).strip()
    cleaned = re.sub(r"\bSDE\s*I\b", "Software Development Engineer 1", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*II\b", "Software Development Engineer 2", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*III\b", "Software Development Engineer 3", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*1\b", "Software Development Engineer 1", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*2\b", "Software Development Engineer 2", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\s*3\b", "Software Development Engineer 3", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSDE\b", "Software Development Engineer", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bSWE\b", "Software Engineer", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


class PlanSlot(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    index: int = 0
    stage: str = Field(..., description="greeting | background | technical | custom_screening | candidate_qa | closing")
    kind: str = Field(..., description="greeting | background | anchor | anchor_alt | probe | resume_probe | custom | candidate_qa | closing")
    skill_id: Optional[str] = None
    skill_name: Optional[str] = None
    weight_percentage: Optional[float] = None
    question_text: str = Field(..., description="Spoken text to be delivered over voice TTS")
    expected_key_points: List[str] = Field(default_factory=list, description="Private evaluation hints (never sent to client)")
    rubric_anchor_ids: List[str] = Field(default_factory=list, description="Rubric anchor references")
    followup_probes: List[str] = Field(default_factory=list, description="Prepared follow-up probes")
    estimated_seconds: int = 90
    follow_up_depth_allowed: int = 2
    is_required: bool = True
    parent_question_id: Optional[str] = None
    variant_group: Optional[str] = None
    source: str = Field("template", description="blueprint | resume | personalization | template")
    source_refs: List[str] = Field(default_factory=list)


class ScriptPlan(BaseModel):
    schema_version: str = "interview_script.v1"
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    application_id: str
    job_id: str
    blueprint_id: Optional[str] = None
    blueprint_version: Optional[int] = None
    input_hash: str
    prompt_version: str = "interview_plan.v1"
    model: str = "deterministic_skeleton"
    duration_minutes: int = 20
    question_order: List[str] = Field(default_factory=list)
    coverage_requirements: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = Field("draft", description="draft | approved | superseded")
    slots: List[PlanSlot] = Field(default_factory=list)

    @model_validator(mode="after")
    def populate_question_order(self) -> "ScriptPlan":
        if self.slots and not self.question_order:
            self.question_order = [s.id for s in self.slots if s.kind != "anchor_alt"]
        return self

    def get_slot_by_id(self, slot_id: str) -> Optional[PlanSlot]:
        for s in self.slots:
            if s.id == slot_id:
                return s
        return None

    def get_ordered_slots(self) -> List[PlanSlot]:
        id_to_slot = {s.id: s for s in self.slots}
        if self.question_order:
            ordered = []
            for q_id in self.question_order:
                if q_id in id_to_slot and id_to_slot[q_id].kind != "anchor_alt":
                    ordered.append(id_to_slot[q_id])
            if ordered:
                return ordered
        return [s for s in sorted(self.slots, key=lambda s: s.index) if s.kind != "anchor_alt"]


def compute_plan_input_hash(context: HydratedInterviewContext, prompt_version: str) -> str:
    """Compute SHA-256 input hash for idempotent plan caching."""
    canonical_data = {
        "prompt_version": prompt_version,
        "job_id": context.job_id,
        "application_id": context.application_id,
        "blueprint_id": str(context.blueprint_id or ""),
        "blueprint_version": str(context.blueprint_version or ""),
        "department": context.department or "",
        "interviewer_tone": context.interviewer_tone or "",
        "job_title": context.job_title,
        "job_description": context.job_description or "",
        "seniority_level": context.seniority_level,
        "duration_minutes": context.interview_duration_mins,
        "max_followup_depth": context.max_followup_depth,
        "candidate_first_name": context.candidate_first_name,
        "self_reported_experience_years": context.self_reported_experience_years,
        "fit_pitch": context.fit_pitch or "",
        "resume_work_experience": context.resume_work_experience,
        "resume_projects": context.resume_projects,
        "resume_skills": context.resume_skills,
        "resume_education": context.resume_education,
        "resume_certifications": context.resume_certifications,
        "skills": [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "category": s.get("category") or "",
                "target_level": s.get("target_level_max") or s.get("target_level_min") or s.get("target_level") or "L3-L4",
                "weight_percentage": s.get("weight_percentage"),
                "priority_tier": s.get("priority_tier"),
                "rubric_l1": s.get("rubric_l1"),
                "rubric_l2": s.get("rubric_l2"),
                "rubric_l3": s.get("rubric_l3"),
                "rubric_l4": s.get("rubric_l4"),
                "rubric_l5": s.get("rubric_l5"),
            }
            for s in context.skills
        ],
        "custom_questions": [
            {
                "id": cq.get("id"),
                "question_text": cq.get("question_text"),
                "is_required": cq.get("is_required", True),
            }
            for cq in context.custom_questions
        ],
        "blueprint_sections": context.blueprint_sections,
        "personalization_intro_hook": context.personalization_intro_hook or "",
        "personalization_probes": context.personalization_probes,
        "claims_to_verify": context.claims_to_verify,
    }
    raw = json.dumps(canonical_data, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_plan_skeleton(context: HydratedInterviewContext) -> ScriptPlan:
    """Build a deterministic, validated PlanSkeleton with stable IDs and code-calculated budgets."""
    duration_mins = context.interview_duration_mins or 20
    total_seconds = duration_mins * 60

    # Fixed reservations
    greeting_sec = 60
    intro_sec = 120
    qa_sec = 180
    closing_sec = 60
    buffer_sec = 60
    reserved_sec = greeting_sec + intro_sec + qa_sec + closing_sec + buffer_sec

    usable_sec = max(180, total_seconds - reserved_sec)

    slots: List[PlanSlot] = []
    slot_idx = 0

    # 1. Greeting slot
    clean_title = clean_role_title_for_speech(context.job_title)
    
    # Extract topics for agenda
    topics = []
    if context.blueprint_sections:
        for sec in context.blueprint_sections:
            if sec.get("section_type") == "skill":
                topics.append(sec.get("skill_name") or sec.get("title") or "Technical Skills")
    if not topics and context.skills:
        for s in context.skills:
            if s.get("priority_tier") == "P0" or (s.get("weight_percentage") or 0) >= 15:
                topics.append(s.get("name", "Technical Topic"))
    if not topics:
        topics = ["your technical background and core problem-solving experience"]

    if len(topics) > 1:
        agenda_str = ", ".join(topics[:-1]) + f", and {topics[-1]}"
    else:
        agenda_str = topics[0]

    first_name = context.candidate_first_name or "there"
    greeting_text = (
        f"Hi {first_name}! Welcome to your interview for the {clean_title} role. "
        f"Today we will cover {agenda_str}, followed by time for any questions you have for us. "
        "Does that sound good to you?"
    )

    greeting_slot = PlanSlot(
        id=str(uuid.uuid4()),
        index=slot_idx,
        stage="greeting",
        kind="greeting",
        question_text=greeting_text,
        expected_key_points=["Candidate acknowledges readiness to proceed"],
        estimated_seconds=greeting_sec,
        follow_up_depth_allowed=0,
        is_required=True,
        source="template",
        source_refs=["job:job_title"],
    )
    slots.append(greeting_slot)
    slot_idx += 1

    # 2. Background slot
    intro_text = (
        context.personalization_intro_hook
        or "To start off, could you please introduce yourself, tell me about your background, and share some highlights from your key projects and experiences?"
    )
    intro_slot = PlanSlot(
        id=str(uuid.uuid4()),
        index=slot_idx,
        stage="background",
        kind="background",
        question_text=intro_text,
        expected_key_points=[
            "Candidate self-introduction",
            "Recent project or work highlights",
            "Technical stack overview",
        ],
        estimated_seconds=intro_sec,
        follow_up_depth_allowed=min(1, context.max_followup_depth),
        is_required=True,
        source="personalization" if context.personalization_intro_hook else "template",
        source_refs=["resume:work_experience", "candidate:fit_pitch"],
    )
    slots.append(intro_slot)
    slot_idx += 1

    # 3. Technical & Custom Screening slots
    # Sort skills by priority (P0 first, then P1, then P2) and weight percentage descending
    sorted_skills = sorted(
        context.skills,
        key=lambda s: (
            0 if s.get("priority_tier") == "P0" else (1 if s.get("priority_tier") == "P1" else 2),
            -float(s.get("weight_percentage") or 0.0),
        )
    )

    total_weight = sum(float(s.get("weight_percentage") or 0.0) for s in sorted_skills) or 100.0

    coverage_reqs = []

    # Map blueprint sections by skill name / skill id if present
    bp_section_map = {}
    if context.blueprint_sections:
        for sec in context.blueprint_sections:
            if sec.get("section_type") == "skill":
                name = sec.get("skill_name") or sec.get("title")
                if name:
                    bp_section_map[name.lower()] = sec
                if sec.get("skill_id"):
                    bp_section_map[sec["skill_id"]] = sec

    for skill in sorted_skills:
        s_id = skill.get("id")
        s_name = skill.get("name") or "Core Technical"
        weight = float(skill.get("weight_percentage") or 0.0)
        tier = skill.get("priority_tier") or "P0"

        # Time allocation
        skill_sec = max(60, int(usable_sec * (weight / total_weight))) if total_weight > 0 else 180

        # Look up blueprint section
        bp_sec = bp_section_map.get(s_name.lower()) or (bp_section_map.get(s_id) if s_id else None)

        anchor_text = None
        anchor_alt_text = None
        expected_points = []
        prepared_probes = []

        if bp_sec:
            bp_qs = bp_sec.get("questions") or []
            bp_exps = bp_sec.get("expectations") or []
            for exp in bp_exps:
                exp_text = exp.get("expectation_text")
                if exp_text:
                    expected_points.append(exp_text)

            for q in bp_qs:
                role = q.get("question_role")
                q_text = q.get("question_text")
                if role == "anchor" and not anchor_text and q_text:
                    anchor_text = q_text
                elif role == "anchor_alt" and not anchor_alt_text and q_text:
                    anchor_alt_text = q_text
                elif role in ("probe", "escalation") and q_text:
                    prepared_probes.append(q_text)

        # Fallback anchor text if no blueprint
        if not anchor_text:
            rubric_l3 = skill.get("rubric_l3") or skill.get("rubric_l4")
            if rubric_l3:
                anchor_text = f"In your work with {s_name}, how have you approached {rubric_l3[:60].strip()}?"
            else:
                anchor_text = f"Could you walk me through your hands-on experience and architectural approach when working with {s_name}?"

        # Include candidate personalization probes if available
        custom_probe = context.personalization_probes.get(s_name) or (context.personalization_probes.get(s_id) if s_id else None)
        if custom_probe and custom_probe not in prepared_probes:
            prepared_probes.insert(0, custom_probe)

        if not expected_points:
            expected_points = [
                f"Demonstrates production-level proficiency in {s_name}",
                "Explains trade-offs and architectural considerations",
            ]

        # Record coverage requirements
        coverage_reqs.append({
            "skill_id": s_id,
            "skill_name": s_name,
            "priority_tier": tier,
            "weight_percentage": weight,
            "target_expectations": expected_points,
        })

        anchor_slot_id = str(uuid.uuid4())
        tech_slot = PlanSlot(
            id=anchor_slot_id,
            index=slot_idx,
            stage="technical",
            kind="anchor",
            skill_id=s_id,
            skill_name=s_name,
            weight_percentage=weight,
            question_text=anchor_text,
            expected_key_points=expected_points,
            followup_probes=prepared_probes,
            estimated_seconds=skill_sec,
            follow_up_depth_allowed=context.max_followup_depth,
            is_required=(tier == "P0"),
            variant_group=f"{s_name}_variant" if anchor_alt_text else None,
            source="blueprint" if bp_sec else "template",
            source_refs=[f"job_skill:{s_name}"],
        )
        slots.append(tech_slot)
        slot_idx += 1

        # If blueprint provided anchor_alt, add optional variant slot
        if anchor_alt_text:
            alt_slot = PlanSlot(
                id=str(uuid.uuid4()),
                index=slot_idx,
                stage="technical",
                kind="anchor_alt",
                skill_id=s_id,
                skill_name=s_name,
                weight_percentage=weight,
                question_text=anchor_alt_text,
                expected_key_points=expected_points,
                followup_probes=prepared_probes,
                estimated_seconds=skill_sec,
                follow_up_depth_allowed=context.max_followup_depth,
                is_required=False,
                parent_question_id=anchor_slot_id,
                variant_group=f"{s_name}_variant",
                source="blueprint",
                source_refs=[f"job_skill:{s_name}:alt"],
            )
            slots.append(alt_slot)
            slot_idx += 1

    # Custom screening questions
    for cq in context.custom_questions:
        cq_text = cq.get("question_text")
        if not cq_text:
            continue
        cq_slot = PlanSlot(
            id=str(uuid.uuid4()),
            index=slot_idx,
            stage="custom_screening",
            kind="custom",
            skill_id=None,
            skill_name="Custom Screening",
            weight_percentage=None,
            question_text=cq_text,
            expected_key_points=[f"Candidate addresses: {cq_text[:60]}"],
            followup_probes=[],
            estimated_seconds=60,
            follow_up_depth_allowed=1,
            is_required=bool(cq.get("is_required", True)),
            source="template",
            source_refs=[f"job_custom_question:{cq.get('id', slot_idx)}"],
        )
        slots.append(cq_slot)
        slot_idx += 1

    # 4. Candidate Q&A slot
    qa_text = "Now I would love to open up the floor to you. What questions or thoughts do you have for us regarding the team, our technical stack, or this role?"
    qa_slot = PlanSlot(
        id=str(uuid.uuid4()),
        index=slot_idx,
        stage="candidate_qa",
        kind="candidate_qa",
        question_text=qa_text,
        expected_key_points=["Candidate asks informed questions about the role or team"],
        estimated_seconds=qa_sec,
        follow_up_depth_allowed=0,
        is_required=True,
        source="template",
        source_refs=["job:candidate_qa"],
    )
    slots.append(qa_slot)
    slot_idx += 1

    # 5. Closing slot
    closing_text = "Thank you so much for taking the time to speak with me today. Our team will review your session and be in touch with next steps shortly. Have a wonderful rest of your day!"
    closing_slot = PlanSlot(
        id=str(uuid.uuid4()),
        index=slot_idx,
        stage="closing",
        kind="closing",
        question_text=closing_text,
        expected_key_points=["Candidate acknowledges closing remarks"],
        estimated_seconds=closing_sec,
        follow_up_depth_allowed=0,
        is_required=True,
        source="template",
        source_refs=["system:closing"],
    )
    slots.append(closing_slot)
    slot_idx += 1

    input_hash = compute_plan_input_hash(context, "interview_plan.v1")

    return ScriptPlan(
        plan_id=str(uuid.uuid4()),
        application_id=context.application_id,
        job_id=context.job_id,
        blueprint_id=context.blueprint_id,
        blueprint_version=context.blueprint_version,
        input_hash=input_hash,
        prompt_version="interview_plan.v1",
        model="deterministic_skeleton",
        duration_minutes=duration_mins,
        question_order=[s.id for s in slots if s.kind != "anchor_alt"],
        coverage_requirements=coverage_reqs,
        status="draft",
        slots=slots,
    )


def validate_script_plan(plan: ScriptPlan, skeleton: ScriptPlan) -> List[str]:
    """Validate that plan has exact 1:1 match with skeleton without added, missing, or altered slots."""
    errors: List[str] = []

    skel_slots = {s.id: s for s in skeleton.slots}
    plan_slots = {s.id: s for s in plan.slots}

    if set(skel_slots.keys()) != set(plan_slots.keys()):
        missing = set(skel_slots.keys()) - set(plan_slots.keys())
        added = set(plan_slots.keys()) - set(skel_slots.keys())
        if missing:
            errors.append(f"Plan is missing skeleton slot IDs: {sorted(missing)}")
        if added:
            errors.append(f"Plan has illegal unexpected slot IDs: {sorted(added)}")

    # Check stages
    greetings = [s for s in plan.slots if s.stage == "greeting"]
    if len(greetings) != 1:
        errors.append(f"Plan must have exactly 1 greeting slot, found {len(greetings)}")

    backgrounds = [s for s in plan.slots if s.stage == "background"]
    if len(backgrounds) != 1:
        errors.append(f"Plan must have exactly 1 background slot, found {len(backgrounds)}")

    qas = [s for s in plan.slots if s.stage == "candidate_qa"]
    if len(qas) != 1:
        errors.append(f"Plan must have exactly 1 candidate_qa slot, found {len(qas)}")

    closings = [s for s in plan.slots if s.stage == "closing"]
    if len(closings) != 1:
        errors.append(f"Plan must have exactly 1 closing slot, found {len(closings)}")

    # Check question text quality
    for s in plan.slots:
        t = (s.question_text or "").strip()
        if not t:
            errors.append(f"Slot {s.id} ({s.stage}) has empty question text")
            continue
        # Check rubric/leakage words
        t_lower = t.lower()
        if "rubric" in t_lower or "l1" in t_lower or "l4" in t_lower or "l5" in t_lower:
            errors.append(f"Slot {s.id} leaked rubric keywords: '{t}'")

    return errors
