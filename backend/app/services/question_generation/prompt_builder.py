import json

from .contracts import QuestionGenerationSnapshot

PROMPT_VERSION = "v1"


def build_prompt(snapshot: QuestionGenerationSnapshot) -> str:
    return f"""You are Candidly's interview-plan generator. Prompt template {PROMPT_VERSION}.
Generate an ordered, role-relevant interview question set from the JSON snapshot and attached candidate PDF.
Use only evidence present in the snapshot or resume. Do not invent candidate experience.
Map each question to a known skill_id or an approved custom question id in source_refs.
Respect allocated_questions, P0 coverage, max follow-up depth, and the role duration.
Keep rubric anchors and expected key points in the structured response only; never include hidden rubric text in question_text.
Return only JSON matching the supplied response schema.

SNAPSHOT:
{json.dumps(snapshot.model_dump(exclude={"input_snapshot_hash"}), indent=2, sort_keys=True)}
"""
