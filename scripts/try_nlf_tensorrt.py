#!/usr/bin/env python3
"""Attempt TensorRT FP16 compile of NLF crop_model — only if torch_tensorrt is installed.

The game fast path already meets CUDA p95 < 33ms without TRT on RTX 3060.
This script is the Phase-2 hook from the speed plan.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--model",
        type=Path,
        default=LAB_ROOT / "data/models/nlf/nlf_s_multi_0.2.2.torchscript",
    )
    ap.add_argument("--out", type=Path, default=LAB_ROOT / "experiments/nlf_speed/trt_attempt.json")
    args = ap.parse_args()

    report = {
        "model": str(args.model),
        "torch_tensorrt_available": False,
        "tensorrt_available": False,
        "compiled": False,
        "skipped_reason": None,
        "note": "Fast-path CUDA p95 already under 33ms; TRT is optional headroom.",
    }

    try:
        import tensorrt  # noqa: F401

        report["tensorrt_available"] = True
        report["tensorrt_version"] = getattr(tensorrt, "__version__", "?")
    except Exception as e:
        report["tensorrt_error"] = str(e)

    try:
        import torch_tensorrt  # noqa: F401

        report["torch_tensorrt_available"] = True
        report["torch_tensorrt_version"] = getattr(torch_tensorrt, "__version__", "?")
    except Exception as e:
        report["torch_tensorrt_error"] = str(e)

    if not report["torch_tensorrt_available"]:
        report["skipped_reason"] = "torch_tensorrt not installed — see TRT_DECISION.md"
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        print(
            "SKIP: install torch-tensorrt + tensorrt to compile crop_model FP16.",
            file=sys.stderr,
        )
        return 0

    import torchvision  # noqa: F401
    import torch

    model = torch.jit.load(str(args.model), map_location="cuda").eval()
    crop = model.crop_model
    # Example compile of a fixed 256² crop forward is non-trivial because the
    # public game path uses estimate_poses_batched (warp + head + weights).
    # We only probe that torch_tensorrt can see the module.
    try:
        example = torch.randn(1, 3, 256, 256, device="cuda", dtype=torch.float16)
        trt_mod = torch_tensorrt.compile(
            crop.backbone.half(),
            inputs=[example],
            enabled_precisions={torch.float16},
        )
        _ = trt_mod(example)
        report["compiled"] = True
        report["compiled_submodule"] = "crop_model.backbone"
    except Exception as e:
        report["compile_error"] = str(e)
        report["skipped_reason"] = "compile failed — keep TorchScript fast path"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["compiled"] or report["skipped_reason"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
