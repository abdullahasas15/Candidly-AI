"""Service-layer Context Hydration for Candidly Live Interviewer.

Queries real SQLAlchemy models and produces a sanitized, PII-stripped
HydratedInterviewContext used for:
1. Offline plan generation (full sanitized context via to_generation_prompt_vars)
2. Live turn selection (compact summary under 400-600 tokens via to_live_turn_summary)
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models import (
    JobPosting,
    JobApplication,
    JobSkill,
    JobCertification,
    JobCustomQuestion,
    InterviewBlueprint,
    BlueprintSection,
    BlueprintExpectation,
    BlueprintQuestion,
    CandidateResume,
    CandidatePersonalization,
)

logger = logging.getLogger(__name__)


@dataclass
class HydratedInterviewContext:
    # Application & Candidate Info (Sanitized - no email, phone, address, salary)
    application_id: str
    job_id: str
    candidate_full_name: str
    candidate_first_name: str
    self_reported_experience_years: float = 0.0
    fit_pitch: Optional[str] = None
    screening_answers: List[Dict[str, Any]] = field(default_factory=list)

    # Resume Derived (Safe Structured Data)
    resume_work_experience: List[Dict[str, Any]] = field(default_factory=list)
    resume_projects: List[Dict[str, Any]] = field(default_factory=list)
    resume_skills: Dict[str, List[str]] = field(default_factory=dict)
    resume_education: List[Dict[str, Any]] = field(default_factory=list)
    resume_certifications: List[Dict[str, Any]] = field(default_factory=list)
    resume_raw_summary: Optional[str] = None

    # Candidate Personalization (from CandidatePersonalization model)
    personalization_intro_hook: Optional[str] = None
    personalization_probes: Dict[str, str] = field(default_factory=dict)
    claims_to_verify: List[str] = field(default_factory=list)

    # Job & Policy Info
    job_title: str = "Software Engineer"
    seniority_level: str = "mid"
    department: str = "Engineering"
    job_description: str = ""
    interview_duration_mins: int = 20
    max_followup_depth: int = 2
    interviewer_tone: str = "Direct, technical, tech-lead caliber; warm but concise."

    # Competencies & Rubrics
    skills: List[Dict[str, Any]] = field(default_factory=list)
    certifications: List[Dict[str, Any]] = field(default_factory=list)
    custom_questions: List[Dict[str, Any]] = field(default_factory=list)

    # Blueprint Info (if present)
    blueprint_id: Optional[str] = None
    blueprint_version: Optional[int] = None
    blueprint_sections: List[Dict[str, Any]] = field(default_factory=list)

    def to_generation_prompt_vars(self) -> Dict[str, Any]:
        """Produce sanitized variables for pre-interview script writing templates."""
        cand_dict = {
            "name": self.candidate_first_name,
            "years_of_experience": self.self_reported_experience_years,
            "fit_pitch": self.fit_pitch,
            "work_experience": self.resume_work_experience[:5],
            "projects": self.resume_projects[:4],
            "skills": self.resume_skills,
            "education": self.resume_education[:3],
            "certifications": self.resume_certifications[:4],
        }

        job_dict = {
            "title": self.job_title,
            "seniority": self.seniority_level,
            "department": self.department,
            "description": self.job_description[:1200] if self.job_description else "",
            "duration_minutes": self.interview_duration_mins,
            "max_followup_depth": self.max_followup_depth,
            "interviewer_tone": self.interviewer_tone,
        }

        competencies_list = []
        for s in self.skills:
            competencies_list.append({
                "skill_id": s.get("id"),
                "name": s.get("name"),
                "category": s.get("category"),
                "priority_tier": s.get("priority_tier"),
                "weight_percentage": s.get("weight_percentage"),
                "target_level": s.get("target_level_max") or s.get("target_level_min") or "L3-L4",
                "rubric": {
                    "L1": s.get("rubric_l1"),
                    "L2": s.get("rubric_l2"),
                    "L3": s.get("rubric_l3"),
                    "L4": s.get("rubric_l4"),
                    "L5": s.get("rubric_l5"),
                },
            })

        personalization_dict = {
            "intro_hook": self.personalization_intro_hook,
            "probes": self.personalization_probes,
            "claims_to_verify": self.claims_to_verify,
        }

        constraints_dict = {
            "max_words_per_question": 40,
            "questions_per_slot": 1,
            "disallowed_phrases": [
                "as mentioned in your resume",
                "according to your CV",
                "the rubric requires",
                "level 4 expectation",
            ],
            "format": "pure voice conversation; natural cadence; no leaked scoring guidelines",
        }

        return {
            "candidate_profile_json": json.dumps(cand_dict, indent=2),
            "job_profile_json": json.dumps(job_dict, indent=2),
            "competencies_json": json.dumps(competencies_list, indent=2),
            "personalization_json": json.dumps(personalization_dict, indent=2),
            "constraints_json": json.dumps(constraints_dict, indent=2),
        }

    def to_live_turn_summary(self) -> str:
        """Produce a dense, compact summary under 400-600 tokens for live turns."""
        top_skills = []
        for s in self.skills:
            if s.get("priority_tier") == "P0" or (s.get("weight_percentage") or 0) >= 20:
                top_skills.append(s.get("name", ""))
        skill_str = ", ".join(top_skills[:5]) if top_skills else "Core Technical"

        companies = []
        for w in self.resume_work_experience[:3]:
            role = w.get("role") or w.get("title") or "Engineer"
            comp = w.get("company") or w.get("organization") or ""
            if comp:
                companies.append(f"{role} at {comp}")
            else:
                companies.append(role)
        comp_str = "; ".join(companies) if companies else "Relevant Engineering Experience"

        return (
            f"Candidate: {self.candidate_first_name} ({self.self_reported_experience_years:.1f} yrs exp). "
            f"Background: {comp_str}. "
            f"Applying for: {self.job_title} ({self.seniority_level.title()}, {self.interview_duration_mins}m). "
            f"Key Focus Skills: {skill_str}. Tone: {self.interviewer_tone}"
        )

    def to_live_candidate_dossier(self) -> Dict[str, Any]:
        """Compact candidate dossier (~250-350 tokens) for the live selector:
        who they are, what they built, and which claims to verify. This is the
        grounding the interviewer needs to probe the candidate's REAL work."""
        work = []
        for w in self.resume_work_experience[:3]:
            role = w.get("role") or w.get("title") or "Engineer"
            comp = w.get("company") or w.get("organization") or ""
            highlight = ""
            highlights = w.get("highlights") or []
            if highlights and isinstance(highlights[0], str):
                highlight = highlights[0][:120]
            entry = f"{role} at {comp}" if comp else role
            if highlight:
                entry += f": {highlight}"
            work.append(entry)

        projects = []
        for p in self.resume_projects[:3]:
            name = p.get("name") or p.get("title") or ""
            if not name:
                continue
            techs = p.get("technologies") or []
            stack = f" ({', '.join(str(t) for t in techs[:4])})" if techs else ""
            desc = (p.get("description") or "")[:140]
            projects.append(f"{name}{stack}: {desc}" if desc else f"{name}{stack}")

        return {
            "name": self.candidate_first_name,
            "years_of_experience": self.self_reported_experience_years,
            "work_experience": work,
            "notable_projects": projects,
            "claims_to_verify": [str(c) for c in (self.claims_to_verify or [])[:4]],
        }


def _safe_parse_resume_data(resume: Optional[CandidateResume]) -> Dict[str, Any]:
    """Extract structured resume fields safely handling string or dict encodings."""
    if not resume:
        return {}

    raw_data = getattr(resume, "parsed_structured_data", None)
    if isinstance(raw_data, str):
        try:
            parsed = json.loads(raw_data)
        except Exception:
            parsed = {}
    elif isinstance(raw_data, dict):
        parsed = raw_data
    else:
        parsed = {}

    work_exp = parsed.get("work_experience") or parsed.get("experience") or parsed.get("companies") or []
    if isinstance(work_exp, list):
        clean_exp = []
        for item in work_exp:
            if isinstance(item, dict):
                clean_exp.append({
                    "company": item.get("company") or item.get("name") or "",
                    "role": item.get("role") or item.get("title") or "",
                    "duration": item.get("duration") or item.get("dates") or "",
                    "highlights": item.get("highlights") or item.get("responsibilities") or item.get("description") or [],
                })
            elif isinstance(item, str):
                clean_exp.append({"role": item, "company": "", "duration": "", "highlights": []})
    else:
        clean_exp = []

    projects = parsed.get("projects") or []
    if isinstance(projects, list):
        clean_proj = []
        for p in projects:
            if isinstance(p, dict):
                clean_proj.append({
                    "name": p.get("name") or p.get("title") or "",
                    "description": p.get("description") or p.get("summary") or "",
                    "technologies": p.get("technologies") or p.get("skills") or [],
                })
            elif isinstance(p, str):
                clean_proj.append({"name": p, "description": "", "technologies": []})
    else:
        clean_proj = []

    skills = parsed.get("skills") or {}
    clean_skills: Dict[str, List[str]] = {}
    if isinstance(skills, dict):
        for k, v in skills.items():
            clean_skills[str(k)] = [str(x) for x in v] if isinstance(v, list) else [str(v)]
    elif isinstance(skills, list):
        clean_skills["General"] = [str(s) for s in skills]

    education = parsed.get("education") or parsed.get("degrees") or []
    clean_edu = []
    if isinstance(education, list):
        for ed in education:
            if isinstance(ed, dict):
                clean_edu.append({
                    "degree": ed.get("degree") or ed.get("degree_level") or "",
                    "institution": ed.get("institution") or ed.get("school") or ed.get("university") or "",
                    "major": ed.get("major") or ed.get("field_of_study") or "",
                    "grad_year": ed.get("grad_year") or ed.get("year") or "",
                })
            elif isinstance(ed, str):
                clean_edu.append({"degree": ed, "institution": "", "major": "", "grad_year": ""})

    certs = parsed.get("certifications") or []
    clean_certs = []
    if isinstance(certs, list):
        for c in certs:
            if isinstance(c, dict):
                clean_certs.append({
                    "name": c.get("name") or c.get("title") or "",
                    "issuer": c.get("issuer") or c.get("issuing_org") or "",
                })
            elif isinstance(c, str):
                clean_certs.append({"name": c, "issuer": ""})

    return {
        "work_experience": clean_exp,
        "projects": clean_proj,
        "skills": clean_skills,
        "education": clean_edu,
        "certifications": clean_certs,
        "parsed_text": getattr(resume, "parsed_text", "") or "",
    }


async def hydrate_interview_context(
    db: AsyncSession,
    job_id_or_app_id: str,
    application_id: Optional[str] = None,
) -> HydratedInterviewContext:
    """Hydrate context from real database models for job_id and application_id."""
    if application_id is None:
        actual_app_id = job_id_or_app_id
        app_stmt = (
            select(JobApplication)
            .where(JobApplication.id == actual_app_id)
            .options(
                selectinload(JobApplication.resume),
                selectinload(JobApplication.personalization),
            )
        )
        app_res = await db.execute(app_stmt)
        application = app_res.scalar_one_or_none()
        if not application:
            raise ValueError(f"JobApplication not found with id: {actual_app_id}")
        actual_job_id = application.job_id
    else:
        actual_job_id = job_id_or_app_id
        actual_app_id = application_id
        app_stmt = (
            select(JobApplication)
            .where(JobApplication.id == actual_app_id)
            .options(
                selectinload(JobApplication.resume),
                selectinload(JobApplication.personalization),
            )
        )
        app_res = await db.execute(app_stmt)
        application = app_res.scalar_one_or_none()
        if not application:
            raise ValueError(f"JobApplication not found with id: {actual_app_id}")

    # 1. Query JobPosting with skills, certifications, custom questions, and active blueprint
    job_stmt = (
        select(JobPosting)
        .where(JobPosting.id == actual_job_id)
        .options(
            selectinload(JobPosting.skills),
            selectinload(JobPosting.certifications),
            selectinload(JobPosting.custom_questions),
            selectinload(JobPosting.active_blueprint).selectinload(InterviewBlueprint.sections).selectinload(BlueprintSection.expectations),
            selectinload(JobPosting.active_blueprint).selectinload(InterviewBlueprint.sections).selectinload(BlueprintSection.questions),
        )
    )
    job_res = await db.execute(job_stmt)
    job = job_res.scalar_one_or_none()
    if not job:
        raise ValueError(f"JobPosting not found with id: {actual_job_id}")

    # Candidate Name derivation (first name preference)
    full_name = getattr(application, "full_name", "") or "Candidate"
    first_name = full_name.split()[0] if full_name.split() else "Candidate"

    # Resume data extraction
    resume_data = _safe_parse_resume_data(application.resume)

    # Personalization data extraction
    pers = application.personalization
    intro_hook = getattr(pers, "intro_hook", None) if pers else None
    claims = getattr(pers, "claims_to_verify", []) or [] if pers else []

    raw_probes = getattr(pers, "per_skill_probes", {}) if pers else {}
    per_skill_probes: Dict[str, str] = {}
    if isinstance(raw_probes, dict):
        per_skill_probes = {str(k): str(v) for k, v in raw_probes.items() if v}
    elif isinstance(raw_probes, list):
        for item in raw_probes:
            if isinstance(item, dict) and item.get("skill_name") and item.get("probe_text"):
                per_skill_probes[str(item["skill_name"])] = str(item["probe_text"])

    # Skills formatting
    skills_list = []
    for s in (job.skills or []):
        skills_list.append({
            "id": s.id,
            "name": s.name,
            "category": s.category,
            "priority_tier": s.priority_tier or "P0",
            "weight_percentage": float(s.weight_percentage or 0.0),
            "target_level_min": s.target_level_min,
            "target_level_max": s.target_level_max,
            "rubric_l1": s.rubric_l1,
            "rubric_l2": s.rubric_l2,
            "rubric_l3": s.rubric_l3,
            "rubric_l4": s.rubric_l4,
            "rubric_l5": s.rubric_l5,
        })

    # Certifications formatting
    certs_list = []
    for c in (job.certifications or []):
        certs_list.append({
            "name": c.name,
            "issuing_org": c.issuing_org,
            "priority_tier": c.priority_tier or "P1",
        })

    # Custom questions formatting
    custom_qs_list = []
    for cq in (job.custom_questions or []):
        custom_qs_list.append({
            "id": cq.id,
            "question_text": cq.question_text,
            "priority_tier": cq.priority_tier or "P0",
            "question_type": cq.question_type or "text",
            "is_required": bool(cq.is_required),
            "options": cq.options or [],
        })

    # Blueprint formatting
    bp = job.active_blueprint
    bp_id = bp.id if bp else None
    bp_version = bp.version if bp else None
    bp_sections: List[Dict[str, Any]] = []
    if bp and getattr(bp, "sections", None):
        for sec in bp.sections:
            exps = [
                {
                    "id": e.id,
                    "order_index": e.order_index,
                    "expectation_text": e.expectation_text,
                    "importance": e.importance,
                    "source_rubric_level": e.source_rubric_level,
                }
                for e in (sec.expectations or [])
            ]
            b_qs = [
                {
                    "id": q.id,
                    "order_index": q.order_index,
                    "question_role": q.question_role,
                    "question_text": q.question_text,
                    "trigger_condition": q.trigger_condition,
                    "target_expectation_ids": q.target_expectation_ids,
                }
                for q in (sec.questions or [])
            ]
            bp_sections.append({
                "id": sec.id,
                "order_index": sec.order_index,
                "section_type": sec.section_type,
                "title": sec.title,
                "skill_id": sec.skill_id,
                "skill_name": sec.skill_name,
                "priority_tier": sec.priority_tier,
                "allocated_minutes": float(sec.allocated_minutes or 0.0),
                "welcome_script": sec.welcome_script,
                "closing_script": sec.closing_script,
                "expectations": exps,
                "questions": b_qs,
            })

    # Duration: authoritative from job
    duration = int(getattr(job, "interview_duration_mins", 20) or 20)
    followup_depth = int(getattr(job, "max_followup_depth", 2) or 2)

    return HydratedInterviewContext(
        application_id=application.id,
        job_id=job.id,
        candidate_full_name=full_name,
        candidate_first_name=first_name,
        self_reported_experience_years=float(getattr(application, "self_reported_experience_years", 0.0) or 0.0),
        fit_pitch=getattr(application, "fit_pitch", None),
        screening_answers=getattr(application, "screening_answers", []) or [],
        resume_work_experience=resume_data.get("work_experience", []),
        resume_projects=resume_data.get("projects", []),
        resume_skills=resume_data.get("skills", {}),
        resume_education=resume_data.get("education", []),
        resume_certifications=resume_data.get("certifications", []),
        resume_raw_summary=resume_data.get("parsed_text", "")[:500] if resume_data.get("parsed_text") else None,
        personalization_intro_hook=intro_hook,
        personalization_probes=per_skill_probes,
        claims_to_verify=claims,
        job_title=job.job_title or "Software Engineer",
        seniority_level=job.seniority_level or "mid",
        department=job.department or "Engineering",
        job_description=job.job_description or "",
        interview_duration_mins=duration,
        max_followup_depth=followup_depth,
        interviewer_tone=job.interviewer_tone or "Direct, technical, tech-lead caliber; warm but concise.",
        skills=skills_list,
        certifications=certs_list,
        custom_questions=custom_qs_list,
        blueprint_id=bp_id,
        blueprint_version=bp_version,
        blueprint_sections=bp_sections,
    )
