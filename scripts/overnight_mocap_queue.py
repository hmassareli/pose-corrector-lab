#!/usr/bin/env python3
"""Wait for YOLO people batch, then run MediaPipe + GVHMR teacher overnight.

Usage (from pose_corrector_lab):
  python -u scripts/overnight_mocap_queue.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
PEOPLE = LAB_ROOT / "data" / "input" / "people"
YOLO_MANIFEST = PEOPLE / "batch_from_scratch_manifest.json"
LOG = LAB_ROOT / "data" / "overnight_mocap_queue.log"


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def wait_yolo(timeout_sec: float, poll_sec: float) -> None:
    log(f"Waiting for YOLO manifest: {YOLO_MANIFEST}")
    t0 = time.time()
    while True:
        if YOLO_MANIFEST.exists():
            try:
                m = json.loads(YOLO_MANIFEST.read_text(encoding="utf-8"))
                n = m.get("n_jobs")
                done = len(m.get("jobs") or [])
                failed = m.get("n_failed")
                log(f"YOLO manifest ready jobs={done}/{n} failed={failed}")
                return
            except Exception as e:
                log(f"manifest present but unreadable yet: {e}")
        if time.time() - t0 > timeout_sec:
            raise TimeoutError(f"YOLO batch not finished after {timeout_sec/3600:.1f}h")
        time.sleep(poll_sec)


def run(cmd: list[str], cwd: Path | None = None) -> None:
    log("+ " + " ".join(cmd))
    r = subprocess.run(cmd, cwd=str(cwd or LAB_ROOT))
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(cmd)}")


def ensure_mediapipe() -> None:
    try:
        import mediapipe  # noqa: F401
        return
    except ImportError:
        pass
    log("Installing mediapipe...")
    run([sys.executable, "-m", "pip", "install", "mediapipe"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-wait", action="store_true", help="YOLO already done")
    ap.add_argument("--skip-mediapipe", action="store_true")
    ap.add_argument("--skip-teacher", action="store_true")
    ap.add_argument("--yolo-timeout-h", type=float, default=24.0)
    ap.add_argument("--poll-sec", type=float, default=60.0)
    args = ap.parse_args()

    log("=== overnight mocap queue start ===")
    if not args.skip_wait:
        wait_yolo(args.yolo_timeout_h * 3600, args.poll_sec)
    else:
        log("skip-wait: assuming base YOLO people ready")

    # Extra source added after the main YOLO batch started (max calories left half)
    people_marker = PEOPLE / "max_calories_left_half"
    if (people_marker / "shot_000" / "people_manifest.json").exists():
        log("extra YOLO already done: max_calories_left_half")
    else:
        log("Running extra YOLO people split: max_calories_left_half (4 shots)")
        run(
            [
                sys.executable,
                "-u",
                str(LAB_ROOT / "scripts" / "batch_split_all_people.py"),
                "--only",
                "left_half",
                "--crop-mode",
                "max_box",
                "--pad",
                "0",
                "--dedup-iou",
                "0.55",
            ]
        )

    n_clips = len(list(PEOPLE.rglob("clip.mp4")))
    log(f"people clips found: {n_clips}")
    if n_clips == 0:
        log("ERROR: no clip.mp4 under people/")
        sys.exit(1)

    status = {"mediapipe": None, "teacher": None, "extra_yolo": "max_calories_left_half"}

    if not args.skip_mediapipe:
        try:
            ensure_mediapipe()
            run(
                [
                    sys.executable,
                    "-u",
                    str(LAB_ROOT / "scripts" / "run_mediapipe.py"),
                    "--people-root",
                    str(PEOPLE),
                    "--out",
                    str(LAB_ROOT / "data" / "mediapipe"),
                    "--skip-existing",
                ]
            )
            status["mediapipe"] = "ok"
        except Exception as e:
            status["mediapipe"] = f"fail: {e}"
            log(f"MediaPipe failed: {e}")
    else:
        status["mediapipe"] = "skipped"

    if not args.skip_teacher:
        sh = LAB_ROOT / "scripts" / "wsl_batch_teacher_people.sh"
        # normalize line endings for bash
        text = sh.read_text(encoding="utf-8").replace("\r\n", "\n")
        sh.write_text(text, encoding="utf-8", newline="\n")
        # C:\foo\bar → /mnt/c/foo/bar
        drive = sh.drive.rstrip(":").lower()
        wsl_sh = "/mnt/" + drive + sh.as_posix()[2:]
        try:
            run(["wsl", "-e", "bash", "-lc", f"chmod +x '{wsl_sh}' && bash '{wsl_sh}'"])
            status["teacher"] = "ok"
        except Exception as e:
            status["teacher"] = f"fail: {e}"
            log(f"Teacher failed: {e}")
    else:
        status["teacher"] = "skipped"

    summary = LAB_ROOT / "data" / "overnight_mocap_status.json"
    summary.write_text(
        json.dumps(
            {
                "finished_unix": time.time(),
                "n_people_clips": n_clips,
                "status": status,
                "log": str(LOG),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    log(f"=== overnight done status={status} ===")
    log(f"summary: {summary}")
    if any(str(v).startswith("fail") for v in status.values() if v):
        sys.exit(1)


if __name__ == "__main__":
    main()
