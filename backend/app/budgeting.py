import math
from typing import List, Dict, Any

def calculate_question_budget(duration_mins: int, skills: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Implements Part 2: Time Limits & Question Budgeting Mathematics
    
    1. Operational Overhead = 3.5 mins (intro 1.0m, wrapup 1.5m, network/speech buffer 1.0m)
       For 15m duration, overhead is adjusted to 3.0m (12.0m active).
    2. Active Evaluation Time = Duration - Overhead
    3. Core Questions = int(Active Evaluation Time / 2.0)
    4. Largest Remainder Allocation Method with P0 priority guarantee
    """
    if duration_mins <= 15:
        overhead_mins = 3.0
    elif duration_mins <= 20:
        overhead_mins = 3.5
    elif duration_mins <= 30:
        overhead_mins = 4.0
    elif duration_mins <= 45:
        overhead_mins = 5.0
    else:
        overhead_mins = 6.0

    active_eval_time = max(2.0, duration_mins - overhead_mins)
    total_core_questions = int(round(active_eval_time / 2.0))
    max_followups = int(round(total_core_questions * 0.5))

    if not skills:
        return {
            "duration_mins": duration_mins,
            "overhead_mins": overhead_mins,
            "active_eval_time": active_eval_time,
            "total_core_questions": total_core_questions,
            "max_followups": max_followups,
            "allocations": [],
        }

    # Prepare raw quotas and priority ranks
    priority_order = {"P0": 3, "P1": 2, "P2": 1}
    processed_skills = []
    total_assigned = 0

    for s in skills:
        weight = float(s.get("weight_percentage", 0))
        priority = s.get("priority_tier", "P1").upper()
        raw_quota = (total_core_questions * weight) / 100.0
        base_int = int(math.floor(raw_quota))
        
        # P0 Guarantee: Ensure at least 1 question if P0
        if priority == "P0" and base_int < 1 and total_core_questions > 0:
            base_int = 1

        remainder = raw_quota - math.floor(raw_quota)
        
        processed_skills.append({
            "name": s.get("name", "Unnamed Skill"),
            "category": s.get("category", "Core Technical"),
            "priority": priority,
            "weight": weight,
            "base_int": base_int,
            "remainder": remainder,
            "allocated": base_int,
        })
        total_assigned += base_int

    # Distribute leftover question slots based on largest remainder and priority
    leftover = total_core_questions - total_assigned
    if leftover > 0:
        # Sort by remainder descending, then priority rank descending
        processed_skills.sort(
            key=lambda x: (x["remainder"], priority_order.get(x["priority"], 1)),
            reverse=True
        )
        for i in range(leftover):
            idx = i % len(processed_skills)
            processed_skills[idx]["allocated"] += 1
    elif leftover < 0:
        # If over-assigned due to P0 guarantees, reduce non-P0 skills with lowest remainders
        processed_skills.sort(
            key=lambda x: (priority_order.get(x["priority"], 1), x["remainder"])
        )
        to_reduce = abs(leftover)
        for s in processed_skills:
            if to_reduce == 0:
                break
            if s["priority"] != "P0" and s["allocated"] > 1:
                s["allocated"] -= 1
                to_reduce -= 1

    allocations = []
    for s in processed_skills:
        alloc_questions = s["allocated"]
        time_mins = round(alloc_questions * 2.0, 1)
        target_tier = "L4-L5 Expert" if s["priority"] == "P0" else "L3-L4 Proficient"
        allocations.append({
            "skill_name": s["name"],
            "skill_priority": s["priority"],
            "allocated_questions": alloc_questions,
            "time_allocation_minutes": time_mins,
            "weight_percentage": s["weight"],
            "target_rubric_tier": target_tier,
        })

    return {
        "duration_mins": duration_mins,
        "overhead_mins": overhead_mins,
        "active_eval_time": active_eval_time,
        "total_core_questions": total_core_questions,
        "max_followups": max_followups,
        "allocations": allocations,
    }


def calculate_blueprint_section_budgets(
    duration_mins: int,
    skills: List[Dict[str, Any]],
    seniority_level: str = "mid",
) -> Dict[str, Any]:
    """
    Budgeting mathematics for Layer 1 Job Blueprint sections.

    Fixed Overhead: 6.0 min total
      - welcome: 1.5 min
      - intro: 2.0 min
      - candidate_qa: 2.0 min
      - closing: 0.5 min

    Active Skill Time: duration_mins - 6.0 min (minimum 4.0 min)
    Floors: P0 >= 4.0 min, P1 >= 3.0 min, P2 >= 3.0 min.
    Ordering: P0 -> P1 -> P2.
    Dropping policy: Drop P2 lowest-weight first if time tight, then P1.
    Remaining time above floor distributed via Largest Remainder proportional to weight.
    """
    from backend.app.services.blueprint.seniority_config import get_seniority_profile
    fixed_overhead = 6.0
    active_skill_time = max(4.0, float(duration_mins) - fixed_overhead)
    warnings: List[str] = []
    dropped_skills: List[Dict[str, Any]] = []

    priority_rank = {"P0": 3, "P1": 2, "P2": 1}
    raw_skills = []
    for idx, s in enumerate(skills or []):
        raw_skills.append({
            "id": s.get("id"),
            "name": s.get("name", f"Skill {idx + 1}"),
            "category": s.get("category", "Core Technical"),
            "priority": (s.get("priority_tier") or s.get("priority") or "P1").upper(),
            "weight": float(s.get("weight_percentage") or s.get("weight") or 0.0),
            "original_index": idx,
            "rubrics": {
                "l1": s.get("rubric_l1"),
                "l2": s.get("rubric_l2"),
                "l3": s.get("rubric_l3"),
                "l4": s.get("rubric_l4"),
                "l5": s.get("rubric_l5"),
            },
        })

    # Sort strictly: P0 first, then P1, then P2; within priority by weight descending
    sorted_skills = sorted(
        raw_skills,
        key=lambda x: (priority_rank.get(x["priority"], 1), x["weight"]),
        reverse=True,
    )

    # Determine required floor per priority
    def floor_for(priority: str) -> float:
        return 4.0 if priority == "P0" else 3.0

    # Prune from bottom (P2 lowest weight first, then P1) if floors exceed active time
    active_candidates = list(sorted_skills)
    while active_candidates:
        total_floors = sum(floor_for(c["priority"]) for c in active_candidates)
        if total_floors <= active_skill_time:
            break

        # Find drop candidate: lowest priority first (P2, then P1). Never drop P0.
        drop_idx = None
        for i in reversed(range(len(active_candidates))):
            cand = active_candidates[i]
            if cand["priority"] == "P2":
                drop_idx = i
                break
        if drop_idx is None:
            for i in reversed(range(len(active_candidates))):
                cand = active_candidates[i]
                if cand["priority"] == "P1":
                    drop_idx = i
                    break

        if drop_idx is not None:
            dropped = active_candidates.pop(drop_idx)
            dropped_skills.append(dropped)
            warnings.append(
                f"Dropped {dropped['priority']} skill '{dropped['name']}' to preserve required "
                f"eval depth within {duration_mins}m total interview time."
            )
        else:
            # Only P0s remain and their standard floors exceed active_skill_time
            # Compress P0 floors equally rather than dropping mandatory competencies
            num_p0 = len(active_candidates)
            compressed_floor = round(active_skill_time / num_p0, 2)
            warnings.append(
                f"Compressed {num_p0} mandatory P0 competencies to {compressed_floor:.1f}m each "
                f"to fit within {active_skill_time:.1f}m active time."
            )
            break

    # If no skills provided, create a default competency section
    if not active_candidates:
        active_candidates = [{
            "id": None,
            "name": "General Technical & Problem Solving",
            "category": "Core Technical",
            "priority": "P0",
            "weight": 100.0,
            "original_index": 0,
            "rubrics": {},
        }]

    # Now calculate allocated minutes
    p0_count = sum(1 for c in active_candidates if c["priority"] == "P0")
    if p0_count == len(active_candidates) and sum(floor_for(c["priority"]) for c in active_candidates) > active_skill_time:
        # P0 compressed case
        base_mins = round(active_skill_time / len(active_candidates), 1)
        for c in active_candidates:
            c["allocated_minutes"] = base_mins
        # Adjust rounding difference on first skill
        diff = round(active_skill_time - sum(c["allocated_minutes"] for c in active_candidates), 2)
        active_candidates[0]["allocated_minutes"] = round(active_candidates[0]["allocated_minutes"] + diff, 1)
    else:
        # Normal Largest Remainder above floor
        for c in active_candidates:
            c["base_floor"] = floor_for(c["priority"])
        allocated_floors = sum(c["base_floor"] for c in active_candidates)
        remaining_time = max(0.0, active_skill_time - allocated_floors)

        total_weight = sum(c["weight"] for c in active_candidates) or 1.0
        # Allocate remaining in 0.5 min steps
        half_minute_steps = int(round(remaining_time / 0.5))

        step_quotas = []
        for c in active_candidates:
            q = (half_minute_steps * c["weight"]) / total_weight
            base_steps = int(math.floor(q))
            remainder = q - base_steps
            step_quotas.append({
                "cand": c,
                "base_steps": base_steps,
                "remainder": remainder,
            })

        steps_assigned = sum(sq["base_steps"] for sq in step_quotas)
        steps_leftover = half_minute_steps - steps_assigned
        if steps_leftover > 0:
            step_quotas.sort(
                key=lambda x: (
                    x["remainder"],
                    priority_rank.get(x["cand"]["priority"], 1),
                    x["cand"]["weight"],
                ),
                reverse=True,
            )
            for i in range(steps_leftover):
                idx = i % len(step_quotas)
                step_quotas[idx]["base_steps"] += 1

        for sq in step_quotas:
            c = sq["cand"]
            c["allocated_minutes"] = round(c["base_floor"] + (sq["base_steps"] * 0.5), 1)

    # Assemble complete section plan
    sections: List[Dict[str, Any]] = []
    current_order = 0

    # 1. Welcome
    sections.append({
        "order_index": current_order,
        "section_type": "welcome",
        "title": "Welcome & Setup",
        "skill_id": None,
        "skill_name": None,
        "priority_tier": None,
        "allocated_minutes": 1.5,
        "target_rubric_tier": None,
        "recommended_expectations": 0,
    })
    current_order += 1

    # 2. Intro
    sections.append({
        "order_index": current_order,
        "section_type": "intro",
        "title": "Candidate Introduction & Career Journey",
        "skill_id": None,
        "skill_name": None,
        "priority_tier": None,
        "allocated_minutes": 2.0,
        "target_rubric_tier": None,
        "recommended_expectations": 0,
    })
    current_order += 1

    # 3. Skill sections
    seniority_profile = get_seniority_profile(seniority_level)
    for c in active_candidates:
        allocated_m = c["allocated_minutes"]
        # Rule of thumb: ~2 min per expectation (min 2, max 5; core <= 3, stretch <= 2)
        rec_exp = max(2, min(5, int(round(allocated_m / 2.0))))
        target_rubric = seniority_profile["target_rubric_tier"]
        sections.append({
            "order_index": current_order,
            "section_type": "skill",
            "title": f"{c['name']} Deep Dive",
            "skill_id": c.get("id"),
            "skill_name": c["name"],
            "category": c.get("category", "Core Technical"),
            "priority_tier": c["priority"],
            "weight_percentage": c["weight"],
            "allocated_minutes": allocated_m,
            "target_rubric_tier": target_rubric,
            "recommended_expectations": rec_exp,
            "rubrics": c.get("rubrics", {}),
        })
        current_order += 1

    # 4. Candidate Q&A
    sections.append({
        "order_index": current_order,
        "section_type": "candidate_qa",
        "title": "Candidate Questions & Open Discussion",
        "skill_id": None,
        "skill_name": None,
        "priority_tier": None,
        "allocated_minutes": 2.0,
        "target_rubric_tier": None,
        "recommended_expectations": 0,
    })
    current_order += 1

    # 5. Closing
    sections.append({
        "order_index": current_order,
        "section_type": "closing",
        "title": "Interview Wrap-Up & Next Steps",
        "skill_id": None,
        "skill_name": None,
        "priority_tier": None,
        "allocated_minutes": 0.5,
        "target_rubric_tier": None,
        "recommended_expectations": 0,
    })

    total_calc = sum(s["allocated_minutes"] for s in sections)
    return {
        "duration_mins": duration_mins,
        "fixed_overhead_mins": fixed_overhead,
        "active_skill_mins": round(sum(s["allocated_minutes"] for s in sections if s["section_type"] == "skill"), 1),
        "total_budgeted_mins": round(total_calc, 1),
        "sections": sections,
        "dropped_skills": [d["name"] for d in dropped_skills],
        "warnings": warnings,
    }


