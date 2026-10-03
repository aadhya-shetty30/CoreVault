"""
REQ-7.1/7.2 evidence: fires N concurrent uploads for the SAME user against a
*running* CoreVault backend and asserts the final storage_used_bytes exactly
equals the sum of the bytes actually written -- i.e. the
threading.Lock-protected read-modify-write in app/workers.py's
finalize_upload() has no lost updates, even though all N requests are
handled by different worker threads in the same producer-consumer pool
(see app/workers.py's module docstring).

Each of the N uploads carries distinct content (no two payloads share a
SHA-256), so dedup can't reduce the total and confuse this specifically
being a test of the *quota counter's* concurrency-safety, not of dedup.

Usage (from backend/, with the venv active and the API already running --
see the project README):
    python scripts/test_concurrent_quota.py [base_url] [N]

base_url defaults to http://127.0.0.1:8000, N defaults to 20.
"""
import sys
import threading
import time

import requests

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 20


def main() -> None:
    stamp = int(time.time())
    email = f"quota{stamp}@example.com"
    username = f"quota{stamp}"
    password = "correct-horse-battery-staple"

    print(f"1. Registering {email} ...")
    r = requests.post(f"{BASE_URL}/auth/register", json={"email": email, "username": username, "password": password})
    r.raise_for_status()

    print("2. Logging in ...")
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    print(f"3. Preparing {N} distinct payloads (different content each, so dedup never kicks in) ...")
    payloads = [f"quota-race payload #{i} - {stamp} - {'x' * i}".encode() for i in range(N)]
    expected_total = sum(len(p) for p in payloads)

    print(f"4. Firing all {N} uploads at once from {N} threads ...")
    start_barrier = threading.Barrier(N)
    results: list[requests.Response] = [None] * N  # type: ignore[list-item]
    errors: list[Exception] = []

    def upload(i: int) -> None:
        start_barrier.wait()  # line every thread up so they all race the API together
        try:
            files = {"file": (f"race{i}.bin", payloads[i], "application/octet-stream")}
            resp = requests.post(f"{BASE_URL}/files/upload", files=files, headers=headers)
            results[i] = resp
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=upload, args=(i,)) for i in range(N)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"   All {N} requests completed in {time.time() - t0:.2f}s")

    if errors:
        raise SystemExit(f"FAIL: {len(errors)} request(s) raised an exception: {errors[:3]}")

    failed = [(i, r.status_code, r.text) for i, r in enumerate(results) if r is None or r.status_code != 201]
    if failed:
        raise SystemExit(f"FAIL: {len(failed)} upload(s) did not succeed: {failed[:5]}")
    print(f"   All {N} uploads returned 201 Created")

    print("5. Checking the user's final storage_used_bytes ...")
    r = requests.get(f"{BASE_URL}/auth/me", headers=headers)
    r.raise_for_status()
    actual_total = r.json()["storage_used_bytes"]

    print(f"   expected total (sum of {N} unique payload sizes): {expected_total} bytes")
    print(f"   actual storage_used_bytes on the server:          {actual_total} bytes")

    assert actual_total == expected_total, (
        f"LOST UPDATE DETECTED: expected {expected_total}, got {actual_total} "
        f"(short by {expected_total - actual_total} bytes) -- the quota lock in "
        f"app/workers.py did not fully serialize concurrent updates."
    )
    print("\nNo lost updates: storage_used_bytes exactly matches the sum of all concurrent uploads' sizes.")
    print("This is REQ-7.1/7.2 evidence for the per-user threading.Lock around storage_used_bytes in app/workers.py.")


if __name__ == "__main__":
    main()
