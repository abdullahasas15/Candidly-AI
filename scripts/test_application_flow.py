import asyncio
import os
import base64
from httpx import AsyncClient, ASGITransport
from docx import Document
from PIL import Image, ImageDraw

from backend.app.main import app
from backend.app.database import engine, Base
from scripts.test_helpers import create_test_accounts

async def run_integration_test():
    print("=== STARTING CANDIDATE APPLICATION FLOW INTEGRATION TEST ===")
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        recruiter_headers, candidate_headers, recruiter_user, candidate_user = await create_test_accounts(client, "application-flow")
        job_res = await client.post(
            "/api/jobs",
            headers=recruiter_headers,
            json={
                "job_title": "Application Flow Test Role",
                "department": "Engineering",
                "job_description": "Test role for application lifecycle.",
                "skills": [{"name": "Python", "priority_tier": "P0", "weight_percentage": 100}],
            },
        )
        assert job_res.status_code == 201, job_res.text
        owned_job = job_res.json()
        # 1. Fetch jobs
        res = await client.get("/api/jobs")
        assert res.status_code == 200, f"Failed to list jobs: {res.text}"
        jobs = res.json()
        assert len(jobs) > 0, "No jobs in database"
        test_job = next(job for job in jobs if job["id"] == owned_job["id"])
        job_id = test_job["id"]
        print(f"✓ Retrieved Job: '{test_job['job_title']}' (ID: {job_id})")
        print(f"  Salary Range: ${test_job.get('salary_range_min')} - ${test_job.get('salary_range_max')} {test_job.get('salary_currency')}")

        # 2. Create Candidate Application (Draft)
        stated_years = 6.5
        app_payload = {
            "job_id": job_id,
            "candidate_id": candidate_user["id"],
            "full_name": "Marcus Vance",
            "email": candidate_user["email"],
            "phone": "+1 (555) 345-6789",
            "linkedin_url": "https://linkedin.com/in/marcus-vance",
            "portfolio_url": "https://github.com/marcus-vance",
            "self_reported_experience_years": stated_years,
            "fit_pitch": "Architected low-latency message streaming pipelines with Kafka and distributed databases.",
            "expected_salary": 160000.0,
            "expected_salary_currency": "USD"
        }
        res = await client.post("/api/applications", json=app_payload, headers=candidate_headers)
        assert res.status_code == 201, f"Failed to create application: {res.text}"
        application = res.json()
        app_id = application["id"]
        print(f"✓ Application Draft Created: ID {app_id} for {application['full_name']}")

        # 3. Create a real test resume file (DOCX)
        os.makedirs("scripts", exist_ok=True)
        docx_path = "scripts/test_marcus_resume.docx"
        doc = Document()
        doc.add_heading("Marcus Vance", level=1)
        doc.add_paragraph("Work Experience:")
        doc.add_paragraph("CloudScale Inc - Senior Infrastructure Engineer (Jan 2021 - Present)")
        doc.add_paragraph("Nexus Data - Distributed Systems Engineer (Jan 2019 - Dec 2020)")
        doc.add_paragraph("Education: Bachelor of Science in Computer Engineering, MIT, 2018")
        doc.add_paragraph("Skills: Go, Python, Kubernetes, Docker, PostgreSQL, Redis, Kafka, Distributed Systems")
        doc.save(docx_path)
        print(f"✓ Generated real test resume: {docx_path}")

        # 4. Upload resume & trigger real parsing pipeline
        with open(docx_path, "rb") as f:
            files = {"file": ("test_marcus_resume.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
            res = await client.post(f"/api/applications/{app_id}/resume", files=files, headers=candidate_headers)
        assert res.status_code == 200, f"Failed to parse resume: {res.text}"
        resume_res = res.json()
        assert resume_res["status"] == "success"
        parsed_struct = resume_res["parsed_structured_data"]
        computed_exp = parsed_struct["total_experience_years"]
        print(f"✓ Resume Ingestion & Parsing Successful!")
        print(f"  File Type: {resume_res['file_type']}, OCR Used: {resume_res['ocr_used']}")
        print(f"  Computed Experience: {computed_exp:.1f} years (from non-overlapping intervals)")
        print(f"  Parsed Skills ({len(parsed_struct['skills'])}): {parsed_struct['skills']}")
        print(f"  Work Entries: {len(parsed_struct['work_experience'])}")
        print(f"  Education: {parsed_struct['education']}")

        # 5. Check Discrepancy Detection
        flags = resume_res["discrepancy_flags"]
        print(f"✓ Discrepancy Flags Detected: {len(flags)}")
        for f in flags:
            print(f"  [FLAG] {f['field_name']}: {f['flag_reason']} (Stated: {f['candidate_stated_value']}, Derived: {f['resume_derived_value']})")

        # 6. Candidate edits structured resume corrections
        correction_payload = {
            "parsed_structured_data": parsed_struct,
            "self_reported_experience_years": 7.5
        }
        res = await client.patch(f"/api/applications/{app_id}/parsed-resume", json=correction_payload, headers=candidate_headers)
        assert res.status_code == 200
        updated_app = res.json()
        print(f"✓ Updated Parsed Resume Corrections: Stated experience adjusted to {updated_app['self_reported_experience_years']} years")

        # 7. Candidate live webcam photo verification
        # Generate a small 1x1 test JPEG data URI
        img = Image.new("RGB", (320, 240), color=(60, 90, 180))
        img_path = "scripts/test_webcam.jpg"
        img.save(img_path, "JPEG")
        with open(img_path, "rb") as f:
            b64_data = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("utf-8")

        verif_payload = {
            "live_photo": b64_data,
            "government_id": None
        }
        res = await client.post(f"/api/applications/{app_id}/verification", json=verif_payload, headers=candidate_headers)
        assert res.status_code == 200, f"Verification failed: {res.text}"
        verif_res = res.json()
        assert verif_res["id"] == app_id
        print("✓ Live Webcam Photo Stored & Verified (candidate-safe response)")

        # 8. Finalize Submission
        res = await client.patch(f"/api/applications/{app_id}/submit", json={"fit_pitch": "Updated fit pitch with production experience."}, headers=candidate_headers)
        assert res.status_code == 200
        final_app = res.json()
        assert final_app["status"] == "submitted"
        print(f"✓ Application Finalized and Marked: status='{final_app['status']}'")

        # 9. Recruiter View: List applications for this job
        res = await client.get(f"/api/jobs/{job_id}/applications", headers=recruiter_headers)
        assert res.status_code == 200
        recruiter_apps = res.json()
        assert any(a["id"] == app_id for a in recruiter_apps), "Submitted application missing from recruiter queue"
        print(f"✓ Recruiter Job Applications Query: Found {len(recruiter_apps)} applicants in pipeline")

        # 10. Recruiter View: Detailed dossier inspection
        res = await client.get(f"/api/applications/{app_id}", headers=recruiter_headers)
        assert res.status_code == 200
        dossier = res.json()
        assert dossier["resume"] is not None
        assert dossier["id_verification"] is not None
        print(f"✓ Recruiter Dossier Inspection for '{dossier['full_name']}':")
        print(f"  Resume Path: {dossier['resume']['original_file_path']}")
        print(f"  Webcam Path: {dossier['id_verification']['live_photo_path']}")

        # 11. Recruiter reviews discrepancy flag
        if dossier["discrepancy_flags"]:
            flag_to_toggle = dossier["discrepancy_flags"][0]["id"]
            res = await client.patch(f"/api/applications/{app_id}/discrepancies/{flag_to_toggle}", headers=recruiter_headers)
            assert res.status_code == 200
            toggled = res.json()
            print(f"✓ Recruiter Toggled Discrepancy Flag: reviewed_by_recruiter={toggled['reviewed_by_recruiter']}")

        # 12. Recruiter updates applicant status
        res = await client.patch(f"/api/applications/{app_id}/status", json={"status": "ready_for_interview"}, headers=recruiter_headers)
        assert res.status_code == 200
        status_updated = res.json()
        assert status_updated["status"] == "ready_for_interview"
        print(f"✓ Recruiter Advanced Applicant Status: status='{status_updated['status']}'")

        # 13. Test Scanned PDF OCR Fallback on Application
        scanned_img = Image.new('RGB', (800, 600), color=(255, 255, 255))
        draw = ImageDraw.Draw(scanned_img)
        draw.text((40, 40), "Name: Samantha Vance", fill=(0, 0, 0))
        draw.text((40, 70), "Senior Backend Engineer at Apple (2020 - 2024)", fill=(0, 0, 0))
        draw.text((40, 100), "Education: B.S. in Computer Science, UC Berkeley, 2019", fill=(0, 0, 0))
        draw.text((40, 130), "Skills: Swift, Python, Rust, PostgreSQL, Kubernetes, Redis", fill=(0, 0, 0))
        scanned_pdf_path = "scripts/test_scanned_candidate.pdf"
        scanned_img.save(scanned_pdf_path, "PDF")

        with open(scanned_pdf_path, "rb") as f:
            files = {"file": ("test_scanned_candidate.pdf", f, "application/pdf")}
            res = await client.post(f"/api/applications/{app_id}/resume", files=files, headers=candidate_headers)
        assert res.status_code == 200
        scanned_res = res.json()
        assert scanned_res["ocr_used"] is True, "OCR should have been triggered for image-based PDF"
        print(f"✓ Scanned PDF OCR Pipeline Verified: ocr_used={scanned_res['ocr_used']}")
        print(f"  OCR Parsed Skills: {scanned_res['parsed_structured_data']['skills']}")

    print("\n=======================================================")
    print("ALL APPLICATION FLOW & RECRUITER VERIFICATION TESTS PASSED!")
    print("=======================================================")

if __name__ == "__main__":
    asyncio.run(run_integration_test())
