"""Probe the practice-flow room wiring: capture /webrtc, /begin, /commit responses.

Run: PYTHONPATH=. ./.venv/bin/python scripts/probe_room_begin.py --voice samantha
"""
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
BACKEND_URL = "http://localhost:8000"
FRONTEND_URL = "http://localhost:3000"

VOICE_MAP = {"samantha": "Samantha (English (US))", "daniel": "Daniel (English (UK))", "rishi": "Rishi (English (India))"}
WAV = REPO / "debug" / "e2e_voice" / "capture_samantha.wav"


async def main() -> int:
    from playwright.async_api import async_playwright
    import httpx

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=[
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
            f"--use-file-for-fake-audio-capture={WAV}%noloop",
            "--autoplay-policy=no-user-gesture-required",
        ])
        page = await browser.new_page()
        page.set_default_timeout(15000)

        observed: list = []
        def on_response(r):
            url = r.url
            if any(k in url for k in ("/webrtc", "/begin", "/practice-interview", "/start", "/commit")):
                observed.append({"t": round(time.time(), 1), "url": url, "status": r.status})
        page.on("response", on_response)
        errors: list = []
        page.on("console", lambda m: errors.append(f"[{m.type}] {m.text[:200]}") if m.type in ("error", "warning") else None)

        async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=30) as api:
            stamp = f"probe-{int(time.time())}"
            email = f"e2e.{stamp}@candidly.test"
            r = await api.post("/api/auth/signup", json={
                "email": email, "password": "E2eVoicePass123!", "role": "candidate",
                "full_name": "Probe",
            })
            auth = r.json()
        token, user = auth.get("access_token"), auth.get("user")
        print(f"[probe] candidate={email}")

        await page.add_init_script(
            f"localStorage.setItem('candidly-auth-token-candidate', {json.dumps(token)});"
            f"localStorage.setItem('candidly-auth-token', {json.dumps(token)});"
            f"localStorage.setItem('candidly-auth-user', {json.dumps(json.dumps(user))});"
        )
        await page.goto(FRONTEND_URL)
        await page.get_by_role("button", name="Explore Jobs").click()
        await page.get_by_title("Conduct a 5-minute warm-up interview with the AI interviewer").click()
        begin_btn = page.get_by_role("button", name="Begin Interview")
        await begin_btn.wait_for(state="visible")
        t0 = time.time()
        await begin_btn.click()
        print(f"[probe] Begin clicked at +{round(time.time() - t0, 1)}s")
        # Watch the visible state for 15s
        for i in range(15):
            await page.wait_for_timeout(1000)
            body = await page.inner_text("body")
            interesting = []
            m = re.search(r"connection error|Connection interrupted|Another live|Unable to establish|network", body, re.I)
            if m:
                interesting.append(m.group(0))
            sub = re.search(r"Your words[^\n]*\n([^\n]{0,70})", body)
            print(f"[probe] +{i + 1}s notice={interesting} words-line={sub.group(1) if sub else (body[body.find('Your words') + 12:body.find('Your words') + 60] if 'Your words' in body else '?')}")
        print("\n[probe] observed responses:")
        for o in observed:
            print("  ", o)
        errs = [e for e in errors if "favicon" not in e.lower()][:14]
        if errs:
            print("\n[probe] console errors/warnings:")
            for e in errs:
                print("  ", e)
        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
