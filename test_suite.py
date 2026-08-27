"""
test_suite.py

Automated integration and end-to-end verification for Video Agent.
"""

import sys
import time
import requests

BASE_URL = "http://127.0.0.1:8000"

def test_health():
    print("[1/6] Testing GET /health...")
    resp = requests.get(f"{BASE_URL}/health", timeout=5)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert resp.json().get("status") == "ok", "Expected status: ok"
    print("  -> PASS")

def test_static_files():
    print("[2/6] Testing static file serving...")
    index_resp = requests.get(f"{BASE_URL}/", timeout=5)
    assert index_resp.status_code == 200
    assert "Video Agent" in index_resp.text

    css_resp = requests.get(f"{BASE_URL}/static/style.css", timeout=5)
    assert css_resp.status_code == 200

    js_resp = requests.get(f"{BASE_URL}/static/script.js", timeout=5)
    assert js_resp.status_code == 200
    print("  -> PASS")

def test_invalid_url():
    print("[3/6] Testing error handling for invalid URLs...")
    resp = requests.post(
        f"{BASE_URL}/analyze",
        json={"url": "https://google.com/not-youtube", "language": "english"},
        timeout=10,
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    time.sleep(2)
    poll_resp = requests.get(f"{BASE_URL}/analyze/{job_id}", timeout=5)
    data = poll_resp.json()
    assert data.get("status") == "error", f"Expected error, got {data}"
    print("  -> PASS")

def test_not_found_job():
    print("[4/6] Testing 404 on nonexistent job...")
    resp = requests.get(f"{BASE_URL}/analyze/non_existent_id", timeout=5)
    assert resp.status_code == 404
    print("  -> PASS")

def test_video_analysis_e2e():
    print("[5/6] Testing real video analysis end-to-end...")
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    resp = requests.post(
        f"{BASE_URL}/analyze",
        json={"url": test_url, "language": "english"},
        timeout=10,
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    print(f"  -> Job ID: {job_id}. Polling for completion...")

    deadline = time.time() + 60
    final_data = None
    while time.time() < deadline:
        time.sleep(3)
        poll_resp = requests.get(f"{BASE_URL}/analyze/{job_id}", timeout=5)
        data = poll_resp.json()
        if data.get("status") in ("success", "error"):
            final_data = data
            break

    assert final_data is not None, "Timed out waiting for analysis"
    assert final_data.get("status") == "success", f"Analysis failed: {final_data}"
    assert final_data.get("video_title"), "Missing video_title"
    assert final_data.get("short_summary"), "Missing short_summary"
    assert final_data.get("detailed_summary"), "Missing detailed_summary"
    assert len(final_data.get("key_points", [])) > 0, "Missing key_points"
    assert len(final_data.get("keywords", [])) > 0, "Missing keywords"
    assert final_data.get("transcript_preview"), "Missing transcript_preview"

    print(f"  -> Video Title: {final_data.get('video_title')}")
    print(f"  -> Short Summary: {final_data.get('short_summary')[:100]}...")
    print(f"  -> Key points count: {len(final_data.get('key_points'))}")
    print(f"  -> Keywords: {', '.join(final_data.get('keywords')[:5])}")
    print("  -> PASS")

def test_target_video_analysis():
    print("[6/6] Testing user's target video (l-QPwk_f4eE) end-to-end...")
    test_url = "https://www.youtube.com/watch?v=l-QPwk_f4eE"
    resp = requests.post(
        f"{BASE_URL}/analyze",
        json={"url": test_url, "language": "english"},
        timeout=10,
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    print(f"  -> Job ID: {job_id}. Polling for completion...")

    deadline = time.time() + 60
    final_data = None
    while time.time() < deadline:
        time.sleep(3)
        poll_resp = requests.get(f"{BASE_URL}/analyze/{job_id}", timeout=5)
        data = poll_resp.json()
        if data.get("status") in ("success", "error"):
            final_data = data
            break

    assert final_data is not None, "Timed out waiting for analysis"
    assert final_data.get("status") == "success", f"Analysis failed: {final_data}"
    assert final_data.get("video_title"), "Missing video_title"
    print(f"  -> Video Title: {final_data.get('video_title')}")
    print(f"  -> Short Summary: {final_data.get('short_summary')[:100]}...")
    print("  -> PASS")

if __name__ == "__main__":
    try:
        test_health()
        test_static_files()
        test_invalid_url()
        test_not_found_job()
        test_video_analysis_e2e()
        test_target_video_analysis()
        print("\n==========================================")
        print("ALL TESTS PASSED SUCCESSFULLY! (6/6)")
        print("==========================================")
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        sys.exit(1)
