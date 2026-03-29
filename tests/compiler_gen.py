import os

from qlego.registry import PassRegistry
from qlego_generator.registry import aggregate_from_environment, aggregate_from_script
from qlego.qpass import QPipeline, QPassContext

# Trigger runtime aggregation of local plugin registries (now handled safely by generator)
aggregate_from_environment("envs/env_config.json")
aggregate_from_script("custom_passes.py")

# Fetch categorized registry references for the pipeline build
circuits = PassRegistry.get_passes_by_category("Circuit Creation")
inits = PassRegistry.get_passes_by_category("Initialization")
layouts = PassRegistry.get_passes_by_category("Layout")
routings = PassRegistry.get_passes_by_category("Routing")
translations = PassRegistry.get_passes_by_category("Translation")
optimizations = PassRegistry.get_passes_by_category("Optimization")
schedulings = PassRegistry.get_passes_by_category("Scheduling")
evaluations = PassRegistry.get_passes_by_category("Evaluation")

print("Circuit Passes")
print(circuits)
print("Init Passes")
print(inits)
print("Layout Passes")
print(layouts)
print("Routing Passes")
print(routings)
print("Translation Passes")
print(translations)
print("Optimization Passes")
print(optimizations)
print("Scheduling Passes")
print(schedulings)
print("Evaluation Passes")
print(evaluations)
# Removed conditional block from here

# Generate the payload if missing
if not os.path.exists("backend.json"):
    import subprocess
    subprocess.run(["envs/env_1/bin/python", "dump_backend.py"], check=True)

with open("backend.json", "r") as f:
    backend = f.read()

def build_toolcentric_qpipeline(
    coupling_map,
    basis_gates,
    *,
    optimization_level: int = 2,
    seed: int | None = 0,
    instruction_durations=None,
):
    # lp = LayoutPass( optimization_level)
    # print(lp.c_name())
    return QPipeline([
        circuits["qlego-mqt-workload_DJCircuitInitialization"](5),
        inits["qlego-qiskit_PresetInitPass"](),
        layouts["qlego-qiskit_PresetLayoutPass"](),
        routings["qlego-qiskit_PresetRoutingPass"](),
        translations["qlego-qiskit_PresetTranslationPass"](),
        optimizations["qlego-qiskit_PresetOptimizationPass"](),
        optimizations["custom-passes_MyCustomPass"](),
        schedulings["qlego-qiskit_PresetSchedulingPass"](),
        evaluations["qlego-evaluation_EvaluationPass"](),
        # verifications["qlego-mqt-verification_MQTVerficiation"](),
    ], env_config_path="envs/env_config.json")

cm = []

pipeline = build_toolcentric_qpipeline(
    coupling_map=cm,
    basis_gates=["rz", "sx", "x", "cx", "measure"],
    optimization_level=2,
    seed=42,
)

ctx = QPassContext(
    hardware=backend
)

out_ctx = pipeline.run("", ctx)
final_qasm = out_ctx.qasm
eval_metrics = out_ctx.metadata
print(final_qasm)
# qc = loads(final_qasm, custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS)
# print(qc)
print("Evaluation Metrics")
print(eval_metrics)
# print("Coupling Map Edges")
# print(QBackend.from_json(backend).edges)