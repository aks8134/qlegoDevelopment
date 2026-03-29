import os
from qlego.qpass import QPass

from qlego.registry import register_pass

@register_pass("Verification")
class MQTVerification(QPass):
    name = "Verification Pass"
    venv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.venv/bin/python"))
    def __init__(self):
        pass


    def run(self, ctx):
        from mqt.qcec import verify, verify_compilation
        from qiskit.qasm2 import loads, LEGACY_CUSTOM_INSTRUCTIONS
        import json
        
        # Debugging artifacts
        json.dump(ctx.qasm, open("temp_final_circ.json", "w"))
        json.dump(ctx.metadata.get("initial_qasm", ""), open("temp_initial_circ.json", "w"))
        
        initial_qc = loads(ctx.metadata["initial_qasm"], custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS)
        final_qc = loads(ctx.qasm, custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS)

        layout_info = ctx.metadata.get("layout", None)
        if layout_info:
            from qiskit.transpiler import TranspileLayout, Layout
            from qiskit.circuit import QuantumCircuit, QuantumRegister, AncillaRegister
            in_qbs = initial_qc.qubits
            num_physical = final_qc.num_qubits
            num_logical = len(in_qbs)
            num_ancilla = num_physical - num_logical

            init_layout = list(layout_info["initial"])
            final_layout_list = list(layout_info["final"])

            # Correct the final layout using measurement info: in the original
            # circuit, logical qubit k is measured to c[k]. In the compiled
            # circuit, if c[k] measures physical qubit p, then logical qubit k
            # ended at physical position p.
            # Also detect if the initial layout is stale (a position in the
            # layout isn't even used in the circuit).
            # Correct final layout using measurement info from both circuits.
            # In the original circuit, c[k] measures logical qubit k_orig.
            # In the compiled circuit, c[k] measures physical qubit p.
            # Therefore logical qubit k_orig ended at physical position p.
            orig_meas = {}  # c[k] -> logical qubit index in original
            for inst in initial_qc.data:
                if inst.operation.name == "measure":
                    qi = initial_qc.qubits.index(inst.qubits[0])
                    ci = initial_qc.clbits.index(inst.clbits[0])
                    orig_meas[ci] = qi

            compiled_meas = {}  # c[k] -> physical qubit in compiled
            for inst in final_qc.data:
                if inst.operation.name == "measure":
                    qi = final_qc.qubits.index(inst.qubits[0])
                    ci = final_qc.clbits.index(inst.clbits[0])
                    compiled_meas[ci] = qi

            # For each classical bit, logical qubit orig_meas[k] ends at compiled_meas[k]
            assigned_positions = set()
            for ci in orig_meas:
                if ci in compiled_meas:
                    k = orig_meas[ci]
                    final_layout_list[k] = compiled_meas[ci]
                    assigned_positions.add(compiled_meas[ci])

            # For unmeasured logical qubits, assign from remaining used positions
            used_qubits = set()
            for inst in final_qc.data:
                for q in inst.qubits:
                    used_qubits.add(final_qc.qubits.index(q))
            remaining_used = sorted(used_qubits - assigned_positions)
            for k in range(num_logical):
                if k not in [orig_meas.get(ci) for ci in orig_meas if ci in compiled_meas]:
                    if remaining_used:
                        final_layout_list[k] = remaining_used.pop(0)

            # Check if any initial positions are not used in the circuit,
            # indicating the routing stage moved qubits without tracking.
            init_positions_used = all(p in used_qubits for p in init_layout)
            if not init_positions_used:
                init_layout = list(final_layout_list)

            # Rebuild final_qc with proper register structure so MQT can
            # identify ancilla qubits (it checks for AncillaRegister).
            if num_ancilla > 0:
                qr = QuantumRegister(num_logical, "q")
                anc = AncillaRegister(num_ancilla, "ancilla")
                new_qc = QuantumCircuit(qr, anc, *final_qc.cregs)
                old_to_new = dict(zip(final_qc.qubits, new_qc.qubits))
                for inst in final_qc.data:
                    new_qc.append(
                        inst.operation,
                        [old_to_new[q] for q in inst.qubits],
                        list(inst.clbits),
                    )
                final_qc = new_qc
            else:
                qr = final_qc.qregs[0]

            qr = final_qc.qregs[0]
            anc_reg = final_qc.qregs[1] if num_ancilla > 0 else None
            out_qbs = final_qc.qubits

            # initial_layout: map logical qr[k] -> physical position init[k],
            # ancilla qubits to the remaining physical positions.
            initial_layout_dict = {}
            for k in range(num_logical):
                initial_layout_dict[qr[k]] = init_layout[k]
            if anc_reg is not None:
                used_positions = set(init_layout)
                anc_positions = [p for p in range(num_physical) if p not in used_positions]
                for j in range(len(anc_reg)):
                    initial_layout_dict[anc_reg[j]] = anc_positions[j]
            initial_layout_obj = Layout(initial_layout_dict)
            initial_layout_obj._regs = list(final_qc.qregs)

            # input_qubit_mapping: qr[k] -> k, anc[j] -> num_logical + j
            input_mapping = {}
            for k in range(num_logical):
                input_mapping[qr[k]] = k
            if anc_reg is not None:
                for j in range(len(anc_reg)):
                    input_mapping[anc_reg[j]] = num_logical + j

            # final_layout
            final_layout_dict = {out_qbs[p]: p for p in range(num_physical)}
            for k in range(num_logical):
                final_layout_dict[out_qbs[init_layout[k]]] = final_layout_list[k]
            final_layout_obj = Layout(final_layout_dict)

            tl = TranspileLayout(
                initial_layout=initial_layout_obj,
                input_qubit_mapping=input_mapping,
                final_layout=final_layout_obj,
                _input_qubit_count=num_logical,
                _output_qubit_list=list(out_qbs),
            )
            final_qc._layout = tl

        results = verify_compilation( initial_qc, final_qc )
        ctx.metadata["exact_equivalence"] = str(results.equivalence)
        results = verify_compilation( initial_qc, final_qc, check_partial_equivalence=True )
        ctx.metadata["partial_equivalence"] = str(results.equivalence)

        return ctx