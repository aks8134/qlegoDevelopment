#!/usr/bin/env python3

import sys
import subprocess
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        print("Usage: python runner.py <script.py>")
        sys.exit(1)

    script = Path(sys.argv[1]).resolve()
    if not script.exists():
        print(f"Error: script not found: {script}")
        sys.exit(1)

    # assume runner.py is inside qlego_qiskit/
    project_root = Path(__file__).resolve().parent
    venv = project_root / ".venv"

    if sys.platform == "win32":
        python_exe = venv / "Scripts" / "python.exe"
    else:
        python_exe = venv / "bin" / "python"

    if not python_exe.exists():
        print(f"Error: venv python not found at {python_exe}")
        sys.exit(1)

    subprocess.run(
        [str(python_exe), str(script)],
        check=True,
    )


if __name__ == "__main__":
    main()
