#!/usr/bin/env python3
"""Clone / configure GVHMR as the offline teacher for this lab."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = LAB_ROOT / "external"
GVHMR_DIR = EXTERNAL / "GVHMR"
GVHMR_REPO = "https://github.com/zju3dv/GVHMR.git"
CONFIG_PATH = LAB_ROOT / "configs" / "gvhmr_local.yaml"


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> int:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=check).returncode


def write_config(python_path: str | None = None) -> None:
    text = f"""# Auto-updated by scripts/setup_gvhmr.py
gvhmr_root: {GVHMR_DIR.as_posix()}
python: {python_path if python_path else 'null'}
checkpoint: null
static_camera_default: true
device: cuda
input_dir: data/input
output_dir: data/teacher
video_extensions: [".mp4", ".mov", ".avi", ".mkv", ".webm"]
extra_args: []
"""
    CONFIG_PATH.write_text(text, encoding="utf-8")
    print(f"Wrote {CONFIG_PATH}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Setup GVHMR teacher for Pose Corrector Lab")
    ap.add_argument("--skip-clone", action="store_true")
    ap.add_argument("--skip-pip", action="store_true", help="Only clone + write config")
    ap.add_argument("--python", default=sys.executable, help="Python to record in gvhmr_local.yaml")
    args = ap.parse_args()

    EXTERNAL.mkdir(parents=True, exist_ok=True)

    if not args.skip_clone:
        if GVHMR_DIR.exists():
            print(f"GVHMR already present at {GVHMR_DIR}")
            run(["git", "-C", str(GVHMR_DIR), "pull", "--ff-only"], check=False)
        else:
            run(["git", "clone", "--depth", "1", GVHMR_REPO, str(GVHMR_DIR)])

    readme = GVHMR_DIR / "README.md"
    if readme.exists():
        print("\n=== Upstream README (follow checkpoints / SMPL instructions) ===")
        print(f"Open: {readme}")
        print("Typical next steps inside external/GVHMR:")
        print("  1) Create conda/venv as documented")
        print("  2) Install requirements + PyTorch CUDA")
        print("  3) Download body models + checkpoints into inputs/")
        print("  4) Test: python tools/demo/demo.py ...")
        print("==============================================================\n")

    if not args.skip_pip:
        req = GVHMR_DIR / "requirements.txt"
        if req.exists():
            print("NOTE: Prefer installing GVHMR deps in a *dedicated* env.")
            print(f"  cd {GVHMR_DIR}")
            print(f"  {args.python} -m pip install -r requirements.txt")
        else:
            print("No requirements.txt found yet — check upstream docs.")

    # Helper launcher path note
    launcher = LAB_ROOT / "scripts" / "run_teacher.py"
    print(f"After weights are ready, run: {launcher} --input data/input --out data/teacher --static-camera")

    write_config(python_path=args.python)

    # Drop a marker README in external
    (EXTERNAL / "README.md").write_text(
        "# External dependencies\n\n"
        "- `GVHMR/` — teacher (cloned by `scripts/setup_gvhmr.py`)\n"
        "Do not commit large checkpoints. See `.gitignore`.\n",
        encoding="utf-8",
    )

    print("Setup scaffold done.")


if __name__ == "__main__":
    main()
