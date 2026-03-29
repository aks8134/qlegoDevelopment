import gymnasium as gym
from gymnasium import spaces
import numpy as np
import os
import copy

from qlego.registry import PassRegistry
from qlego_generator.registry import aggregate_from_environment
from qlego.qpass import QPipeline, QPassContext

# Import Qiskit presets to use as defaults
from qlego_qiskit.adapter.passes import (
    PresetInitPass, PresetLayoutPass, PresetRoutingPass, 
    PresetOptimizationPass, PresetTranslationPass
)
from qlego_evaluation.adapter.passes import EvaluationPass

# Environment stages
STAGE_LAYOUT = 0
STAGE_ROUTING = 1
STAGE_OPTIMIZATION = 2
STAGE_DONE = 3

class QLegoEnv(gym.Env):
    """
    Gymnasium Environment that formulates the QLego compilation process as an MDP.
    Stages: Layout -> Routing -> Optimization.
    """
    def __init__(self, initial_circuit_qasm, backend_json, 
                 w1=1.0, w2=1.0, step_penalty=0.1, max_steps_per_stage=5):
        super(QLegoEnv, self).__init__()
        
        self.initial_circuit_qasm = initial_circuit_qasm
        self.backend_json = backend_json
        
        self.w1 = w1 # Weight for 2Q count
        self.w2 = w2 # Weight for Depth
        self.step_penalty = step_penalty
        self.max_steps_per_stage = max_steps_per_stage
        
        # Load all passes
        self._load_passes()
        
        self.total_actions = len(self.layout_passes) + len(self.routing_passes) + len(self.opt_passes) + 1
        self.ADVANCE_ACTION = self.total_actions - 1
        
        # Define action and observation space
        # Actions: discrete choices among all passes + advance
        self.action_space = spaces.Discrete(self.total_actions)
        
        # Observation space: features + action_mask
        # features = [4 one-hot stage] + [total_gates, depth, 2q_gates] + [layout_cnt, routing_cnt, opt_cnt, total_steps]
        # Total feature dim = 4 + 3 + 4 = 11
        self.observation_space = spaces.Dict({
            "features": spaces.Box(low=0.0, high=np.inf, shape=(11,), dtype=np.float32),
            "action_mask": spaces.Box(low=0, high=1, shape=(self.total_actions,), dtype=np.int8)
        })

    def _load_passes(self):
        env_config_path = os.path.join(os.path.dirname(__file__), "envs/env_config.json")
        aggregate_from_environment(env_config_path)
        
        self.layout_passes = list(PassRegistry.get_passes_by_category("Layout").items())
        self.routing_passes = list(PassRegistry.get_passes_by_category("Routing").items())
        self.opt_passes = list(PassRegistry.get_passes_by_category("Optimization").items())
        
        # Build action mappings
        self.idx_to_pass = {}
        idx = 0
        for name, cls in self.layout_passes:
            self.idx_to_pass[idx] = ("Layout", name, cls)
            idx += 1
        for name, cls in self.routing_passes:
            self.idx_to_pass[idx] = ("Routing", name, cls)
            idx += 1
        for name, cls in self.opt_passes:
            self.idx_to_pass[idx] = ("Optimization", name, cls)
            idx += 1

    def evaluate_circuit(self, qasm):
        pipeline = QPipeline([EvaluationPass()])
        ctx = QPassContext(qasm=qasm)
        ctx = pipeline.run("", ctx)
        return ctx.metadata.get("evaluation_metrics", {})

    def get_score(self, metrics):
        # Using negative cost since we want to maximize reward (minimize score)
        q2 = metrics.get('2Q Count', 0)
        depth = metrics.get('Circuit Depth', 0)
        return self.w1 * q2 + self.w2 * depth

    def get_obs(self):
        # 1. Stage one-hot
        stage_one_hot = np.zeros(4, dtype=np.float32)
        stage_one_hot[self.current_stage] = 1.0
        
        # 2. Metrics
        total_gates = self.current_metrics.get('Gate Count', 0)
        depth = self.current_metrics.get('Circuit Depth', 0)
        q2 = self.current_metrics.get('2Q Count', 0)
        metric_vec = np.array([total_gates, depth, q2], dtype=np.float32)
        
        # 3. History
        history_vec = np.array([
            self.layout_count, 
            self.routing_count, 
            self.opt_count, 
            self.total_steps
        ], dtype=np.float32)
        
        features = np.concatenate([stage_one_hot, metric_vec, history_vec])
        
        # Action Mask
        mask = np.zeros(self.total_actions, dtype=np.int8)
        
        can_advance = True
        if self.current_stage == STAGE_LAYOUT and self.layout_count == 0:
            can_advance = False
        if self.current_stage == STAGE_ROUTING and self.routing_count == 0:
            can_advance = False
            
        if can_advance:
            mask[self.ADVANCE_ACTION] = 1 
        
        if self.current_stage == STAGE_LAYOUT and self.layout_count < self.max_steps_per_stage:
            start_idx = 0
            end_idx = len(self.layout_passes)
            mask[start_idx:end_idx] = 1
            
        elif self.current_stage == STAGE_ROUTING and self.routing_count < self.max_steps_per_stage:
            start_idx = len(self.layout_passes)
            end_idx = start_idx + len(self.routing_passes)
            mask[start_idx:end_idx] = 1
            
        elif self.current_stage == STAGE_OPTIMIZATION and self.opt_count < self.max_steps_per_stage:
            start_idx = len(self.layout_passes) + len(self.routing_passes)
            end_idx = start_idx + len(self.opt_passes)
            mask[start_idx:end_idx] = 1
            
        return {
            "features": features,
            "action_mask": mask
        }

    def action_masks(self) -> np.ndarray:
        return self.get_obs()["action_mask"]

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        # Apply Translation to get to Layout Stage
        transpile_pl = QPipeline([PresetInitPass(), PresetTranslationPass()])
        ctx = QPassContext(qasm=self.initial_circuit_qasm, hardware=self.backend_json)
        ctx = transpile_pl.run("", ctx)
        
        self.ctx = ctx
        self.current_stage = STAGE_LAYOUT
        
        self.layout_count = 0
        self.routing_count = 0
        self.opt_count = 0
        self.total_steps = 0
        
        self.current_metrics = self.evaluate_circuit(self.ctx.qasm)
        self.current_score = self.get_score(self.current_metrics)
        
        return self.get_obs(), {}

    def step(self, action):
        terminated = False
        reward = 0.0
        
        # Check if action is valid
        obs = self.get_obs()
        if obs["action_mask"][action] == 0:
            return obs, -100.0, True, False, {"error": "Invalid action selected"}
            
        if action == self.ADVANCE_ACTION:
            self.current_stage += 1
            if self.current_stage >= STAGE_DONE:
                terminated = True
                reward = 50.0  # Terminal bonus for successfully reaching full compilation
        else:
            cat, name, cls = self.idx_to_pass[action]
            try:
                pass_instance = cls()
                # Run the pass
                new_ctx = copy.deepcopy(self.ctx)
                new_ctx = pass_instance.run(new_ctx)
                self.ctx = new_ctx
                
                # Evaluate new metrics
                new_metrics = self.evaluate_circuit(self.ctx.qasm)
                new_score = self.get_score(new_metrics)
                
                # Reward is improvement in score
                reward = (self.current_score - new_score) - self.step_penalty
                
                self.current_metrics = new_metrics
                self.current_score = new_score
                
                # Update history
                if self.current_stage == STAGE_LAYOUT: self.layout_count += 1
                elif self.current_stage == STAGE_ROUTING: self.routing_count += 1
                elif self.current_stage == STAGE_OPTIMIZATION: self.opt_count += 1
                
            except Exception as e:
                # Pass failed - heavy penalty and stay in place (or terminate)
                # print(f"Pass {name} failed: {e}") # Enable for debugging
                reward = -10.0
                
        self.total_steps += 1
        if self.total_steps >= 100: # safety cap
            terminated = True
            
        return self.get_obs(), reward, terminated, False, {}

