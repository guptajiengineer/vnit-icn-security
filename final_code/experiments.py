from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, Dict, List, Optional, Sequence, Tuple

import config
import crypto_auth
from models import BaseTopology, ChunkRecord, ContentSpec
from network import build_base_topology
from network import expand_user_edge_nodes, get_user_nodes
from content import assign_content_publishers, publish_content
from chain import SimulatedLedger
from network_scenario import (build_exploration_snapshot, simulate_lmm1, simulate_lmm2,)


def effective_arrival_window(
    arrival_window: float,
    num_users: int,
    load_normalized_arrivals: bool,
    reference_user_count: int,
) -> float:
    if not load_normalized_arrivals:
        return arrival_window
    baseline_users = max(1, reference_user_count)
    window = arrival_window * (max(1, num_users) / baseline_users)
    return window

def  evaluate_topology_scenarios(
    base: BaseTopology,
    topology_seed: int,
    publisher_values: Sequence[int],
    user_values: Sequence[int],
    arrival_window: float,
    content_specs: Sequence[ContentSpec],
    iteration_index: int,
    content_replication_k: int = 5,
    chunking_mode: str = config.CHUNKING_MODE_WITHOUT,
    auth_mode: str = config.AUTH_MODE_WITHOUT,
    load_normalized_arrivals: bool = False,
    arrival_window_reference_users: Optional[int] = None,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    reference_user_count = (
        max(1, arrival_window_reference_users)
        if arrival_window_reference_users is not None
        else max(1, min(user_values, default=1))
    )

    for num_publishers in publisher_values:
        active_publishers = base.publisher_candidates[:num_publishers]
        ordered_edge_nodes = get_user_nodes(
            base,
            active_publishers,
            max_candidates=max(user_values, default=1),
        )  # should be removed??????
        content_publishers = assign_content_publishers(
            active_publishers,
            content_specs,
            min_publishers_per_content=content_replication_k,
            seed=(topology_seed * 1009) + (num_publishers * 97),
        )
        # builds a snapshot of the network to be reused later by varying Nu & lmm.
        exploration_snapshot =  build_exploration_snapshot(
            base,
            active_publishers,
            ordered_edge_nodes,
            content_specs,
            exploration_window=arrival_window,
            content_publishers=content_publishers,
        )

        for num_users in user_values:
            access_node_ids = expand_user_edge_nodes(ordered_edge_nodes, num_users)
            effective_window = effective_arrival_window(
                arrival_window,
                num_users,
                load_normalized_arrivals=load_normalized_arrivals,
                reference_user_count=reference_user_count,
            )
            for chunking_enabled in config.enabled_chunking_modes(chunking_mode):
                chunking_label = config.chunking_label(chunking_enabled)

                # -----------------------------------------------------------
                # Obj2: auth-mode inner loop — mirrors chunking_mode pattern.
                # For each (num_publishers, num_users, chunking_enabled)
                # combination, iterate over enabled auth modes.
                # -----------------------------------------------------------
                for auth_enabled in config.enabled_auth_modes(auth_mode):
                    a_label = config.auth_label(auth_enabled)
                    print(
                        f"Iteration - {iteration_index + 1}; Np={num_publishers}; "
                        f"Nu={num_users}; chunking={chunking_label}; auth={a_label}"
                    )

                    # --------------------------------------------------------
                    # Obj2: if auth is enabled, run publish_content() for each
                    # content object to generate chunk records and register
                    # Merkle roots on the (simulated) ledger.
                    # chunk_count = num_users (upper bound on path count,
                    # matching the max paths that can be selected).
                    # --------------------------------------------------------
                    ledger = None
                    chunk_records_map: Dict[str, List[ChunkRecord]] = {}
                    # Step 5: consumer keypair and wrapped manifests.
                    # Initialised here so they are always defined regardless
                    # of auth_enabled, avoiding NameError in the lmm calls.
                    consumer_private_key = None
                    wrapped_manifests_map: Dict[str, bytes] = {}

                    if auth_enabled:
                        ledger = SimulatedLedger()

                        # Step 5: Generate one X25519 consumer keypair per
                        # experiment run.  All edge nodes share this keypair
                        # in the simulation — it represents "the consumer side"
                        # of the network.  In a real deployment each consumer
                        # device would hold its own long-term keypair.
                        consumer_private_key, consumer_public_key = (
                            crypto_auth.generate_consumer_keypair()
                        )

                        # Use num_users as the chunk_count proxy — it's the
                        # maximum number of paths that can be simultaneously
                        # selected (one per user), matching the runtime logic
                        # in NetworkScenario.on_user_request().
                        chunk_count_for_publish = max(1, num_users)
                        for content_spec in content_specs:
                            producer_id = (
                                active_publishers[0] if active_publishers else "producer_0"
                            )
                            # publish_content now returns a 3-tuple:
                            # (plaintext_manifest, chunk_records, wrapped_manifest)
                            _manifest, chunk_records, wrapped_manifest = publish_content(
                                content_spec=content_spec,
                                chunk_count=chunk_count_for_publish,
                                ledger=ledger,
                                producer_id=producer_id,
                                consumer_public_key=consumer_public_key,
                            )
                            chunk_records_map[content_spec.content_id] = chunk_records
                            if wrapped_manifest is not None:
                                wrapped_manifests_map[content_spec.content_id] = (
                                    wrapped_manifest
                                )

                    lmm1 = simulate_lmm1(
                        base,
                        active_publishers,
                        access_node_ids,
                        num_users,
                        content_specs=content_specs,
                        content_publishers=content_publishers,
                        chunking_enabled=chunking_enabled,
                        arrival_window=effective_window,
                        exploration_window=arrival_window,
                        exploration_snapshot=exploration_snapshot,
                        auth_enabled=auth_enabled,
                        ledger=ledger,
                        chunk_records_map=chunk_records_map,
                        consumer_private_key=consumer_private_key,
                        wrapped_manifests_map=wrapped_manifests_map,
                    )
                    lmm2 = simulate_lmm2(
                        base,
                        active_publishers,
                        access_node_ids,
                        num_users,
                        content_specs=content_specs,
                        content_publishers=content_publishers,
                        chunking_enabled=chunking_enabled,
                        arrival_window=effective_window,
                        exploration_window=arrival_window,
                        exploration_snapshot=exploration_snapshot,
                        auth_enabled=auth_enabled,
                        ledger=ledger,
                        chunk_records_map=chunk_records_map,
                        consumer_private_key=consumer_private_key,
                        wrapped_manifests_map=wrapped_manifests_map,
                    )

                    records.append(
                        {
                            "iteration": iteration_index + 1,
                            "seed": topology_seed,
                            "num_publishers": num_publishers,
                            "num_users": num_users,
                            "arrival_window_used": effective_window,
                            "chunking_mode": chunking_label,
                            "auth_mode": a_label,
                            "lmm": "LMM-1",
                            **lmm1,
                        }
                    )
                    records.append(
                        {
                            "iteration": iteration_index + 1,
                            "seed": topology_seed,
                            "num_publishers": num_publishers,
                            "num_users": num_users,
                            "arrival_window_used": effective_window,
                            "chunking_mode": chunking_label,
                            "auth_mode": a_label,
                            "lmm": "LMM-2",
                            **lmm2,
                        }
                    )

    return records


def run_full_experiment(
    iterations: int,
    publisher_values: Sequence[int],
    user_values: Sequence[int],
    seed_base: int,
    arrival_window: float,
    content_specs: Sequence[ContentSpec],
    content_replication_k: int = 2,
    chunking_mode: str = config.CHUNKING_MODE_WITH,
    auth_mode: str = config.AUTH_MODE_WITHOUT,
    load_normalized_arrivals: bool = False,
    arrival_window_reference_users: Optional[int] = None,
    edge_node_count: Optional[int] = None,
) -> List[Dict[str, Any]]:
    raw_records: List[Dict[str, Any]] = []
    if edge_node_count is None:
        edge_node_count = max(1, max(user_values, default=1))

    for iteration in range(iterations):
        topology_seed = seed_base + iteration
        base = build_base_topology(topology_seed, edge_node_count=edge_node_count)
        raw_records.extend(
             evaluate_topology_scenarios(
                base=base,
                topology_seed=topology_seed,
                publisher_values=publisher_values,
                user_values=user_values,
                arrival_window=arrival_window,
                content_specs=content_specs,
                iteration_index=iteration,
                content_replication_k=content_replication_k,
                chunking_mode=chunking_mode,
                auth_mode=auth_mode,
                load_normalized_arrivals=load_normalized_arrivals,
                arrival_window_reference_users=arrival_window_reference_users,
            )
        )

    return raw_records


def summarize_records(
    records: Sequence[Dict[str, Any]],
    key_fields: Sequence[str],
) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[object, ...], List[Dict[str, Any]]] = {}
    for record in records:
        key = tuple(record[field] for field in key_fields)
        grouped.setdefault(key, []).append(record)

    summary_rows: List[Dict[str, Any]] = []
    metric_names = ("avg_hops", "avg_delay", "avg_success_rate")

    for key, group in grouped.items():
        row: Dict[str, Any] = {
            field: value for field, value in zip(key_fields, key)
        }
        row["samples"] = len(group)
        for metric in metric_names:
            values = [float(item[metric]) for item in group]
            row[metric] = fmean(values)
            row[f"{metric}_std"] = pstdev(values) if len(values) > 1 else 0.0
        summary_rows.append(row)

    summary_rows.sort(key=lambda row: tuple(row[field] for field in key_fields))
    return summary_rows


def write_csv(path: Path, rows: Sequence[Dict[str, object]]) :
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: object) :
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
