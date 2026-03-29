import sys
sys.path.insert(0, ".")
from rl_env import QLegoEnv
from utils import DJCircuitInitialization
from qlego_qiskit.adapter.backend import QiskitBackend
from qiskit_ibm_runtime.fake_provider import FakeBrooklynV2
from qlego.qpass import QPipeline, QPassContext

def main():
    print("Initialize backend and circuit...")
    backend = FakeBrooklynV2()
    backend_json = QiskitBackend.from_qiskit(backend).to_json()
    
    # Generate 5-qubit DJ circuit
    generator = DJCircuitInitialization(5)
    pipeline = QPipeline([generator])
    ctx = QPassContext()
    ctx = pipeline.run("", ctx)
    initial_qasm = ctx.qasm
    
    print("Instantiating QLegoEnv...")
    env = QLegoEnv(initial_qasm, backend_json, max_steps_per_stage=3)
    
    print("Resetting environment...")
    obs, info = env.reset()
    print("Reset done. Stage:", env.current_stage)
    
    for i in range(20):
        # Sample random valid action
        valid_actions = [a for a, valid in enumerate(obs["action_mask"]) if valid == 1]
        import random
        action = random.choice(valid_actions)
        
        pass_name = "ADVANCE" if action == env.ADVANCE_ACTION else env.idx_to_pass[action][1]
        print(f"--- Step {i} ---")
        print(f"Action: {action} ({pass_name})")
        
        obs, reward, done, truncated, info = env.step(action)
        print(f"Reward: {reward:.2f}, Done: {done}, New Stage: {env.current_stage}")
        print(f"Metrics: {env.current_metrics.get('depth',0)} depth, {env.current_metrics.get('size',0)} total gates")
        
        if done:
            print("Episode finished.")
            break

if __name__ == "__main__":
    main()
