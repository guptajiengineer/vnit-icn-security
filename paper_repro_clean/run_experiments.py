from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from .models import ContentSpec
    from .network import build_base_topology
    from .plotting import PLOTTING_AVAILABLE, plot_iteration_profiles, plot_summary_curves, plot_topology
    from .simulator import (
        CHUNKING_MODE_BOTH,
        CHUNKING_MODE_WITH,
        CHUNKING_MODE_WITHOUT,
        assign_content_publishers,
        build_default_content_specs,
        build_provider_paths,
        choose_cache_node,
        run_full_experiment,
        select_multipaths,
        summarize_records,
        write_csv,
        write_json,
    )
except ImportError:  # pragma: no cover
    from models import ContentSpec
    from network import build_base_topology
    from plotting import PLOTTING_AVAILABLE, plot_iteration_profiles, plot_summary_curves, plot_topology
    from simulator import (
        CHUNKING_MODE_BOTH,
        CHUNKING_MODE_WITH,
        CHUNKING_MODE_WITHOUT,
        assign_content_publishers,
        build_default_content_specs,
        build_provider_paths,
        choose_cache_node,
        run_full_experiment,
        select_multipaths,
        summarize_records,
        write_csv,
        write_json,
    )


def _inclusive_step_range(start: int, stop: int, step: int) -> List[int]:
    if stop < start:
        raise ValueError("range end must be >= range start")
    if step <= 0:
        raise ValueError("step must be > 0")
    return list(range(start, stop + 1, step))


def _parse_csv_values(raw: Optional[str], *, cast, label: str) -> Optional[List[object]]:
    if raw is None:
        return None

    values = [part.strip() for part in raw.split(",") if part.strip()]
    if not values:
        raise ValueError(f"{label} must not be empty")

    try:
        return [cast(value) for value in values]
    except ValueError as exc:
        raise ValueError(f"could not parse {label}: {raw}") from exc


def _build_content_specs(args: argparse.Namespace) -> List[ContentSpec]:
    content_specs = build_default_content_specs(args.content_count)
    expected_length = len(content_specs)

    ids = _parse_csv_values(args.content_ids, cast=str, label="content ids")
    generation_rounds = _parse_csv_values(
        args.content_generation_rounds,
        cast=int,
        label="content generation rounds",
    )
    lifespans = _parse_csv_values(args.content_lifespans, cast=int, label="content lifespans")
    cache_costs = _parse_csv_values(args.content_cache_costs, cast=float, label="content cache costs")
    popularities = _parse_csv_values(args.content_popularities, cast=float, label="content popularities")
    availability_thresholds = _parse_csv_values(
        args.content_availability_thresholds,
        cast=float,
        label="content availability thresholds",
    )
    lifetime_thresholds = _parse_csv_values(
        args.content_lifetime_thresholds,
        cast=float,
        label="content lifetime thresholds",
    )

    overrides = (
        (ids, "content ids"),
        (generation_rounds, "content generation rounds"),
        (lifespans, "content lifespans"),
        (cache_costs, "content cache costs"),
        (popularities, "content popularities"),
        (availability_thresholds, "content availability thresholds"),
        (lifetime_thresholds, "content lifetime thresholds"),
    )
    for values, label in overrides:
        if values is not None and len(values) != expected_length:
            raise ValueError(f"{label} must contain exactly {expected_length} values")

    for index, content in enumerate(content_specs):
        if ids is not None:
            content.content_id = str(ids[index])
        if generation_rounds is not None:
            content.generation_round = int(generation_rounds[index])
        if lifespans is not None:
            content.lifespan_rounds = int(lifespans[index])
        if cache_costs is not None:
            content.cache_cost = float(cache_costs[index])
        if popularities is not None:
            content.popularity = float(popularities[index])
        if availability_thresholds is not None:
            content.availability_threshold = float(availability_thresholds[index])
        if lifetime_thresholds is not None:
            content.lifetime_threshold = float(lifetime_thresholds[index])

    return content_specs


def _maybe_plot_topology(
    *,
    output_dir: Path,
    seed_base: int,
    publisher_values: List[int],
    user_values: List[int],
    content_specs: List[ContentSpec],
    content_replication_k: int,
    topology_seed: Optional[int],
    topology_publishers: Optional[int],
    topology_users: Optional[int],
) -> Optional[str]:
    if not PLOTTING_AVAILABLE:
        return None

    seed = topology_seed if topology_seed is not None else seed_base
    num_publishers = topology_publishers if topology_publishers is not None else publisher_values[-1]
    num_users = topology_users if topology_users is not None else user_values[-1]

    base = build_base_topology(seed)
    active_publishers = base.publisher_candidates[:num_publishers]
    content_publishers = assign_content_publishers(
        active_publishers,
        content_specs,
        min_publishers_per_content=content_replication_k,
        seed=(seed * 1009) + (num_publishers * 97),
    )
    preview_content = content_specs[0]

    cache_node_ids = set()
    selected_paths = select_multipaths(
        build_provider_paths(
            base,
            active_publishers,
            base.subscriber_id,
            preview_content.content_id,
            content_publishers=content_publishers,
            include_cached_providers=True,
        )
    )
    cache_node_id = choose_cache_node(
        base,
        selected_paths,
        base.subscriber_id,
        content=preview_content,
        round_index=0,
    )
    if cache_node_id is not None:
        cache_node_ids.add(cache_node_id)

    file_name = f"topology_seed_{seed}_Np_{num_publishers}_Nu_{num_users}.png"
    plot_topology(
        base,
        output_dir / file_name,
        active_publishers=active_publishers,
        user_node_ids=[],
        cache_node_ids=sorted(cache_node_ids),
        title=(
            f"Topology snapshot: seed={seed}, Np={num_publishers}, "
            f"Nu={num_users} via {base.subscriber_id}, content={preview_content.content_id}"
        ),
    )
    return file_name


def _write_mode_outputs(
    *,
    output_dir: Path,
    raw_records: Sequence[Dict[str, Any]],
    fixed_user_sweep_publishers: int,
    plots_enabled: bool,
) -> None:
    full_summary = summarize_records(
        raw_records,
        key_fields=("num_publishers", "num_users", "lmm"),
    )
    publisher_summary = summarize_records(
        raw_records,
        key_fields=("num_publishers", "lmm"),
    )
    user_summary = [
        row
        for row in full_summary
        if int(row["num_publishers"]) == fixed_user_sweep_publishers
    ]
    publisher_iteration_summary = summarize_records(
        raw_records,
        key_fields=("iteration", "num_publishers", "lmm"),
    )
    user_iteration_summary = summarize_records(
        raw_records,
        key_fields=("iteration", "num_users", "lmm"),
    )

    write_csv(output_dir / "raw_results.csv", raw_records)
    write_csv(output_dir / "summary_by_publishers_and_users.csv", full_summary)
    write_csv(output_dir / "summary_by_publishers.csv", publisher_summary)
    write_csv(output_dir / "summary_by_users.csv", user_summary)
    write_csv(output_dir / "iteration_profile_by_publishers.csv", publisher_iteration_summary)
    write_csv(output_dir / "iteration_profile_by_users.csv", user_iteration_summary)

    if plots_enabled:
        plot_summary_curves(
            publisher_summary,
            user_summary,
            output_dir,
            user_sweep_fixed_publishers=fixed_user_sweep_publishers,
        )
        plot_iteration_profiles(publisher_iteration_summary, user_iteration_summary, output_dir)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run clean LMM-1 vs LMM-2 reproduction experiments.",
    )
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--seed-base", type=int, default=1000)
    parser.add_argument("--publisher-start", type=int, default=4)
    parser.add_argument("--publisher-end", type=int, default=10)
    parser.add_argument("--user-start", type=int, default=2)
    parser.add_argument("--user-end", type=int, default=8)
    parser.add_argument(
        "--user-sweep-fixed-publishers",
        type=int,
        default=None,
        help="Publisher count to hold fixed in the bottom-row user summary plots; defaults to the largest Np in the sweep.",
    )
    parser.add_argument("--arrival-window", type=float, default=40.0)
    parser.add_argument(
        "--content-replication-k",
        type=int,
        default=2,
        help="Minimum number of publishers that each content is randomly assigned to.",
    )
    parser.add_argument(
        "--chunking-mode",
        type=str,
        choices=(CHUNKING_MODE_WITHOUT, CHUNKING_MODE_WITH, CHUNKING_MODE_BOTH),
        default=CHUNKING_MODE_BOTH,
        help="Fetch mode: single best path, chunked across all selected paths, or run both and save separate result bundles.",
    )
    parser.add_argument(
        "--load-normalized-arrivals",
        action="store_true",
        help="Scale arrival_window linearly with Nu so per-user offered load stays roughly constant.",
    )
    parser.add_argument(
        "--arrival-window-reference-users",
        type=int,
        default=None,
        help="Reference user count for load-normalized arrivals; defaults to the smallest Nu in the sweep.",
    )
    parser.add_argument("--content-count", type=int, default=4)
    parser.add_argument("--content-ids", type=str, default=None)
    parser.add_argument("--content-generation-rounds", type=str, default=None)
    parser.add_argument("--content-lifespans", type=str, default=None)
    parser.add_argument("--content-cache-costs", type=str, default=None)
    parser.add_argument("--content-popularities", type=str, default=None)
    parser.add_argument("--content-availability-thresholds", type=str, default=None)
    parser.add_argument("--content-lifetime-thresholds", type=str, default=None)
    parser.add_argument(
        "--topology-reuse-span",
        type=int,
        default=20,
        help="Reuse one topology for this many iterations before advancing to the next seed block.",
    )
    parser.add_argument(
        "--vary-topology-per-iteration",
        action="store_true",
        help="Rebuild a new topology for each iteration instead of reusing one base topology.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("paper_repro_clean") / "results",
    )
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--plot-topology", action="store_true")
    parser.add_argument("--topology-seed", type=int, default=None)
    parser.add_argument("--topology-publishers", type=int, default=None)
    parser.add_argument("--topology-users", type=int, default=None)
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()

    publisher_values = _inclusive_step_range(args.publisher_start, args.publisher_end, 2)
    user_values = _inclusive_step_range(args.user_start, args.user_end, 2)
    content_specs = _build_content_specs(args)
    if args.content_replication_k <= 0:
        raise ValueError("content-replication-k must be > 0")
    topology_reuse_span = 1 if args.vary_topology_per_iteration else max(1, args.topology_reuse_span)

    raw_records = run_full_experiment(
        iterations=args.iterations,
        publisher_values=publisher_values,
        user_values=user_values,
        seed_base=args.seed_base,
        arrival_window=args.arrival_window,
        content_specs=content_specs,
        content_replication_k=args.content_replication_k,
        reuse_topology=(topology_reuse_span > 1),
        topology_reuse_span=topology_reuse_span,
        chunking_mode=args.chunking_mode,
        load_normalized_arrivals=args.load_normalized_arrivals,
        arrival_window_reference_users=args.arrival_window_reference_users,
    )
    fixed_user_sweep_publishers = (
        args.user_sweep_fixed_publishers
        if args.user_sweep_fixed_publishers is not None
        else publisher_values[-1]
    )
    if fixed_user_sweep_publishers not in publisher_values:
        raise ValueError(
            f"user-sweep-fixed-publishers must be one of {publisher_values}, got {fixed_user_sweep_publishers}"
        )

    output_dir: Path = args.output_dir
    if args.chunking_mode == CHUNKING_MODE_BOTH:
        write_csv(output_dir / "raw_results.csv", raw_records)
        write_csv(
            output_dir / "summary_by_publishers_and_users.csv",
            summarize_records(
                raw_records,
                key_fields=("chunking_mode", "num_publishers", "num_users", "lmm"),
            ),
        )
        mode_output_dirs = {}
        for chunking_label in ("without_chunking", "with_chunking"):
            mode_records = [
                row
                for row in raw_records
                if str(row["chunking_mode"]) == chunking_label
            ]
            mode_dir = output_dir / chunking_label
            _write_mode_outputs(
                output_dir=mode_dir,
                raw_records=mode_records,
                fixed_user_sweep_publishers=fixed_user_sweep_publishers,
                plots_enabled=bool(PLOTTING_AVAILABLE and not args.no_plots),
            )
            mode_output_dirs[chunking_label] = str(mode_dir)
    else:
        _write_mode_outputs(
            output_dir=output_dir,
            raw_records=raw_records,
            fixed_user_sweep_publishers=fixed_user_sweep_publishers,
            plots_enabled=bool(PLOTTING_AVAILABLE and not args.no_plots),
        )
        mode_output_dirs = {}

    write_json(
        output_dir / "manifest.json",
        {
            "iterations": args.iterations,
            "seed_base": args.seed_base,
            "publisher_values": publisher_values,
            "user_values": user_values,
            "user_sweep_fixed_publishers": fixed_user_sweep_publishers,
            "arrival_window": args.arrival_window,
            "content_replication_k": args.content_replication_k,
            "chunking_mode": args.chunking_mode,
            "mode_output_dirs": mode_output_dirs,
            "load_normalized_arrivals": args.load_normalized_arrivals,
            "arrival_window_reference_users": args.arrival_window_reference_users,
            "content_specs": [content.__dict__ for content in content_specs],
            "reuse_topology": (topology_reuse_span > 1),
            "topology_reuse_span": topology_reuse_span,
            "plots_created": bool(PLOTTING_AVAILABLE and not args.no_plots),
        },
    )

    topology_file_name = None
    if args.plot_topology:
        topology_file_name = _maybe_plot_topology(
            output_dir=output_dir,
            seed_base=args.seed_base,
            publisher_values=publisher_values,
            user_values=user_values,
            content_specs=content_specs,
            content_replication_k=args.content_replication_k,
            topology_seed=args.topology_seed,
            topology_publishers=args.topology_publishers,
            topology_users=args.topology_users,
        )

    if args.chunking_mode == CHUNKING_MODE_BOTH:
        print(f"Saved combined and per-mode results to {output_dir}")
    else:
        print(f"Saved raw and summary results to {output_dir}")
    if args.no_plots:
        print("Plots were skipped because --no-plots was set.")
    elif not PLOTTING_AVAILABLE:
        print("matplotlib is not available, so only CSV/JSON outputs were written.")
    elif args.chunking_mode == CHUNKING_MODE_BOTH:
        print("Plots were written inside the without_chunking/ and with_chunking/ result subfolders.")
    else:
        print("Plots were written to summary_curves.png and iteration_profiles.png.")
    if args.plot_topology and topology_file_name is not None:
        print(f"Topology snapshot was written to {topology_file_name}.")


if __name__ == "__main__":
    main()
