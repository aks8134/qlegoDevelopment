#!/bin/bash
# Setup script for qlego-bqskit plugin
set -e

cd "$(dirname "$0")"

echo "Setting up qlego-bqskit environment..."

# Create virtual environment
python3 -m venv .venv

# Upgrade pip
.venv/bin/pip install --upgrade pip

# Install qlego-core as editable dependency
.venv/bin/pip install -e ../qlego-core

# Install plugin-specific dependencies

# Install the plugin package itself in editable mode
.venv/bin/pip install -e .
.venv/bin/pip install -r requirements.txt

echo "qlego-bqskit setup complete!"
