from utils import *

from tqdm import tqdm 
import argparse


def run_experiments(add_verification = False):
    original_add_verification = add_verification
    backend = FakeBrooklynV2()
    results = []
    for num_qubits in tqdm([5, 
                            10, 
                            # 30,
                            # 60
        ]):
        for circuit_generator in [
            DJCircuitInitialization,
            GHZCircuitInitialization, 
            GroverCircuitInitialization,
            QFTCircuitInitialization
        ]:
            if (original_add_verification and circuit_generator in [
                # DJCircuitInitialization,
            #  QFTCircuitInitialization
             ]):
                add_verification = False
            else:
                add_verification = original_add_verification
            for optimization_level in [0,1,2,3]:
                for compiler in [qiskit_compile, qlego_qiskit_compile, qlego_qiskit_compose_compile]:
                    try:
                        result = {}
                        initial_qasm = initialize_circuit(circuit_generator, num_qubits)
                        if( add_verification ):
                            output_qasm, compiler_name, metadata = compiler(initial_qasm, optimization_level, backend, add_verification)
                            result["exact_equivalence"] = metadata["exact_equivalence"]
                            result["partial_equivalence"] = metadata["partial_equivalence"]
                        else:
                            output_qasm, compiler_name = compiler(initial_qasm, optimization_level, backend)
                        metrics = evaluation_metrics(output_qasm, initial_qasm)
                        result["compiler"] = compiler_name
                        result["optimization_level"] = optimization_level
                        result["circuit_type"] = circuit_generator.name
                        result["num_qubits"] = num_qubits
                        result = { **result, **metrics }
                        results.append(result)
                    except Exception as e:
                        print(f"Error in experiment: {circuit_generator.name} | {optimization_level} | {compiler} | {num_qubits} | {e}")
                        continue
    df = pd.DataFrame(results)
    df.to_csv("experiment1_results.csv", index=False)
            
            

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--add_verification", action="store_true")
    args = parser.parse_args()
    run_experiments(args.add_verification)