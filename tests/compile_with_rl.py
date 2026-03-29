import sys
sys.path.insert(0, ".")

from sb3_contrib import MaskablePPO
from rl_env import QLegoEnv
from utils import HalfAdderCircuitInitialization
from qlego_qiskit.adapter.backend import QiskitBackend
from qiskit_ibm_runtime.fake_provider import FakeBrooklynV2
from qlego.qpass import QPipeline, QPassContext

def main():
    print("Loading backend...")
    backend = FakeBrooklynV2()
    backend_json = QiskitBackend.from_qiskit(backend).to_json()
    
    print("Generating initial circuit...")
    generator = HalfAdderCircuitInitialization(5) # Testing on a different circuit type
    pipeline = QPipeline([generator])
    ctx = QPassContext()
    ctx = pipeline.run("", ctx)
    initial_qasm = ctx.qasm
    
    print("Initializing environment...")
    # Instantiate environment for inference
    env = QLegoEnv(initial_qasm, backend_json, max_steps_per_stage=3)
    
    print("Loading trained PPO agent...")
    try:
        model = MaskablePPO.load("ppo_qlego_agent")
    except FileNotFoundError:
        print("Model file 'ppo_qlego_agent.zip' not found. Please run 'python tests/train_ppo.py' first.")
        return

    obs, info = env.reset()
    
    print(f"\n--- Starting RL Compilation ---")
    print(f"Initial metrics: Depth={env.current_metrics.get('Circuit Depth',0)}, Total Gates={env.current_metrics.get('Gate Count',0)}, 2Q Gates={env.current_metrics.get('2Q Count',0)}")
    
    done = False
    step_count = 0
    while not done:
        # Use deterministic=True for exploitation during actual compilation
        action, _states = model.predict(obs, action_masks=env.action_masks(), deterministic=True)
        action_idx = int(action)
        
        pass_name = "ADVANCE STAGE" if action_idx == env.ADVANCE_ACTION else f"[{env.idx_to_pass[action_idx][0]}] {env.idx_to_pass[action_idx][1]}"
        print(f"\nStep {step_count}: Agent chose action: {pass_name}")
        
        obs, reward, done, truncated, info = env.step(action_idx)
        print(f" -> Reward: {reward:.2f} | Current Stage: {env.current_stage}")
        print(f" -> Metrics: Depth={env.current_metrics.get('Circuit Depth',0)}, Total Gates={env.current_metrics.get('Gate Count',0)}, 2Q={env.current_metrics.get('2Q Count',0)}")
        
        step_count += 1
        if step_count > 20: 
            print("Force stopping to prevent infinite loop.")
            break
        
    print(f"\n--- Compilation Finished ---")
    print("The final compiled circuit is stored in `env.ctx.qasm`.")

if __name__ == "__main__":
    main()
