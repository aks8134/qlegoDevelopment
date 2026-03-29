import os
from qlego.qpass import QPass

class MQTWorkloadPass(QPass):
    name = "MQT Workload Pass"
    venv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.venv/bin/python"))

    def run( self ):
        pass


from qlego.registry import register_pass


@register_pass("Circuit Creation")
class CircuitInitialization(MQTWorkloadPass):
    def __init__(self, num_qubits):
        self.num_qubits = num_qubits

    # @classmethod
    # def from_config(cls, cfg ):
    #     return cls(**cfg)
    
    def to_config(self):
        return {
            "num_qubits": self.num_qubits
        }

    def run(self, ctx):
        from mqt.bench import BenchmarkLevel, get_benchmark
        from qiskit.qasm2 import dumps

        qc = get_benchmark(benchmark=self.benchmark, level=BenchmarkLevel.ALG, circuit_size=self.num_qubits)
        ctx.qasm = dumps(qc)
        ctx.metadata["initial_qasm"] = ctx.qasm
        return ctx


@register_pass("Circuit Creation")
class DJCircuitInitialization(CircuitInitialization):
    name = "DJ Circuit"
    benchmark = "dj"   

@register_pass("Circuit Creation")
class GHZCircuitInitialization(CircuitInitialization):
    name = "GHZ Circuit"
    benchmark = "ghz"   
    
@register_pass("Circuit Creation")
class GroverCircuitInitialization(CircuitInitialization):
    name = "Grover Circuit"
    benchmark = "grover" 

@register_pass("Circuit Creation")
class QFTCircuitInitialization(CircuitInitialization):
    name = "QFT Circuit"
    benchmark = "qft" 

@register_pass("Circuit Creation")
class AECircuitInitialization(CircuitInitialization):
    name = "Amplitude Estimation Circuit"
    benchmark = "ae" 

@register_pass("Circuit Creation")
class QPECircuitInitialization(CircuitInitialization):
    name = "Quantum Phase Estimation Circuit"
    benchmark = "qpeexact" 

@register_pass("Circuit Creation")
class ShorCircuitInitialization(CircuitInitialization):
    name = "Shor Circuit"
    benchmark = "shor" 

@register_pass("Circuit Creation")
class WStateCircuitInitialization(CircuitInitialization):
    name = "W State Circuit"
    benchmark = "wstate" 

@register_pass("Circuit Creation")
class HalfAdderCircuitInitialization(CircuitInitialization):
    name = "Half Adder Circuit"
    benchmark = "half_adder"

@register_pass("Circuit Creation")
class BVCircuitInitialization(CircuitInitialization):
    name = "BV Circuit"
    benchmark = "bv"

@register_pass("Circuit Creation")
class GraphStateCircuitInitialization(CircuitInitialization):
    name = "Graph State Circuit"
    benchmark = "graphstate"

