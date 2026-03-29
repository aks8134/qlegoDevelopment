import os
import subprocess
import venv
import json
from pathlib import Path
from typing import List

def setup_environments(plugin_paths: List[str], output_dir: str = "envs"):
    """
    Creates optimal shared virtual environments for the given plugins
    and generates env_config.json.
    """
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Resolve the physical path to qlego-core
    # Assuming standard project structure: qlego/packages/qlego-generator/src/...
    repo_root = Path(__file__).parent.parent.parent.parent.parent
    core_path = repo_root / "packages" / "qlego-core"
    
    plugin_reqs = {}
    for p in plugin_paths:
        p_path = Path(p).resolve()
        req_file = p_path / "requirements.txt"
        reqs = []
        if req_file.exists():
            reqs = [line.strip() for line in req_file.read_text().splitlines() if line.strip() and not line.startswith("#")]
        plugin_reqs[p_path.name] = {
            "path": p_path,
            "reqs": reqs
        }

    groups = []
    env_counter = 0

    temp_req_txt = out_dir / "temp_group_reqs.txt"

    for p_name, p_info in plugin_reqs.items():
        placed = False
        
        # We try greedily: Can we install this plugin's requirements into an existing environment?
        # If it fails (e.g., pip reports conflict), we catch it and create a new env.
        for group in groups:
            env_dir = group["env_dir"]
            env_python = env_dir / "bin" / "python"
            
            if not p_info["reqs"]:
                # If no requirements, we can trivially associate it with this env.
                # However, it might need to run the actual plugin code, but the plugin code
                # typically relies on qlego-core which is installed, and just needs to be in PYTHONPATH.
                group["plugins"].append(p_name)
                placed = True
                break
                
            temp_req_txt.write_text("\n".join(p_info["reqs"]))
            print(f"Trying to add {p_name} to existing {env_dir}...")
            
            res = subprocess.run(
                [str(env_python), "-m", "pip", "install", "-r", str(temp_req_txt)],
                capture_output=True,
                text=True
            )
            
            if res.returncode == 0:
                print(f" -> Successfully merged {p_name} into {env_dir}")
                group["plugins"].append(p_name)
                # Install the plugin itself into the environment
                subprocess.run(
                    [str(env_python), "-m", "pip", "install", "-e", str(p_info["path"])],
                    capture_output=True
                )
                placed = True
                break
            else:
                print(f" -> Compatibility conflict for {p_name} in {env_dir}. Trying next...")

        if not placed:
            env_counter += 1
            env_dir = out_dir / f"env_{env_counter}"
            print(f"Creating new environment for {p_name} at {env_dir}...")
            venv.create(env_dir, with_pip=True)
            env_python = env_dir / "bin" / "python"
            
            # Ensure pip is up to date
            subprocess.run([str(env_python), "-m", "pip", "install", "--upgrade", "pip"], capture_output=True)
            
            # Install qlego-core
            print(f" -> Installing qlego-core into {env_dir}...")
            core_install_res = subprocess.run(
                [str(env_python), "-m", "pip", "install", "-e", str(core_path)],
                capture_output=True, text=True
            )
            if core_install_res.returncode != 0:
                print(f"Warning: Failed to install qlego-core into {env_dir}\n{core_install_res.stderr}")
            
            # Install plugin dependencies
            if p_info["reqs"]:
                temp_req_txt.write_text("\n".join(p_info["reqs"]))
                print(f" -> Installing requirements for {p_name}...")
                subprocess.run(
                    [str(env_python), "-m", "pip", "install", "-r", str(temp_req_txt)],
                    check=True
                )
            # Install the plugin itself
            print(f" -> Installing plugin {p_name} itself into {env_dir}...")
            subprocess.run(
                [str(env_python), "-m", "pip", "install", "-e", str(p_info["path"])],
                capture_output=True
            )
            
            groups.append({
                "env_dir": env_dir,
                "plugins": [p_name]
            })

    if temp_req_txt.exists():
        temp_req_txt.unlink()

    # Generate config mapping plugin name -> venv python path
    config = {}
    for group in groups:
        # Use absolute paths for reliability
        env_python = str((group["env_dir"] / "bin" / "python").resolve())
        for p in group["plugins"]:
            # Standardize package module names (dashes to underscores usually)
            p_module = p.replace("-", "_")
            config[p_module] = {"venv_path": env_python}
            config[p] = {"venv_path": env_python} # also save the raw dash path just in case
            
    config_file = out_dir / "env_config.json"
    with open(config_file, "w") as f:
        json.dump(config, f, indent=4)
        
    print(f"\nSuccess! Generated {config_file} configuring {len(groups)} environments.")
    return config_file

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="QLego Plugin Environment Generator")
    parser.add_argument("plugins", nargs="+", help="Paths to plugin directories")
    parser.add_argument("--out", default="envs", help="Output directory for environments")
    args = parser.parse_args()
    
    setup_environments(args.plugins, args.out)
