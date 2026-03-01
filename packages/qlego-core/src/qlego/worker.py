# qlego_qiskit/worker.py
from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import Any, Dict

JSON = Dict[str, Any]

from .timer import timer


def _import_symbol(ref: str):
    """
    ref format: "package.module:SymbolName"
    Example: "qpassport.qlego_qiskit.adapter.passes:LayoutPass"
    """
    mod, sep, name = ref.partition(":")
    if not sep or not mod or not name:
        raise ValueError("pass_class must look like 'package.module:SymbolName'")
    m = importlib.import_module(mod)
    try:
        return getattr(m, name)
    except AttributeError:
        raise ImportError(f"Symbol '{name}' not found in module '{mod}'")


def main() -> int:
    ap = argparse.ArgumentParser(description="Qiskit plugin worker (run a QPass class)")
    ap.add_argument("--pass-class", required=True, help="Dotted ref 'module:ClassName'")
    args = ap.parse_args()

    payload = json.loads(sys.stdin.read())
    # print(payload)
    # --- ctx payload ---
    # Expect ctx to be a JSON dict containing at least "qasm".
    ctxd = payload.get("ctx", {})
    if not isinstance(ctxd, dict):
        raise ValueError("payload['ctx'] must be a dict")
    if "qasm" not in ctxd:
        raise ValueError("payload['ctx']['qasm'] is required")

    # # --- pass payload ---
    cfg = payload.get("pass_cfg", {})
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise ValueError("payload['pass_cfg'] must be a dict")

    PassCls = _import_symbol(args.pass_class)

    # Build pass instance.
    # Recommended: implement @classmethod from_config on your passes.
    if hasattr(PassCls, "from_config") and callable(getattr(PassCls, "from_config")):
        p = PassCls.from_config(cfg)
    else:
        # fallback: treat cfg as kwargs
        p = PassCls(**cfg)

    # Build QPassContext in the plugin env.
    # This requires core.qpass to be importable in the plugin venv.
    from qlego.qpass import QPassContext

    # ctx = QPassContext(
    #     seed=ctxd.get("seed", None),
    #     hardware=ctxd.get("hardware", None),
    #     metadata=ctxd.get("metadata", {}),
    #     qasm=ctxd.get("qasm", None),
    # )
    ctx = QPassContext.from_dict(ctxd)
    with timer("algo_time") as algo_time:
        out_ctx = p.run(ctx)

    out_ctx.metadata["time_profile"][p.name]["pass"] = {k : v for k,v in algo_time.items() if k in ["wall", "cpu", "non_cpu"]}

    sys.stdout.write(
        out_ctx.to_json()
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        sys.stderr.write(str(e) + "\n")
        raise
