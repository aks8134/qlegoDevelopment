import os
from qlego_bqskit.adapter.backend import BQSKITBackend, QBackend
from qlego.qpass import QPass, QPassContext
def _bqskit_circuit_from_qasm_str(qasm: str):
    from bqskit import Circuit
    import tempfile, os
    import re
    
    # Remove measurements and classical registers for BQSKit processing
    # They'll be restored later or added back at the end of the pipeline
    qasm_no_measurements = re.sub(r'creg\s+\w+\[\d+\];', '', qasm)
    qasm_no_measurements = re.sub(r'measure\s+\w+\[\d+\]\s*->\s*\w+\[\d+\];', '', qasm_no_measurements)
    qasm_no_measurements = re.sub(r'barrier[^;]*;', '', qasm_no_measurements)  # Also remove barriers
    
    f = tempfile.NamedTemporaryFile("w", suffix=".qasm", delete=False)
    try:
        f.write(qasm_no_measurements)
        f.close()
        return Circuit.from_file(f.name)
    finally:
        try:
            os.remove(f.name)
        except OSError:
            pass


# In _bqskit_circuit_to_qasm_str
def _bqskit_circuit_to_qasm_str(circ):
    import tempfile, os
    import re
    
    f = tempfile.NamedTemporaryFile("w+", suffix=".qasm", delete=False)
    try:
        f.close()
        circ.save(f.name)
        with open(f.name, "r") as g:
            qasm = g.read()
            # Remove duplicate creg declarations
            lines = qasm.split('\n')
            seen_cregs = set()
            cleaned_lines = []
            for line in lines:
                if line.strip().startswith('creg'):
                    if line.strip() not in seen_cregs:
                        seen_cregs.add(line.strip())
                        cleaned_lines.append(line)
                else:
                    cleaned_lines.append(line)
            return '\n'.join(cleaned_lines)
    finally:
        try:
            os.remove(f.name)
        except OSError:
            pass


class BQSKITPass(QPass):
    name = "bqskit_pass"
    venv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.venv/bin/python"))
    def __init__(self, bqskit_passes):
        """
        bqskit_passes: iterable of BQSKit BasePass OR a BQSKit Workflow
        num_workers: forwarded to bqskit.compiler.Compiler
        request_data: if True, store BQSKit PassData mapping info into ctx.metadata
        """
        self.bqskit_passes = bqskit_passes
        # self.num_workers = num_workers
        # self.request_data = request_data

    def get_compatible_backend(self, backend):
        from bqskit.compiler import MachineModel

        if isinstance(backend, MachineModel):
            return backend
        elif isinstance(backend, QBackend):
            # If it's already our BQSKITBackend subclass, it has to_bqskit_machine_model.
            return backend.to_bqskit_machine_model()
        elif isinstance(backend, str):
            backend = BQSKITBackend.from_json(backend)
            return backend.to_bqskit_machine_model()
        else:
            raise TypeError("Invalid type of backend given")

    def run(self, ctx: QPassContext) -> QPassContext:
        from bqskit.compiler import Compiler, Workflow
        from bqskit.passes import SetModelPass

        circ = _bqskit_circuit_from_qasm_str(ctx.qasm)

        # Build workflow
        # if hasattr(self.bqskit_passes, "run") and hasattr(self.bqskit_passes, "__iter__") is False:
        #     # very defensive: if someone passed a single pass object
        #     workflow = Workflow([self.bqskit_passes])
        # else:
        #     # WorkflowLike is a Workflow OR iterable of passes. :contentReference[oaicite:6]{index=6}
        workflow = Workflow(self.bqskit_passes)

        # If ctx.hardware exists, encode it into the workflow using SetModelPass.
        # (Compiler.compile itself does not take a model kwarg.) :contentReference[oaicite:7]{index=7} :contentReference[oaicite:8]{index=8}
        if getattr(ctx, "hardware", None) is not None:
            model = self.get_compatible_backend(ctx.hardware)
            workflow = Workflow([SetModelPass(model)]) + workflow

        # Run compilation
        # Compiler.compile signature: (circuit, workflow, request_data=..., data=...). :contentReference[oaicite:9]{index=9}
        with Compiler() as compiler:
            # if self.request_data:
            #     compiled, data = compiler.compile(circ, workflow, request_data=True)
            #     # PassData exposes initial_mapping/final_mapping/placement. :contentReference[oaicite:10]{index=10}
            #     ctx.metadata.setdefault("bqskit", {})
            #     ctx.metadata["bqskit"]["initial_mapping"] = getattr(data, "initial_mapping", None)
            #     ctx.metadata["bqskit"]["final_mapping"] = getattr(data, "final_mapping", None)
            #     ctx.metadata["bqskit"]["placement"] = getattr(data, "placement", None)
            # else:
            compiled = compiler.compile(circ, workflow)

        ctx.qasm = _bqskit_circuit_to_qasm_str(compiled)
        return ctx



