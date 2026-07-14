import argparse
from pprint import pprint
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from models import ContentSpec
from network import build_base_topology
from plotting import plot_iteration_profiles, plot_summary_curves, plot_topology
from simulator import (
    AUTH_MODE_BOTH,
    AUTH_MODE_WITH,
    AUTH_MODE_WITHOUT,
    CHUNKING_MODE_BOTH,
    CHUNKING_MODE_WITH,
    CHUNKING_MODE_WITHOUT,
    assign_content_publishers,
    build_default_content_specs,
    build_provider_paths,
    choose_cache_node,
    expand_user_edge_nodes,
    get_user_nodes,
    run_full_experiment,
    select_multipaths,
    summarize_records,
    write_csv,
)


# def inclusive_step_range(start: int, stop: int, step: int) -> List[int]:
#     if stop < start:
#         raise ValueError("range end must be >= range start")
#     if step <= 0:
#         raise ValueError("step must be > 0")
#     return list(range(start, stop + 1, step))


def validate_args(args: argparse.Namespace) :
    if args.content_replication_k <= 0:
        raise ValueError("content-replication-k must be > 0")
    if args.edge_node_count <= 0:
        raise ValueError("edge-node-count must be > 0")


def plot_network_topology(
    output_dir: Path,
    seed_base: int,
    publisher_values: List[int],
    user_values: List[int],
    content_specs: List[ContentSpec],
    content_replication_k: int,
    topology_seed: Optional[int],
    topology_publishers: Optional[int],
    topology_users: Optional[int],
    edge_node_count: int,
) -> Optional[str]:

    seed = topology_seed if topology_seed is not None else seed_base
    num_publishers = topology_publishers if topology_publishers is not None else publisher_values[-1]
    num_users = topology_users if topology_users is not None else user_values[-1]

    base = build_base_topology(seed, edge_node_count=edge_node_count)
    active_publishers = base.publisher_candidates[:num_publishers]
    ranked_edge_nodes = get_user_nodes(
        base,
        active_publishers,
        max_candidates=max(1, edge_node_count),
    )
    selected_user_nodes = expand_user_edge_nodes(ranked_edge_nodes, num_users)
    content_publishers = assign_content_publishers(
        active_publishers,
        content_specs,
        min_publishers_per_content=content_replication_k,
        seed=(seed * 1009) + (num_publishers * 97),
    )
    preview_content = content_specs[0]
    request_node_id = selected_user_nodes[0] if selected_user_nodes else base.subscriber_id

    cache_node_ids = set()
    selected_paths = select_multipaths(
        build_provider_paths(
            base,
            active_publishers,
            request_node_id,
            preview_content.content_id,
            content_publishers=content_publishers,
            include_cached_providers=True,
        )
    )
    cache_node_id = choose_cache_node(
        base,
        selected_paths,
        request_node_id,
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
        user_node_ids=selected_user_nodes,
        cache_node_ids=sorted(cache_node_ids),
        title=(
            f"Topology snapshot: seed={seed}, Np={num_publishers}, "
            f"Nu={num_users}, request={request_node_id}, content={preview_content.content_id}"
        ),
    )
    return file_name


def write_mode_outputs(
    output_dir: Path,
    raw_records: Sequence[Dict[str, Any]],
    fixed_user_sweep_publishers: int,
) :
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

    plot_summary_curves(
        publisher_summary,
        user_summary,
        output_dir,
        user_sweep_fixed_publishers=fixed_user_sweep_publishers,
    )
    plot_iteration_profiles(publisher_iteration_summary, user_iteration_summary, output_dir)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--seed-base", type=int, default=1200)
    parser.add_argument("--publisher-start", type=int, default=4)
    parser.add_argument("--publisher-end", type=int, default=10)
    parser.add_argument("--user-start", type=int, default=2)
    parser.add_argument("--user-end", type=int, default=8)
    parser.add_argument(
        "--user-sweep-fixed-publishers",
        type=int,
        default=None,
        help="Publisher count to hold fixed in  user summary plots; defaults to the largest Np in the list.",
    )
    parser.add_argument("--arrival-window", type=float, default=20.0)
    parser.add_argument(
        "--content-replication-k",
        type=int,
        default=10,
        help="Minimum number of publishers that each content is randomly assigned to.",
    )
    parser.add_argument(
        "--chunking-mode",
        type=str,
        choices=(CHUNKING_MODE_WITHOUT, CHUNKING_MODE_WITH, CHUNKING_MODE_BOTH),
        default=CHUNKING_MODE_WITH,
        help="Fetch mode: single best path, chunked across all selected paths, or run both and save separate result bundles.",
    )
    # -----------------------------------------------------------------------
    # Obj2: --auth-mode argument — mirrors --chunking-mode exactly.
    # without : run without auth (baseline, same as final_code behaviour).
    # with    : run with full auth layer (hash + encrypt + Merkle verify).
    # both    : run both and save separate result bundles for overhead comparison.
    # -----------------------------------------------------------------------
    parser.add_argument(
        "--auth-mode",
        type=str,
        choices=(AUTH_MODE_WITHOUT, AUTH_MODE_WITH, AUTH_MODE_BOTH),
        default=AUTH_MODE_WITHOUT,
        help=(
            "Authentication mode: "
            "'without' = no auth (baseline); "
            "'with' = full cryptographic auth (hash+encrypt+Merkle); "
            "'both' = run both and save separate result bundles for overhead comparison."
        ),
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
    )#tosee / remove
    parser.add_argument("--content-count", type=int, default=2)
    
    parser.add_argument(
        "--edge-node-count",
        type=int,
        default=1,
        help="Number of edge nodes ENi to create in the topology.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output") / "results",
    )#change name of output file -> output
    parser.add_argument("--plot-topology", action="store_true")
    parser.add_argument("--topology-seed", type=int, default=None)
    parser.add_argument("--topology-publishers", type=int, default=None)
    parser.add_argument("--topology-users", type=int, default=None)
    return parser


def main() :
    parser = build_argument_parser()
    args = parser.parse_args()

    publisher_values = [4,6,8, 10] #inclusive_step_range(args.publisher_start, args.publisher_end, 2)
    user_values = [2, 4, 6, 8]#inclusive_step_range(args.user_start, args.user_end, 2)
    content_specs = build_default_content_specs(args.content_count)
    validate_args(args)

    raw_records = run_full_experiment(
        iterations=args.iterations,
        publisher_values=publisher_values,
        user_values=user_values,
        seed_base=args.seed_base,
        arrival_window=args.arrival_window,
        content_specs=content_specs,
        content_replication_k=args.content_replication_k,
        chunking_mode=args.chunking_mode,
        auth_mode=args.auth_mode,
        load_normalized_arrivals=args.load_normalized_arrivals,
        arrival_window_reference_users=args.arrival_window_reference_users,
        edge_node_count=args.edge_node_count,
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

    # -----------------------------------------------------------------------
    # Obj2: handle auth-mode BOTH output splitting — mirrors chunking_mode BOTH.
    # -----------------------------------------------------------------------
    auth_mode_labels = {
        AUTH_MODE_WITHOUT: ["without_auth"],
        AUTH_MODE_WITH:    ["with_auth"],
        AUTH_MODE_BOTH:    ["without_auth", "with_auth"],
    }
    auth_labels_for_mode = auth_mode_labels.get(args.auth_mode, ["without_auth"])

    if args.chunking_mode == CHUNKING_MODE_BOTH:
        write_csv(output_dir / "raw_results.csv", raw_records)
        write_csv(
            output_dir / "summary_by_publishers_and_users.csv",
            summarize_records(
                raw_records,
                key_fields=("chunking_mode", "auth_mode", "num_publishers", "num_users", "lmm"),
            ),
        )
        mode_output_dirs = {}
        for chunking_label in ("without_chunking", "with_chunking"):
            for a_label in auth_labels_for_mode:
                mode_records = [
                    row
                    for row in raw_records
                    if str(row["chunking_mode"]) == chunking_label
                    and str(row["auth_mode"]) == a_label
                ]
                mode_dir = output_dir / chunking_label / a_label
                write_mode_outputs(
                    output_dir=mode_dir,
                    raw_records=mode_records,
                    fixed_user_sweep_publishers=fixed_user_sweep_publishers,
                )
                mode_output_dirs[f"{chunking_label}/{a_label}"] = str(mode_dir)
    elif args.auth_mode == AUTH_MODE_BOTH:
        write_csv(output_dir / "raw_results.csv", raw_records)
        write_csv(
            output_dir / "summary_by_publishers_and_users.csv",
            summarize_records(
                raw_records,
                key_fields=("auth_mode", "num_publishers", "num_users", "lmm"),
            ),
        )
        mode_output_dirs = {}
        for a_label in auth_labels_for_mode:
            mode_records = [
                row for row in raw_records if str(row["auth_mode"]) == a_label
            ]
            mode_dir = output_dir / a_label
            write_mode_outputs(
                output_dir=mode_dir,
                raw_records=mode_records,
                fixed_user_sweep_publishers=fixed_user_sweep_publishers,
            )
            mode_output_dirs[a_label] = str(mode_dir)
    else:
        write_mode_outputs(
            output_dir=output_dir,
            raw_records=raw_records,
            fixed_user_sweep_publishers=fixed_user_sweep_publishers,
        )
        mode_output_dirs = {}

    manifest = {
        "iterations": args.iterations,
        "seed_base": args.seed_base,
        "publisher_values": publisher_values,
        "user_values": user_values,
        "user_sweep_fixed_publishers": fixed_user_sweep_publishers,
        "arrival_window": args.arrival_window,
        "content_replication_k": args.content_replication_k,
        "edge_node_count": args.edge_node_count,
        "chunking_mode": args.chunking_mode,
        "auth_mode": args.auth_mode,
        "mode_output_dirs": mode_output_dirs,
        "load_normalized_arrivals": args.load_normalized_arrivals,
        "arrival_window_reference_users": args.arrival_window_reference_users,
        "content_specs": [content.__dict__ for content in content_specs],
    }
    pprint(manifest)

    topology_file_name = None
    if args.plot_topology:
        topology_file_name = plot_network_topology(
            output_dir=output_dir,
            seed_base=args.seed_base,
            publisher_values=publisher_values,
            user_values=user_values,
            content_specs=content_specs,
            content_replication_k=args.content_replication_k,
            topology_seed=args.topology_seed,
            topology_publishers=args.topology_publishers,
            topology_users=args.topology_users,
            edge_node_count=args.edge_node_count,
        )

    if args.chunking_mode == CHUNKING_MODE_BOTH or args.auth_mode == AUTH_MODE_BOTH:
        print(f"Saved combined and per-mode results to {output_dir}")
    else:
        print(f"Saved raw and summary results to {output_dir}")
    if args.chunking_mode == CHUNKING_MODE_BOTH:
        print("Chunking plots written inside the without_chunking/ and with_chunking/ result subfolders.")
    if args.auth_mode == AUTH_MODE_BOTH:
        print("Auth plots written inside the without_auth/ and with_auth/ result subfolders.")
    if args.plot_topology and topology_file_name is not None:
        print(f"Topology snapshot was written to {topology_file_name}.")


if __name__ == "__main__":
    main()
