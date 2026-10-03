"""
End-to-end smoke test against a *running* CoreVault backend (see the
project README for how to start it): register -> login -> create nested
folders -> upload a file -> download it back -> verify the bytes and the
server-computed SHA-256 both round-tripped intact.

Usage (from backend/, with the venv active and the API already running):
    python scripts/seed_and_demo.py [base_url]

base_url defaults to http://127.0.0.1:8000
"""
import hashlib
import sys
import time

import requests

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def main() -> None:
    stamp = int(time.time())
    email = f"demo{stamp}@example.com"
    username = f"demo{stamp}"
    password = "correct-horse-battery-staple"

    print(f"1. Registering {email} ...")
    r = requests.post(f"{BASE_URL}/auth/register", json={"email": email, "username": username, "password": password})
    r.raise_for_status()
    print("   OK:", r.json())

    print("2. Logging in ...")
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("   OK, got JWT")

    print("3. Creating nested folders: Documents -> 2026 -> Reports ...")
    r = requests.post(f"{BASE_URL}/folders", json={"name": "Documents", "parent_folder_id": None}, headers=headers)
    r.raise_for_status()
    documents = r.json()

    r = requests.post(f"{BASE_URL}/folders", json={"name": "2026", "parent_folder_id": documents["id"]}, headers=headers)
    r.raise_for_status()
    year_folder = r.json()

    r = requests.post(f"{BASE_URL}/folders", json={"name": "Reports", "parent_folder_id": year_folder["id"]}, headers=headers)
    r.raise_for_status()
    reports = r.json()
    print("   Breadcrumb of Reports:", [c["name"] for c in reports["breadcrumb"]])

    print("4. Uploading a file into Reports ...")
    content = f"CoreVault demo file created at {time.time()}\n".encode()
    expected_hash = hashlib.sha256(content).hexdigest()
    files = {"file": ("hello.txt", content, "text/plain")}
    data = {"folder_id": reports["id"]}
    r = requests.post(f"{BASE_URL}/files/upload", files=files, data=data, headers=headers)
    r.raise_for_status()
    uploaded = r.json()
    print("   Uploaded:", uploaded)
    assert uploaded["content_hash"] == expected_hash, "server-computed hash does not match the client's!"
    print("   SHA-256 computed server-side while streaming to disk matches the client's: OK")

    print("5. Downloading it back ...")
    r = requests.get(f"{BASE_URL}/files/{uploaded['id']}/download", headers=headers)
    r.raise_for_status()
    downloaded_hash = hashlib.sha256(r.content).hexdigest()
    assert downloaded_hash == expected_hash, "downloaded bytes don't match what was uploaded!"
    print("   Downloaded bytes match: OK")

    print("\nAll good -- full flow (register -> login -> nested folders -> upload -> download) verified.")
    print("Now try `python scripts/test_file_lock.py` to see the portalocker lock in action.")


if __name__ == "__main__":
    main()
