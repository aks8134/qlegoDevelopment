import os
from qlego.qpass import QPass

class MQTVerficiation(QPass):
    name = "Verification Pass"
    venv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.venv/bin/python"))
    def __init__(self):
        pass


    def run(self, ctx):
        from mqt.qcec import verify
        from qiskit.qasm2 import loads
        import json
        json.dump(ctx.qasm, open("temp_final_circ.json", "w"))
        json.dump(ctx.metadata["initial_qasm"], open("temp_initial_circ.json", "w"))
        # circ1 = loads()
        results = verify( ctx.qasm, ctx.metadata["initial_qasm"], backpropagate_output_permutation=True )
        ctx.metadata["exact_equivalence"] = str(results.equivalence)
        results = verify( ctx.qasm, ctx.metadata["initial_qasm"], check_partial_equivalence=True, backpropagate_output_permutation=True )
        ctx.metadata["partial_equivalence"] = str(results.equivalence)

        return ctx