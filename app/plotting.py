from __future__ import annotations

from collections import defaultdict
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
import matplotlib.pyplot as plt
from models import BaseTopology


SUMMARY_METRICS = [
    ("avg_hops", "Average hops"),
    ("avg_delay", "Average delay"),
    ("avg_success_rate", "Success rate"),
]
LMM_COLORS = {
    "LMM-1": "#1f77b4",
    "LMM-2": "#ff7f0e",
}
LMM_MARKERS = {
    "LMM-1": "o",
    "LMM-2": "s",
}


def  group(rows: Sequence[Dict[str, object]], key: str) -> Dict[object, List[Dict[str, object]]]:
    grouped: Dict[object, List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    return grouped


def plot_topology(
    base: BaseTopology,
    output_path: Path,
    active_publishers: Optional[Sequence[str]] = None,
    user_node_ids: Optional[Sequence[str]] = None,
    cache_node_ids: Optional[Sequence[str]] = None,
    title: Optional[str] = None,
) :
    if plt is None:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)

    active_publishers_set = set(active_publishers or [])
    user_attachment_ids = list(user_node_ids or [])
    user_edge_nodes = set(user_attachment_ids)
    cache_nodes = set(cache_node_ids or [])
    edge_nodes = set(base.edge_node_ids)
    idle_edge_nodes = edge_nodes - user_edge_nodes

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

    def  user_positions() -> List[Tuple[str, str, float, float]]:
        positions: List[Tuple[str, str, float, float]] = []
        users_per_edge: Dict[str, int] = defaultdict(int)
        for edge_id in user_attachment_ids:
            users_per_edge[edge_id] += 1

        used_per_edge: Dict[str, int] = defaultdict(int)
        for user_index, edge_id in enumerate(user_attachment_ids, start=1):
            edge_node = base.nodes[edge_id]
            slot = used_per_edge[edge_id]
            used_per_edge[edge_id] += 1
            total = users_per_edge[edge_id]
            radius = 5.0
            if total == 1:
                angle = -math.pi / 2.0
            else:
                angle = (-math.pi / 2.0) + ((2.0 * math.pi * slot) / total)
            x = edge_node.x + (radius * math.cos(angle))
            y = edge_node.y + (radius * math.sin(angle))
            positions.append((f"U{user_index}", edge_id, x, y))
        return positions

    def  scatter(
        node_ids,
        label,
        color,
        marker,
        size,
        edgecolor="white",
        linewidth=0.8,
        alpha=1.0,
    ):
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
        if node_id not in edge_nodes
        and node_id not in base.publisher_candidates
        and node_id not in user_edge_nodes
        and node_id not in cache_nodes
    ]

    scatter(router_ids, label="Routers", color="#9aa4b2", marker="o", size=28, edgecolor="none", linewidth=0.0, alpha=0.9)
    scatter(sorted(active_publishers_set), label="Active publishers", color="#f28e2b", marker="s", size=110, edgecolor="white", linewidth=1.0, alpha=1.0)
    scatter(sorted(idle_edge_nodes), label="Edge nodes", color="#4e79a7", marker="^", size=115, edgecolor="white", linewidth=1.0, alpha=0.95)
    scatter(sorted(user_edge_nodes), label="Access edge nodes", color="#2f6f9f", marker="^", size=130, edgecolor="white", linewidth=1.0, alpha=1.0)
    scatter(sorted(cache_nodes), label="Cache nodes", color="#d62798", marker="D", size=105, edgecolor="white", linewidth=1.0, alpha=1.0)

    user_positions = user_positions()
    if user_positions:
        first_user_link = True
        for _, edge_id, user_x, user_y in user_positions:
            edge_node = base.nodes[edge_id]
            axis.plot(
                [edge_node.x, user_x],
                [edge_node.y, user_y],
                color="#7f8c8d",
                linewidth=0.8,
                alpha=0.75,
                zorder=2,
                label="User attachment" if first_user_link else "_nolegend_",
            )
            first_user_link = False

        axis.scatter(
            [user_x for _, _, user_x, _ in user_positions],
            [user_y for _, _, _, user_y in user_positions],
            s=72,
            c="#2ca02c",
            marker="o",
            edgecolors="white",
            linewidths=0.9,
            alpha=1.0,
            label="Users",
            zorder=4,
        )

        for user_label, _, user_x, user_y in user_positions:
            axis.text(
                user_x + 0.5,
                user_y + 0.5,
                user_label,
                fontsize=8,
                color="#1f2937",
                zorder=5,
            )

    # Label only the important nodes, otherwise the figure gets too cluttered.
    labeled_nodes = edge_nodes | active_publishers_set | cache_nodes
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
    user_sweep_fixed_publishers: Optional[int] = None,
) :
    if plt is None:
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 3, figsize=(15, 9))

    pub_by_lmm = group(publisher_summary, "lmm")
    user_by_lmm = group(user_summary, "lmm")
    bar_width = 0.36

    def plot_grouped_bars(
        axis,
        rows_by_lmm: Dict[object, List[Dict[str, object]]],
        x_key: str,
        xlabel: str,
        metric: str,
        ylabel: str,
    ) :
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
            color=LMM_COLORS["LMM-1"],
            alpha=0.82,
            label="LMM-1",
        )
        axis.bar(
            right_positions,
            lmm2_values,
            width=bar_width,
            color=LMM_COLORS["LMM-2"],
            alpha=0.82,
            label="LMM-2",
        )

        axis.plot(
            left_positions,
            lmm1_values,
            linestyle="None",
            marker=LMM_MARKERS["LMM-1"],
            markersize=6,
            markerfacecolor="white",
            markeredgewidth=1.4,
            markeredgecolor=LMM_COLORS["LMM-1"],
            label="_nolegend_",
        )
        axis.plot(
            right_positions,
            lmm2_values,
            linestyle="None",
            marker=LMM_MARKERS["LMM-2"],
            markersize=6,
            markerfacecolor="white",
            markeredgewidth=1.4,
            markeredgecolor=LMM_COLORS["LMM-2"],
            label="_nolegend_",
        )

        axis.set_xticks(positions)
        axis.set_xticklabels(x_values)
        axis.set_xlabel(xlabel)
        axis.set_ylabel(ylabel)
        axis.grid(axis="y", alpha=0.3)
        axis.legend()

    for column, (metric, ylabel) in enumerate(SUMMARY_METRICS):
        axis = axes[0, column]
        plot_grouped_bars(
            axis,
            pub_by_lmm,
            x_key="num_publishers",
            xlabel="Number of publishers",
            metric=metric,
            ylabel=ylabel,
        )

    for column, (metric, ylabel) in enumerate(SUMMARY_METRICS):
        axis = axes[1, column]
        xlabel = "Number of users"
        if user_sweep_fixed_publishers is not None:
            xlabel = f"Number of users (fixed Np={user_sweep_fixed_publishers})"
        plot_grouped_bars(
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
) :
    if plt is None:
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
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

    for column, (metric, ylabel) in enumerate(SUMMARY_METRICS):
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

    for column, (metric, ylabel) in enumerate(SUMMARY_METRICS):
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
