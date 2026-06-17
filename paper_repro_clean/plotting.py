from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence

try:
    from .models import BaseTopology
except ImportError:  # pragma: no cover
    from models import BaseTopology


try:
    import matplotlib.pyplot as plt
except ImportError:  # pragma: no cover
    plt = None


PLOTTING_AVAILABLE = plt is not None


def _group(rows: Sequence[Dict[str, object]], key: str) -> Dict[object, List[Dict[str, object]]]:
    grouped: Dict[object, List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    return grouped


def plot_topology(
    base: BaseTopology,
    output_path: Path,
    *,
    active_publishers: Optional[Sequence[str]] = None,
    user_node_ids: Optional[Sequence[str]] = None,
    cache_node_ids: Optional[Sequence[str]] = None,
    title: Optional[str] = None,
) -> None:
    if plt is None:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)

    active_publishers_set = set(active_publishers or [])
    user_node_set = set(user_node_ids or [])
    cache_node_set = set(cache_node_ids or [])
    standby_publisher_set = set(base.publisher_candidates) - active_publishers_set

    fig, axis = plt.subplots(figsize=(10, 10))

    drawn_edges = set()
    for node_id, neighbors in base.adjacency.items():
        node = base.nodes[node_id]
        for neighbor_id in neighbors:
            edge_key = tuple(sorted((node_id, neighbor_id)))
            if edge_key in drawn_edges:
                continue
            drawn_edges.add(edge_key)
            neighbor = base.nodes[neighbor_id]
            axis.plot(
                [node.x, neighbor.x],
                [node.y, neighbor.y],
                color="#cfd4dc",
                linewidth=0.75,
                alpha=0.55,
                zorder=1,
            )

    def _scatter(node_ids, *, label, color, marker, size, edgecolor="white", linewidth=0.8, alpha=1.0):
        if not node_ids:
            return
        xs = [base.nodes[node_id].x for node_id in node_ids]
        ys = [base.nodes[node_id].y for node_id in node_ids]
        axis.scatter(
            xs,
            ys,
            s=size,
            c=color,
            marker=marker,
            edgecolors=edgecolor,
            linewidths=linewidth,
            alpha=alpha,
            label=label,
            zorder=3,
        )

    router_ids = [
        node_id
        for node_id in base.nodes
        if node_id != base.subscriber_id
        and node_id not in base.publisher_candidates
        and node_id not in user_node_set
        and node_id not in cache_node_set
    ]

    _scatter(router_ids, label="Routers", color="#9aa4b2", marker="o", size=28, edgecolor="none", linewidth=0.0, alpha=0.9)
    _scatter(sorted(standby_publisher_set), label="Publisher candidates", color="#f7c97f", marker="s", size=80, edgecolor="#9c6b1f", linewidth=0.9, alpha=0.95)
    _scatter(sorted(active_publishers_set), label="Active publishers", color="#f28e2b", marker="s", size=110, edgecolor="white", linewidth=1.0, alpha=1.0)
    _scatter(sorted(user_node_set), label="Users", color="#2ca02c", marker="o", size=115, edgecolor="white", linewidth=1.0, alpha=1.0)
    _scatter(sorted(cache_node_set), label="Cache nodes", color="#d62798", marker="D", size=105, edgecolor="white", linewidth=1.0, alpha=1.0)
    _scatter([base.subscriber_id], label="Subscriber EN0", color="#1f77b4", marker="*", size=260, edgecolor="white", linewidth=1.0, alpha=1.0)

    labeled_nodes = {base.subscriber_id} | active_publishers_set | user_node_set | cache_node_set
    for node_id in sorted(labeled_nodes):
        node = base.nodes[node_id]
        axis.text(
            node.x + 1.2,
            node.y + 1.2,
            node_id,
            fontsize=8,
            color="#1f2937",
            zorder=4,
        )

    axis.set_title(title or "Topology snapshot", fontsize=12)
    axis.set_xlabel("X position (m)")
    axis.set_ylabel("Y position (m)")
    axis.set_aspect("equal", adjustable="box")
    axis.grid(alpha=0.18)
    axis.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_summary_curves(
    publisher_summary: Sequence[Dict[str, object]],
    user_summary: Sequence[Dict[str, object]],
    output_dir: Path,
    *,
    user_sweep_fixed_publishers: Optional[int] = None,
) -> None:
    if plt is None:
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 3, figsize=(15, 9))
    metrics = [
        ("avg_hops", "Average hops"),
        ("avg_delay", "Average delay"),
        ("avg_success_rate", "Success rate"),
    ]

    pub_by_lmm = _group(publisher_summary, "lmm")
    user_by_lmm = _group(user_summary, "lmm")
    bar_width = 0.36
    colors = {
        "LMM-1": "#1f77b4",
        "LMM-2": "#ff7f0e",
    }
    markers = {
        "LMM-1": "o",
        "LMM-2": "s",
    }

    def _plot_grouped_bars(
        axis,
        rows_by_lmm: Dict[object, List[Dict[str, object]]],
        x_key: str,
        xlabel: str,
        metric: str,
        ylabel: str,
    ) -> None:
        lmm1_rows = sorted(rows_by_lmm.get("LMM-1", []), key=lambda row: int(row[x_key]))
        lmm2_rows = sorted(rows_by_lmm.get("LMM-2", []), key=lambda row: int(row[x_key]))
        x_values = [int(row[x_key]) for row in lmm1_rows or lmm2_rows]
        positions = list(range(len(x_values)))
        left_positions = [pos - (bar_width / 2.0) for pos in positions]
        right_positions = [pos + (bar_width / 2.0) for pos in positions]

        lmm1_values = [float(row[metric]) for row in lmm1_rows]
        lmm2_values = [float(row[metric]) for row in lmm2_rows]

        axis.bar(
            left_positions,
            lmm1_values,
            width=bar_width,
            color=colors["LMM-1"],
            alpha=0.82,
            label="LMM-1",
        )
        axis.bar(
            right_positions,
            lmm2_values,
            width=bar_width,
            color=colors["LMM-2"],
            alpha=0.82,
            label="LMM-2",
        )

        axis.plot(
            left_positions,
            lmm1_values,
            linestyle="None",
            marker=markers["LMM-1"],
            markersize=6,
            markerfacecolor="white",
            markeredgewidth=1.4,
            markeredgecolor=colors["LMM-1"],
            label="_nolegend_",
        )
        axis.plot(
            right_positions,
            lmm2_values,
            linestyle="None",
            marker=markers["LMM-2"],
            markersize=6,
            markerfacecolor="white",
            markeredgewidth=1.4,
            markeredgecolor=colors["LMM-2"],
            label="_nolegend_",
        )

        axis.set_xticks(positions)
        axis.set_xticklabels(x_values)
        axis.set_xlabel(xlabel)
        axis.set_ylabel(ylabel)
        axis.grid(axis="y", alpha=0.3)
        axis.legend()

    for column, (metric, ylabel) in enumerate(metrics):
        axis = axes[0, column]
        _plot_grouped_bars(
            axis,
            pub_by_lmm,
            x_key="num_publishers",
            xlabel="Number of publishers",
            metric=metric,
            ylabel=ylabel,
        )

    for column, (metric, ylabel) in enumerate(metrics):
        axis = axes[1, column]
        xlabel = "Number of users"
        if user_sweep_fixed_publishers is not None:
            xlabel = f"Number of users (fixed Np={user_sweep_fixed_publishers})"
        _plot_grouped_bars(
            axis,
            user_by_lmm,
            x_key="num_users",
            xlabel=xlabel,
            metric=metric,
            ylabel=ylabel,
        )

    fig.suptitle("LMM-1 vs LMM-2 summary metrics", fontsize=12)
    fig.tight_layout()
    fig.savefig(output_dir / "summary_curves.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_iteration_profiles(
    publisher_iteration_summary: Sequence[Dict[str, object]],
    user_iteration_summary: Sequence[Dict[str, object]],
    output_dir: Path,
) -> None:
    if plt is None:
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
    metrics = [
        ("avg_hops", "Average hops"),
        ("avg_delay", "Average delay"),
        ("avg_success_rate", "Success rate"),
    ]
    colors = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
    ]
    styles = {
        "LMM-1": "-",
        "LMM-2": "--",
    }

    for column, (metric, ylabel) in enumerate(metrics):
        axis = axes[0, column]
        grouped = defaultdict(list)
        for row in publisher_iteration_summary:
            grouped[(int(row["num_publishers"]), str(row["lmm"]))].append(row)
        for color_index, num_publishers in enumerate(sorted({int(row["num_publishers"]) for row in publisher_iteration_summary})):
            color = colors[color_index % len(colors)]
            for lmm in ("LMM-1", "LMM-2"):
                rows = sorted(grouped[(num_publishers, lmm)], key=lambda row: int(row["iteration"]))
                axis.plot(
                    [int(row["iteration"]) for row in rows],
                    [float(row[metric]) for row in rows],
                    linestyle=styles[lmm],
                    color=color,
                    linewidth=1.1,
                    label=f"Np={num_publishers} {lmm}",
                )
        axis.set_xlabel("Iteration")
        axis.set_ylabel(ylabel)
        axis.grid(alpha=0.25)
        axis.legend(fontsize=7, ncol=2)

    for column, (metric, ylabel) in enumerate(metrics):
        axis = axes[1, column]
        grouped = defaultdict(list)
        for row in user_iteration_summary:
            grouped[(int(row["num_users"]), str(row["lmm"]))].append(row)
        for color_index, num_users in enumerate(sorted({int(row["num_users"]) for row in user_iteration_summary})):
            color = colors[color_index % len(colors)]
            for lmm in ("LMM-1", "LMM-2"):
                rows = sorted(grouped[(num_users, lmm)], key=lambda row: int(row["iteration"]))
                axis.plot(
                    [int(row["iteration"]) for row in rows],
                    [float(row[metric]) for row in rows],
                    linestyle=styles[lmm],
                    color=color,
                    linewidth=1.1,
                    label=f"Nu={num_users} {lmm}",
                )
        axis.set_xlabel("Iteration")
        axis.set_ylabel(ylabel)
        axis.grid(alpha=0.25)
        axis.legend(fontsize=7, ncol=2)

    fig.suptitle("Per-iteration profiles over 200 runs", fontsize=12)
    fig.tight_layout()
    fig.savefig(output_dir / "iteration_profiles.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
