"""Hybrid LLM resume parser tests.

The parser must combine LLM semantic extraction (Bedrock-first) with the
deterministic regex parser, keep the canonical structured-data shape that
context_hydrator / STT keyterms / personalization consume, and never block an
application when the LLM stage fails.
"""

import pytest

from backend.app.services.resume_parser import (
    parse_resume_with_llm,
    parse_structured_resume_data,
    _normalize_llm_resume_output,
)

RESUME_TEXT = """
Mohammad Abdullah
mohammad@example.com | +1 415 555 0100 | linkedin.com/in/mohammad-abdullah

SUMMARY
Backend engineer focused on realtime data systems.

WORK EXPERIENCE
Senior Backend Engineer at Stripe            Jan 2021 - Present
- Built realtime fraud scoring with Flink and Kafka.
- Cut p99 latency by 40 percent.

Data Engineer at Grab                        06/2018 - Dec 2020
- Built ingestion pipelines on Airflow and Snowflake.

SKILLS
Python, Go, Kubernetes, PostgreSQL

CERTIFICATIONS
AWS Certified Solutions Architect - Associate (2022)

EDUCATION
B.Tech in Computer Science, Indian Institute of Technology, 2018
"""


def _llm_payload():
    return {
        "candidate_name": "Mohammad Abdullah",
        "summary": "Backend engineer focused on realtime data systems.",
        "work_experience": [
            {
                "company": "Stripe",
                "role": "Senior Backend Engineer",
                "start_date": "Jan 2021",
                "end_date": "Present",
                "description": "Realtime fraud scoring platform.",
                "highlights": ["Built realtime fraud scoring with Apache Flink and Kafka"],
                "technologies": ["Apache Flink", "Kafka", "Python"],
            },
            {
                "company": "Grab",
                "role": "Data Engineer",
                "start_date": "06/2018",
                "end_date": "Dec 2020",
                "description": "Ingestion pipelines.",
                "highlights": [],
                "technologies": ["Airflow", "Snowflake"],
            },
        ],
        "education": [
            {
                "degree": "Bachelor of Technology",
                "institution": "Indian Institute of Technology",
                "field": "Computer Science",
                "graduation_year": 2018,
                "gpa": None,
                "honors": None,
            }
        ],
        "certifications": [],
        "projects": [
            {"name": "realtime-fraud-scoring", "description": "Low latency scoring service.", "technologies": ["Flink", "Redis"]}
        ],
        "skills_by_category": {
            "Languages": ["Python", "Go"],
            "Frameworks": ["Apache Flink", "Airflow"],
            "Databases": ["PostgreSQL", "Redis", "Snowflake"],
            "Cloud & DevOps": ["Kubernetes", "AWS"],
            "Tools": ["Kafka"],
            "Other": [],
        },
    }


@pytest.mark.asyncio
async def test_llm_extraction_wins_and_deterministic_parts_are_preserved(monkeypatch):
    async def fake_llm(system_prompt, user_prompt):
        assert "Resume text" in user_prompt
        return _llm_payload()

    data = await parse_resume_with_llm(RESUME_TEXT, llm_fn=fake_llm)

    assert data["_parser"] == "llm+regex"
    # LLM semantics won
    assert data["work_experience"][0]["company"] == "Stripe"
    assert "Apache Flink" in data["skills"]["Frameworks"]
    assert "Apache Flink" in data["skills_flat"]
    assert "realtime-fraud-scoring" in [p["name"] for p in data["projects"]]
    # Regex taxonomy hits are unioned in
    assert "Go" in data["skills"]["Languages"]

    # Contact info is deterministic (exact regex)
    assert data["contact_info"]["email"] == "mohammad@example.com"
    assert data["contact_info"]["linkedin"] == "https://linkedin.com/in/mohammad-abdullah"

    # Experience math is recomputed deterministically from LLM dates (2 jobs, non-overlapping)
    assert data["total_experience_years"] > 4.0
    assert data["work_experience"][0]["duration_years"] is not None


@pytest.mark.asyncio
async def test_regex_backfills_what_llm_missed(monkeypatch):
    payload = _llm_payload()
    payload["certifications"] = []  # LLM missed the AWS cert
    payload["work_experience"] = []  # and the jobs entirely

    async def fake_llm(system_prompt, user_prompt):
        return payload

    data = await parse_resume_with_llm(RESUME_TEXT, llm_fn=fake_llm)

    # Cert backfilled from the deterministic parser
    cert_names = " ".join(c["name"].lower() for c in data["certifications"])
    assert "aws certified solutions architect" in cert_names
    # Work experience backfilled wholesale when the LLM returned none
    assert data["work_experience"], "regex work experience must backfill empty LLM output"
    assert data["total_experience_years"] > 0


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_deterministic(monkeypatch):
    async def broken_llm(system_prompt, user_prompt):
        raise RuntimeError("bedrock exploded")

    data = await parse_resume_with_llm(RESUME_TEXT, llm_fn=broken_llm)
    assert data["_parser"] == "deterministic"
    assert data["contact_info"]["email"] == "mohammad@example.com"
    assert data["skills"], "deterministic parser still detects taxonomy skills"

    async def junk_llm(system_prompt, user_prompt):
        return {"unrelated": True}

    data2 = await parse_resume_with_llm(RESUME_TEXT, llm_fn=junk_llm)
    assert data2["_parser"] == "deterministic"


@pytest.mark.asyncio
async def test_kill_switch_disables_llm_stage(monkeypatch):
    monkeypatch.setenv("RESUME_LLM_PARSER", "0")
    called = {"n": 0}

    async def fake_llm(system_prompt, user_prompt):
        called["n"] += 1
        return _llm_payload()

    data = await parse_resume_with_llm(RESUME_TEXT, llm_fn=fake_llm)
    assert called["n"] == 0
    assert data["_parser"] == "deterministic"


def test_normalize_rejects_bad_payloads():
    assert _normalize_llm_resume_output("not a dict") is None
    assert _normalize_llm_resume_output({"unrelated": 1}) is None
    assert _normalize_llm_resume_output({"work_experience": "nope"}) is None
    good = _normalize_llm_resume_output(_llm_payload())
    assert good is not None
    assert good["work_experience"][0]["company"] == "Stripe"


@pytest.mark.asyncio
async def test_merged_shape_feeds_downstream_consumers(monkeypatch):
    """The merged structure must survive context_hydrator's resume reader and
    the STT keyterm extractor unchanged (same canonical keys)."""
    async def fake_llm(system_prompt, user_prompt):
        return _llm_payload()

    data = await parse_resume_with_llm(RESUME_TEXT, llm_fn=fake_llm)

    from backend.app.services.interview_v2.context_hydrator import _safe_parse_resume_data
    from backend.app.services.voice.gateway import _resume_keyterms

    class FakeResume:
        parsed_structured_data = data

    class FakeApp:
        resume = FakeResume()

    parsed = _safe_parse_resume_data(FakeResume())
    assert parsed["work_experience"][0]["company"] == "Stripe"
    assert "Python" in parsed["skills"]["Languages"]

    terms = _resume_keyterms(FakeApp())
    assert "Stripe" in terms
    assert "Kafka" in terms
    assert "realtime-fraud-scoring" in terms
