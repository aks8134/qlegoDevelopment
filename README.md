# QLego

A modular quantum compilation framework with plugin-based architecture and isolated environments.

## Overview

QLego provides a flexible framework for quantum circuit compilation using multiple quantum software frameworks. It features a plugin architecture where each framework (Qiskit, Tket, BQSKit, Cirq, etc.) operates in its own isolated environment, preventing dependency conflicts.

## Features

- **Modular Plugin Architecture**: Each quantum framework is a separate plugin
- **Isolated Environments**: Plugins run in isolated virtual environments with independent dependencies
- **Framework Agnostic**: Support for multiple quantum frameworks (Qiskit, Tket, BQSKit, Cirq, MQT)
- **Pipeline System**: Chain multiple compilation passes together with `QPipeline`
- **Extensible**: Easy to add new plugins and passes

## Architecture

### Core Components

- **qlego-core**: Base framework providing `QPass`, `QPipeline`, and `QPassContext`
- **Plugin Packages**: Individual packages for each quantum framework

### Available Plugins

| Plugin | Description | Dependencies |
|--------|-------------|--------------|
| `qlego-qiskit` | Qiskit integration | qiskit, qiskit-ibm-runtime, qiskit-aer |
| `qlego-tket` | Pytket integration | pytket, pytket-qiskit |
| `qlego-bqskit` | BQSKit integration | bqskit |
| `qlego-cirq` | Cirq integration | cirq |
| `qlego-evaluation` | Circuit evaluation utilities | qiskit |
| `qlego-mqt-verification` | Circuit verification | mqt.qcec, qiskit |
| `qlego-mqt-workload` | MQT workload generation | mqt.bench, qiskit |

## Installation

### Prerequisites

- Python 3.10 or higher
- `venv` module for creating virtual environments

### Setup Core Package

```bash
cd packages/qlego-core
pip install -e .
```

### Setup Plugins

Each plugin has its own setup script that creates an isolated environment:

```bash
# Setup individual plugin
cd packages/qlego-qiskit
bash setup.sh

# Setup all plugins
for plugin in packages/qlego-*/; do
    if [ -f "$plugin/setup.sh" ]; then
        (cd "$plugin" && bash setup.sh)
    fi
done
```

The setup script will:
1. Create a `.venv/` directory in the plugin folder
2. Install `qlego-core` in editable mode
3. Install plugin-specific dependencies from `requirements.txt`
4. Install the plugin package itself in editable mode

## Usage

### Basic Example

```python
from qlego.qpass import QPipeline, QPassContext
from qlego_qiskit.adapter.passes import QiskitPass
from qlego_tket.adapter.passes import TKetPass
from qiskit.transpiler.passes import Optimize1qGates, CXCancellation

# Define your compilation pipeline
pipeline = QPipeline([
    QiskitPass([Optimize1qGates(), CXCancellation()]),
    TKetPass([...])  # Add Tket passes
])

# Run the pipeline
qasm_input = """
OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
h q[0];
cx q[0], q[1];
"""

ctx = QPassContext(qasm=qasm_input)
result = pipeline.run(qasm_input, ctx)
print(result.qasm)
```

### Running Tests

```bash
python3 -m tests.compiler
```

## Project Structure

```
qlego/
├── packages/
│   ├── qlego-core/          # Core framework
│   │   ├── src/qlego/       # Core source code
│   │   └── pyproject.toml
│   ├── qlego-qiskit/        # Qiskit plugin
│   │   ├── .venv/           # Isolated environment (gitignored)
│   │   ├── src/qlego_qiskit/
│   │   ├── requirements.txt
│   │   ├── setup.sh
│   │   └── pyproject.toml
│   ├── qlego-tket/          # Pytket plugin
│   ├── qlego-bqskit/        # BQSKit plugin
│   ├── qlego-cirq/          # Cirq plugin
│   ├── qlego-evaluation/    # Evaluation plugin
│   ├── qlego-mqt-verification/
│   └── qlego-mqt-workload/
├── tests/                   # Test files
└── README.md
```

## How It Works

### Isolated Plugin Execution

1. Each plugin has a `venv_path` attribute pointing to its isolated Python interpreter
2. When a pass executes, it spawns a subprocess using the plugin's venv
3. The subprocess runs the pass logic with plugin-specific dependencies
4. Results are serialized and returned to the main process

This architecture allows:
- Different plugins to use different versions of the same library
- Clean dependency separation
- Easy plugin development without affecting other plugins

### Pass System

All passes inherit from `QPass` and implement a `run()` method:

```python
class MyCustomPass(QPass):
    name = "my_custom_pass"
    
    def run(self, ctx: QPassContext) -> QPassContext:
        # Transform ctx.qasm
        # Update ctx.metadata
        return ctx
```

### Pipeline Execution

`QPipeline` chains multiple passes sequentially:

```python
pipeline = QPipeline([pass1, pass2, pass3])
result_ctx = pipeline.run(input_qasm, initial_ctx)
```

## Adding a New Plugin

1. Create plugin directory structure:
```bash
mkdir -p packages/qlego-myplugin/src/qlego_myplugin/adapter
```

2. Create `requirements.txt` with dependencies

3. Create `setup.sh` script (copy from existing plugin)

4. Implement your pass in `adapter/passes.py`

5. Create `pyproject.toml` for package metadata

6. Run `bash setup.sh` to set up the environment

## Contributing

Contributions are welcome! Please ensure:
- New plugins follow the established architecture
- Tests are included for new functionality
- Dependencies are properly isolated in plugin requirements

## License

[Add your license here]

## Citation

If you use QLego in your research, please cite:

```
[Add citation information]
```
