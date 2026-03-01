import os
from qlego.qpass import QPass, QPassContext
import json
import subprocess

class EvaluationPass(QPass):
    venv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.venv/bin/python"))
    name = "Evaluation Pass"
    def run(self, ctx):
        from qiskit.qasm2 import loads, dumps, LEGACY_CUSTOM_INSTRUCTIONS # qasm2/qasm3 here
        from .metrics import MetricsAggregator, GateCount, Depth, Q2Count, Q2Depth
        qc = loads(ctx.qasm, custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS)
        ma = MetricsAggregator(qc)
        ma.append([ GateCount, Depth, Q2Count, Q2Depth ])
        metric_dict = ma.compute()
        ctx.metadata["evaluation_metrics"] = metric_dict
        return ctx