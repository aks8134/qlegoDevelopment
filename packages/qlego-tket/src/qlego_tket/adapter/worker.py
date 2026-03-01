# qlego_tket/worker.py
from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import Any, Dict

JSON = Dict[str, Any]


def _import_symbol(ref: str):
    mod, sep, name = ref.partition(":")
    if not sep or not mod or not name:
        raise ValueError("pass_class must look like 'module:ClassName'")
    m = importlib.import_module(mod)
    return getattr(m, name)


def main() -> int:
    ap = argparse.ArgumentParser(description="tket plugin worker (run a QPass class)")
    ap.add_argument("--pass-class", required=True, help="module:ClassName")
    args = ap.parse_args()

    payload = json.loads(sys.stdin.read())
    ctxd = payload["ctx"]
    cfg = payload.get("pass_cfg", {}) or {}

    PassCls = _import_symbol(args.pass_class)

    # Instantiate pass
    if hasattr(PassCls, "from_config") and callable(getattr(PassCls, "from_config")):
        p = PassCls.from_config(cfg)
    else:
        p = PassCls(**cfg)

    # Build ctx
    from qlego.qpass import QPassContext
    ctx = QPassContext(
        qasm=ctxd["qasm"],
        seed=ctxd.get("seed"),
        hardware=ctxd.get("hardware"),
        metadata=ctxd.get("metadata", {}),
    )

    out_ctx = p.run(ctx)

    # JSON-only stdout
    sys.stdout.write(json.dumps({"ctx": {
        "qasm": out_ctx.qasm,
        "seed": out_ctx.seed,
        "hardware": out_ctx.hardware,
        "metadata": out_ctx.metadata,
    }}))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        sys.stderr.write(str(e) + "\n")
        raise
