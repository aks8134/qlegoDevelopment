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
    ap.add_argument("--pass-class", required=False, help="Dotted ref 'module:ClassName'")
    ap.add_argument("--group", action="store_true", help="Run a group of passes")
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

    from qlego.qpass import QPassContext
    ctx = QPassContext.from_dict(ctxd)

    if args.group:
        passes_cfg = payload.get("passes", [])
        for p_info in passes_cfg:
            PassCls = _import_symbol(p_info["class"])
            cfg = p_info.get("cfg", {})
            if hasattr(PassCls, "from_config") and callable(getattr(PassCls, "from_config")):
                p = PassCls.from_config(cfg)
            else:
                p = PassCls(**cfg)
            
            with timer("algo_time") as algo_time:
                print(f"Starting pass {p.name}", file=sys.stderr)
                ctx = p.run(ctx)
                print(f"Finished pass {p.name}", file=sys.stderr)
            
            if p.name not in ctx.metadata.get("time_profile", {}):
                if "time_profile" not in ctx.metadata:
                    ctx.metadata["time_profile"] = {}
                ctx.metadata["time_profile"][p.name] = {}
            ctx.metadata["time_profile"][p.name]["pass"] = {k : v for k,v in algo_time.items() if k in ["wall", "cpu", "non_cpu"]}
        
        sys.stdout.write(ctx.to_json())
        return 0

    # Old --pass-class behavior fallback
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

    with timer("algo_time") as algo_time:
        out_ctx = p.run(ctx)

    if p.name not in out_ctx.metadata.get("time_profile", {}):
        if "time_profile" not in out_ctx.metadata:
            out_ctx.metadata["time_profile"] = {}
        out_ctx.metadata["time_profile"][p.name] = {}
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
