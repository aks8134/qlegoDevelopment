# qpass.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import json
import subprocess
from .timer import timer

JSON = Dict[str, Any]


@dataclass
class QPassContext:
    """
    Shared context across passes in a pipeline run.
    Use this to carry:
      - hardware model (coupling map, basis, noise model id, etc.)
      - deterministic seed
      - accumulated artifacts/metadata
    """
    hardware: Optional[JSON] = None
    metadata: JSON = field(default_factory=dict)
    qasm: Optional[str] = None 

    def store(self, key: str, value: Any) -> None:
        """Store an artifact in the context."""
        self.metadata[key] = value

    def to_dict(self):
        return {
            "qasm" : self.qasm,
            "hardware" : self.hardware,
            "metadata" : self.metadata
        }
    @classmethod
    def from_dict(cls, cfg_dict):
        return cls( 
            qasm = cfg_dict["qasm"],
            hardware = cfg_dict["hardware"],
            metadata = cfg_dict["metadata"]
        )

    def to_json( self ):
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str):
        cfg_dict = json.loads(json_str)
        return cls.from_dict(cfg_dict)


class QPass(ABC):
    """
    Abstract pass: QASM in -> QASM out.

    Contract:
      - input and output are QASM strings (ideally OpenQASM 3).
      - pass may read/write ctx.metadata for artifacts.
      - pass should be deterministic given the same input + ctx.seed + ctx.hardware.
    """
    name: str = "QPass"
    venv_path :str = "random_string"

    def __call__(self, ctx: Optional[QPassContext] = None):
        if ctx is None:
            ctx = QPassContext()
        return self.executor(ctx)
    
    def c_name(self):
        return f"{self.__class__.__module__}:{self.__class__.__name__}"
    
    @classmethod
    def from_config(cls, cfg ):
        return cls(**cfg)
    
    def to_config(self):
        return {}
    
    def executor(self, ctx):
        ctx.metadata["time_profile"][self.name] = {}
        with timer("total") as total_t:
            payload = {
                "pass_cfg": self.to_config(),
                "ctx": ctx.to_dict(),
            }
            print( self.c_name())
            # print(payload)
            proc = subprocess.run(
                [
                    self.venv_path,
                    "-m",
                    "qlego.worker",
                    "--pass-class",
                    self.c_name(),
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
            )
            print("Hi printing something here")
            # print("STDOUT repr:", repr(proc.stdout))
            print("STDERR repr:", repr(proc.stderr))
            
            # Check for subprocess errors
            if proc.returncode != 0:
                raise RuntimeError(f"Worker subprocess failed with code {proc.returncode}\nSTDERR: {proc.stderr}\nSTDOUT: {proc.stdout}")
            
            # Check for empty output
            if not proc.stdout.strip():
                raise RuntimeError(f"Worker subprocess returned no output\nSTDERR: {proc.stderr}")
            
            out = json.loads(proc.stdout)
        
        ctx = QPassContext.from_dict(out)
        # print(ctx.qasm)
        ctx.metadata["time_profile"][self.name]["total"] = {k:v for k, v in total_t.items() if k in [ "wall", "cpu", "non_cpu"]}
        return ctx

    @abstractmethod
    def run(self, ctx: QPassContext) -> str:
        raise NotImplementedError


class QPipeline:
    """Simple sequential runner for QPass objects."""
    def __init__(self, passes: List[QPass]) -> None:
        self.passes = passes

    def run(self, qasm_in: str, ctx: Optional[QPassContext] = None) -> QPassContext:
        if ctx is None:
            ctx = QPassContext(qasm = qasm_in)
        ctx.metadata["time_profile"] = {}
        for p in self.passes:
            ctx = p(ctx)
        return ctx
