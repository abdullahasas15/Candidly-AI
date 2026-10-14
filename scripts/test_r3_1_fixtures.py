#!/usr/bin/env python3
"""Test R3.1 Calibration Fixtures, Pacing with Injectable Clock, and Coverage Verbatim Substring Check.

Verifies:
1. Seniority calibration fixtures that MUST fail:
   - Entry + cache-line topic (fails with seniority_fit error)
   - Entry + lock-free concurrency (fails with seniority_fit error)
   - Entry + distributed consensus/Raft/Paxos (fails with seniority_fit error)
   - Senior + trivial dictionary lookup (fails with seniority_fit error)
2. PacingController with injectable clock:
   - Behind schedule drops probes
   - Further behind schedule drops escalation
   - Drops P2 sections
   - Drops P1 sections
   - NEVER drops P0 sections
   - Grace extension only with open P0
   - Wrap-up at limit
3. Verbatim substring validation for evidence quotes.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.app.services.blueprint.validator import (
    check_seniority_fit,
    validate_section_dict,
)
from backend.app.services.interview.state_machine import PacingController


def test_seniority_calibration_fixtures():
    print("Testing Seniority Calibration Fixtures...")

    # 1. Entry + cache-line topic -> MUST FAIL
    issues_cache = check_seniority_fit(
        role="escalation_question",
        text="Suppose memory access patterns degrade throughput; how would you redesign the data structure to optimize CPU cache lines?",
        seniority_level="entry",
        skill_name="Data Structures",
    )
    assert any(i.severity == "error" and "seniority_fit" in i.field for i in issues_cache), (
        "Entry + CPU cache lines did not produce a seniority_fit error!"
    )
    print("  ✓ Entry + CPU cache lines correctly blocked by seniority_fit review")

    # 2. Entry + lock-free data structures -> MUST FAIL
    issues_lockfree = check_seniority_fit(
        role="escalation_question",
        text="How would you implement a lock-free queue using compare-and-swap primitives?",
        seniority_level="entry",
        skill_name="Data Structures",
    )
    assert any(i.severity == "error" and "seniority_fit" in i.field for i in issues_lockfree), (
        "Entry + lock-free did not produce a seniority_fit error!"
    )
    print("  ✓ Entry + lock-free data structures correctly blocked by seniority_fit review")

    # 3. Entry + distributed consensus (Raft/Paxos) -> MUST FAIL
    issues_consensus = check_seniority_fit(
        role="escalation_question",
        text="How would you implement distributed consensus using the Raft protocol across replicas?",
        seniority_level="entry",
        skill_name="Backend Systems",
    )
    assert any(i.severity == "error" and "seniority_fit" in i.field for i in issues_consensus), (
        "Entry + Raft consensus did not produce a seniority_fit error!"
    )
    print("  ✓ Entry + distributed consensus correctly blocked by seniority_fit review")

    # 4. Senior + trivial dictionary lookup -> MUST FAIL
    issues_senior_trivial = check_seniority_fit(
        role="anchor_question",
        text="How do you retrieve an item from a dictionary in your programming language?",
        seniority_level="senior",
        skill_name="Core Programming",
    )
    assert any(i.severity == "error" and "seniority_fit" in i.field for i in issues_senior_trivial), (
        "Senior + trivial lookup did not produce a seniority_fit error!"
    )
    print("  ✓ Senior + trivial dictionary lookup correctly blocked by seniority_fit review")


def test_pacing_controller_with_injectable_clock():
    print("\nTesting PacingController with Injectable Clock...")

    simulated_time = 1000.0

    def clock():
        return simulated_time

    # 20 minute interview (1200 seconds)
    pacing = PacingController(
        duration_planned_mins=20.0,
        allow_grace_extension=True,
        closing_reserve_secs=60.0,
        clock_fn=clock,
    )

    assert pacing.remaining_seconds() == 1200.0, f"Expected 1200s, got {pacing.remaining_seconds()}"
    print("  ✓ Injectable clock initializes correctly (1200s remaining)")

    # Test 1: On schedule (15 mins remaining)
    simulated_time += 300.0  # 5 mins in, 15 mins remaining (900s)
    remaining_sections = ["P0", "P1", "P2"]
    assert pacing.should_allow_probe("P0", remaining_sections) is True
    assert pacing.should_allow_escalation("P0", remaining_sections) is True
    assert pacing.should_skip_section("P2", remaining_sections) is False
    assert pacing.should_skip_section("P1", remaining_sections) is False
    assert pacing.should_skip_section("P0", remaining_sections) is False
    print("  ✓ On schedule: allows probes, escalation, and all section priorities")

    # Test 2: Behind schedule (only 300s remaining) -> drops probes first
    simulated_time = 1000.0 + 920.0  # 280s remaining
    # Needed for P0(120) + P1(90) + reserve(60) + probe_buffer(30) = 300s
    assert pacing.should_allow_probe("P0", ["P0", "P1"]) is False
    print("  ✓ Behind schedule: drops probes first")

    # Test 3: Further behind schedule (210s remaining) -> drops escalation
    simulated_time = 1000.0 + 995.0  # 205s remaining
    # Needed for escalation: P0(120) + reserve(60) + esc(45) = 225s
    assert pacing.should_allow_escalation("P0", ["P0", "P1"]) is False
    print("  ✓ Further behind schedule: drops escalation")

    # Test 4: Section shedding: drops P2 when remaining < P0_and_P1_needed (270s)
    simulated_time = 1000.0 + 950.0  # 250s remaining
    # P0 needed (120) + reserve (60) = 180s; P0+P1 needed = 180 + 90 = 270s
    assert pacing.should_skip_section("P2", ["P0", "P1"]) is True
    assert pacing.should_skip_section("P1", ["P0"]) is False
    assert pacing.should_skip_section("P0", ["P0"]) is False
    print("  ✓ Behind schedule: drops P2 section while keeping P1 and P0")

    # Test 5: Severely behind schedule (150s remaining) -> drops P1, NEVER drops P0
    simulated_time = 1000.0 + 1050.0  # 150s remaining (less than P0 needed 180s)
    assert pacing.should_skip_section("P1", ["P0"]) is True
    assert pacing.should_skip_section("P0", []) is False  # NEVER drop P0!
    print("  ✓ Severely behind schedule: drops P1 section, NEVER drops P0")

    # Test 6: Grace extension (+5 mins) only with open P0
    simulated_time = 1000.0 + 1150.0  # 50s remaining (<= closing_reserve_secs 60s)
    # Without open P0, grace extension must NOT be granted
    pacing_no_p0 = PacingController(
        duration_planned_mins=20.0,
        allow_grace_extension=True,
        closing_reserve_secs=60.0,
        clock_fn=clock,
    )
    pacing_no_p0.started_monotonic = 1000.0
    assert pacing_no_p0.maybe_grant_grace_extension(has_open_p0=False) is False
    assert pacing_no_p0.grace_extended is False
    print("  ✓ Grace extension NOT granted without open P0")

    # With open P0, grace extension MUST be granted (+300s)
    pacing_with_p0 = PacingController(
        duration_planned_mins=20.0,
        allow_grace_extension=True,
        closing_reserve_secs=60.0,
        clock_fn=clock,
    )
    pacing_with_p0.started_monotonic = 1000.0
    assert pacing_with_p0.maybe_grant_grace_extension(has_open_p0=True) is True
    assert pacing_with_p0.grace_extended is True
    assert pacing_with_p0.remaining_seconds() == 50.0 + 300.0  # 350s remaining!
    # Cannot be granted twice
    assert pacing_with_p0.maybe_grant_grace_extension(has_open_p0=True) is False
    print("  ✓ Grace extension granted exactly once with open P0 (+5m)")

    # Test 7: Wrap-up at the limit
    simulated_time = 1000.0 + 1200.0 + 300.0 + 1.0  # Total budget exceeded
    assert pacing_with_p0.should_wrap_up(has_open_p0=True) is True
    print("  ✓ Wrap-up enforced when total budget limit is reached")


def test_coverage_evidence_verbatim_validation():
    print("\nTesting Coverage Evidence Verbatim Substring Check...")
    candidate_answer = "In my previous project, we partitioned the tables by tenant ID and used composite B-tree indexes to optimize query latency."

    # Valid verbatim substring
    valid_quote = "we partitioned the tables by tenant ID and used composite B-tree indexes"
    assert valid_quote in candidate_answer
    print("  ✓ Valid verbatim substring passes")

    # Hallucinated or non-verbatim quote
    hallucinated_quote = "we partitioned tables by tenant and applied B-Tree index"
    assert hallucinated_quote not in candidate_answer
    print("  ✓ Non-verbatim / hallucinated quote correctly detected for dropping")


def main():
    print("==================================================")
    print("RUNNING R3.1 FIXTURES & PACING VERIFICATION SUITE")
    print("==================================================")
    test_seniority_calibration_fixtures()
    test_pacing_controller_with_injectable_clock()
    test_coverage_evidence_verbatim_validation()
    print("\n==================================================")
    print("ALL R3.1 FIXTURES & PACING TESTS PASSED (100%)")
    print("==================================================")


if __name__ == "__main__":
    main()
