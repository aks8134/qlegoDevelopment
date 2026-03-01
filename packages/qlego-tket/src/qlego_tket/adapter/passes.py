from __future__ import annotations
import os
# core/tket_remote_pass.py

import json
import os
import subprocess
from typing import Any, Dict, Optional

from qlego.qpass import QPass, QPassContext
from qlego_tket.adapter.backend import QBackend, TketBackend
JSON = Dict[str, Any]


class TKetPass(QPass):
    venv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.venv/bin/python"))
    def __init__(self, tket_passes):
        self.tket_passes = tket_passes

    def get_compatible_backend(self, backend):
        from pytket.backends.backendinfo import BackendInfo

        if(isinstance(backend, BackendInfo)):
            return backend
        elif(isinstance(backend, QBackend)):
            return backend.to_tket_backend_info()
        elif(isinstance(backend, str)):
            backend = TketBackend.from_json(backend)
            return backend.to_tket_backend_info()
        else:
            raise TypeError("Invalid type of backend given")

    def run( self, ctx: QPassContext ):
        from pytket.qasm import circuit_from_qasm_str, circuit_to_qasm_str
        from pytket.passes import BasePass, SequencePass

        circ = circuit_from_qasm_str(ctx.qasm)

        # Apply passes in-place
        for p in self.tket_passes:
            if isinstance(p, BasePass):
                p.apply(circ)
            elif isinstance(p, (list, tuple)):
                SequencePass(list(p)).apply(circ)
            else:
                raise TypeError(f"Incompatible tket pass type: {type(p)}")

        # Make implicit wire swaps explicit so the QASM reflects routing changes
        circ.replace_implicit_wire_swaps()

        ctx.qasm = circuit_to_qasm_str(circ, header="qelib1")

        return ctx

    # def executor(self, ctx: QPassContext) -> QPassContext:
    #     payload = {
    #         "pass_cfg": self.to_config(),
    #         "ctx": {
    #             "qasm": ctx.qasm,
    #             "seed": ctx.seed,
    #             "hardware": ctx.hardware,
    #             "metadata": ctx.metadata,
    #         },
    #     }

    #     proc = subprocess.run(
    #         ["./tket_plugin/.venv/bin/python",
    #           "-u", 
    #           "-m",
    #           "core.worker",
    #           "--pass-class", 
    #           self.c_name()
    #         ],
    #         input=json.dumps(payload),
    #         text=True,
    #         capture_output=True,
    #         env=os.environ.copy(),
    #     )

    #     if proc.returncode != 0:
    #         raise RuntimeError(f"tket worker failed\nSTDERR:\n{proc.stderr}\nSTDOUT:\n{proc.stdout}")

    #     # Parse last JSON object in stdout (robust to stray prints)
    #     lines = proc.stdout.splitlines()
    #     json_line = next((ln for ln in reversed(lines) if ln.lstrip().startswith("{")), None)
    #     if json_line is None:
    #         raise RuntimeError(f"No JSON in tket worker stdout:\n{proc.stdout}")

    #     out = json.loads(json_line)["ctx"]
    #     ctx.qasm = out["qasm"]
    #     ctx.metadata = out.get("metadata", ctx.metadata)
    #     return ctx
