#!/usr/bin/env bash
set -e

git clone https://github.com/aks8134/qlegoDevelopment.git
cd qlegoDevelopment

python -m venv tests/.venv
source tests/.venv/bin/activate

python -m pip install --upgrade pip
pip install -e .
pip install -e packages/qlego-generator
pip install qiskit-ibm-runtime tqdm pandas mqt.qcec mqt.bench