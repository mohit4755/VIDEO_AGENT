"""
validate_4_links.py

Comprehensive live test on 4 different YouTube links across genres and lengths.
"""

import sys
import time
import requests

BASE_URL = "http://127.0.0.1:8000"

TEST_VIDEOS = [
    {
        "name": "Tech / AI Lecture (User's target video)",
        "url": "https://www.youtube.com/watch?v=l-QPwk_f4eE",
    },
    {
        "name": "Music / Song (Rick Astley)",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    },
    {
        "name": "Historical / Short Clip (Me at the zoo)",
        "url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    },
    {
        "name": "TED Talk (Simon Sinek: How Great Leaders Inspire Action)",
        "url": "https://www.youtube.com/watch?v=qp0HIF3SfI4",
    },
]

def run_test():
    print("=" * 70)
    print("STARTING LIVE 4-LINK END-TO-END VALIDATION")
    print("=" * 70)

    results = []

    for idx, item in enumerate(TEST_VIDEOS, 1):
        name = item["name"]
        url = item["url"]

        print(f"\n[{idx}/4] Testing: {name}")
        print(f"      URL: {url}")
        t_start = time.time()

        try:
            # 1. Trigger analysis
            resp = requests.post(
                f"{BASE_URL}/analyze",
                json={"url": url, "language": "english"},
                timeout=15,
            )

            if resp.status_code != 202:
                print(f"      ❌ Failed to queue analysis: HTTP {resp.status_code} - {resp.text}")
                results.append((name, False, f"HTTP {resp.status_code}"))
                continue

            job_id = resp.json().get("job_id")
            print(f"      Job queued successfully: {job_id}. Polling...")

            # 2. Poll for completion
            deadline = time.time() + 60
            final_data = None

            while time.time() < deadline:
                time.sleep(3)
                poll = requests.get(f"{BASE_URL}/analyze/{job_id}", timeout=10)
                if poll.status_code == 200:
                    d = poll.json()
                    if d.get("status") in ("success", "error"):
                        final_data = d
                        break

            t_elapsed = time.time() - t_start

            if not final_data:
                print(f"      ❌ Timed out after {t_elapsed:.1f}s")
                results.append((name, False, "Timeout"))
                continue

            if final_data.get("status") != "success":
                err = final_data.get("error", "Unknown error")
                print(f"      ❌ Analysis returned error: {err}")
                results.append((name, False, err))
                continue

            # 3. Print verified details
            title = final_data.get("video_title", "N/A")
            short_summary = final_data.get("short_summary", "")
            key_points = final_data.get("key_points", [])
            keywords = final_data.get("keywords", [])
            source = final_data.get("source_used", "captions")

            print(f"      ✅ SUCCESS in {t_elapsed:.1f}s")
            print(f"      Title: {title}")
            print(f"      Source: {source}")
            print(f"      Short Summary: {short_summary[:120]}...")
            print(f"      Key Points ({len(key_points)}): {key_points[0] if key_points else 'None'}")
            print(f"      Keywords ({len(keywords)}): {', '.join(keywords[:5])}")

            results.append((name, True, f"{t_elapsed:.1f}s"))

        except Exception as e:
            print(f"      ❌ Exception: {e}")
            results.append((name, False, str(e)))

    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    all_passed = True
    for name, passed, info in results:
        status_sym = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status_sym} | {name} ({info})")
        if not passed:
            all_passed = False

    print("=" * 70)
    if all_passed:
        print("ALL 4/4 YOUTUBE VIDEOS ANALYZED AND SUMMARIZED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED.")
        sys.exit(1)

if __name__ == "__main__":
    run_test()
