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

