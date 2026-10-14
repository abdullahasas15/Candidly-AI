import asyncio
import os
import shutil
from sqlalchemy import text
from backend.app.database import AsyncSessionLocal, engine

async def wipe_all():
    print("=========================================================")
    print("STARTING COMPLETE DATABASE & UPLOADS WIPE")
    print("=========================================================")

    async with AsyncSessionLocal() as session:
        # Disable foreign key checks or cascade delete in order
        tables_to_truncate = [
            "interview_skill_scores",
            "interview_evaluations",
            "interview_integrity_events",
            "interview_feedback",
            "interview_transcript_turns",
            "interview_questions",
            "interview_generation_runs",
            "interview_sessions",
            "candidate_id_verification",
            "resume_discrepancy_flags",
            "candidate_resumes",
            "job_applications",
            "candidate_applications",
            "job_question_plans",
            "job_custom_questions",
            "job_certifications",
            "job_skills",
            "job_postings",
            "users"
        ]

        for table in tables_to_truncate:
            try:
                await session.execute(text(f"TRUNCATE TABLE {table} CASCADE;"))
                print(f"✓ Truncated table: {table}")
            except Exception as e:
                print(f"! Notice for {table}: {e}")
        
        await session.commit()

    # Clear uploads folder
    for folder in ["uploads/resumes", "uploads/id_verifications"]:
        if os.path.exists(folder):
            for item in os.listdir(folder):
                item_path = os.path.join(folder, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                    print(f"✓ Cleared upload artifact: {item_path}")
                except Exception as e:
                    print(f"! Could not remove {item_path}: {e}")

    print("\n=========================================================")
    print("DATABASE AND UPLOADS SUCCESSFULLY WIPED CLEAN!")
    print("Ready for fresh testing from zero records.")
    print("=========================================================")

if __name__ == "__main__":
    asyncio.run(wipe_all())
