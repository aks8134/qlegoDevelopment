from setuptools import setup, find_packages
from setuptools.command.install import install
from setuptools.command.develop import develop
import os
import subprocess
import sys
import urllib.parse

def run_environment_generator():
    """Executes the setup.py plugin generator script automatically."""
    print("Running QLego plugin environment generator...")
    packages_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    generator_script = os.path.join(os.path.dirname(__file__), "src", "qlego_generator", "setup.py")
    
    # We define the plugins to look for
    plugins = [
        "qlego-qiskit", "qlego-tket", "qlego-bqskit", 
        "qlego-cirq", "qlego-evaluation", "qlego-mqt-verification", 
        "qlego-mqt-workload"
    ]
    
    # Ensure they exist
    valid_plugins = []
    for p in plugins:
        target = os.path.join(packages_dir, p)
        if os.path.exists(target):
            valid_plugins.append(target)
            
    out_dir = os.path.abspath(os.path.join(packages_dir, "..", "tests", "envs"))
    
    if valid_plugins:
        cmd = [sys.executable, generator_script] + valid_plugins + ["--out", out_dir]
        subprocess.check_call(cmd)


try:
    with open("/tmp/generator_log.txt", "w") as f:
        f.write(f"Args: {sys.argv}\n")
    if "egg_info" not in sys.argv and "--help" not in sys.argv:
        run_environment_generator()
        with open("/tmp/generator_log.txt", "a") as f:
            f.write("run_environment_generator completed.\n")
except Exception as e:
    with open("/tmp/generator_err.txt", "w") as f:
        f.write(str(e))

setup(
    name="qlego-generator",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        f"qlego-core @ file://localhost{urllib.parse.quote(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'qlego-core')))}",
        f"qlego-bqskit @ file://localhost{urllib.parse.quote(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'qlego-bqskit')))}",
        f"qlego-cirq @ file://localhost{urllib.parse.quote(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'qlego-cirq')))}",
        f"qlego-evaluation @ file://localhost{urllib.parse.quote(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'qlego-evaluation')))}",
        f"qlego-mqt-verification @ file://localhost{urllib.parse.quote(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'qlego-mqt-verification')))}",
        f"qlego-mqt-workload @ file://localhost{urllib.parse.quote(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'qlego-mqt-workload')))}",
        f"qlego-qiskit @ file://localhost{urllib.parse.quote(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'qlego-qiskit')))}",
        f"qlego-tket @ file://localhost{urllib.parse.quote(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'qlego-tket')))}"
    ]
)
