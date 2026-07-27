#!/usr/bin/env python3
"""Train the MediaPipe → residual corrector (GRU v1)."""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
import yaml
from torch.utils.data import DataLoader, WeightedRandomSampler

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "src"))

from pose_lab.data import WindowNPZDataset  # noqa: E402
from pose_lab.logging_utils import JsonlLogger, make_run_dir, write_json  # noqa: E402
from pose_lab.losses import total_loss  # noqa: E402
from pose_lab.metrics import hard_mask  # noqa: E402
from pose_lab.models import build_model  # noqa: E402


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def cosine_lr(epoch: int, epochs: int, base_lr: float, warmup: int) -> float:
    if epoch < warmup:
        return base_lr * float(epoch + 1) / max(1, warmup)
    t = (epoch - warmup) / max(1, epochs - warmup)
    return base_lr * 0.5 * (1.0 + math.cos(math.pi * t))


@torch.no_grad()
def eval_delta(model: torch.nn.Module, loader: DataLoader, device: torch.device) -> dict:
    model.eval()
    preds, trues, confs = [], [], []
    for batch in loader:
        x = batch["x"].to(device)
        out = model(x)
        preds.append(out["delta"].cpu().numpy())
        trues.append(batch["y"].numpy())
        confs.append(batch["conf"].numpy())
    pred = np.concatenate(preds, axis=0)
    true = np.concatenate(trues, axis=0)
    conf = np.concatenate(confs, axis=0)
    hard = hard_mask(true, conf)
    easy = ~hard

    n_j = pred.shape[-1] // 3

    def mean_l2(a: np.ndarray, b: np.ndarray) -> float:
        if len(a) == 0:
            return float("nan")
        return float(np.linalg.norm((a - b).reshape(len(a), n_j, 3), axis=-1).mean())

    # body-frame units → report as "bf_mm" = *1000 for readability (not real meters)
    scale = 1000.0
    mp_err = np.linalg.norm(true.reshape(len(true), n_j, 3), axis=-1).mean(axis=-1)  # baseline Δ=0
    pr_err = np.linalg.norm((pred - true).reshape(len(true), n_j, 3), axis=-1).mean(axis=-1)

    out = {
        "n": int(len(true)),
        "n_hard": int(hard.sum()),
        "n_easy": int(easy.sum()),
        "delta_l2": mean_l2(pred, true),
        "delta_l2_hard": mean_l2(pred[hard], true[hard]),
        "delta_l2_easy": mean_l2(pred[easy], true[easy]),
        "mpjpe_hard_mm": float(pr_err[hard].mean() * scale) if hard.any() else float("nan"),
        "mpjpe_easy_mm": float(pr_err[easy].mean() * scale) if easy.any() else float("nan"),
        "mpjpe_mp_hard_mm": float(mp_err[hard].mean() * scale) if hard.any() else float("nan"),
        "mpjpe_mp_easy_mm": float(mp_err[easy].mean() * scale) if easy.any() else float("nan"),
        "mpjpe_overall_mm": float(pr_err.mean() * scale),
        "mpjpe_mp_overall_mm": float(mp_err.mean() * scale),
    }
    if hard.any() and out["mpjpe_mp_hard_mm"] > 1e-6:
        out["hard_improvement_pct"] = 100.0 * (
            1.0 - out["mpjpe_hard_mm"] / out["mpjpe_mp_hard_mm"]
        )
    else:
        out["hard_improvement_pct"] = float("nan")
    # overcorrect: predict large Δ when true is tiny
    td = np.linalg.norm(true.reshape(len(true), n_j, 3), axis=-1).mean(axis=-1)
    pd = np.linalg.norm(pred.reshape(len(pred), n_j, 3), axis=-1).mean(axis=-1)
    easy_m = easy & (td < 0.01)
    if easy_m.any():
        out["overcorrect_rate"] = float(((pd > 0.02) & easy_m).sum() / easy_m.sum())
    else:
        out["overcorrect_rate"] = 0.0
    return out


def train_one_epoch(
    model: torch.nn.Module,
    loader: DataLoader,
    opt: torch.optim.Optimizer,
    device: torch.device,
    cfg: dict,
    scaler: torch.amp.GradScaler | None,
    *,
    geometry_scale: float = 1.0,
) -> dict[str, float]:
    model.train()
    totals: dict[str, float] = {}
    n = 0
    use_amp = scaler is not None
    # Scale teacher-extend geometry weights (warmup / ramp without mutating cfg on disk).
    cfg_epoch = cfg
    if geometry_scale != 1.0:
        cfg_epoch = dict(cfg)
        lcfg = dict(cfg.get("loss") or {})
        lcfg["w_reach"] = float(lcfg.get("w_reach", 0.0)) * float(geometry_scale)
        lcfg["w_angle"] = float(lcfg.get("w_angle", 0.0)) * float(geometry_scale)
        cfg_epoch["loss"] = lcfg
    for batch in loader:
        x = batch["x"].to(device, non_blocking=True)
        y = batch["y"].to(device, non_blocking=True)
        conf = batch["conf"].to(device, non_blocking=True)
        motion = batch["motion"].to(device, non_blocking=True)
        opt.zero_grad(set_to_none=True)
        with torch.amp.autocast("cuda", enabled=use_amp):
            out = model(x)
            loss, parts = total_loss(
                out["delta"],
                y,
                conf,
                out.get("motion_logits"),
                motion,
                cfg_epoch,
                features=x,
            )
        if use_amp:
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(
                model.parameters(), float((cfg.get("optim") or {}).get("grad_clip", 1.0))
            )
            scaler.step(opt)
            scaler.update()
        else:
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                model.parameters(), float((cfg.get("optim") or {}).get("grad_clip", 1.0))
            )
            opt.step()
        n += 1
        for k, v in parts.items():
            totals[k] = totals.get(k, 0.0) + v
    return {k: v / max(1, n) for k, v in totals.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=LAB_ROOT / "configs" / "train.yaml")
    ap.add_argument("--dataset-dir", type=Path, default=LAB_ROOT / "data" / "dataset")
    ap.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--epochs", type=int, default=0, help="override config epochs (0=use config)")
    ap.add_argument("--batch-size", type=int, default=0)
    ap.add_argument(
        "--name",
        type=str,
        default="",
        help="run name suffix (default: logging.run_name or gru_v1)",
    )
    ap.add_argument("--debug-one-batch", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="build model+loaders, exit (no train)")
    ap.add_argument(
        "--init-ckpt",
        type=Path,
        default=None,
        help="warm-start model weights from a prior checkpoint (finetune; optimizer starts fresh)",
    )
    args = ap.parse_args()

    cfg = _load_yaml(args.config)
    seed = int(cfg.get("seed", 42))
    set_seed(seed)
    ocfg = cfg.get("optim") or {}
    epochs = int(args.epochs or ocfg.get("epochs", 80))
    batch_size = int(args.batch_size or ocfg.get("batch_size", 64))
    device = torch.device(args.device)

    train_path = args.dataset_dir / "train.npz"
    val_path = args.dataset_dir / "val.npz"
    meta = {}
    meta_path = args.dataset_dir / "meta.json"
    if meta_path.is_file():
        import json

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    F = int(meta.get("F") or np.load(train_path)["x"].shape[-1])
    T = int(meta.get("T") or np.load(train_path)["x"].shape[1])

    run_name = (
        args.name
        or str((cfg.get("logging") or {}).get("run_name") or "").strip()
        or "gru_v1"
    )
    run_dir = make_run_dir(LAB_ROOT / (cfg.get("logging") or {}).get("dir", "runs"), name=run_name)
    # Persist resolved cfg (incl. CLI batch/epoch overrides) for reproducibility.
    cfg_resolved = dict(cfg)
    cfg_resolved["optim"] = dict(ocfg)
    cfg_resolved["optim"]["epochs"] = epochs
    cfg_resolved["optim"]["batch_size"] = batch_size
    cfg_resolved["logging"] = dict(cfg.get("logging") or {})
    cfg_resolved["logging"]["run_name"] = run_name
    write_json(run_dir / "config.json", cfg_resolved)
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg_resolved, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    cfg = cfg_resolved
    write_json(
        run_dir / "system.json",
        {
            "seed": seed,
            "device": str(device),
            "torch": torch.__version__,
            "cuda": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "F": F,
            "T": T,
            "dataset": str(args.dataset_dir),
            "run_name": run_name,
        },
    )
    log = JsonlLogger(run_dir / "metrics.jsonl")

    hard_warmup = int(ocfg.get("hard_warmup_epochs", 5))
    fcfg = cfg.get("features") or {}
    zero_accel = bool(fcfg.get("zero_accel", False))
    zero_2d = bool(fcfg.get("zero_2d", False))
    if zero_accel or zero_2d:
        print(f"[train] feature ablation zero_accel={zero_accel} zero_2d={zero_2d}")
    train_ds = WindowNPZDataset(
        train_path, mirror_p=0.5, hard_only=False, zero_accel=zero_accel, zero_2d=zero_2d
    )
    val_ds = WindowNPZDataset(
        val_path, mirror_p=0.0, zero_accel=zero_accel, zero_2d=zero_2d
    )

    def make_train_loader(epoch: int) -> DataLoader:
        if epoch < hard_warmup:
            # overweight hard windows
            y = train_ds.y
            conf = train_ds.conf
            hard = hard_mask(y, conf)
            w = np.where(hard, 3.0, 1.0).astype(np.float64)
            # map through indices if subset — full dataset here
            sampler = WeightedRandomSampler(w, num_samples=len(w), replacement=True)
            return DataLoader(
                train_ds,
                batch_size=batch_size,
                sampler=sampler,
                num_workers=0,
                pin_memory=device.type == "cuda",
            )
        return DataLoader(
            train_ds,
            batch_size=batch_size,
            shuffle=True,
            num_workers=0,
            pin_memory=device.type == "cuda",
        )

    val_loader = DataLoader(
        val_ds,
        batch_size=batch_size,
        shuffle=False,
        num_workers=0,
        pin_memory=device.type == "cuda",
    )

    model = build_model(cfg, in_dim=F).to(device)
    if args.init_ckpt is not None:
        ckpt_path = args.init_ckpt
        if not ckpt_path.is_file():
            raise FileNotFoundError(f"--init-ckpt not found: {ckpt_path}")
        ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        state = ckpt["model"] if isinstance(ckpt, dict) and "model" in ckpt else ckpt
        model.load_state_dict(state, strict=True)
        ep = ckpt.get("epoch") if isinstance(ckpt, dict) else "?"
        print(f"[train] init from {ckpt_path} (epoch={ep})")
    n_params = model.count_params()
    print(f"[train] run={run_dir.name} F={F} T={T} params={n_params/1e6:.3f}M device={device}")
    print(f"[train] windows train={len(train_ds)} val={len(val_ds)} batch={batch_size} epochs={epochs}")

    if args.dry_run:
        print("[train] dry-run OK — not training")
        write_json(run_dir / "dry_run.json", {"ok": True, "params": n_params})
        return

    if args.debug_one_batch:
        loader = make_train_loader(0)
        batch = next(iter(loader))
        out = model(batch["x"].to(device))
        loss, parts = total_loss(
            out["delta"],
            batch["y"].to(device),
            batch["conf"].to(device),
            out.get("motion_logits"),
            batch["motion"].to(device),
            cfg,
            features=batch["x"].to(device),
        )
        print("[debug-one-batch]", parts, "delta", tuple(out["delta"].shape))
        write_json(run_dir / "debug_one_batch.json", parts)
        return

    base_lr = float(ocfg.get("lr", 3e-4))
    opt = torch.optim.AdamW(
        model.parameters(),
        lr=base_lr,
        weight_decay=float(ocfg.get("weight_decay", 0.01)),
    )
    use_amp = bool(ocfg.get("amp", True)) and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    best_hard = float("inf")
    best_epoch = -1
    patience = int((cfg.get("eval") or {}).get("patience", 15))
    bad = 0
    easy_max_reg = float((cfg.get("eval") or {}).get("easy_max_regression", 0.03))

    geo_warmup = int((cfg.get("loss") or {}).get("geometry_warmup_epochs", hard_warmup))
    t0 = time.time()
    for epoch in range(epochs):
        lr = cosine_lr(epoch, epochs, base_lr, int(ocfg.get("warmup_epochs", 3)))
        for pg in opt.param_groups:
            pg["lr"] = lr
        # Residual first; ramp extend geometry after hard-window warmup.
        if geo_warmup <= 0:
            geo_scale = 1.0
        elif epoch < geo_warmup:
            geo_scale = 0.0
        elif epoch < geo_warmup + 3:
            geo_scale = float(epoch - geo_warmup + 1) / 3.0
        else:
            geo_scale = 1.0
        tr = train_one_epoch(
            model,
            make_train_loader(epoch),
            opt,
            device,
            cfg,
            scaler if use_amp else None,
            geometry_scale=geo_scale,
        )
        va = eval_delta(model, val_loader, device)

        # easy regression constraint vs MP baseline
        easy_ok = True
        if not math.isnan(va["mpjpe_easy_mm"]) and not math.isnan(va["mpjpe_mp_easy_mm"]):
            # corrected should not be much worse than MP on easy
            if va["mpjpe_easy_mm"] > va["mpjpe_mp_easy_mm"] * (1.0 + easy_max_reg) + 1.0:
                easy_ok = False

        record = {
            "epoch": epoch,
            "lr": lr,
            **{f"train/{k}": v for k, v in tr.items()},
            **{f"val/{k}": v for k, v in va.items()},
            "easy_ok": easy_ok,
            "elapsed_s": time.time() - t0,
        }
        log.log(record)
        print(
            f"epoch {epoch:03d} loss={tr['loss']:.4f} "
            f"reach={tr.get('l_reach', 0):.4f} "
            f"angle={tr.get('l_angle', 0):.4f} "
            f"ext={tr.get('extend_frac', 0):.2f} geo={geo_scale:.2f} "
            f"val_hard={va['mpjpe_hard_mm']:.2f} (mp={va['mpjpe_mp_hard_mm']:.2f}) "
            f"impr={va.get('hard_improvement_pct', float('nan')):.1f}% "
            f"easy_ok={easy_ok} lr={lr:.2e}",
            flush=True,
        )

        ckpt = {
            "epoch": epoch,
            "model": model.state_dict(),
            "opt": opt.state_dict(),
            "cfg": cfg,
            "F": F,
            "T": T,
            "val": va,
        }
        torch.save(ckpt, run_dir / "checkpoints" / "last.pt")

        metric = va["mpjpe_hard_mm"]
        improved = (not math.isnan(metric)) and metric < best_hard and easy_ok
        if improved:
            best_hard = metric
            best_epoch = epoch
            bad = 0
            torch.save(ckpt, run_dir / "checkpoints" / "best_hard.pt")
            write_json(run_dir / "eval" / f"val_epoch_{epoch:03d}.json", va)
        else:
            bad += 1
            if bad >= patience:
                print(f"[train] early stop at epoch {epoch} (best={best_epoch} hard={best_hard:.2f})")
                break

    best_path = run_dir / "checkpoints" / "best_hard.pt"
    last_path = run_dir / "checkpoints" / "last.pt"
    if not best_path.is_file() and last_path.is_file():
        # No easy_ok improvement — still keep a selectable ckpt for export/bench.
        import shutil

        shutil.copy2(last_path, best_path)
        print(f"[train] warn: no easy_ok best; copied last.pt -> best_hard.pt")

    write_json(
        run_dir / "summary.json",
        {
            "best_epoch": best_epoch,
            "best_hard_mm": best_hard if best_hard < float("inf") else None,
            "run_dir": str(run_dir),
            "elapsed_s": time.time() - t0,
        },
    )
    print(f"[train] done best_epoch={best_epoch} best_hard_mm={best_hard:.2f} -> {run_dir}")


if __name__ == "__main__":
    main()
