#!/bin/bash
# Run all experiments for the QCE 2026 paper.
# Execute from the experiments/ directory.
#
# Usage:
#   ./run_all.sh              # Run everything sequentially
#   ./run_all.sh exp0         # Run only experiment 0
#   ./run_all.sh exp1         # Run all Exp 1 (layout + routing + optimization)
#   ./run_all.sh exp2         # Run only experiment 2
#   etc.

set -e
cd "$(dirname "$0")"

EXP="${1:-all}"

run_exp() {
    echo ""
    echo "================================================================"
    echo "  $1"
    echo "================================================================"
    python "$2" ${@:3}
}

if [[ "$EXP" == "all" || "$EXP" == "exp0" ]]; then
    run_exp "Experiment 0: Correctness Validation" exp0_correctness.py
fi

if [[ "$EXP" == "all" || "$EXP" == "exp1" || "$EXP" == "exp1a" ]]; then
    run_exp "Experiment 1A: Layout Specialization" exp1_layout.py
fi

if [[ "$EXP" == "all" || "$EXP" == "exp1" || "$EXP" == "exp1b" ]]; then
    run_exp "Experiment 1B: Routing Specialization" exp1_routing.py
fi

if [[ "$EXP" == "all" || "$EXP" == "exp1" || "$EXP" == "exp1c" ]]; then
    run_exp "Experiment 1C: Optimization Specialization" exp1_optimization.py
fi

if [[ "$EXP" == "all" || "$EXP" == "exp2" ]]; then
    run_exp "Experiment 2: Cross-SDK Complementarity" exp2_complementarity.py
fi

if [[ "$EXP" == "all" || "$EXP" == "exp3" ]]; then
    run_exp "Experiment 3: Destructive Interference" exp3_destructive.py
fi

if [[ "$EXP" == "all" || "$EXP" == "exp4" ]]; then
    run_exp "Experiment 4: Scale Invariance" exp4_scale_invariance.py
fi

if [[ "$EXP" == "all" || "$EXP" == "exp5" ]]; then
    run_exp "Experiment 5: Topology Dependence" exp5_topology.py
fi

echo ""
echo "================================================================"
echo "  All requested experiments complete. Results in results/"
echo "================================================================"
