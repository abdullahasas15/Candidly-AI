import uuid


async def create_test_accounts(client, prefix: str):
    suffix = uuid.uuid4().hex
    recruiter = (
        await client.post(
            "/api/auth/signup",
            json={
                "email": f"{prefix}-recruiter-{suffix}@example.test",
                "password": "Password123!",
                "full_name": "Test Recruiter",
                "role": "recruiter",
                "company_name": "Candidly Test Co",
            },
        )
    )
    assert recruiter.status_code == 201, recruiter.text
    candidate = (
        await client.post(
            "/api/auth/signup",
            json={
                "email": f"{prefix}-candidate-{suffix}@example.test",
                "password": "Password123!",
                "full_name": "Test Candidate",
                "role": "candidate",
            },
        )
    )
    assert candidate.status_code == 201, candidate.text
    recruiter_data = recruiter.json()
    candidate_data = candidate.json()
    return (
        {"Authorization": f"Bearer {recruiter_data['access_token']}"},
        {"Authorization": f"Bearer {candidate_data['access_token']}"},
        recruiter_data["user"],
        candidate_data["user"],
    )
