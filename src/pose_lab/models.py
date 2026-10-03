"""Causal pose corrector models (GRU / optional TCN)."""



from __future__ import annotations



import torch

import torch.nn as nn



from .labels import MOTION_LABELS

from .skeleton import DELTA_DIM





def take_delta_last(delta: torch.Tensor) -> torch.Tensor:

    """Accept (B, D) or (B, T, D) and return last-frame (B, D)."""

    if delta.ndim == 3:

        return delta[:, -1]

    return delta





class CausalGRUCorrector(nn.Module):

    """x: (B, T, F) → delta at last step (B, D) or full sequence (B, T, D)."""



    def __init__(

        self,

        in_dim: int,

        hidden: int = 256,

        layers: int = 2,

        dropout: float = 0.1,

        aux_motion: bool = True,

        n_motion: int = len(MOTION_LABELS),

        delta_dim: int = DELTA_DIM,

        predict_sequence: bool = False,

    ):

        super().__init__()

        self.in_dim = in_dim

        self.delta_dim = delta_dim

        self.aux_motion = aux_motion

        self.predict_sequence = bool(predict_sequence)

        self.input_norm = nn.LayerNorm(in_dim)

        self.gru = nn.GRU(

            input_size=in_dim,

            hidden_size=hidden,

            num_layers=layers,

            batch_first=True,

            dropout=dropout if layers > 1 else 0.0,

        )

        self.head_delta = nn.Sequential(

            nn.LayerNorm(hidden),

            nn.Linear(hidden, hidden),

            nn.GELU(),

            nn.Dropout(dropout),

            nn.Linear(hidden, delta_dim),

        )

        self.head_motion = nn.Linear(hidden, n_motion) if aux_motion else None



    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:

        # x: (B, T, F)

        h, _ = self.gru(self.input_norm(x))

        if self.predict_sequence:

            delta = self.head_delta(h)  # (B, T, D)

        else:

            delta = self.head_delta(h[:, -1])  # (B, D)

        out: dict[str, torch.Tensor] = {"delta": delta}

        if self.head_motion is not None:

            out["motion_logits"] = self.head_motion(h[:, -1])

        return out



    def count_params(self) -> int:

        return sum(p.numel() for p in self.parameters() if p.requires_grad)





def build_model(cfg: dict, in_dim: int, delta_dim: int | None = None) -> nn.Module:

    mcfg = cfg.get("model") or {}

    name = str(mcfg.get("name", "gru")).lower()

    hidden = int(mcfg.get("hidden", 256))

    layers = int(mcfg.get("layers", 2))

    dropout = float(mcfg.get("dropout", 0.1))

    aux = bool(mcfg.get("aux_motion", True))

    predict_sequence = bool(mcfg.get("predict_sequence", False))

    ddim = int(delta_dim) if delta_dim is not None else DELTA_DIM

    if name in ("gru", "causal_gru"):

        model = CausalGRUCorrector(

            in_dim=in_dim,

            hidden=hidden,

            layers=layers,

            dropout=dropout,

            aux_motion=aux,

            delta_dim=ddim,

            predict_sequence=predict_sequence,

        )

    else:

        raise ValueError(f"Unsupported model.name={name!r} (v1 implements gru only)")

    max_m = float(mcfg.get("max_params_m", 2.0))

    n = model.count_params()

    if n > max_m * 1e6:

        raise RuntimeError(f"model has {n/1e6:.2f}M params > max {max_m}M")

    return model


