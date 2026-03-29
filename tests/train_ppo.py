import sys
import argparse
sys.path.insert(0, ".")

from sb3_contrib import MaskablePPO
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.callbacks import EvalCallback
from stable_baselines3.common.vec_env import DummyVecEnv

from rl_env import QLegoEnv
from utils import DJCircuitInitialization, GHZCircuitInitialization
from qlego_qiskit.adapter.backend import QiskitBackend
from qiskit_ibm_runtime.fake_provider import FakeBrooklynV2
from qlego.qpass import QPipeline, QPassContext


from sb3_contrib.common.wrappers import ActionMasker

def make_env(circuit_generator, num_qubits, backend_json):
    def _init():
        pipeline = QPipeline([circuit_generator(num_qubits)])
        ctx = QPassContext()
        ctx = pipeline.run("", ctx)
        initial_qasm = ctx.qasm
        
        # Max steps per stage 2 to keep episodes short during training
        env = QLegoEnv(initial_qasm, backend_json, max_steps_per_stage=2)
        
        def mask_fn(env):
            return env.action_masks()
            
        return ActionMasker(env, mask_fn)
        
    return _init

def main(args):
    print("Initializing backend...")
    backend = FakeBrooklynV2()
    backend_json = QiskitBackend.from_qiskit(backend).to_json()
    
    # Check env
    print("Checking environment compatibility with SB3...")
    test_env = make_env(DJCircuitInitialization, 5, backend_json)()
    check_env(test_env)
    
    # Create vectorized environment for training
    print("Creating Vectorized Environment for PPO training...")
    train_env = DummyVecEnv([make_env(DJCircuitInitialization, 5, backend_json)])
    
    # Optionally, create an evaluation environment (e.g., using GHZ)
    eval_env = DummyVecEnv([make_env(GHZCircuitInitialization, 5, backend_json)])
    
    # Setup PPO agent
    model = MaskablePPO(
        "MultiInputPolicy", 
        train_env, 
        verbose=1,
        learning_rate=0.0003,
        n_steps=128,          # Number of steps per update
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        clip_range=0.2
    )
    
    # Train
    print(f"Starting training for {args.timesteps} timesteps...")
    eval_callback = EvalCallback(
        eval_env, 
        eval_freq=500,
        deterministic=True, 
        render=False
    )
    
    try:
        model.learn(total_timesteps=args.timesteps, callback=eval_callback)
    except KeyboardInterrupt:
        print("Training interrupted manually.")
    
    # Save the agent
    print(f"Saving model to {args.save_path}...")
    model.save(args.save_path)
    print("Training script completed successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--timesteps", type=int, default=1000, help="Timesteps to train the RL agent")
    parser.add_argument("--save_path", type=str, default="ppo_qlego_agent", help="Filepath to save the model")
    args = parser.parse_args()
    main(args)
