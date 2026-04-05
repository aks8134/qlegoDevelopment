"""
Plot Results for QLego Paper
============================
Generates all paper figures from experiment CSVs.

Usage:
    python plot_results.py              # all figures
    python plot_results.py --fig 1 3   # specific figures

Figures:
  1  H1a: Layout pass domain specialization (best pass per SDK per circuit)
  2  H1b: Optimization SDK chains vs baseline (% improvement)
  3  H2:  Cross-SDK complementarity residuals
  4  H3:  Destructive interference trajectory (depth vs step)
  5  Exp5: Topology ranking stability (Spearman rho)
  6  Exp6: Per-pass runtime by category
"""

import argparse
import os
import warnings
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")
matplotlib.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 8.5,
    "axes.titlesize": 9,
    "axes.labelsize": 8.5,
    "xtick.labelsize": 7.5,
    "ytick.labelsize": 7.5,
    "legend.fontsize": 7.5,
    "legend.framealpha": 0.85,
    "legend.edgecolor": "#cccccc",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.6,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "axes.grid": True,
    "grid.color": "#e0e0e0",
    "grid.linewidth": 0.5,
    "grid.linestyle": "-",
})

RESULTS = os.path.join(os.path.dirname(__file__), "results")
FIGURES = os.path.join(os.path.dirname(__file__), "figures")
os.makedirs(FIGURES, exist_ok=True)

# ── clean, muted colour palette — no hatching anywhere ──────────────────────
# Inspired by Paul Tol's colorblind-safe muted set
SDK_COLOR = {
    "Qiskit":    "#4878CF",   # muted blue
    "TKet":      "#D65F5F",   # muted red
    "BQSKit":    "#6ACC65",   # muted green
    "Baseline":  "#999999",   # medium grey
    "Cross-SDK": "#8172B2",   # muted purple
}
SDK_HATCH = {"Qiskit": "", "TKet": "", "BQSKit": "", "Baseline": "", "Cross-SDK": ""}

CIRCUIT_ABBREV = {
    "DJ Circuit": "DJ",
    "GHZ Circuit": "GHZ",
    "Grover Circuit": "Grover",
    "QFT Circuit": "QFT",
    "Amplitude Estimation Circuit": "AE",
    "Quantum Phase Estimation Circuit": "QPE",
    "W State Circuit": "W-State",
    "Half Adder Circuit": "HAdder",
    "BV Circuit": "BV",
    "Graph State Circuit": "GraphSt",
}

# ── Estimated fidelity (FakeBrooklyn V2 mean error rates) ───────────────────

def _get_backend_error_rates():
    """Extract mean 1Q and 2Q gate error rates from FakeBrooklynV2 calibration data."""
    try:
        try:
            from qiskit_ibm_runtime.fake_provider import FakeBrooklynV2
        except ImportError:
            from qiskit.providers.fake_provider import FakeBrooklynV2
        backend = FakeBrooklynV2()
        target = backend.target
        err_1q, err_2q = [], []
        for op_name, qargs_dict in target.items():
            if not qargs_dict:
                continue
            for qargs, props in qargs_dict.items():
                if props is None or props.error is None:
                    continue
                if len(qargs) == 1:
                    err_1q.append(props.error)
                elif len(qargs) == 2:
                    err_2q.append(props.error)
        mean_1q = float(np.mean(err_1q)) if err_1q else 0.0003
        mean_2q = float(np.mean(err_2q)) if err_2q else 0.006
        label = "FakeBrooklynV2 calibration"
        print(f"  Backend error rates: ε_1Q={mean_1q:.5f}, ε_2Q={mean_2q:.5f}")
        return mean_1q, mean_2q, label
    except Exception as e:
        print(f"  Warning: could not load FakeBrooklynV2 ({e}); using fallback rates.")
        return 0.0003, 0.006, "FakeBrooklyn V2 (fallback)"

_ERR_1Q, _ERR_2Q, _ERR_LABEL = _get_backend_error_rates()


def log_fidelity(gate_count, twoq_count):
    """
    log10(F_est) = N_1Q * log10(1-ε_1Q) + N_2Q * log10(1-ε_2Q)
    Numerically stable for large gate counts where F_est itself underflows to 0.
    """
    n1q = np.maximum(np.asarray(gate_count, float) - np.asarray(twoq_count, float), 0)
    n2q = np.asarray(twoq_count, float)
    return n1q * np.log10(1 - _ERR_1Q) + n2q * np.log10(1 - _ERR_2Q)


def add_log_fidelity(df, gate_col="Gate Count", twoq_col="2Q Count", out="log_fidelity"):
    """Add log10(F_est) column. Stable for circuits with hundreds of gates."""
    df = df.copy()
    df[out] = log_fidelity(df[gate_col].fillna(0), df[twoq_col].fillna(0))
    return df


PASS_SDK = {}  # populated by _pass_sdk()

def _pass_sdk(pass_key: str) -> str:
    """Extract SDK name from pass key like 'qlego-qiskit_SabreLayoutPass'."""
    if "qiskit" in pass_key.lower():
        return "Qiskit"
    if "tket" in pass_key.lower():
        return "TKet"
    if "bqskit" in pass_key.lower():
        return "BQSKit"
    return "Other"


def _save(fig, name):
    path_pdf = os.path.join(FIGURES, name + ".pdf")
    path_png = os.path.join(FIGURES, name + ".png")
    fig.savefig(path_pdf)
    fig.savefig(path_png)
    print(f"  Saved: {path_png}")
    plt.close(fig)


# ════════════════════════════════════════════════════════════════════════════
# Figure 1 — H1a: Layout Domain Specialization
# ════════════════════════════════════════════════════════════════════════════

def fig1_layout():
    """
    Heatmap-style comparison: for each (circuit, qubit_scale), which SDK
    achieves the lowest circuit depth?  Also shows a grouped-bar summary
    at 10q (where all SDKs have data).
    """
    df = pd.read_csv(os.path.join(RESULTS, "exp1_layout.csv"))
    s = df[(df["status"] == "success") & (df["Circuit Depth"] < 50_000)].copy()
    s["sdk"] = s["layout_pass"].apply(_pass_sdk)
    # Shorten pass names to strip the SDK prefix for display
    s["pass_short"] = s["layout_pass"].str.split("_", n=1).str[1]

    # ── Panel A: best depth per SDK per circuit at 10q ──────────────────────
    nq = 10
    sub = s[s["num_qubits"] == nq]
    best = sub.groupby(["circuit_type", "sdk"])["Circuit Depth"].min().reset_index()
    circuits = [c for c in CIRCUIT_ABBREV if c in best["circuit_type"].unique()]
    sdks = ["Qiskit", "TKet", "BQSKit"]
    x = np.arange(len(circuits))
    width = 0.25

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4))

    # grouped bar — panel A
    ax = axes[0]
    for i, sdk in enumerate(sdks):
        vals = []
        for circ in circuits:
            row = best[(best["circuit_type"] == circ) & (best["sdk"] == sdk)]
            vals.append(row["Circuit Depth"].values[0] if len(row) else np.nan)
        ax.bar(x + i * width, vals, width, label=sdk,
               color=SDK_COLOR[sdk], edgecolor="none")
    ax.set_xticks(x + width)
    ax.set_xticklabels([CIRCUIT_ABBREV[c] for c in circuits], rotation=40, ha="right")
    ax.set_ylabel("Circuit depth (log scale)")
    ax.set_title(f"(a) Best layout pass per SDK  [{nq}q]")
    ax.legend(loc="upper right", frameon=True)   # ← moved to upper right
    ax.set_yscale("log")
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)

    # ── Panel B: winner heatmap across qubit scales ─────────────────────────
    ax2 = axes[1]
    qubits = sorted(s["num_qubits"].unique())
    circuits_all = [c for c in CIRCUIT_ABBREV if c in s["circuit_type"].unique()]
    nrows_h = len(circuits_all)
    ncols_h = len(qubits)

    winner_grid = np.full((nrows_h, ncols_h), "", dtype=object)
    for qi, nq_ in enumerate(qubits):
        for ci, circ in enumerate(circuits_all):
            sub2 = s[(s["num_qubits"] == nq_) & (s["circuit_type"] == circ)]
            if sub2.empty:
                winner_grid[ci, qi] = "—"
                continue
            best_pass = sub2.loc[sub2["Circuit Depth"].idxmin(), "sdk"]
            winner_grid[ci, qi] = best_pass

    sdk_int = {"Qiskit": 0, "TKet": 1, "BQSKit": 2, "—": -1}
    grid_num = np.vectorize(lambda x: sdk_int.get(x, -1))(winner_grid).astype(float)
    grid_num[grid_num == -1] = np.nan

    cmap = matplotlib.colors.ListedColormap([SDK_COLOR["Qiskit"],
                                             SDK_COLOR["TKet"],
                                             SDK_COLOR["BQSKit"]])
    ax2.imshow(grid_num, aspect="auto", cmap=cmap, vmin=0, vmax=2,
               interpolation="nearest")
    ax2.set_xticks(range(ncols_h))
    ax2.set_xticklabels([f"{q}q" for q in qubits])
    ax2.set_yticks(range(nrows_h))
    ax2.set_yticklabels([CIRCUIT_ABBREV[c] for c in circuits_all])
    ax2.set_title("(b) Winner by circuit & qubit scale")
    ax2.set_xlabel("Qubit count")
    ax2.tick_params(left=False, bottom=False)
    for spine in ax2.spines.values():
        spine.set_visible(False)

    # Turn off the global grid (it bleeds onto the heatmap and cuts letters)
    ax2.grid(False)
    for spine in ax2.spines.values():
        spine.set_visible(False)

    # Draw separator lines only at cell boundaries (between rows and columns)
    sep_kw = dict(color="white", linewidth=1.5, clip_on=True, zorder=3)
    for qi in range(1, ncols_h):
        ax2.axvline(qi - 0.5, **sep_kw)
    for ci in range(1, nrows_h):
        ax2.axhline(ci - 0.5, **sep_kw)

    # overlay initial letter
    for ci in range(nrows_h):
        for qi in range(ncols_h):
            txt = winner_grid[ci, qi]
            if txt and txt != "—":
                ax2.text(qi, ci, txt[:1], ha="center", va="center",
                         fontsize=7, color="white", fontweight="bold")
            elif txt == "—":
                ax2.text(qi, ci, "—", ha="center", va="center",
                         fontsize=7, color="white", alpha=0.6)


    fig.tight_layout()
    _save(fig, "fig1_layout")


# ════════════════════════════════════════════════════════════════════════════
# Figure 2 — H1c: Optimization SDK Chains vs Baseline
# ════════════════════════════════════════════════════════════════════════════

def fig2_optimization():
    """
    For each circuit type, show % reduction in circuit depth from baseline
    for each SDK chain and the best random cross-SDK sample.
    """
    df = pd.read_csv(os.path.join(RESULTS, "exp1_optimization.csv"))
    s = df[df["status"] == "success"].copy()

    # Compute mean per circuit/pipeline across all qubit sizes
    baseline = (s[s["pipeline_type"] == "baseline"]
                .groupby("circuit_type")["Circuit Depth"].mean()
                .rename("baseline"))

    chains = {}
    for pt in ["sdk_chain_qiskit", "sdk_chain_tket", "sdk_chain_bqskit"]:
        chains[pt] = (s[s["pipeline_type"] == pt]
                      .groupby("circuit_type")["Circuit Depth"].mean())

    # Best random cross-SDK sample
    rand = (s[s["pipeline_type"] == "random_sample"]
            .groupby("circuit_type")["Circuit Depth"].min()
            .rename("best_random"))

    circuits = sorted(baseline.index,
                      key=lambda c: baseline[c], reverse=True)
    circuits = [c for c in circuits if c in baseline.index]

    labels = {
        "sdk_chain_qiskit": "Qiskit chain",
        "sdk_chain_tket":   "TKet chain",
        "sdk_chain_bqskit": "BQSKit chain",
        "best_random":      "Best cross-SDK",
    }
    colors = {
        "sdk_chain_qiskit": SDK_COLOR["Qiskit"],
        "sdk_chain_tket":   SDK_COLOR["TKet"],
        "sdk_chain_bqskit": SDK_COLOR["BQSKit"],
        "best_random":      SDK_COLOR["Cross-SDK"],
    }
    hatches = {
        "sdk_chain_qiskit": SDK_HATCH["Qiskit"],
        "sdk_chain_tket":   SDK_HATCH["TKet"],
        "sdk_chain_bqskit": SDK_HATCH["BQSKit"],
        "best_random":      "**",
    }

    items = list(labels.keys())
    x = np.arange(len(circuits))
    width = 0.19
    offsets = np.linspace(-(len(items) - 1) / 2, (len(items) - 1) / 2, len(items)) * width

    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    for i, key in enumerate(items):
        vals = []
        for circ in circuits:
            b = baseline.get(circ, np.nan)
            if key == "best_random":
                v = rand.get(circ, np.nan)
            else:
                v = chains[key].get(circ, np.nan)
            if pd.notna(b) and b > 0 and pd.notna(v):
                vals.append(100.0 * (b - v) / b)
            else:
                vals.append(np.nan)
        ax.bar(x + offsets[i], vals, width, label=labels[key],
               color=colors[key], edgecolor="none")

    ax.axhline(0, color="#555555", linewidth=0.8, linestyle="--")
    ax.set_xticks(x)
    ax.set_xticklabels([CIRCUIT_ABBREV.get(c, c) for c in circuits],
                       rotation=40, ha="right")
    ax.set_ylabel("Circuit depth reduction from baseline (%)")
    ax.set_title("Optimization: SDK chains vs. baseline  (H1)")
    ax.legend(loc="lower left", frameon=True)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    fig.tight_layout()
    _save(fig, "fig2_optimization")


# ════════════════════════════════════════════════════════════════════════════
# Figure 3 — H2: Cross-SDK Complementarity Residuals
# ════════════════════════════════════════════════════════════════════════════

def fig3_complementarity():
    """
    For each 3-SDK ordering, show mean residual improvement (%) at step 1
    (after 2nd SDK) and step 2 (after 3rd SDK).  Positive = improvement,
    negative = regression.
    """
    df = pd.read_csv(os.path.join(RESULTS, "exp2_complementarity.csv"))
    s = df[df["status"] == "success"].copy()

    orderings = s["ordering"].unique()
    # Shorten ordering labels
    def shorten(o):
        return o.replace("Qiskit", "Q").replace("TKet", "T").replace("BQSKit", "B")

    agg = s.groupby("ordering")[["step1_residual_pct", "step2_residual_pct"]].agg(
        ["mean", "sem"]
    )

    means1 = agg["step1_residual_pct"]["mean"]
    errs1  = agg["step1_residual_pct"]["sem"]
    means2 = agg["step2_residual_pct"]["mean"]
    errs2  = agg["step2_residual_pct"]["sem"]

    orderings_sorted = means1.sort_values(ascending=False).index
    x = np.arange(len(orderings_sorted))
    width = 0.35

    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.bar(x - width / 2,
           means1.loc[orderings_sorted], width,
           yerr=errs1.loc[orderings_sorted], capsize=3,
           label="Step 1 (2nd SDK)", color="#4878CF",
           edgecolor="none", error_kw={"linewidth": 0.8, "capthick": 0.8})
    ax.bar(x + width / 2,
           means2.loc[orderings_sorted], width,
           yerr=errs2.loc[orderings_sorted], capsize=3,
           label="Step 2 (3rd SDK)", color="#D65F5F",
           edgecolor="none", error_kw={"linewidth": 0.8, "capthick": 0.8})

    ax.axhline(0, color="#555555", linewidth=0.8, linestyle="--")
    ax.set_xticks(x)
    ax.set_xticklabels([shorten(o) for o in orderings_sorted],
                       rotation=30, ha="right")
    ax.set_ylabel("Residual depth improvement (%)")
    ax.set_title("Cross-SDK complementarity by ordering  (H2)")
    ax.legend(frameon=True)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    fig.tight_layout()
    _save(fig, "fig3_complementarity")


# ════════════════════════════════════════════════════��═══════════════════════
# Figure 4 — H3: Destructive Interference Trajectories
# ════════════════════════════════════════════════════════════════════════════

def fig4_destructive():
    """
    Line plots: normalized circuit depth vs. step for each ordering.
    Multiple panels — one per representative circuit.
    Shaded regions highlight destructive steps (depth increases).
    """
    df = pd.read_csv(os.path.join(RESULTS, "exp3_destructive.csv"))
    s = df[df["status"] == "success"].copy()

    # Select a diverse set of representative circuits/qubits
    show = [
        ("DJ Circuit", 10),
        ("GHZ Circuit", 10),
        ("QFT Circuit", 10),
        ("W State Circuit", 10),
        ("BV Circuit", 10),
        ("Graph State Circuit", 10),
    ]
    show = [(c, n) for c, n in show if not s[
        (s["circuit_type"] == c) & (s["num_qubits"] == n)
    ].empty]

    orderings = ["Order_A (Q-T-B-Q-T-B)", "Order_B (T-B-Q-T-B-Q)", "Order_C (B-Q-T-B-Q-T)"]
    ord_colors = {"Order_A (Q-T-B-Q-T-B)": "#4878CF",
                  "Order_B (T-B-Q-T-B-Q)": "#D65F5F",
                  "Order_C (B-Q-T-B-Q-T)": "#6ACC65"}
    ord_labels = {"Order_A (Q-T-B-Q-T-B)": "Order A (Q→T→B→Q→T→B)",
                  "Order_B (T-B-Q-T-B-Q)": "Order B (T→B→Q→T→B→Q)",
                  "Order_C (B-Q-T-B-Q-T)": "Order C (B→Q→T→B→Q→T)"}

    ncols = 3
    nrows = int(np.ceil(len(show) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(7.2, 2.4 * nrows),
                              sharex=False, sharey=False)
    axes = np.array(axes).flatten()

    for idx, (circ, nq) in enumerate(show):
        ax = axes[idx]
        # Get baseline depth (step 0, ordering='ALL')
        baseline_row = s[(s["circuit_type"] == circ) &
                         (s["num_qubits"] == nq) &
                         (s["ordering"] == "ALL") &
                         (s["step"] == 0)]
        baseline_depth = baseline_row["Circuit Depth"].values[0] if len(baseline_row) else None

        for ord_name in orderings:
            sub = s[(s["circuit_type"] == circ) &
                    (s["num_qubits"] == nq) &
                    (s["ordering"] == ord_name)].sort_values("step")
            if sub.empty:
                continue
            steps = sub["step"].tolist()
            depths = sub["Circuit Depth"].tolist()

            # Prepend step 0 (baseline)
            if baseline_depth is not None:
                steps = [0] + steps
                depths = [baseline_depth] + depths

            # Normalize to baseline
            if baseline_depth and baseline_depth > 0:
                norm = [d / baseline_depth for d in depths]
            else:
                norm = depths

            color = ord_colors[ord_name]
            ax.plot(steps, norm, marker="o", markersize=3, color=color,
                    label=ord_labels[ord_name], linewidth=1.2)

            # Shade destructive segments (depth goes up)
            for i in range(1, len(norm)):
                if norm[i] > norm[i - 1]:
                    ax.axvspan(steps[i - 1], steps[i], alpha=0.12,
                               color="red", zorder=0)

        ax.axhline(1.0, color="#888888", linewidth=0.8, linestyle="--")
        ax.set_title(f"{CIRCUIT_ABBREV.get(circ, circ)} ({nq}q)", fontsize=8)
        ax.set_xlabel("Step", fontsize=7.5)
        if idx % ncols == 0:
            ax.set_ylabel("Norm. depth", fontsize=7.5)
        ax.yaxis.grid(True)
        ax.set_axisbelow(True)
        ax.set_xticks(range(0, 7))

    # Hide unused axes
    for idx in range(len(show), len(axes)):
        axes[idx].set_visible(False)

    # Shared legend
    handles = [Line2D([0], [0], color=ord_colors[o], linewidth=1.5,
                      label=ord_labels[o]) for o in orderings]
    handles.append(mpatches.Patch(color="#e05c5c", alpha=0.3, label="Destructive step"))
    fig.legend(handles=handles, loc="lower center",
               ncol=2, bbox_to_anchor=(0.5, -0.10), fontsize=7.5, frameon=True)

    fig.tight_layout()
    _save(fig, "fig4_destructive")


# ════════════════════════════════════════════════════════════════════════════
# Figure 5 — Topology: Spearman Rank Correlation
# ════════════════════════════════════════════════════════════════════════════

def fig5_topology():
    """
    Bar chart: Spearman ρ between heavy-hex and all-to-all pass rankings
    for each circuit at 5q and 10q.  Stars mark circuits where the
    best-ranked pass changes between topologies.
    """
    df = pd.read_csv(os.path.join(RESULTS, "exp5_topology.csv"))
    s = df[df["status"] == "success"].copy()

    circuits = [c for c in CIRCUIT_ABBREV if c in s["circuit_type"].unique()]
    qubits = [5, 10]

    rho_data = {nq: [] for nq in qubits}
    changed_data = {nq: [] for nq in qubits}

    for nq in qubits:
        for circ in circuits:
            hh = (s[(s["circuit_type"] == circ) & (s["num_qubits"] == nq) &
                    (s["topology"] == "heavy_hex")]
                  .set_index("optimization_pass")["Circuit Depth"])
            aa = (s[(s["circuit_type"] == circ) & (s["num_qubits"] == nq) &
                    (s["topology"] == "all_to_all")]
                  .set_index("optimization_pass")["Circuit Depth"])
            common = hh.index.intersection(aa.index)
            if len(common) >= 3:
                rho, _ = spearmanr(hh.loc[common].values, aa.loc[common].values)
                best_hh = hh.loc[common].idxmin()
                best_aa = aa.loc[common].idxmin()
                rho_data[nq].append(rho)
                changed_data[nq].append(best_hh != best_aa)
            else:
                rho_data[nq].append(np.nan)
                changed_data[nq].append(False)

    x = np.arange(len(circuits))
    width = 0.36
    bar_colors = ["#4878CF", "#D65F5F"]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))

    for i, nq in enumerate(qubits):
        offset = (i - 0.5) * width
        ax.bar(x + offset, rho_data[nq], width,
               label=f"{nq} qubits",
               color=bar_colors[i], edgecolor="none")
        # Small dot (not star) where best pass changed — cleaner
        for j, (rho, changed) in enumerate(zip(rho_data[nq], changed_data[nq])):
            if changed and pd.notna(rho):
                ax.plot(x[j] + offset, rho + 0.025, marker="v",
                        color="#c0392b", markersize=4, zorder=5)

    ax.axhline(1.0, color="#888888", linewidth=0.7, linestyle="--")
    ax.set_xticks(x)
    ax.set_xticklabels([CIRCUIT_ABBREV.get(c, c) for c in circuits],
                       rotation=40, ha="right")
    ax.set_ylabel("Spearman ρ  (heavy-hex vs. all-to-all)")
    ax.set_ylim(0, 1.15)
    ax.legend(frameon=True)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    fig.tight_layout()
    _save(fig, "fig5_topology")


# ════════════════════════════════════════════════════════════════════════════
# Figure 6 — Runtime: Per-pass wall time by SDK category
# ════════════════════════════════════════════════════════════════════════════

def fig6_runtime():
    """
    Two panels:
      (a) Per-pass wall time by category (Layout / Routing / Optimization)
      (b) Pipeline total wall time scaling with qubit count (Part C)
    """
    df = pd.read_csv(os.path.join(RESULTS, "exp6_runtime.csv"))
    s = df[df["status"] == "success"].copy()

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4))

    # ── Panel A: per-pass median wall time by category & SDK ────────────────
    ax = axes[0]
    parta = s[(s["part"] == "A_per_pass") & (s["pass_name"] != "__TOTAL__")].copy()
    if not parta.empty:
        # sdk column should already exist; if not, derive from pass_key
        if "sdk" not in parta.columns or parta["sdk"].isna().all():
            parta["sdk"] = parta.get("pass_key", pd.Series(dtype=str)).apply(
                lambda k: _pass_sdk(str(k)) if pd.notna(k) else "Unknown"
            )
        cats = ["Layout", "Routing", "Optimization"]
        sdks = ["Qiskit", "TKet", "BQSKit"]
        x = np.arange(len(cats))
        width = 0.25
        for i, sdk in enumerate(sdks):
            vals = []
            for cat in cats:
                sub = parta[(parta["category"] == cat) & (parta["sdk"] == sdk.lower())]
                if sub.empty:
                    # try capitalized
                    sub = parta[(parta["category"] == cat) & (
                        parta["sdk"].str.lower() == sdk.lower())]
                vals.append(sub["wall_s"].median() if not sub.empty else np.nan)
            ax.bar(x + (i - 1) * width, vals, width, label=sdk,
                   color=SDK_COLOR[sdk], edgecolor="none")
        ax.set_xticks(x)
        ax.set_xticklabels(cats)
        ax.set_ylabel("Median wall time per pass (s)")
        ax.set_title("(a) Per-pass runtime by SDK & category")
        ax.legend()
        ax.grid(axis="y", linestyle="--", alpha=0.4)
    else:
        ax.text(0.5, 0.5, "No Part A data", ha="center", va="center",
                transform=ax.transAxes)

    # ── Panel B: total pipeline wall time scaling (Part C) ──────────────────
    ax2 = axes[1]
    partc = s[(s["part"] == "C_scaling") & (s["pass_name"] == "__TOTAL__")].copy()
    if not partc.empty:
        pipelines = partc["pipeline_name"].unique()
        pipe_colors = {p: list(SDK_COLOR.values())[i % len(SDK_COLOR)]
                       for i, p in enumerate(pipelines)}
        for pipe in pipelines:
            sub = (partc[partc["pipeline_name"] == pipe]
                   .groupby("num_qubits")["wall_s"].mean().reset_index())
            label = pipe.replace(" (end-to-end)", "").replace("Cross-SDK: ", "×")
            ax2.plot(sub["num_qubits"], sub["wall_s"],
                     marker="o", markersize=4, label=label,
                     color=pipe_colors[pipe], linewidth=1.5)
        ax2.set_xlabel("Qubit count")
        ax2.set_ylabel("Total pipeline wall time (s)")
        ax2.set_title("(b) Compilation time scaling")
        ax2.legend(fontsize=7)
        ax2.grid(True, linestyle="--", alpha=0.4)
        ax2.set_yscale("log")
    else:
        ax2.text(0.5, 0.5, "No Part C data", ha="center", va="center",
                 transform=ax2.transAxes)

    fig.tight_layout()
    _save(fig, "fig6_runtime")


# ════════════════════════════════════════════════════════════════════════════
# Figure 7 — Summary: best-per-circuit winner across all experiments
# ════════════════════════════════════════════════════════════════════════════

def fig7_summary_heatmap():
    """
    Summary heatmap: rows = circuits, cols = {best layout SDK, best routing
    SDK, best opt SDK}.  Shows which SDK wins in each dimension per circuit.
    """
    circuits = list(CIRCUIT_ABBREV.keys())

    def best_sdk(df, group_col, metric="Circuit Depth"):
        s = df[df["status"] == "success"].copy()
        if s.empty or metric not in s.columns:
            return {}
        s["sdk"] = s[group_col].apply(_pass_sdk)
        best = (s.groupby(["circuit_type", "sdk"])[metric]
                .mean().reset_index()
                .sort_values(metric)
                .groupby("circuit_type").first()["sdk"])
        return best.to_dict()

    layout_df = pd.read_csv(os.path.join(RESULTS, "exp1_layout.csv"))
    routing_df = pd.read_csv(os.path.join(RESULTS, "exp1_routing.csv"))
    opt_df = pd.read_csv(os.path.join(RESULTS, "exp1_optimization.csv"))

    # Filter out huge outliers
    layout_df = layout_df[layout_df["Circuit Depth"] < 50_000]
    routing_df = routing_df[routing_df["Circuit Depth"] < 50_000]

    layout_win = best_sdk(layout_df, "layout_pass")
    routing_win = best_sdk(routing_df, "routing_pass")

    # For optimization, chains only
    opt_s = opt_df[(opt_df["status"] == "success") &
                   (opt_df["pipeline_type"].str.startswith("sdk_chain"))].copy()
    def chain_sdk(pt):
        if "qiskit" in pt:
            return "Qiskit"
        if "tket" in pt:
            return "TKet"
        if "bqskit" in pt:
            return "BQSKit"
        return "Other"
    opt_s["sdk"] = opt_s["pipeline_type"].apply(chain_sdk)
    opt_win = (opt_s.groupby(["circuit_type", "sdk"])["Circuit Depth"]
               .mean().reset_index().sort_values("Circuit Depth")
               .groupby("circuit_type").first()["sdk"].to_dict())

    dims = ["Layout", "Routing", "Optimization"]
    wins = [layout_win, routing_win, opt_win]

    sdk_int = {"Qiskit": 0, "TKet": 1, "BQSKit": 2}
    grid = np.full((len(circuits), len(dims)), np.nan)
    for ci, circ in enumerate(circuits):
        for di, w in enumerate(wins):
            if circ in w:
                grid[ci, di] = sdk_int.get(w[circ], np.nan)

    cmap = matplotlib.colors.ListedColormap([SDK_COLOR["Qiskit"],
                                             SDK_COLOR["TKet"],
                                             SDK_COLOR["BQSKit"]])

    fig, ax = plt.subplots(figsize=(4, 4.5))
    im = ax.imshow(grid, aspect="auto", cmap=cmap, vmin=0, vmax=2,
                   interpolation="nearest")
    ax.set_xticks(range(len(dims)))
    ax.set_xticklabels(dims, rotation=25, ha="right")
    ax.set_yticks(range(len(circuits)))
    ax.set_yticklabels([CIRCUIT_ABBREV.get(c, c) for c in circuits])
    ax.set_title("Best-performing SDK per circuit × phase")

    sdks = ["Qiskit", "TKet", "BQSKit"]
    for ci in range(len(circuits)):
        for di in range(len(dims)):
            if not np.isnan(grid[ci, di]):
                txt = sdks[int(grid[ci, di])][0]
                ax.text(di, ci, txt, ha="center", va="center",
                        color="white", fontweight="bold", fontsize=9)
            else:
                ax.text(di, ci, "—", ha="center", va="center",
                        color="gray", fontsize=9)

    patches = [mpatches.Patch(color=SDK_COLOR[s], label=s) for s in sdks]
    ax.legend(handles=patches, loc="upper left",
              bbox_to_anchor=(1.02, 1), borderaxespad=0)
    fig.tight_layout()
    _save(fig, "fig7_summary_heatmap")


# ═════════════���══════════════════════════════════════════════════════════════
# Figure 8 — Estimated Fidelity: Layout Pass Comparison
# ════════════════════════════════════════════════════════════════════════════

def fig8_fidelity_layout():
    """
    Panel A: grouped bar of best log10(F_est) per SDK per circuit at 10q.
    Panel B: winner heatmap by log-fidelity across qubit scales.
    Y-axis is log10(F_est) — higher (less negative) = better.
    """
    df = pd.read_csv(os.path.join(RESULTS, "exp1_layout.csv"))
    s = add_log_fidelity(
        df[(df["status"] == "success") & (df["Circuit Depth"] < 50_000)].copy()
    )
    s["sdk"] = s["layout_pass"].apply(_pass_sdk)

    nq = 10
    sub = s[s["num_qubits"] == nq]
    best = sub.groupby(["circuit_type", "sdk"])["log_fidelity"].max().reset_index()
    circuits = [c for c in CIRCUIT_ABBREV if c in best["circuit_type"].unique()]
    sdks = ["Qiskit", "TKet", "BQSKit"]
    x = np.arange(len(circuits))
    width = 0.25

    # Qiskit best log-fidelity per circuit (reference for normalization)
    qiskit_lf = {
        circ: row["log_fidelity"].values[0]
        for circ in circuits
        for row in [best[(best["circuit_type"] == circ) & (best["sdk"] == "Qiskit")]]
        if len(row)
    }

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4))

    # Panel A: Δlog(F) / |log(F)_Qiskit| × 100
    # Normalizing by Qiskit's log-fidelity magnitude makes the metric circuit-size
    # independent: a large circuit with large |log(F)| is treated the same as a small one.
    ax = axes[0]
    for i, sdk in enumerate(sdks):
        vals = []
        for circ in circuits:
            ref = qiskit_lf.get(circ, np.nan)
            row = best[(best["circuit_type"] == circ) & (best["sdk"] == sdk)]
            v = row["log_fidelity"].values[0] if len(row) else np.nan
            if pd.notna(ref) and ref != 0 and pd.notna(v):
                vals.append(100.0 * (v - ref) / abs(ref))
            else:
                vals.append(np.nan)
        ax.bar(x + i * width, vals, width, label=sdk,
               color=SDK_COLOR[sdk], edgecolor="none")
    ax.axhline(0, color="#555", linewidth=0.8, linestyle="--")
    ax.set_xticks(x + width)
    ax.set_xticklabels([CIRCUIT_ABBREV[c] for c in circuits], rotation=40, ha="right")
    ax.set_ylabel("Δlog(F_est) / |log(F_Qiskit)| × 100  [higher = better]")
    ax.set_title(f"(a) Relative log-fidelity vs. Qiskit  [{nq}q]")
    ax.legend(loc="upper right", frameon=True)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)

    # Panel B: winner heatmap (by log-fidelity)
    ax2 = axes[1]
    qubits = sorted(s["num_qubits"].unique())
    circuits_all = [c for c in CIRCUIT_ABBREV if c in s["circuit_type"].unique()]
    nrows_h, ncols_h = len(circuits_all), len(qubits)
    winner_grid = np.full((nrows_h, ncols_h), "", dtype=object)
    for qi, nq_ in enumerate(qubits):
        for ci, circ in enumerate(circuits_all):
            sub2 = s[(s["num_qubits"] == nq_) & (s["circuit_type"] == circ)]
            if sub2.empty:
                winner_grid[ci, qi] = "—"
                continue
            winner_grid[ci, qi] = sub2.loc[sub2["log_fidelity"].idxmax(), "sdk"]

    sdk_int = {"Qiskit": 0, "TKet": 1, "BQSKit": 2, "—": -1}
    grid_num = np.vectorize(lambda v: sdk_int.get(v, -1))(winner_grid).astype(float)
    grid_num[grid_num == -1] = np.nan
    cmap = matplotlib.colors.ListedColormap(
        [SDK_COLOR["Qiskit"], SDK_COLOR["TKet"], SDK_COLOR["BQSKit"]]
    )
    ax2.imshow(grid_num, aspect="auto", cmap=cmap, vmin=0, vmax=2, interpolation="nearest")
    ax2.set_xticks(range(ncols_h))
    ax2.set_xticklabels([f"{q}q" for q in qubits])
    ax2.set_yticks(range(nrows_h))
    ax2.set_yticklabels([CIRCUIT_ABBREV[c] for c in circuits_all])
    ax2.set_title("(b) Winner by circuit & qubit scale")
    ax2.set_xlabel("Qubit count")
    ax2.tick_params(left=False, bottom=False)
    ax2.grid(False)
    for spine in ax2.spines.values():
        spine.set_visible(False)
    sep_kw = dict(color="white", linewidth=1.5, clip_on=True, zorder=3)
    for qi in range(1, ncols_h):
        ax2.axvline(qi - 0.5, **sep_kw)
    for ci in range(1, nrows_h):
        ax2.axhline(ci - 0.5, **sep_kw)
    for ci in range(nrows_h):
        for qi in range(ncols_h):
            txt = winner_grid[ci, qi]
            color = "white" if txt not in ("—", "") else "gray"
            ax2.text(qi, ci, txt[:1] if txt != "—" else "—",
                     ha="center", va="center", fontsize=7, color=color, fontweight="bold")

    note = f"ε_1Q={_ERR_1Q:.5f}, ε_2Q={_ERR_2Q:.5f}  ({_ERR_LABEL})"
    fig.text(0.5, -0.02, note, ha="center", fontsize=6.5, color="#888888", style="italic")
    fig.tight_layout()
    _save(fig, "fig8_fidelity_layout")


# ════════════════════════════════════════════════════════════════════════════
# Figure 9 — Estimated Fidelity: Optimization SDK Chains
# ════════════════════════════════════════════════════════════════════════════

def fig9_fidelity_optimization():
    """
    Δlog₁₀(F_est) = log10(F_after) - log10(F_baseline) for each SDK chain
    and best cross-SDK sample. Positive = fidelity improvement over baseline.
    """
    df = pd.read_csv(os.path.join(RESULTS, "exp1_optimization.csv"))
    s = add_log_fidelity(df[df["status"] == "success"].copy())

    baseline = (s[s["pipeline_type"] == "baseline"]
                .groupby("circuit_type")["log_fidelity"].mean()
                .rename("baseline"))

    chains = {}
    for pt in ["sdk_chain_qiskit", "sdk_chain_tket", "sdk_chain_bqskit"]:
        chains[pt] = (s[s["pipeline_type"] == pt]
                      .groupby("circuit_type")["log_fidelity"].mean())

    rand = (s[s["pipeline_type"] == "random_sample"]
            .groupby("circuit_type")["log_fidelity"].max()
            .rename("best_random"))

    circuits = sorted(baseline.index, key=lambda c: baseline.get(c, 0))
    circuits = [c for c in circuits if c in baseline.index]

    labels = {
        "sdk_chain_qiskit": "Qiskit chain",
        "sdk_chain_tket":   "TKet chain",
        "sdk_chain_bqskit": "BQSKit chain",
        "best_random":      "Best cross-SDK",
    }
    colors = {
        "sdk_chain_qiskit": SDK_COLOR["Qiskit"],
        "sdk_chain_tket":   SDK_COLOR["TKet"],
        "sdk_chain_bqskit": SDK_COLOR["BQSKit"],
        "best_random":      SDK_COLOR["Cross-SDK"],
    }
    items = list(labels.keys())
    x = np.arange(len(circuits))
    width = 0.19
    offsets = np.linspace(-(len(items)-1)/2, (len(items)-1)/2, len(items)) * width

    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    for i, key in enumerate(items):
        vals = []
        for circ in circuits:
            b = baseline.get(circ, np.nan)
            v = rand.get(circ, np.nan) if key == "best_random" else chains[key].get(circ, np.nan)
            if pd.notna(b) and b != 0 and pd.notna(v):
                vals.append(100.0 * (v - b) / abs(b))
            else:
                vals.append(np.nan)
        ax.bar(x + offsets[i], vals, width, label=labels[key],
               color=colors[key], edgecolor="none")

    ax.axhline(0, color="#555555", linewidth=0.8, linestyle="--")
    ax.set_xticks(x)
    ax.set_xticklabels([CIRCUIT_ABBREV.get(c, c) for c in circuits], rotation=40, ha="right")
    ax.set_ylabel("Δlog(F_est) / |log(F_baseline)| × 100  [higher = better]")
    ax.set_title("Optimization: relative log-fidelity improvement per SDK chain  (H1)")
    ax.legend(loc="upper left", frameon=True)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    note = f"ε_1Q={_ERR_1Q:.5f}, ε_2Q={_ERR_2Q:.5f}  ({_ERR_LABEL})"
    fig.text(0.5, -0.02, note, ha="center", fontsize=6.5, color="#888888", style="italic")
    fig.tight_layout()
    _save(fig, "fig9_fidelity_optimization")


# ════════════════════════════════════════════════════════════════════════════
# Figure 10 — Estimated Fidelity: Cross-SDK Complementarity
# ════════════════════════════════════════════════════════════════════════════

def fig10_fidelity_complementarity():
    """
    Panel A: mean Δlog₁₀(F_est) per ordering (step1 vs step2) — mirrors fig3.
    Panel B: scatter — depth residual (%) vs Δlog10(F) at step1.
    """
    df = pd.read_csv(os.path.join(RESULTS, "exp2_complementarity.csv"))
    s = df[df["status"] == "success"].copy()

    for col_g, col_q, out in [
        ("step0_gates", "step0_2q", "lf_step0"),
        ("step1_gates", "step1_2q", "lf_step1"),
        ("step2_gates", "step2_2q", "lf_step2"),
    ]:
        if col_g in s.columns and col_q in s.columns:
            s[out] = log_fidelity(s[col_g].fillna(0), s[col_q].fillna(0))

    if "lf_step0" in s.columns and "lf_step1" in s.columns:
        s["dlf_step1"] = 100.0 * (s["lf_step1"] - s["lf_step0"]) / s["lf_step0"].abs().replace(0, np.nan)
    if "lf_step0" in s.columns and "lf_step2" in s.columns:
        s["dlf_step2"] = 100.0 * (s["lf_step2"] - s["lf_step0"]) / s["lf_step0"].abs().replace(0, np.nan)

    def shorten(o):
        return o.replace("Qiskit", "Q").replace("TKet", "T").replace("BQSKit", "B")

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4))

    # Panel A: bar chart of mean Δlog-fidelity per ordering
    ax = axes[0]
    if "dlf_step1" in s.columns:
        agg = s.groupby("ordering")[["dlf_step1", "dlf_step2"]].agg(["mean", "sem"])
        means1 = agg["dlf_step1"]["mean"]
        errs1  = agg["dlf_step1"]["sem"]
        means2 = agg["dlf_step2"]["mean"]
        errs2  = agg["dlf_step2"]["sem"]
        orderings_sorted = means1.sort_values(ascending=False).index
        xp = np.arange(len(orderings_sorted))
        width = 0.35
        ax.bar(xp - width/2, means1.loc[orderings_sorted], width,
               yerr=errs1.loc[orderings_sorted], capsize=3,
               label="Step 1 (2nd SDK)", color="#4878CF", edgecolor="none",
               error_kw={"linewidth": 0.8, "capthick": 0.8})
        ax.bar(xp + width/2, means2.loc[orderings_sorted], width,
               yerr=errs2.loc[orderings_sorted], capsize=3,
               label="Step 2 (3rd SDK)", color="#D65F5F", edgecolor="none",
               error_kw={"linewidth": 0.8, "capthick": 0.8})
        ax.axhline(0, color="#555555", linewidth=0.8, linestyle="--")
        ax.set_xticks(xp)
        ax.set_xticklabels([shorten(o) for o in orderings_sorted], rotation=30, ha="right")
        ax.set_ylabel("Δlog(F) / |log(F_step0)| × 100  [positive = better]")
        ax.set_title("(a) Relative log-fidelity gain by ordering")
        ax.legend(frameon=True)
        ax.yaxis.grid(True)
        ax.set_axisbelow(True)
    else:
        ax.text(0.5, 0.5, "No step gate data", ha="center", va="center",
                transform=ax.transAxes)

    # Panel B: scatter — depth residual vs Δlog-fidelity (step1)
    ax2 = axes[1]
    if "step1_residual_pct" in s.columns and "dlf_step1" in s.columns:
        valid = s[s["dlf_step1"].notna() & s["step1_residual_pct"].notna()]
        ordering_list = valid["ordering"].unique()
        colors_ord = {o: list(SDK_COLOR.values())[i % len(SDK_COLOR)]
                      for i, o in enumerate(ordering_list)}
        for ord_name, grp in valid.groupby("ordering"):
            ax2.scatter(grp["step1_residual_pct"], grp["dlf_step1"],
                        color=colors_ord[ord_name], alpha=0.7, s=18, edgecolors="none",
                        label=shorten(ord_name))
        ax2.axhline(0, color="#888", linewidth=0.7, linestyle="--")
        ax2.axvline(0, color="#888", linewidth=0.7, linestyle="--")
        ax2.set_xlabel("Depth residual improvement (%)")
        ax2.set_ylabel("Δlog(F) / |log(F_step0)| × 100")
        ax2.set_title("(b) Depth vs. relative log-fidelity (Step 1)")
        ax2.legend(fontsize=6.5, frameon=True, markerscale=1.5)
        ax2.yaxis.grid(True)
        ax2.xaxis.grid(True)
        ax2.set_axisbelow(True)
    else:
        ax2.text(0.5, 0.5, "No step gate data in CSV", ha="center", va="center",
                 transform=ax2.transAxes)

    note = f"ε_1Q={_ERR_1Q:.5f}, ε_2Q={_ERR_2Q:.5f}  ({_ERR_LABEL})"
    fig.text(0.5, -0.02, note, ha="center", fontsize=6.5, color="#888888", style="italic")
    fig.tight_layout()
    _save(fig, "fig10_fidelity_complementarity")


# ════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════

FIGURE_FUNCS = {
    1: ("fig1_layout",        fig1_layout),
    2: ("fig2_optimization",  fig2_optimization),
    3: ("fig3_complementarity", fig3_complementarity),
    4: ("fig4_destructive",   fig4_destructive),
    5: ("fig5_topology",      fig5_topology),
    6: ("fig6_runtime",       fig6_runtime),
    7: ("fig7_summary_heatmap", fig7_summary_heatmap),
    # ── Estimated fidelity figures (FakeBrooklyn V2 mean error rates) ────────
    8: ("fig8_fidelity_layout",         fig8_fidelity_layout),
    9: ("fig9_fidelity_optimization",   fig9_fidelity_optimization),
    10: ("fig10_fidelity_complementarity", fig10_fidelity_complementarity),
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate QLego paper figures")
    parser.add_argument("--fig", type=int, nargs="+", default=None,
                        help="Figure numbers to generate (default: all)")
    args = parser.parse_args()

    to_run = args.fig if args.fig else list(FIGURE_FUNCS.keys())
    for num in to_run:
        if num not in FIGURE_FUNCS:
            print(f"  Unknown figure {num}, skipping")
            continue
        name, fn = FIGURE_FUNCS[num]
        print(f"\n[Figure {num}] {name}")
        try:
            fn()
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()

    print(f"\nDone. Figures saved to: {FIGURES}")
