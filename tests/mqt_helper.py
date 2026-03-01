from qlego_mqt_workload.adapter.passes import *

class DJCircuitInitialization(MQTWorkloadPass):
    name = "DJ Circuit Pass"

    def run(self, ctx):
        from mqt.bench import BenchmarkLevel, get_benchmark
        from qiskit.qasm2 import dumps

        qc = get_benchmark(benchmark="ghz", level=BenchmarkLevel.ALG, circuit_size=5)
        ctx.qasm = dumps(qc)
        ctx.metadata["initial_qasm"] = ctx.qasm
        # print(ctx.qasm)
        return ctx
