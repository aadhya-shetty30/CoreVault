"""
Standalone demo (no FastAPI/DB needed): proves portalocker's exclusive lock
really serializes two concurrent writers to the same path, on whatever OS
this happens to run on -- flock() on Linux/macOS, msvcrt.locking() on
Windows, transparently, via portalocker's single cross-platform API. This
is the same mechanism app/routers/files.py's upload handler relies on.

Run it directly from backend/ (with the venv active):
    python scripts/test_file_lock.py

What to expect: both worker processes are released to race for the lock at
(almost) the same instant, but their "ACQUIRED lock" timestamps come out
~LOCK_HOLD_SECONDS apart -- proving the second worker blocked inside
portalocker.Lock(...).__enter__() until the first worker's `with` block
released the lock, instead of both writing at once.
"""
import multiprocessing
import time
from pathlib import Path

import portalocker

TARGET_FILE = Path(__file__).resolve().parent / "_lock_demo_target.txt"
LOCK_HOLD_SECONDS = 3


def worker(label: str, payload: str, start_barrier) -> None:
    start_barrier.wait()  # line both processes up so they race for the lock together
    requested_at = time.time()
    print(f"[{label}] requesting lock at t={requested_at:.3f}")
    with portalocker.Lock(str(TARGET_FILE), mode="w", timeout=30) as f:
        acquired_at = time.time()
        print(f"[{label}] ACQUIRED lock at t={acquired_at:.3f}  (waited {acquired_at - requested_at:.3f}s)")
        f.write(payload)
        f.flush()
        time.sleep(LOCK_HOLD_SECONDS)  # hold the lock so the other process visibly has to wait
        print(f"[{label}] releasing lock at t={time.time():.3f}")


if __name__ == "__main__":
    # Windows defaults to the "spawn" start method, which re-imports this
    # module fresh in each child process -- the __main__ guard above is
    # required for that to work. It's harmless on Linux/macOS too, so one
    # code path covers all three target OSes.
    barrier = multiprocessing.Barrier(2)
    p1 = multiprocessing.Process(target=worker, args=("writer-A", "content from A\n", barrier))
    p2 = multiprocessing.Process(target=worker, args=("writer-B", "content from B\n", barrier))

    print(f"Target file: {TARGET_FILE}")
    print("Starting two processes that both try to write to it at the same time...\n")
    p1.start()
    p2.start()
    p1.join()
    p2.join()

    print("\nDone. Final file contents (whichever writer went second -- intact and unmixed, not interleaved):")
    print(TARGET_FILE.read_text())
