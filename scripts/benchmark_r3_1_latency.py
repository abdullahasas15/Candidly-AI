"""R3.1 Live Model Per-Turn Decision Latency Benchmark.

Measures per-turn decision latency (p50 / p95) on the live model
for a text-mode entry-level interview across all 4 role templates:
1. Software Development Engineer (SDE Entry)
2. Data Engineer (DE Entry)
3. AI Engineer (AIE Entry)
4. DevOps / SRE Engineer (DevOps Entry)

Uses stream_section_turn_decision from backend.app.services.interview.followup_policy
measuring time-to-first-token (TTFT) across realistic interview turns.
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Any
import numpy as np

from backend.app.services.interview.followup_policy import stream_section_turn_decision
from backend.app.services.question_generation.provider import LIVE_MODEL_NAME

# Template seeds
TEMPLATE_DIR = Path("backend/app/seeds/role_templates")

# Realistic candidate turns per template for entry-level scenarios
ENTRY_TURNS_BY_TEMPLATE = {
    "Software Development Engineer": [
        {
            "section_name": "Data Structures & Core Algorithms",
            "priority": "P0",
            "expectations": [
                {"importance": "core", "expectation_text": "Selects appropriate collection type based on operations", "status": "not_probed"},
                {"importance": "core", "expectation_text": "Explains average vs worst-case complexity", "status": "not_probed"},
                {"importance": "stretch", "expectation_text": "Discusses memory footprint of data structures", "status": "not_probed"},
            ],
            "probes": [
                {"id": "p1", "trigger_condition": "Candidate uses basic array lookup", "question_text": "How does your lookup performance change if the data size grows by a factor of 100?"},
                {"id": "p2", "trigger_condition": "Candidate mentions collision handling", "question_text": "What collision resolution strategy would you pick if hash keys cluster closely?"},
            ],
            "candidate_turns": [
                "For tracking frequent web errors, I would start with an in-memory hash map where the key is the error string and the value is the count, giving O(1) average lookup.",
                "If we run out of memory or need top-k most frequent errors, we could maintain a min-heap of size K alongside the map to track the top frequencies in O(log K).",
                "For collisions in the hash map, separate chaining with linked lists or balanced trees is standard, though open addressing with linear probing works if load factor stays under 0.7.",
                "To optimize memory, we could use a Trie if error strings share common prefixes like HTTP status paths.",
            ],
        },
        {
            "section_name": "API & Backend Service Design",
            "priority": "P0",
            "expectations": [
                {"importance": "core", "expectation_text": "Follows standard HTTP verbs and status codes", "status": "not_probed"},
                {"importance": "core", "expectation_text": "Defines clear validation error models", "status": "not_probed"},
            ],
            "probes": [
                {"id": "p3", "trigger_condition": "Candidate omits error formatting", "question_text": "What structured JSON format would your API return when client input validation fails?"},
            ],
            "candidate_turns": [
                "I would design REST endpoints: POST /orders to create, GET /orders/{id} to retrieve, using JSON payloads and returning 201 Created with a Location header.",
                "For client errors, I return 400 Bad Request with an RFC 7807 problem detail object including field names, error codes, and human-readable messages.",
            ],
        },
    ],
    "Data Engineer": [
        {
            "section_name": "SQL & Relational Modeling",
            "priority": "P0",
            "expectations": [
                {"importance": "core", "expectation_text": "Writes correct joins and aggregation queries", "status": "not_probed"},
                {"importance": "core", "expectation_text": "Understands normalization and indexes", "status": "not_probed"},
            ],
            "probes": [
                {"id": "de_p1", "trigger_condition": "Candidate writes nested subqueries", "question_text": "How would you rewrite that subquery using a window function like ROW_NUMBER?"},
            ],
            "candidate_turns": [
                "To compute daily active customer revenue, I would JOIN customers and orders on customer_id, group by order_date and customer_id, and sum order_amount.",
                "To avoid double-counting on multiple purchases per day, I'd use COUNT(DISTINCT customer_id) and filter out refunded orders in a WHERE clause.",
                "If the query runs slowly on a billion rows, I would partition the table by order_date and cluster by customer_id to eliminate full table scans.",
            ],
        },
        {
            "section_name": "Data Pipeline Fundamentals",
            "priority": "P0",
            "expectations": [
                {"importance": "core", "expectation_text": "Explains batch vs streaming concepts", "status": "not_probed"},
                {"importance": "core", "expectation_text": "Handles nulls and corrupted records gracefully", "status": "not_probed"},
            ],
            "probes": [
                {"id": "de_p2", "trigger_condition": "Candidate skips schema validation", "question_text": "What do you do with incoming records that fail the expected schema types?"},
            ],
            "candidate_turns": [
                "In our Python ETL pipeline, we ingest CSV files daily, validate column types with Pydantic, and route invalid rows to a dead-letter queue table for inspection.",
                "We make the ingestion idempotent by staging data into a temporary partition and running an atomic MERGE statement into the production warehouse.",
            ],
        },
    ],
    "AI Engineer": [
        {
            "section_name": "Machine Learning Fundamentals",
            "priority": "P0",
            "expectations": [
                {"importance": "core", "expectation_text": "Distinguishes precision, recall, and ROC-AUC", "status": "not_probed"},
                {"importance": "core", "expectation_text": "Detects and mitigates overfitting", "status": "not_probed"},
            ],
            "probes": [
                {"id": "ai_p1", "trigger_condition": "Candidate selects accuracy on imbalanced data", "question_text": "Why is raw accuracy misleading when 99% of transactions are legitimate?"},
            ],
            "candidate_turns": [
                "For fraud classification where positive cases are very rare, high accuracy is deceptive. I optimize for precision-recall AUC and evaluate recall at a fixed false-positive rate.",
                "To prevent overfitting, we use K-fold cross-validation, early stopping on validation loss, and L2 weight regularization.",
                "We also perform feature scaling using standard scaler fit strictly on training splits to prevent data leakage.",
            ],
        },
        {
            "section_name": "LLM Application Engineering",
            "priority": "P0",
            "expectations": [
                {"importance": "core", "expectation_text": "Structures prompts with few-shot examples and schemas", "status": "not_probed"},
                {"importance": "core", "expectation_text": "Applies basic retrieval augmented generation", "status": "not_probed"},
            ],
            "probes": [
                {"id": "ai_p2", "trigger_condition": "Candidate uses simple string splitting for chunks", "question_text": "How do you choose your chunk size and overlap to avoid splitting key sentences?"},
            ],
            "candidate_turns": [
                "For our support bot, we chunk technical documentation into 500-token sections with 50-token overlap, embed them with text-embedding-004, and store in Chroma.",
                "When a query arrives, we retrieve top-3 semantic matches and construct a prompt instructing the LLM to cite doc headers and reply 'I don't know' if context is missing.",
            ],
        },
    ],
    "DevOps / SRE Engineer": [
        {
            "section_name": "Linux & Systems Administration",
            "priority": "P0",
            "expectations": [
                {"importance": "core", "expectation_text": "Diagnoses CPU, memory, and disk bottlenecks", "status": "not_probed"},
                {"importance": "core", "expectation_text": "Inspects process states and systemd services", "status": "not_probed"},
            ],
            "probes": [
                {"id": "devops_p1", "trigger_condition": "Candidate uses only top without checking disk IO", "question_text": "What command would you run to check if processes are waiting on disk IO rather than CPU?"},
            ],
            "candidate_turns": [
                "When a server reports high load, I first run 'uptime' and 'vmstat 1' to check CPU run queue versus blocked IO processes.",
                "If wait percentage is high, I check 'iostat -xz 1' to find saturated disks, or 'iotop' to find offending process PIDs.",
                "For memory leaks, I check 'free -m' and examine dmesg to see if the Linux OOM killer has triggered on any containers.",
            ],
        },
        {
            "section_name": "CI/CD & Containerization",
            "priority": "P0",
            "expectations": [
                {"importance": "core", "expectation_text": "Writes multi-stage Dockerfiles", "status": "not_probed"},
                {"importance": "core", "expectation_text": "Configures automated build and test pipelines", "status": "not_probed"},
            ],
            "probes": [
                {"id": "devops_p2", "trigger_condition": "Candidate includes build tools in production image", "question_text": "How does a multi-stage Docker build keep compilation tools out of the final container?"},
            ],
            "candidate_turns": [
                "In our GitHub Actions pipeline, we build a multi-stage Docker image where stage 1 compiles the Go binary and stage 2 copies the binary into a minimal scratch image.",
                "We run unit tests and vulnerability scans with Trivy before pushing the image tag to our registry.",
            ],
        },
    ],
}


from backend.app.services.question_generation.provider import warm_gemini_client


def calc_percentiles(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"count": 0, "min": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0}
    arr = np.array(values, dtype=float)
    return {
        "count": len(arr),
        "min": float(np.min(arr)),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(np.max(arr)),
    }


async def benchmark_template(template_name: str, config_sections: List[Dict[str, Any]]) -> Dict[str, List[float]]:
    print(f"\n---> Benchmarking Template: {template_name} (Entry Level)")
    ttft_list: List[float] = []
    total_list: List[float] = []
    warm_ttft_list: List[float] = []
    warm_total_list: List[float] = []

    turn_idx = 0
    for sec in config_sections:
        sec_name = sec["section_name"]
        priority = sec["priority"]
        exp = sec["expectations"]
        probes = sec["probes"]
        turns = sec["candidate_turns"]

        recent_dialogue = []
        for cand_answer in turns:
            turn_idx += 1
            t0 = time.perf_counter()
            first_sentence = ""

            async def on_sentence(s: str):
                nonlocal first_sentence
                if not first_sentence and s.strip():
                    first_sentence = s.strip()

            decision = await stream_section_turn_decision(
                section_name=sec_name,
                priority_tier=priority,
                expectations=exp,
                available_probes=probes,
                resume_probe=None,
                candidate_resume_notes=None,
                candidate_answer=cand_answer,
                time_left_secs=180.0,
                turn_index=turn_idx,
                on_sentence=on_sentence,
                recent_dialogue=recent_dialogue,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            try:
                ttft = float(decision.llm_ttft_ms) if (decision.llm_ttft_ms is not None and float(decision.llm_ttft_ms) > 0) else elapsed_ms
            except (ValueError, TypeError):
                ttft = elapsed_ms

            ttft_list.append(ttft)
            total_list.append(elapsed_ms)

            # Exclude the first call per template to test warm steady-state latency
            if turn_idx > 1:
                warm_ttft_list.append(ttft)
                warm_total_list.append(elapsed_ms)

            fast_marker = "[FAST]" if decision.is_fast_path else f"[{decision.provider or 'gemini'}:{decision.model_name or LIVE_MODEL_NAME}]"
            call_label = "COLD (Turn 1)" if turn_idx == 1 else "WARM"
            print(f"  Turn #{turn_idx:02d} [{call_label:<13}] | TTFT: {ttft:6.1f}ms | Total: {elapsed_ms:6.1f}ms {fast_marker:<28} | Action: {decision.action:<12} | Spoken: '{decision.spoken_reply[:40]}...'")

            recent_dialogue.append({"speaker": "candidate", "text": cand_answer})
            recent_dialogue.append({"speaker": "ai", "text": decision.spoken_reply})

    return {
        "all_ttft": ttft_list,
        "all_total": total_list,
        "warm_ttft": warm_ttft_list,
        "warm_total": warm_total_list,
    }


async def main():
    print("=========================================================================")
    print("  R3.1 LIVE MODEL PER-TURN DECISION LATENCY BENCHMARK")
    print(f"  Target Model: {LIVE_MODEL_NAME}")
    print("  Pre-warming Gemini live client...")
    warm_success = warm_gemini_client()
    print(f"  Gemini pre-warming status: {'SUCCESS' if warm_success else 'SKIPPED/MOCK'}")
    print("=========================================================================")

    all_warm_ttft: List[float] = []
    all_warm_total: List[float] = []
    all_ttft: List[float] = []
    all_total: List[float] = []
    results_by_template: Dict[str, Dict[str, List[float]]] = {}

    for template_name, sections in ENTRY_TURNS_BY_TEMPLATE.items():
        res = await benchmark_template(template_name, sections)
        results_by_template[template_name] = res
        all_ttft.extend(res["all_ttft"])
        all_total.extend(res["all_total"])
        all_warm_ttft.extend(res["warm_ttft"])
        all_warm_total.extend(res["warm_total"])

    print("\n=========================================================================")
    print("  WARM LATENCY SUMMARY (EXCLUDING 1ST CALL PER TEMPLATE)")
    print("  Target: Decision TTFT p50 <= 700 ms, p95 <= 1500 ms")
    print("=========================================================================")
    print(f"{'Role Template':<30} | {'Turns':<5} | {'TTFT p50':<9} | {'TTFT p95':<9} | {'Tot p50':<9} | {'Tot p95':<9}")
    print("-" * 85)

    for template_name, res in results_by_template.items():
        wt = calc_percentiles(res["warm_ttft"])
        w_tot = calc_percentiles(res["warm_total"])
        print(f"{template_name:<30} | {wt['count']:<5} | {wt['p50']:<8.1f}ms | {wt['p95']:<8.1f}ms | {w_tot['p50']:<8.1f}ms | {w_tot['p95']:<8.1f}ms")

    print("-" * 85)
    overall_ttft = calc_percentiles(all_warm_ttft)
    overall_tot = calc_percentiles(all_warm_total)
    print(f"{'OVERALL WARM (EXCL 1st)':<30} | {overall_ttft['count']:<5} | {overall_ttft['p50']:<8.1f}ms | {overall_ttft['p95']:<8.1f}ms | {overall_tot['p50']:<8.1f}ms | {overall_tot['p95']:<8.1f}ms")
    print("=========================================================================")

    p50_pass = overall_ttft["p50"] <= 700.0
    p95_pass = overall_ttft["p95"] <= 1500.0
    print(f"Target Evaluation: TTFT p50 ({overall_ttft['p50']:.1f}ms <= 700ms): {'PASS ✓' if p50_pass else 'FAIL ✗'}")
    print(f"Target Evaluation: TTFT p95 ({overall_ttft['p95']:.1f}ms <= 1500ms): {'PASS ✓' if p95_pass else 'FAIL ✗'}")
    print("=========================================================================")


if __name__ == "__main__":
    asyncio.run(main())
