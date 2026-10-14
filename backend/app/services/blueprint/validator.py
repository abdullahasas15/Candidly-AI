import asyncio
import json
import logging
import re
from typing import List, Dict, Any, Optional
from backend.app.services.blueprint.contracts import (
    SkillSectionContent,
    ValidationIssue,
    ValidationReport,
    BatchedBlueprintReviewResponse,
    LLMReviewItem,
)
from backend.app.services.blueprint.seniority_config import get_seniority_profile, normalize_seniority

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "about", "above", "across", "after", "again", "against", "all", "and", "any", "are", "because",
    "been", "before", "being", "below", "between", "both", "building", "built", "but", "can", "could",
    "did", "different", "does", "doing", "down", "during", "each", "ensuring", "features", "few",
    "for", "from", "further", "had", "handling", "has", "have", "having", "here", "how", "implementing",
    "into", "issues", "managing", "methods", "more", "most", "multiple", "other", "our", "out", "over",
    "parts", "patterns", "practices", "process", "processes", "project", "projects", "same", "service",
    "services", "should", "solutions", "some", "steps", "such", "system", "systems", "techniques",
    "than", "that", "the", "their", "theirs", "them", "then", "there", "these", "they", "this", "those",
    "through", "too", "under", "understanding", "until", "using", "various", "very", "was", "were",
    "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with", "would",
    "candidate", "demonstrates", "experience", "knowledge", "ability", "proficient", "strong", "skill", "skills",
    "pipeline", "pipelines", "streaming", "storage", "database", "databases", "cloud", "network", "tables",
    "table", "design", "designing", "event", "events", "data", "query", "queries", "model", "models",
    "architecture", "production", "performance", "approach", "processing", "scale", "scaling", "latency",
    "tradeoffs", "trade-offs", "application", "applications", "implementation"
}

VAGUE_SKILL_NAMES = {
    "project", "projects", "work", "skills", "experience", "general",
    "other", "misc", "miscellaneous", "background", "coding", "technical",
    "etc", "tasks", "duties", "responsibilities"
}

# Domain mismatch rules for deterministic relevance enforcement
DOMAIN_MISMATCH_RULES = [
    {
        "skill_patterns": [r"\bai\b", r"machine learning", r"llm", r"prompt", r"rag", r"genai", r"artificial intelligence"],
        "forbidden_patterns": [
            r"\bsharding\b", r"\bmvcc\b", r"\bphantom read", r"\btransaction isolation\b",
            r"\b3nf\b", r"\bthird normal form\b", r"\bb-tree index\b", r"\bcomposite index\b",
            r"\bforeign key constraint\b", r"\bdatabase schema for a service\b"
        ],
        "domain_name": "Relational Database Internals & SQL Sharding",
    },
    {
        "skill_patterns": [r"sql", r"data modeling", r"database"],
        "forbidden_patterns": [
            r"\btransformer attention\b", r"\bp-tuning\b", r"\blora fine-tuning\b",
            r"\bkernal panic\b", r"\bbgp peering\b"
        ],
        "domain_name": "Deep LLM Fine-Tuning / BGP Networking",
    },
    {
        "skill_patterns": [r"devops", r"sre", r"ci/cd", r"cloud infrastructure"],
        "forbidden_patterns": [
            r"\bcss grid\b", r"\bdom manipulation\b", r"\breact fiber\b"
        ],
        "domain_name": "Web Frontend / DOM Layout",
    }
]


def extract_keywords(text: str) -> set[str]:
    words = re.findall(r"\b[a-zA-Z]{5,}\b", text.lower())
    return {w for w in words if w not in STOP_WORDS}


def check_seniority_fit(
    role: str,
    text: str,
    seniority_level: str,
    section_index: Optional[int] = None,
    skill_name: Optional[str] = None,
) -> List[ValidationIssue]:
    """Ensure questions strictly adhere to seniority calibration rules."""
    issues: List[ValidationIssue] = []
    norm_sen = normalize_seniority(seniority_level)
    lower = text.lower()

    if norm_sen == "entry":
        # Topics that MUST fail for entry level (exceeds entry stretch L4)
        entry_forbidden = [
            (r"\b(cpu )?cache[- ]lines?\b", "CPU cache lines / hardware layout"),
            (r"\b(cache misses|cache locality)\b", "CPU cache misses / hardware memory layout"),
            (r"\block[- ]free\b", "lock-free concurrency data structures"),
            (r"\b(distributed consensus|raft|paxos)\b", "distributed consensus protocols (Raft/Paxos)"),
            (r"\bmulti-region active-active\b", "multi-region active-active architectures"),
            (r"\b(memory alignment|false sharing)\b", "hardware memory alignment / false sharing"),
            (r"\b(enterprise-wide|organization-wide)\b", "enterprise-wide governance"),
        ]
        for pat, desc in entry_forbidden:
            if re.search(pat, lower):
                issues.append(ValidationIssue(
                    severity="error",
                    section_index=section_index,
                    skill_name=skill_name,
                    field=f"{role}.seniority_fit",
                    message=f"{role} discusses {desc}, which exceeds entry-level scope (prohibited for entry level)",
                ))
    elif norm_sen == "senior":
        # Topics that MUST fail for senior level (far below senior depth L4/L5)
        senior_forbidden = [
            (r"\b(how (would|do) you )?(retrieve|get|lookup|look up) (an? )?(item|element|value) from (a |an )?(list|array|dict|dictionary|hashmap)\b", "trivial element lookup from a collection"),
            (r"\bwhat is (a |an )?(loop|for loop|while loop|variable|function)\b", "trivial syntactic/programming definition"),
            (r"\bhow to declare (a |an )?(variable|class|function)\b", "basic declaration syntax"),
        ]
        for pat, desc in senior_forbidden:
            if re.search(pat, lower):
                issues.append(ValidationIssue(
                    severity="error",
                    section_index=section_index,
                    skill_name=skill_name,
                    field=f"{role}.seniority_fit",
                    message=f"{role} asks about {desc}, which is far below senior-level depth (prohibited for senior level)",
                ))
    return issues


def validate_question_text(
    text: str,
    role: str,
    expectations: Optional[List[str]] = None,
    section_index: Optional[int] = None,
    skill_name: Optional[str] = None,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    cleaned = text.strip()

    # 1. Word Count Check
    words = cleaned.split()
    word_count = len(words)
    if word_count > 45:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field=f"{role}.word_count",
            message=f"{role} has {word_count} words (hard ceiling is 45 words)",
        ))
    elif word_count > 38:
        issues.append(ValidationIssue(
            severity="warning",
            section_index=section_index,
            skill_name=skill_name,
            field=f"{role}.word_count",
            message=f"{role} has {word_count} words (recommended guideline is <= 35 words)",
        ))
    elif word_count < 5:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field=f"{role}.word_count",
            message=f"{role} is too short ({word_count} words)",
        ))

    # 2. Question Mark Check (Exactly one question per turn)
    qm_count = cleaned.count("?")
    if qm_count == 0:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field=f"{role}.question_mark",
            message=f"{role} has no question mark (?)",
        ))
    elif qm_count > 1:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field=f"{role}.question_mark",
            message=f"{role} has {qm_count} question marks (must be exactly 1 question per turn)",
        ))

    # 3. Markdown / Code Block / Bullet List Check
    has_markdown = (
        bool(re.search(r"[`#]", cleaned)) or
        bool(re.search(r"\*{1,3}[^\s*]+", cleaned)) or
        bool(re.search(r"(?:^|\s)_[^_]+_(?:\s|$)", cleaned)) or
        bool(re.search(r"\[[^\]]+\]\([^\)]+\)", cleaned)) or
        cleaned.startswith(("- ", "* ", "• ", "1. "))
    )
    if has_markdown:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field=f"{role}.formatting",
            message=f"{role} contains markdown, code formatting, or bullet characters",
        ))

    # 4. Definition-First Anti-Pattern Check
    lower_text = cleaned.lower()
    definition_prefixes = ("what is ", "what are ", "define ", "can you define ", "what's the difference between ")
    if any(lower_text.startswith(p) for p in definition_prefixes):
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field=f"{role}.phrasing",
            message=f"{role} uses definition-first phrasing instead of scenario or 'walk me through'",
        ))

    # 5. Prohibit Writing Code Aloud
    code_aloud_patterns = [
        r"\bwrite code\b", r"\bcode aloud\b", r"\btype out\b",
        r"\bwrite a function\b", r"\bwrite the syntax\b", r"\bwrite a script\b"
    ]
    for cap in code_aloud_patterns:
        if re.search(cap, lower_text):
            issues.append(ValidationIssue(
                severity="error",
                section_index=section_index,
                skill_name=skill_name,
                field=f"{role}.code_aloud",
                message=f"{role} asks candidate to write or recite code aloud (prohibited in voice interviews)",
            ))

    # 6. Expectation Leakage Check
    if expectations:
        q_keywords = extract_keywords(cleaned)
        min_overlap = 4 if role.startswith("probe") else 3
        for exp_idx, exp_text in enumerate(expectations):
            exp_keywords = extract_keywords(exp_text)
            overlap = q_keywords.intersection(exp_keywords)
            if len(overlap) >= min_overlap:
                issues.append(ValidationIssue(
                    severity="warning",
                    section_index=section_index,
                    skill_name=skill_name,
                    field=f"{role}.leakage",
                    message=f"{role} may hint at expectation #{exp_idx + 1} with overlapping keywords: {', '.join(sorted(overlap))}",
                ))

    return issues


def validate_escalation_self_contained(
    text: str,
    section_index: Optional[int] = None,
    skill_name: Optional[str] = None,
) -> List[ValidationIssue]:
    """Ensure escalations are self-contained and avoid dangling anaphora without gating premises."""
    issues: List[ValidationIssue] = []
    lower = text.strip().lower()

    # Look for dangling demonstrative references ("in that project", "your database") without premise
    has_gating_premise = any(
        lower.startswith(p) or f", {p}" in lower
        for p in ["if ", "suppose ", "assuming ", "in a scenario where ", "when the "]
    )
    if not has_gating_premise:
        dangling_patterns = [
            r"\b(building on (your|that|what|the)|building upon (your|that|the)|following up on (your|that|the))\b",
            r"\b(in that same project|in that project|in that system|for that same project)\b",
            r"\b(how would you modify that|how would you change that|how would you redesign that)\b",
            r"\b(redesign that memory|redesign that layout|redesign that architecture)\b",
            r"\b(your database|your service|your project|your pipeline)\b",
        ]
        for dp in dangling_patterns:
            if re.search(dp, lower):
                issues.append(ValidationIssue(
                    severity="error",
                    section_index=section_index,
                    skill_name=skill_name,
                    field="escalation_question.self_contained",
                    message=f"Escalation question contains dangling reference ('{dp.strip(r'\b')}') without a self-contained premise or gating condition",
                ))
                break

    return issues


def validate_probe_technique_leakage(
    probe_text: str,
    trigger_condition: Optional[str],
    expectations: List[str],
    probe_role: str,
    section_index: Optional[int] = None,
    skill_name: Optional[str] = None,
) -> List[ValidationIssue]:
    """Check if probe names a target technique unless the candidate's trigger condition mentions it."""
    issues: List[ValidationIssue] = []
    if not trigger_condition or len(trigger_condition.strip()) < 5:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field=f"{probe_role}.trigger_condition",
            message=f"{probe_role} has missing or empty trigger condition",
        ))
        return issues

    probe_keywords = extract_keywords(probe_text)
    trigger_keywords = extract_keywords(trigger_condition)

    # If probe names specific technical techniques found in expectations that the candidate hasn't triggered
    for exp_idx, exp_text in enumerate(expectations):
        exp_kws = extract_keywords(exp_text)
        named_in_probe = probe_keywords.intersection(exp_kws)
        # Techniques mentioned in probe but not triggered by candidate
        untriggered = named_in_probe - trigger_keywords
        if len(untriggered) >= 2:
            issues.append(ValidationIssue(
                severity="error",
                section_index=section_index,
                skill_name=skill_name,
                field=f"{probe_role}.technique_naming",
                message=f"{probe_role} names technique keywords ({', '.join(sorted(untriggered))}) without trigger stating candidate mentioned them",
            ))

    return issues


def validate_no_code_aloud(
    text: str,
    section_index: Optional[int] = None,
    skill_name: Optional[str] = None,
) -> List[ValidationIssue]:
    """Check that questions do not ask the candidate to write, recite, or speak code aloud."""
    issues: List[ValidationIssue] = []
    lower_text = (text or "").lower()
    code_aloud_patterns = [
        r"\bwrite (out )?(the )?code\b",
        r"\bcode aloud\b",
        r"\b(speak|recite) (the )?(code|syntax|brackets|semicolons)\b",
        r"\btype out\b",
        r"\bwrite (out )?(a |the )?function\b",
        r"\bwrite (out )?(the )?syntax\b",
        r"\bwrite (out )?(a |the )?script\b",
    ]
    for cap in code_aloud_patterns:
        if re.search(cap, lower_text):
            issues.append(ValidationIssue(
                severity="error",
                section_index=section_index,
                skill_name=skill_name,
                field="question.code_aloud",
                message="Question asks candidate to write or recite code aloud (prohibited in voice interviews)",
            ))
            break
    return issues


def check_competency_relevance(
    skill_name: str,
    items: List[str],
    section_index: Optional[int] = None,
) -> List[ValidationIssue]:
    """Deterministic & semantic relevance check: ensure items strictly belong to skill_name."""
    issues: List[ValidationIssue] = []
    s_clean = (skill_name or "").strip().lower()

    for rule in DOMAIN_MISMATCH_RULES:
        # Check if skill matches rule
        skill_matches = any(re.search(sp, s_clean) for sp in rule["skill_patterns"])
        if skill_matches:
            for item in items:
                item_lower = item.lower()
                for fp in rule["forbidden_patterns"]:
                    if re.search(fp, item_lower):
                        issues.append(ValidationIssue(
                            severity="error",
                            section_index=section_index,
                            skill_name=skill_name,
                            field="competency.relevance",
                            message=f"Section '{skill_name}' contains content from {rule['domain_name']} ('{item[:70]}...') which is irrelevant to '{skill_name}'",
                        ))
                        break

    return issues


def validate_skill_section(
    section: SkillSectionContent,
    allocated_minutes: float,
    section_index: int,
    seniority_level: str = "mid",
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    skill_name = section.skill_name

    # 1. Vague skill name check
    if skill_name:
        s_clean = skill_name.strip().lower()
        if s_clean in VAGUE_SKILL_NAMES or len(s_clean) < 3:
            issues.append(ValidationIssue(
                severity="warning",
                section_index=section_index,
                skill_name=skill_name,
                field="skill_name.specificity",
                message=f"Skill '{skill_name}' is too vague or generic; consider specifying the exact technology, domain, or competency (e.g., 'Production Projects & Architecture').",
            ))

    # 2. Expectation capacity & core/stretch balance
    expectations = section.expectations
    total_exp = len(expectations)
    core_count = sum(1 for e in expectations if getattr(e, "importance", "core") == "core")
    stretch_count = sum(1 for e in expectations if getattr(e, "importance", "core") == "stretch")

    if core_count > 3:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field="expectations.core_count",
            message=f"Section '{skill_name}' has {core_count} core expectations (maximum allowed is 3)",
        ))
    if stretch_count > 2:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field="expectations.stretch_count",
            message=f"Section '{skill_name}' has {stretch_count} stretch expectations (maximum allowed is 2)",
        ))
    if total_exp < 2 or total_exp > 5:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field="expectations.count",
            message=f"Section '{skill_name}' has {total_exp} expectations (must have between 2 and 5)",
        ))

    # 3. Probes count (3 to 6)
    probe_count = len(section.probes)
    if probe_count < 3 or probe_count > 6:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field="probes.count",
            message=f"Section '{skill_name}' has {probe_count} probes (must have between 3 and 6)",
        ))

    exp_texts = [e.expectation_text for e in expectations]

    # 4. Relevance Check for all expectations
    issues.extend(check_competency_relevance(skill_name, exp_texts, section_index))

    # 5. Anchor Question
    issues.extend(validate_question_text(
        text=section.anchor_question.question_text,
        role="anchor_question",
        expectations=exp_texts,
        section_index=section_index,
        skill_name=skill_name,
    ))
    issues.extend(check_seniority_fit("anchor_question", section.anchor_question.question_text, seniority_level, section_index, skill_name))

    # 6. Anchor Alt Question
    if getattr(section, "anchor_alt_question", None) and section.anchor_alt_question.question_text:
        issues.extend(validate_question_text(
            text=section.anchor_alt_question.question_text,
            role="anchor_alt_question",
            expectations=exp_texts,
            section_index=section_index,
            skill_name=skill_name,
        ))
        issues.extend(check_seniority_fit("anchor_alt_question", section.anchor_alt_question.question_text, seniority_level, section_index, skill_name))
    else:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field="questions.anchor_alt",
            message=f"Section '{skill_name}' has no anchor_alt question (required for hypothetical scenarios)",
        ))

    # 7. Escalation Question
    esc_text = section.escalation_question.question_text
    issues.extend(validate_question_text(
        text=esc_text,
        role="escalation_question",
        expectations=exp_texts,
        section_index=section_index,
        skill_name=skill_name,
    ))
    issues.extend(validate_escalation_self_contained(esc_text, section_index, skill_name))
    issues.extend(check_seniority_fit("escalation_question", esc_text, seniority_level, section_index, skill_name))

    # 8. Probes
    for p_idx, probe in enumerate(section.probes):
        p_role = f"probe_{p_idx + 1}"
        issues.extend(validate_question_text(
            text=probe.question_text,
            role=p_role,
            expectations=exp_texts,
            section_index=section_index,
            skill_name=skill_name,
        ))
        issues.extend(check_seniority_fit(p_role, probe.question_text, seniority_level, section_index, skill_name))
        issues.extend(validate_probe_technique_leakage(
            probe_text=probe.question_text,
            trigger_condition=probe.trigger_condition,
            expectations=exp_texts,
            probe_role=p_role,
            section_index=section_index,
            skill_name=skill_name,
        ))
        if not probe.target_expectation_indices:
            issues.append(ValidationIssue(
                severity="error",
                section_index=section_index,
                skill_name=skill_name,
                field=f"{p_role}.target_expectations",
                message=f"Probe #{p_idx + 1} does not specify target expectation indices",
            ))

    # Check question relevance
    all_q_texts = [section.anchor_question.question_text, esc_text] + [p.question_text for p in section.probes]
    issues.extend(check_competency_relevance(skill_name, all_q_texts, section_index))

    return issues


def validate_section_dict(
    section: Dict[str, Any],
    section_index: int,
    seniority_level: str = "mid",
) -> List[ValidationIssue]:
    """Validate a section represented as a dictionary (from DB or review editor)."""
    issues: List[ValidationIssue] = []
    skill_name = section.get("skill_name") or section.get("title", f"Section {section_index + 1}")

    # Check for vague or generic skill name
    if skill_name:
        s_clean = skill_name.strip().lower()
        if s_clean in VAGUE_SKILL_NAMES or len(s_clean) < 3:
            issues.append(ValidationIssue(
                severity="warning",
                section_index=section_index,
                skill_name=skill_name,
                field="skill_name.specificity",
                message=f"Skill '{skill_name}' is too vague or generic; consider specifying the exact technology, domain, or competency (e.g., 'Production Projects & Architecture').",
            ))

    expectations = section.get("expectations") or []
    total_exp = len(expectations)
    core_count = sum(1 for e in expectations if (e.get("importance") if isinstance(e, dict) else getattr(e, "importance", "core")) == "core")
    stretch_count = sum(1 for e in expectations if (e.get("importance") if isinstance(e, dict) else getattr(e, "importance", "core")) == "stretch")

    if core_count > 3:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field="expectations.core_count",
            message=f"Section '{skill_name}' has {core_count} core expectations (maximum allowed is 3)",
        ))
    if stretch_count > 2:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field="expectations.stretch_count",
            message=f"Section '{skill_name}' has {stretch_count} stretch expectations (maximum allowed is 2)",
        ))
    if total_exp < 2 or total_exp > 5:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field="expectations.count",
            message=f"Section '{skill_name}' has {total_exp} expectations (must have between 2 and 5)",
        ))

    exp_texts = [
        e.get("expectation_text") if isinstance(e, dict) else getattr(e, "expectation_text", str(e))
        for e in expectations
    ]

    # Relevance check for expectations
    issues.extend(check_competency_relevance(skill_name, exp_texts, section_index))

    questions = section.get("questions") or []
    anchors = [
        q for q in questions
        if (q.get("question_role") if isinstance(q, dict) else getattr(q, "question_role", None)) == "anchor"
    ]
    anchor_alts = [
        q for q in questions
        if (q.get("question_role") if isinstance(q, dict) else getattr(q, "question_role", None)) == "anchor_alt"
        or (q.get("kind") if isinstance(q, dict) else getattr(q, "kind", None)) == "anchor_alt"
    ]
    escalations = [
        q for q in questions
        if (q.get("question_role") if isinstance(q, dict) else getattr(q, "question_role", None)) == "escalation"
    ]
    probes = [
        q for q in questions
        if (q.get("question_role") if isinstance(q, dict) else getattr(q, "question_role", None)) == "probe"
    ]

    if not anchors:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field="questions.anchor",
            message=f"Section '{skill_name}' has no anchor question",
        ))
    else:
        for a_idx, a in enumerate(anchors):
            a_text = a.get("question_text", "") if isinstance(a, dict) else getattr(a, "question_text", "")
            issues.extend(validate_question_text(a_text, f"anchor_question_{a_idx+1}" if a_idx > 0 else "anchor_question", exp_texts, section_index, skill_name))
            issues.extend(check_seniority_fit("anchor_question", a_text, seniority_level, section_index, skill_name))

    if not anchor_alts:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field="questions.anchor_alt",
            message=f"Section '{skill_name}' has no anchor_alt question (required for hypothetical scenarios)",
        ))
    else:
        for a_idx, a in enumerate(anchor_alts):
            a_text = a.get("question_text", "") if isinstance(a, dict) else getattr(a, "question_text", "")
            issues.extend(validate_question_text(a_text, f"anchor_alt_{a_idx+1}" if a_idx > 0 else "anchor_alt_question", exp_texts, section_index, skill_name))
            issues.extend(check_seniority_fit("anchor_alt_question", a_text, seniority_level, section_index, skill_name))

    if not escalations:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field="questions.escalation",
            message=f"Section '{skill_name}' has no escalation question",
        ))
    else:
        for e_idx, esc in enumerate(escalations):
            e_text = esc.get("question_text", "") if isinstance(esc, dict) else getattr(esc, "question_text", "")
            issues.extend(validate_question_text(e_text, f"escalation_question_{e_idx+1}" if e_idx > 0 else "escalation_question", exp_texts, section_index, skill_name))
            issues.extend(validate_escalation_self_contained(e_text, section_index, skill_name))
            issues.extend(check_seniority_fit("escalation_question", e_text, seniority_level, section_index, skill_name))

    if len(probes) < 3 or len(probes) > 6:
        issues.append(ValidationIssue(
            severity="error",
            section_index=section_index,
            skill_name=skill_name,
            field="probes.count",
            message=f"Section '{skill_name}' has {len(probes)} probes (must have between 3 and 6)",
        ))

    for p_idx, probe in enumerate(probes):
        p_role = f"probe_{p_idx + 1}"
        p_text = probe.get("question_text", "") if isinstance(probe, dict) else getattr(probe, "question_text", "")
        issues.extend(validate_question_text(p_text, p_role, exp_texts, section_index, skill_name))
        issues.extend(check_seniority_fit(p_role, p_text, seniority_level, section_index, skill_name))
        t_cond = probe.get("trigger_condition", "") if isinstance(probe, dict) else getattr(probe, "trigger_condition", "")
        issues.extend(validate_probe_technique_leakage(
            probe_text=p_text,
            trigger_condition=t_cond,
            expectations=exp_texts,
            probe_role=p_role,
            section_index=section_index,
            skill_name=skill_name,
        ))

    # Relevance check for all questions
    all_q_texts = [q.get("question_text", "") if isinstance(q, dict) else getattr(q, "question_text", "") for q in questions]
    issues.extend(check_competency_relevance(skill_name, all_q_texts, section_index))

    return issues


def run_batched_blueprint_llm_review_sync(
    sections: List[Dict[str, Any]],
    seniority_level: str,
    job_title: str,
    timeout: float = 45.0,
) -> BatchedBlueprintReviewResponse:
    """Run one consolidated batched LLM quality review across all sections of a blueprint.
    
    Verifies:
    1. Relevance to skill: catches foreign domain items (e.g. Postgres DB sharding under K8s or AI Engineering).
    2. Escalation self-containment: doesn't repeat anchor question scenario.
    3. Probe technique leakage: doesn't mention 'STAR method', 'probing for depth', etc.
    4. Seniority fit: checks questions calibrate appropriately to senior/entry.
    5. Voice suitability: conversational verbal flow, <= 35-45 words, 1 question mark.
    """
    skill_sections_summary = []
    for idx, s in enumerate(sections):
        if s.get("section_type") != "skill":
            continue
        s_name = s.get("skill_name") or s.get("title") or f"Section {idx}"
        
        exps = []
        if "content" in s and hasattr(s["content"], "expectations"):
            exps = [e.expectation_text for e in s["content"].expectations]
        elif "content" in s and isinstance(s["content"], dict) and "expectations" in s["content"]:
            exps = [e.get("expectation_text", "") for e in s["content"]["expectations"]]
        else:
            exps = [e.get("expectation_text", "") if isinstance(e, dict) else getattr(e, "expectation_text", "") for e in s.get("expectations", [])]
            
        qs = {}
        if "content" in s and hasattr(s["content"], "anchor_question"):
            qs["anchor"] = s["content"].anchor_question.question_text
            qs["anchor_alt"] = getattr(s["content"].anchor_alt_question, "question_text", None)
            qs["escalation"] = s["content"].escalation_question.question_text
            qs["probes"] = [p.question_text for p in s["content"].probes]
        else:
            q_list = s.get("questions", [])
            for q in q_list:
                role = q.get("question_role") if isinstance(q, dict) else getattr(q, "question_role", "")
                txt = q.get("question_text") if isinstance(q, dict) else getattr(q, "question_text", "")
                if role in ("anchor", "anchor_alt", "escalation"):
                    qs[role] = txt
                elif role and role.startswith("probe"):
                    qs.setdefault("probes", []).append(txt)

        skill_sections_summary.append({
            "section_index": idx,
            "skill_name": s_name,
            "expectations": exps,
            "questions": qs,
        })

    if not skill_sections_summary:
        return BatchedBlueprintReviewResponse(is_approved=True, summary="No skill sections to review")

    prompt = (
        f"Role: {job_title}\n"
        f"Target Seniority: {seniority_level}\n\n"
        "You are an expert technical interviewer evaluating an interview blueprint for voice delivery.\n"
        "Critically evaluate each section against these 5 checks:\n"
        "1. RELEVANCE TO SKILL (CRITICAL ERROR): Does every expectation, question, and probe strictly belong to the declared skill? "
        "If an item evaluates a completely unrelated engineering domain (for example, relational database indexing, SQL sharding, or B-trees placed under 'Kubernetes Operations' or 'AI Engineering'), "
        "you MUST flag it as an ERROR with issue_type='relevance'.\n"
        "2. ESCALATION CONTAINMENT (ERROR): Escalation questions must push depth, scale, or failure modes, NOT repeat the anchor scenario.\n"
        "3. PROBE TECHNIQUE LEAKAGE (ERROR): Probes must NEVER reference meta-interview framework names like 'STAR method', 'probing for depth', 'CAR framework', or 'tell me in 3 steps'.\n"
        "4. SENIORITY FIT (CRITICAL ERROR if mismatched):\n"
        "   - ENTRY LEVEL (L3): Target topics are fundamental data structures, basic algorithms, problem-solving, and single-service APIs. "
        "FORBIDDEN FOR ENTRY: CPU cache lines, memory layout / alignment, lock-free concurrency, distributed consensus (Raft/Paxos), multi-region active-active replication, organization-wide architecture governance. If any question or escalation asks about these, flag as an ERROR with issue_type='seniority_fit'.\n"
        "   - SENIOR / LEAD (L5+): Target topics are system trade-offs, scalability, fault tolerance, observability, and failure domains. "
        "FORBIDDEN FOR SENIOR: Trivial element lookup from a list or dictionary, basic loop/variable syntax definitions. If any question asks trivial definitions, flag as an ERROR with issue_type='seniority_fit'.\n"
        "5. VOICE SUITABILITY: Natural verbal flow, concise (under ~35-45 words), ends with a single question mark.\n\n"
        f"Sections to review:\n{json.dumps(skill_sections_summary, indent=2)}\n\n"
        "Return your evaluation as valid JSON matching this schema:\n"
        "{\n"
        '  "is_approved": false,\n'
        '  "summary": "Summary of review findings",\n'
        '  "issues": [\n'
        "    {\n"
        '      "section_index": 1,\n'
        '      "skill_name": "Kubernetes Operations",\n'
        '      "target_item": "anchor_question",\n'
        '      "issue_type": "relevance",\n'
        '      "severity": "error",\n'
        '      "reason": "PostgreSQL indexing and query optimization belong to Database Administration, not Kubernetes Operations."\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    from backend.app.services.question_generation.provider import get_gemini_client
    from backend.app.services.llm_router import (
        is_fatal_auth_error,
        get_backup_api_key,
        call_backup_chat_sync,
        GEMINI_CIRCUIT_BREAKER,
        GEMINI_KEY_MANAGER,
        rotate_gemini_key,
        ProviderAuthError,
        is_failover_enabled,
        BACKUP_MODEL_PLAN,
    )
    from google.genai import types

    review_res = None
    if GEMINI_CIRCUIT_BREAKER.can_attempt():
        total_keys = max(GEMINI_KEY_MANAGER.key_count, 1)
        for key_attempt in range(total_keys):
            try:
                client = get_gemini_client()
            except Exception as exc:
                if is_fatal_auth_error(exc):
                    raise ProviderAuthError(f"Gemini API key is invalid or unauthorized: {exc}")
                GEMINI_CIRCUIT_BREAKER.record_failure(str(exc))
                break

            if not client:
                break

            key_failed = False
            for m in ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-2.5-flash"]:
                try:
                    resp = client.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction="You are an expert technical interviewer evaluating an interview blueprint for voice delivery. Output valid JSON.",
                            response_mime_type="application/json",
                            response_schema=BatchedBlueprintReviewResponse,
                            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                            http_options=types.HttpOptions(timeout=25000, retry_options=types.HttpRetryOptions(attempts=1)),
                        ),
                    )
                    review_res = BatchedBlueprintReviewResponse.model_validate_json(resp.text)
                    review_res.review_provider = "gemini"
                    review_res.review_model = m
                    GEMINI_CIRCUIT_BREAKER.record_success()
                    break
                except Exception as exc:
                    err_str = str(exc)
                    if is_fatal_auth_error(exc):
                        logger.error("Fatal Gemini auth error on key: %s", err_str[:120])
                        rotate_gemini_key(f"Fatal auth error: {err_str[:60]}")
                        key_failed = True
                        break
                    if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str or "UNAVAILABLE" in err_str or "503" in err_str:
                        logger.warning("Gemini key hit rate limit / 503 during review (%s). Rotating key...", err_str[:80])
                        rotate_gemini_key("Rate-limit/503 during review")
                        key_failed = True
                        break
                    else:
                        logger.warning("Gemini batched review on %s failed: %s", m, exc)
                        break

            if review_res:
                break
            if not key_failed:
                break

    # Failover to backup provider (OpenRouter / NVIDIA) if Gemini was rate limited / unavailable and failover is enabled
    if not review_res and is_failover_enabled() and get_backup_api_key():
        try:
            logger.info("Running batched blueprint review via backup provider (OpenRouter/NVIDIA)")
            system_msg = "You are an expert technical interviewer evaluating an interview blueprint for voice delivery. Output only valid JSON."
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ]
            content, b_model = call_backup_chat_sync(messages=messages, json_mode=True, timeout=timeout)
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            raw_dict = json.loads(cleaned)
            review_res = BatchedBlueprintReviewResponse.model_validate(raw_dict)
            review_res.review_provider = "backup"
            review_res.review_model = b_model or BACKUP_MODEL_PLAN
            logger.info("Backup provider batched review completed: %d issues identified", len(review_res.issues))
        except Exception as b_exc:
            logger.warning("Backup provider batched review failed: %s", b_exc)

    if not review_res:
        return BatchedBlueprintReviewResponse(
            is_approved=True,
            summary="Batched LLM review skipped due to provider unavailability; deterministic rules enforced.",
            issues=[],
            review_provider="none",
            review_model="none",
        )

    return review_res


async def run_batched_blueprint_llm_review(
    sections: List[Dict[str, Any]],
    seniority_level: str,
    job_title: str,
    timeout: float = 45.0,
) -> BatchedBlueprintReviewResponse:
    """Asynchronously execute batched blueprint LLM review."""
    return await asyncio.to_thread(
        run_batched_blueprint_llm_review_sync,
        sections=sections,
        seniority_level=seniority_level,
        job_title=job_title,
        timeout=timeout,
    )


def validate_blueprint(
    sections: List[Dict[str, Any]],
    job_skills: List[Dict[str, Any]],
    active_skill_time: float,
    total_duration_mins: int,
    seniority_level: str = "mid",
    llm_review: Optional[BatchedBlueprintReviewResponse] = None,
) -> ValidationReport:
    """Validate full blueprint against P0 coverage, reachability, word limits, format, variety, and relevance."""
    all_issues: List[ValidationIssue] = []

    # 1. P0 Coverage Check: Every P0 skill MUST have a section
    p0_skills = [
        s.get("name") for s in (job_skills or [])
        if (s.get("priority_tier") or s.get("priority") or "").upper() == "P0"
    ]
    present_skill_names = {
        s.get("skill_name") for s in sections
        if s.get("section_type") == "skill" and s.get("skill_name")
    }

    for p0 in p0_skills:
        if p0 and p0 not in present_skill_names:
            all_issues.append(ValidationIssue(
                severity="error",
                field="p0_coverage",
                message=f"Mandatory P0 skill '{p0}' does not have a dedicated interview section",
            ))

    # Check for vague skill names in job skills
    for s in job_skills or []:
        sname = (s.get("name") or "").strip()
        if sname and (sname.lower() in VAGUE_SKILL_NAMES or len(sname) < 3):
            all_issues.append(ValidationIssue(
                severity="warning",
                skill_name=sname,
                field="skill_name.specificity",
                message=f"Job skill '{sname}' is too vague or generic; consider specifying the exact technology or competency (e.g., 'Production Projects & Architecture').",
            ))

    # 2. Total Expectations Reachability Ratio Check
    # Rule: planning at ~2.0 min per expectation; stretch items never count as required coverage
    core_expectations_count = 0
    total_expectations_count = 0
    for s in sections:
        if s.get("section_type") == "skill":
            if "content" in s and hasattr(s["content"], "expectations"):
                exps = s["content"].expectations
            elif "content" in s and isinstance(s["content"], dict) and "expectations" in s["content"]:
                exps = s["content"]["expectations"]
            else:
                exps = s.get("expectations", [])
            for e in exps:
                imp = e.get("importance") if isinstance(e, dict) else getattr(e, "importance", "core")
                total_expectations_count += 1
                if imp == "core":
                    core_expectations_count += 1

    expected_capacity = max(1.0, active_skill_time / 2.0)
    # Ratio computed against core required coverage
    ratio = core_expectations_count / expected_capacity if expected_capacity > 0 else 1.0

    if ratio > 1.8:
        all_issues.append(ValidationIssue(
            severity="error",
            field="reachability_ratio",
            message=f"Core expectation density too high: {core_expectations_count} core expectations for {active_skill_time}m active time (ratio {ratio:.2f} > 1.8)",
        ))
    elif ratio > 1.3:
        all_issues.append(ValidationIssue(
            severity="warning",
            field="reachability_ratio",
            message=f"Core expectation density elevated: {core_expectations_count} core expectations for {active_skill_time}m active time (ratio {ratio:.2f} > 1.3)",
        ))

    # 3. Sum of Section Durations Check
    sum_durations = sum(s.get("allocated_minutes", 0.0) for s in sections)
    if abs(sum_durations - total_duration_mins) > 0.5:
        all_issues.append(ValidationIssue(
            severity="error",
            field="duration_budget",
            message=f"Total budgeted section time ({sum_durations:.1f}m) does not match job duration ({total_duration_mins}m)",
        ))

    # 4. Check each skill section
    for idx, s in enumerate(sections):
        if s.get("section_type") == "skill":
            if "content" in s and isinstance(s["content"], SkillSectionContent):
                all_issues.extend(validate_skill_section(s["content"], s.get("allocated_minutes", 4.0), idx, seniority_level))
            elif "questions" in s or "expectations" in s:
                all_issues.extend(validate_section_dict(s, idx, seniority_level))

    # 5. Question Opening Variety Check (across ALL questions including probes per R3.1 Requirement 6)
    all_question_texts = []
    for s in sections:
        if s.get("section_type") == "skill":
            if "content" in s and isinstance(s["content"], SkillSectionContent):
                content = s["content"]
                if getattr(content, "anchor_question", None) and getattr(content.anchor_question, "question_text", None):
                    all_question_texts.append(content.anchor_question.question_text)
                if getattr(content, "anchor_alt_question", None) and getattr(content.anchor_alt_question, "question_text", None):
                    all_question_texts.append(content.anchor_alt_question.question_text)
                if getattr(content, "escalation_question", None) and getattr(content.escalation_question, "question_text", None):
                    all_question_texts.append(content.escalation_question.question_text)
                for p in getattr(content, "probes", []):
                    if getattr(p, "question_text", None):
                        all_question_texts.append(p.question_text)
            else:
                qs = s.get("questions") or []
                for q in qs:
                    txt = q.get("question_text") if isinstance(q, dict) else getattr(q, "question_text", "")
                    if txt:
                        all_question_texts.append(txt)

    if len(all_question_texts) >= 5:
        # Check first 3 words across all questions
        openings: Dict[str, int] = {}
        for q_txt in all_question_texts:
            tokens = q_txt.strip().lower().split()[:3]
            pref = " ".join(tokens)
            openings[pref] = openings.get(pref, 0) + 1

        for pref, cnt in openings.items():
            pct = cnt / len(all_question_texts)
            if pct > 0.35 and cnt >= 4:
                all_issues.append(ValidationIssue(
                    severity="warning",
                    field="questions.variety",
                    message=f"Question opening variety alert: {cnt} of {len(all_question_texts)} questions ({pct:.0%}) share opening phrase '{pref}' across anchors and probes (guideline is <= 35%)",
                ))

    # 6. Batched LLM Review Issues (Blocks approval on errors)
    if llm_review and getattr(llm_review, "issues", None):
        for item in llm_review.issues:
            all_issues.append(ValidationIssue(
                severity=item.severity,
                section_index=item.section_index,
                skill_name=item.skill_name,
                field=f"llm_review.{item.issue_type}",
                message=f"[{item.skill_name or 'LLM Review'}] {item.reason}",
            ))

    errors = [i.message for i in all_issues if i.severity == "error"]
    warnings = [i.message for i in all_issues if i.severity == "warning"]

    return ValidationReport(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        issues=all_issues,
        review_provider=getattr(llm_review, "review_provider", None),
        review_model=getattr(llm_review, "review_model", None),
        metrics={
            "total_expectations": total_expectations_count,
            "core_expectations": core_expectations_count,
            "expected_capacity": round(expected_capacity, 1),
            "reachability_ratio": round(ratio, 2),
            "total_budgeted_mins": round(sum_durations, 1),
            "active_skill_mins": round(active_skill_time, 1),
            "p0_skills_count": len(p0_skills),
        },
    )
