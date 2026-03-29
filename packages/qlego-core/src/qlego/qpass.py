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
    def __init__(self, passes: List[QPass], env_config_path: Optional[str] = "envs/env_config.json") -> None:
        import os
        self.passes = passes
        self.env_config = {}
        if env_config_path and os.path.exists(env_config_path):
            try:
                with open(env_config_path, "r") as f:
                    self.env_config = json.load(f)
            except Exception as e:
                print(f"Warning: could not read env config from {env_config_path}: {e}")

    def run(self, qasm_in: str, ctx: Optional[QPassContext] = None) -> QPassContext:
        import sys
        if ctx is None:
            ctx = QPassContext(qasm=qasm_in)
        ctx.metadata["time_profile"] = {}
        
        # Resolve venv_path for each pass based on origin package
        for p in self.passes:
            module_name = p.__class__.__module__.partition(".")[0]
            resolved = False
            if module_name in self.env_config:
                p.venv_path = self.env_config[module_name]["venv_path"]
                resolved = True
            else:
                for base in p.__class__.__mro__:
                    b_mod = base.__module__.partition(".")[0]
                    if b_mod in self.env_config:
                        p.venv_path = self.env_config[b_mod]["venv_path"]
                        resolved = True
                        break
            
            if not resolved:
                if p.venv_path == "random_string" or ".venv/bin/python" in getattr(p, "venv_path", "") or not os.path.exists(p.venv_path):
                    # Fallback to current execution environment
                    p.venv_path = sys.executable

        # Group contiguous passes by venv_path
        groups = []
        for p in self.passes:
            if not groups:
                groups.append({"venv_path": p.venv_path, "passes": [p]})
            else:
                if groups[-1]["venv_path"] == p.venv_path:
                    groups[-1]["passes"].append(p)
                else:
                    groups.append({"venv_path": p.venv_path, "passes": [p]})

        for group in groups:
            ctx = self._run_group(group["passes"], group["venv_path"], ctx)
            
        return ctx

    def _run_group(self, passes: List[QPass], venv_path: str, ctx: QPassContext) -> QPassContext:
        if not passes:
            return ctx
            
        with timer("total") as total_t:
            payload = {
                "passes": [{"class": p.c_name(), "cfg": p.to_config()} for p in passes],
                "ctx": ctx.to_dict(),
            }
            
            group_names = ", ".join(p.name for p in passes)
            # print(f"Running group [{group_names}] in {venv_path}")
            
            proc = subprocess.run(
                [venv_path, "-m", "qlego.worker", "--group"],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
            )
            
            if proc.returncode != 0:
                raise RuntimeError(f"Worker subprocess failed with code {proc.returncode}\nSTDERR: {proc.stderr}\nSTDOUT: {proc.stdout}")
                
            if not proc.stdout.strip():
                raise RuntimeError(f"Worker subprocess returned no output\nSTDERR: {proc.stderr}")
                
            out = json.loads(proc.stdout)
            ctx = QPassContext.from_dict(out)
            
        time_res = {k:v for k, v in total_t.items() if k in ["wall", "cpu", "non_cpu"]}
        for p in passes:
            if p.name not in ctx.metadata["time_profile"]:
                ctx.metadata["time_profile"][p.name] = {}
            ctx.metadata["time_profile"][p.name]["total"] = time_res
            
        return ctx
