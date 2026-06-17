from __future__ import annotations

import csv
import heapq
import itertools
import json
import random
from copy import deepcopy
from dataclasses import dataclass, field
from collections import defaultdict, deque
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from .models import (
        BaseTopology,
        CachedContentState,
        ContentSpec,
        PathRecord,
        ResourceBudget,
        SimNode,
    )
    from .network import build_base_topology
except ImportError:  # pragma: no cover
    from models import BaseTopology, CachedContentState, ContentSpec, PathRecord, ResourceBudget, SimNode
    from network import build_base_topology


LEARNING_LAMBDA = 0.4
LEARNING_SIGMA = 1.0
LEARNED_WEIGHT_BLEND = 0.55
PATH_WEIGHT_THRESHOLD = 0.08
WARMUP_ROUNDS = 3
MEASUREMENT_ROUNDS = 1
CHUNKING_MODE_WITHOUT = "without"
CHUNKING_MODE_WITH = "with"
CHUNKING_MODE_BOTH = "both"


def bfs_shortest_path(
    adjacency: Dict[str, List[str]],
    start: str,
    goal: str,
) -> List[str]:
    if start == goal:
        return [start]

    queue: deque[str] = deque([start])
    previous = {start: None}

    while queue:
        node_id = queue.popleft()
        for neighbor in adjacency[node_id]:
            if neighbor in previous:
                continue
            previous[neighbor] = node_id
            if neighbor == goal:
                queue.clear()
                break
            queue.append(neighbor)

    if goal not in previous:
        return []

    path: List[str] = []
    cursor: Optional[str] = goal
    while cursor is not None:
        path.append(cursor)
        cursor = previous[cursor]
    path.reverse()
    return path


def _avg(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def _clone_base_topology(base: BaseTopology) -> BaseTopology:
    cloned_nodes: Dict[str, SimNode] = {}

    for node_id, node in base.nodes.items():
        cloned_resources = {
            name: ResourceBudget(
                capacity=budget.capacity,
                remaining=budget.remaining,
                threshold=budget.threshold,
                recovery_rate=budget.recovery_rate,
            )
            for name, budget in node.resources.items()
        }
        cloned_cached_contents = {
            content_id: CachedContentState(
                cache_cost=state.cache_cost,
                rounds_remaining=state.rounds_remaining,
            )
            for content_id, state in node.cached_contents.items()
        }
        cloned_nodes[node_id] = SimNode(
            node_id=node.node_id,
            x=node.x,
            y=node.y,
            kind=node.kind,
            active_duration=node.active_duration,
            pending_requests=node.pending_requests,
            packet_loss=node.packet_loss,
            response_time=node.response_time,
            resources=cloned_resources,
            base_active_duration=node.base_active_duration,
            base_packet_loss=node.base_packet_loss,
            base_response_time=node.base_response_time,
            queue_capacity=node.queue_capacity,
            cached_contents=cloned_cached_contents,
        )

    return BaseTopology(
        nodes=cloned_nodes,
        adjacency=base.adjacency,
        subscriber_id=base.subscriber_id,
        publisher_candidates=list(base.publisher_candidates),
        edge_node_ids=list(base.edge_node_ids),
    )


def _clone_provider_hops(
    provider_hops: Dict[str, Dict[str, int]],
) -> Dict[str, Dict[str, int]]:
    return {
        provider_id: dict(hops_map)
        for provider_id, hops_map in provider_hops.items()
    }


def _clone_discovered_paths(
    discovered_paths: Dict[Tuple[str, str], Dict[Tuple[str, ...], Tuple[str, List[str], bool]]],
) -> Dict[Tuple[str, str], Dict[Tuple[str, ...], Tuple[str, List[str], bool]]]:
    cloned: Dict[Tuple[str, str], Dict[Tuple[str, ...], Tuple[str, List[str], bool]]] = defaultdict(dict)
    for state_id, content_paths in discovered_paths.items():
        cloned[state_id] = {
            path_key: (provider_id, list(path), is_cached_provider)
            for path_key, (provider_id, path, is_cached_provider) in content_paths.items()
        }
    return cloned


def _clone_path_record(record: PathRecord) -> PathRecord:
    return PathRecord(
        provider_id=record.provider_id,
        path=list(record.path),
        content_id=record.content_id,
        weight=record.weight,
        instant_weight=record.instant_weight,
        learned_weight=record.learned_weight,
        hops=record.hops,
        delay=record.delay,
        success_rate=record.success_rate,
        is_cached_provider=record.is_cached_provider,
    )


def _clone_path_table(
    path_table: Dict[Tuple[str, str], List[PathRecord]],
) -> Dict[Tuple[str, str], List[PathRecord]]:
    return {
        state_id: [_clone_path_record(record) for record in records]
        for state_id, records in path_table.items()
    }


def _path_success(
    base: BaseTopology,
    path: Sequence[str],
    *,
    exclude_terminal: bool = False,
) -> float:
    success = 1.0
    end_index = -1 if exclude_terminal and len(path) > 1 else None
    for node_id in path[1:end_index]:
        success *= 1.0 - base.nodes[node_id].packet_loss
    return max(0.0, min(1.0, success))


def _normalizer(values: Sequence[float], floor_max: bool) -> float:
    if not values:
        return 1.0
    max_value = max(values)
    min_value = min(values)
    if floor_max:
        max_value = max(1.0, max_value)
    denom = max_value + min_value
    return denom if denom > 0.0 else 1.0


def build_default_content_specs(content_count: int) -> List[ContentSpec]:
    if content_count <= 0:
        raise ValueError("content_count must be > 0")

    content_specs: List[ContentSpec] = []
    for content_index in range(content_count):
        content_specs.append(
            ContentSpec(
                content_id=f"a{content_index + 1}",
                generation_round=-(content_index + 2),
                lifespan_rounds=8 + (2 * content_index),
                cache_cost=6.0 + (1.5 * content_index),
                availability_threshold=0.22,
                lifetime_threshold=0.0,
                popularity=max(0.35, 1.0 - (0.14 * content_index)),
            )
        )
    return content_specs


def _bfs_hop_distances(
    adjacency: Dict[str, List[str]],
    start: str,
) -> Dict[str, int]:
    queue: deque[str] = deque([start])
    hops = {start: 0}

    while queue:
        node_id = queue.popleft()
        for neighbor in adjacency[node_id]:
            if neighbor in hops:
                continue
            hops[neighbor] = hops[node_id] + 1
            queue.append(neighbor)

    return hops


def _content_provider_ids(
    base: BaseTopology,
    active_publishers: Sequence[str],
    content_id: str,
    *,
    content_publishers: Optional[Dict[str, Sequence[str]]] = None,
    include_cached_providers: bool,
) -> List[str]:
    if content_publishers is None:
        provider_ids = list(dict.fromkeys(active_publishers))
    else:
        provider_ids = list(dict.fromkeys(content_publishers.get(content_id, active_publishers)))
    if not include_cached_providers:
        return provider_ids

    cached_provider_ids = sorted(
        node_id
        for node_id, node in base.nodes.items()
        if content_id in node.cached_contents and node_id not in provider_ids
    )
    return provider_ids + cached_provider_ids


def assign_content_publishers(
    active_publishers: Sequence[str],
    content_specs: Sequence[ContentSpec],
    *,
    min_publishers_per_content: int,
    seed: int,
) -> Dict[str, List[str]]:
    if min_publishers_per_content <= 0:
        raise ValueError("min_publishers_per_content must be > 0")

    provider_ids = list(dict.fromkeys(active_publishers))
    if not provider_ids:
        return {content.content_id: [] for content in content_specs}

    min_k = min(len(provider_ids), max(1, min_publishers_per_content))
    rng = random.Random(seed)
    content_publishers: Dict[str, List[str]] = {}

    for content_index, content in enumerate(sorted(content_specs, key=lambda item: item.content_id)):
        shuffled = list(provider_ids)
        rng.shuffle(shuffled)
        max_extra = len(provider_ids) - min_k
        extra_replicas = rng.randint(0, max_extra) if max_extra > 0 else 0
        replica_count = min_k + extra_replicas
        content_publishers[content.content_id] = sorted(shuffled[:replica_count])

    return content_publishers


def _enumerate_provider_paths(
    base: BaseTopology,
    source_id: str,
    provider_id: str,
    *,
    max_extra_hops: int,
    max_paths: int,
) -> List[List[str]]:
    shortest_path = bfs_shortest_path(base.adjacency, source_id, provider_id)
    if not shortest_path:
        return []

    shortest_hops = max(0, len(shortest_path) - 1)
    max_hops = shortest_hops + max(0, max_extra_hops)
    hops_to_provider = _bfs_hop_distances(base.adjacency, provider_id)

    discovered_paths: List[List[str]] = []
    frontier: deque[List[str]] = deque([[source_id]])

    while frontier and len(discovered_paths) < max_paths:
        path = frontier.popleft()
        node_id = path[-1]

        for neighbor in sorted(
            base.adjacency[node_id],
            key=lambda candidate_id: (
                hops_to_provider.get(candidate_id, 10**9),
                len(base.adjacency[candidate_id]),
                candidate_id,
            ),
        ):
            if neighbor in path:
                continue

            next_path = path + [neighbor]
            next_hops = len(next_path) - 1
            remaining_hops = hops_to_provider.get(neighbor)
            if remaining_hops is None or (next_hops + remaining_hops) > max_hops:
                continue

            if neighbor == provider_id:
                discovered_paths.append(next_path)
                if len(discovered_paths) >= max_paths:
                    break
                continue

            frontier.append(next_path)

    return discovered_paths


def _path_records_from_raw_paths(
    base: BaseTopology,
    content_id: str,
    raw_paths: Sequence[Tuple[str, List[str], bool]],
) -> List[PathRecord]:
    enriched_rows: List[Tuple[str, List[str], bool, float, float, float, float]] = []
    for provider_id, path, is_cached_provider in raw_paths:
        path_length = len(path)
        if path_length <= 0:
            continue

        active_sum = 0.0
        pending_sum = 0.0
        loss_sum = 0.0
        response_sum = 0.0

        for node_id in path:
            node = base.nodes[node_id]
            active_sum += node.active_duration
            pending_sum += node.pending_requests
            loss_sum += node.packet_loss
            response_sum += node.response_time

        divisor = float(path_length)
        enriched_rows.append(
            (
                provider_id,
                path,
                is_cached_provider,
                active_sum / divisor,
                pending_sum / divisor,
                loss_sum / divisor,
                response_sum / divisor,
            )
        )

    if not enriched_rows:
        return []

    durations = [row[3] for row in enriched_rows]
    pendings = [row[4] for row in enriched_rows]
    losses = [row[5] for row in enriched_rows]
    responses = [row[6] for row in enriched_rows]

    duration_norm = _normalizer(durations, floor_max=False)
    pending_norm = _normalizer(pendings, floor_max=True)
    loss_norm = _normalizer(losses, floor_max=True)
    response_norm = _normalizer(responses, floor_max=True)

    path_records: List[PathRecord] = []
    for provider_id, path, is_cached_provider, duration, pending, loss, response in enriched_rows:
        d_value = duration / duration_norm
        q_value = pending / pending_norm
        l_value = loss / loss_norm
        o_value = response / response_norm
        weight = d_value / (q_value + l_value + o_value + 1e-9)
        hops = max(0, len(path) - 1)
        response_sum_non_source = 0.0
        success_rate = 1.0
        for node_id in path[1:]:
            node = base.nodes[node_id]
            response_sum_non_source += node.response_time
            success_rate *= 1.0 - node.packet_loss

        live_delay = (0.85 * hops) + (0.18 * response_sum_non_source)
        path_records.append(
            PathRecord(
                provider_id=provider_id,
                path=path,
                content_id=content_id,
                weight=weight,
                instant_weight=weight,
                learned_weight=weight,
                hops=hops,
                delay=live_delay,
                success_rate=max(0.0, min(1.0, success_rate)),
                is_cached_provider=is_cached_provider,
            )
        )

    return path_records


def build_provider_paths(
    base: BaseTopology,
    active_publishers: Sequence[str],
    source_id: str,
    content_id: str,
    *,
    content_publishers: Optional[Dict[str, Sequence[str]]] = None,
    include_cached_providers: bool = True,
    max_extra_hops: int = 2,
    max_paths_per_provider: int = 6,
) -> List[PathRecord]:
    raw_paths: List[Tuple[str, List[str], bool]] = []

    provider_ids = _content_provider_ids(
        base,
        active_publishers,
        content_id,
        content_publishers=content_publishers,
        include_cached_providers=include_cached_providers,
    )
    active_publisher_set = set(active_publishers)

    for provider_id in provider_ids:
        candidate_paths = _enumerate_provider_paths(
            base,
            source_id,
            provider_id,
            max_extra_hops=max_extra_hops,
            max_paths=max_paths_per_provider,
        )
        for path in candidate_paths:
            raw_paths.append((provider_id, path, provider_id not in active_publisher_set))

    if not raw_paths:
        return []
    return _path_records_from_raw_paths(base, content_id, raw_paths)


def _overlap_ratio(path_a: Sequence[str], path_b: Sequence[str]) -> float:
    nodes_a = set(path_a[1:-1])
    nodes_b = set(path_b[1:-1])
    if not nodes_a or not nodes_b:
        return 0.0
    return len(nodes_a & nodes_b) / min(len(nodes_a), len(nodes_b))


def select_multipaths(
    path_records: Sequence[PathRecord],
    *,
    overlap_threshold: float = 0.0,
    min_weight: float = PATH_WEIGHT_THRESHOLD,
) -> List[PathRecord]:
    best_by_provider: Dict[str, PathRecord] = {}
    for record in _ordered_candidates(path_records):
        current = best_by_provider.get(record.provider_id)
        if current is None:
            best_by_provider[record.provider_id] = record
            continue
        if (record.weight, -record.hops, record.success_rate) > (
            current.weight,
            -current.hops,
            current.success_rate,
        ):
            best_by_provider[record.provider_id] = record

    provider_best_records = list(best_by_provider.values())
    selected = [record for record in provider_best_records if record.weight >= min_weight]
    if not selected and provider_best_records:
        selected = [
            max(
                provider_best_records,
                key=lambda record: (record.weight, -record.hops, record.success_rate),
            )
        ]

    selected = _ordered_candidates(selected)
    index = 0
    while index < len(selected):
        left = selected[index]
        compare_index = index + 1
        while compare_index < len(selected):
            right = selected[compare_index]
            if _overlap_ratio(left.path, right.path) > overlap_threshold:
                if (left.weight, -left.hops, left.success_rate) >= (
                    right.weight,
                    -right.hops,
                    right.success_rate,
                ):
                    selected.pop(compare_index)
                    continue
                selected.pop(index)
                index -= 1
                break
            compare_index += 1
        index += 1

    return selected


def _content_availability(selected_paths: Sequence[PathRecord]) -> float:
    return sum(1.0 / max(1, record.hops) for record in selected_paths)


def _caching_weight(
    content: ContentSpec,
    selected_paths: Sequence[PathRecord],
    *,
    round_index: int,
) -> float:
    availability = _content_availability(selected_paths)
    if availability < content.availability_threshold:
        return 0.0

    normalized_lifetime = content.normalized_lifetime(round_index)
    if normalized_lifetime < content.lifetime_threshold:
        return 0.0

    return availability * normalized_lifetime


def choose_cache_node(
    base: BaseTopology,
    selected_paths: Sequence[PathRecord],
    source_id: str,
    *,
    content: ContentSpec,
    round_index: int,
) -> Optional[str]:
    if not selected_paths:
        return None
    if _caching_weight(content, selected_paths, round_index=round_index) <= 0.0:
        return None

    subscriber = base.nodes[source_id]
    candidate_ids = {
        node_id
        for record in selected_paths
        for node_id in record.path[1:-1]
    }
    if not candidate_ids:
        return None

    best_node_id: Optional[str] = None
    best_score = -1.0

    for node_id in candidate_ids:
        node = base.nodes[node_id]
        score = node.resource_weight() * subscriber.distance_to(node)
        if score > best_score:
            best_score = score
            best_node_id = node_id

    return best_node_id


def _prefix_path(path: Sequence[str], node_id: Optional[str]) -> List[str]:
    if node_id is None or node_id not in path:
        return list(path)
    return list(path[: path.index(node_id) + 1])


def _nearest_provider_hops(
    base: BaseTopology,
    node_id: str,
    active_publishers: Sequence[str],
) -> int:
    best_hops: Optional[int] = None
    for publisher_id in active_publishers:
        path = bfs_shortest_path(base.adjacency, node_id, publisher_id)
        if not path:
            continue
        hops = max(0, len(path) - 1)
        if best_hops is None or hops < best_hops:
            best_hops = hops
    return best_hops if best_hops is not None else 10**9


def rank_user_nodes(
    base: BaseTopology,
    active_publishers: Sequence[str],
    *,
    max_candidates: int = 8,
) -> List[str]:
    """Legacy topology helper kept for diagnostics only.

    The active experiment flow now treats users as external requesters that
    send Interests through ``base.subscriber_id`` instead of mapping users to
    internal network nodes.
    """
    candidate_ids = [
        node_id
        for node_id, node in base.nodes.items()
        if node.kind != "subscriber" and node_id not in active_publishers
    ]

    scored = []
    for node_id in candidate_ids:
        hops = _nearest_provider_hops(base, node_id, active_publishers)
        degree = len(base.adjacency[node_id])
        scored.append((hops, degree, node_id))

    scored.sort(key=lambda item: (-item[0], item[1], item[2]))

    selected: List[str] = []
    for _, _, node_id in scored:
        if all(node_id not in base.adjacency[chosen_id] for chosen_id in selected):
            selected.append(node_id)
        if len(selected) >= max_candidates:
            break

    if len(selected) < max_candidates:
        for _, _, node_id in scored:
            if node_id not in selected:
                selected.append(node_id)
            if len(selected) >= max_candidates:
                break

    return selected[:max_candidates]


def _summarize_user_metrics(records: Sequence[Dict[str, float]]) -> Dict[str, float]:
    if not records:
        return {
            "avg_hops": 0.0,
            "avg_delay": 0.0,
            "avg_success_rate": 0.0,
        }
    success_rate = 1.0
    for record in records:
        success_rate *= record["success_rate"]
    return {
        "avg_hops": fmean(record["hops"] for record in records),
        "avg_delay": fmean(record["delay"] for record in records),
        "avg_success_rate": success_rate,
    }


def _refresh_topology_state(base: BaseTopology) -> None:
    for node in base.nodes.values():
        node.refresh_dynamic_metrics()


def _snapshot_dynamic_state(base: BaseTopology) -> Dict[str, Dict[str, Any]]:
    snapshot: Dict[str, Dict[str, Any]] = {}
    for node_id, node in base.nodes.items():
        snapshot[node_id] = {
            "pending_requests": node.pending_requests,
            "active_duration": node.active_duration,
            "packet_loss": node.packet_loss,
            "response_time": node.response_time,
            "cached_contents": deepcopy(node.cached_contents),
            "resources": {
                resource_name: budget.remaining
                for resource_name, budget in node.resources.items()
            },
        }
    return snapshot


def _restore_dynamic_state(
    base: BaseTopology,
    snapshot: Dict[str, Dict[str, Any]],
) -> None:
    for node_id, state in snapshot.items():
        node = base.nodes[node_id]
        node.pending_requests = float(state["pending_requests"])
        node.active_duration = float(state["active_duration"])
        node.packet_loss = float(state["packet_loss"])
        node.response_time = float(state["response_time"])
        node.cached_contents = deepcopy(state["cached_contents"])
        for resource_name, remaining in state["resources"].items():
            resource = node.resource(resource_name)
            if resource is not None:
                resource.remaining = float(remaining)


def _learning_key(
    access_node_id: str,
    content_id: str,
    path: Sequence[str],
) -> Tuple[str, str, Tuple[str, ...]]:
    return access_node_id, content_id, tuple(path)


def _apply_learning_scores(
    path_records: Sequence[PathRecord],
    *,
    access_node_id: str,
    content_id: str,
    learning_scores: Dict[Tuple[str, str, Tuple[str, ...]], float],
) -> None:
    for record in path_records:
        key = _learning_key(access_node_id, content_id, record.path)
        learned_weight = learning_scores.get(key, record.instant_weight)
        record.learned_weight = learned_weight
        record.weight = max(
            0.01,
            ((1.0 - LEARNED_WEIGHT_BLEND) * record.instant_weight)
            + (LEARNED_WEIGHT_BLEND * learned_weight),
        )


def _ordered_candidates(path_records: Sequence[PathRecord]) -> List[PathRecord]:
    return sorted(
        path_records,
        key=lambda record: (-record.weight, record.delay, record.hops, -record.success_rate),
    )


def _touch_path_resources(
    base: BaseTopology,
    path: Sequence[str],
    *,
    load_scale: float,
    cache_hit: bool,
    content_id: Optional[str] = None,
) -> None:
    if load_scale <= 0.0:
        return

    traversed = list(path[1:])
    total_hops = max(1, len(traversed))
    request_scale = load_scale * (0.65 if cache_hit else 1.0)

    for hop_index, node_id in enumerate(traversed, start=1):
        node = base.nodes[node_id]
        terminal_factor = 1.15 if hop_index == total_hops else 1.0
        node.pending_requests += 0.45 * request_scale * terminal_factor

        cpu_resource = node.resource("cpu")
        if cpu_resource is not None:
            cpu_resource.consume(
                request_scale * terminal_factor * (0.08 + (0.012 * hop_index))
            )

        bandwidth_resource = node.resource("bandwidth")
        if bandwidth_resource is not None:
            bandwidth_resource.consume(
                request_scale * terminal_factor * (0.09 + (0.008 * total_hops))
            )

        energy_resource = node.resource("energy")
        if energy_resource is not None:
            energy_resource.consume(
                request_scale * terminal_factor * (0.05 + (0.006 * hop_index))
            )

        if cache_hit and content_id is not None and content_id in node.cached_contents:
            cache_resource = node.resource("cache")
            if cache_resource is not None:
                cache_resource.consume(0.015 * request_scale)

        node.refresh_dynamic_metrics()


def _evaluate_path_profile(
    base: BaseTopology,
    record: PathRecord,
    *,
    load_scale: float,
) -> Dict[str, float]:
    path = record.path
    cache_hit = record.is_cached_provider
    traversed = list(path[1:])
    hops = max(0, len(path) - 1)
    delay = (0.85 * hops) + (0.35 * sum(base.nodes[node_id].response_time for node_id in traversed))
    success_probability = _path_success(base, path, exclude_terminal=False)
    if cache_hit:
        success_probability = min(0.995, success_probability * 1.03)
    success_probability = max(0.02, min(0.995, success_probability))
    _touch_path_resources(
        base,
        path,
        load_scale=load_scale,
        cache_hit=cache_hit,
        content_id=record.content_id,
    )
    return {
        "hops": float(hops),
        "delay": float(delay),
        "success_rate": success_probability,
    }


def _store_in_cache(
    base: BaseTopology,
    cache_node_id: str,
    content: ContentSpec,
) -> None:
    node = base.nodes[cache_node_id]
    cache_resource = node.resource("cache")
    cached_state = node.cached_contents.get(content.content_id)
    cache_rounds = max(2, min(6, content.lifespan_rounds))

    if cached_state is not None:
        cached_state.rounds_remaining = max(cached_state.rounds_remaining, cache_rounds)
        if cache_resource is not None:
            cache_resource.consume(0.2)
        node.refresh_dynamic_metrics()
        return

    if cache_resource is not None:
        if cache_resource.remaining < content.cache_cost:
            return
        cache_resource.consume(content.cache_cost)

    node.cached_contents[content.content_id] = CachedContentState(
        cache_cost=content.cache_cost,
        rounds_remaining=cache_rounds,
    )
    node.refresh_dynamic_metrics()


def _attempt_delivery(
    base: BaseTopology,
    candidate_records: Sequence[PathRecord],
    *,
    max_attempts: int,
) -> Dict[str, Any]:
    ordered = _ordered_candidates(candidate_records)[:max_attempts]
    if not ordered:
        return {
            "hops": 0.0,
            "delay": 0.0,
            "success_rate": 0.0,
            "attempts": [],
        }

    attempts: List[Dict[str, Any]] = []
    residual_failure = 1.0
    expected_delay = 0.0
    success_total = 0.0
    success_weighted_hops = 0.0
    primary_hops = float(ordered[0].hops)

    for record in ordered:
        if residual_failure <= 1e-4:
            break

        profile = _evaluate_path_profile(
            base,
            record,
            load_scale=residual_failure,
        )
        success_probability = profile["success_rate"]
        expected_delay += residual_failure * profile["delay"]
        success_total += residual_failure * success_probability
        success_weighted_hops += residual_failure * success_probability * profile["hops"]
        attempts.append(
            {
                "record": record,
                "attempt_probability": residual_failure,
                "success_probability": success_probability,
            }
        )
        residual_failure *= 1.0 - success_probability

    hops = (
        success_weighted_hops / success_total
        if success_total > 0.0
        else primary_hops
    )
    return {
        "hops": hops,
        "delay": expected_delay,
        "success_rate": success_total,
        "attempts": attempts,
    }


def _update_learning_scores(
    path_records: Sequence[PathRecord],
    attempts: Sequence[Dict[str, Any]],
    *,
    access_node_id: str,
    content_id: str,
    learning_scores: Dict[Tuple[str, str, Tuple[str, ...]], float],
) -> None:
    attempted_keys = set()

    for attempt in attempts:
        record = attempt["record"]
        key = _learning_key(access_node_id, content_id, record.path)
        prior_weight = learning_scores.get(key, record.instant_weight)
        margin = (attempt["success_probability"] - 0.5) * 2.0
        reward_signal = LEARNING_SIGMA * record.instant_weight * margin
        updated = ((1.0 - LEARNING_LAMBDA) * prior_weight) + (
            LEARNING_LAMBDA * (prior_weight + reward_signal)
        )
        learning_scores[key] = max(0.01, updated)
        attempted_keys.add(key)

    for record in path_records:
        key = _learning_key(access_node_id, content_id, record.path)
        if key in attempted_keys:
            continue
        prior_weight = learning_scores.get(key, record.instant_weight)
        learning_scores[key] = max(
            0.01,
            (0.88 * prior_weight) + (0.12 * record.instant_weight),
        )


def _recover_topology_after_round(
    base: BaseTopology,
    *,
    recovery_multiplier: float,
) -> None:
    pending_decay = max(0.18, min(0.72, 0.60 / max(0.6, recovery_multiplier)))

    for node in base.nodes.values():
        node.pending_requests = max(0.0, node.pending_requests * pending_decay)

        cpu_resource = node.resource("cpu")
        if cpu_resource is not None:
            cpu_resource.recover(multiplier=1.05 * recovery_multiplier)

        bandwidth_resource = node.resource("bandwidth")
        if bandwidth_resource is not None:
            bandwidth_resource.recover(multiplier=1.15 * recovery_multiplier)

        cache_resource = node.resource("cache")
        if cache_resource is not None and not node.cached_contents:
            cache_resource.recover(multiplier=0.8 * recovery_multiplier)

        energy_resource = node.resource("energy")
        if energy_resource is not None:
            energy_resource.recover(multiplier=0.15 * recovery_multiplier)

        expired_content_ids: List[str] = []
        for content_id, cached_state in node.cached_contents.items():
            cached_state.rounds_remaining -= 1
            if cached_state.rounds_remaining <= 0:
                if cache_resource is not None:
                    cache_resource.release(cached_state.cache_cost)
                expired_content_ids.append(content_id)

        for content_id in expired_content_ids:
            del node.cached_contents[content_id]

        node.refresh_dynamic_metrics()


def _summarize_rounds(round_summaries: Sequence[Dict[str, float]]) -> Dict[str, float]:
    if not round_summaries:
        return {
            "avg_hops": 0.0,
            "avg_delay": 0.0,
            "avg_success_rate": 0.0,
        }
    return {
        "avg_hops": fmean(round["avg_hops"] for round in round_summaries),
        "avg_delay": fmean(round["avg_delay"] for round in round_summaries),
        "avg_success_rate": fmean(round["avg_success_rate"] for round in round_summaries),
    }


def _build_request_cycle(content_specs: Sequence[ContentSpec]) -> List[str]:
    weighted_cycle: List[str] = []
    for content in sorted(content_specs, key=lambda item: (-item.popularity, item.content_id)):
        repeats = max(1, round(content.popularity * 4))
        weighted_cycle.extend([content.content_id] * repeats)
    return weighted_cycle


def _state_key(edge_id: str, content_id: str) -> Tuple[str, str]:
    return edge_id, content_id


def _chunking_label(chunking_enabled: bool) -> str:
    if chunking_enabled:
        return "with_chunking"
    return "without_chunking"


def _enabled_chunking_modes(chunking_mode: str) -> List[bool]:
    if chunking_mode == CHUNKING_MODE_BOTH:
        return [False, True]
    if chunking_mode == CHUNKING_MODE_WITH:
        return [True]
    if chunking_mode == CHUNKING_MODE_WITHOUT:
        return [False]
    raise ValueError(
        f"chunking_mode must be one of "
        f"{CHUNKING_MODE_WITHOUT!r}, {CHUNKING_MODE_WITH!r}, {CHUNKING_MODE_BOTH!r}; "
        f"got {chunking_mode!r}"
    )


@dataclass
class _InterestMessage:
    content_id: str
    mode: str
    path: List[str]
    provider_id: str
    current_index: int
    chunk_id: int = 0
    chunk_count: int = 1
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    cache_node_id: Optional[str] = None


@dataclass
class _DataMessage:
    content_id: str
    mode: str
    path: List[str]
    provider_id: str
    current_index: int
    chunk_id: int = 0
    chunk_count: int = 1
    request_id: Optional[str] = None
    cache_node_id: Optional[str] = None
    cache_hit: bool = False


@dataclass
class _RequestState:
    request_id: str
    edge_id: str
    content_id: str
    started_at: float
    chunking_enabled: bool
    user_ids: List[str]
    user_started_at: Dict[str, float]
    selected_paths: List[List[str]]
    chunk_count: int
    delivered_chunk_ids: set[int] = field(default_factory=set)
    chunk_arrival_times: Dict[int, float] = field(default_factory=dict)
    chunk_metrics: Dict[int, Dict[str, float]] = field(default_factory=dict)
    delivered_paths: set[Tuple[str, ...]] = field(default_factory=set)
    completed: bool = False
    timed_out: bool = False


@dataclass
class _ExplorationSnapshot:
    provider_hops: Dict[str, Dict[str, int]]
    discovered_paths: Dict[Tuple[str, str], Dict[Tuple[str, ...], Tuple[str, List[str], bool]]]
    path_table: Dict[Tuple[str, str], List[PathRecord]]


class _SymbolicEventLoop:
    def __init__(self) -> None:
        self.time = 0.0
        self._queue: List[Tuple[float, int, Any, Tuple[Any, ...]]] = []
        self._counter = itertools.count()

    def schedule(self, delay: float, callback: Any, *args: Any) -> None:
        heapq.heappush(
            self._queue,
            (self.time + max(0.0, delay), next(self._counter), callback, args),
        )

    def run(self) -> None:
        while self._queue:
            event_time, _, callback, args = heapq.heappop(self._queue)
            self.time = event_time
            callback(*args)


class _RuntimeNode:
    def __init__(self, engine: "_SymbolicScenario", node_id: str) -> None:
        self.engine = engine
        self.node_id = node_id

    def on_interest(self, msg: _InterestMessage, event_loop: _SymbolicEventLoop) -> None:
        self.engine._on_node_interest(self.node_id, msg, event_loop)

    def on_data(self, msg: _DataMessage, event_loop: _SymbolicEventLoop) -> None:
        self.engine._on_node_data(self.node_id, msg, event_loop)


class _EdgeRuntimeNode(_RuntimeNode):
    def start_exploration(
        self,
        content_id: str,
        event_loop: _SymbolicEventLoop,
    ) -> None:
        self.engine._start_exploration(self.node_id, content_id, event_loop)

    def on_exploration_timer(
        self,
        content_id: str,
        event_loop: _SymbolicEventLoop,
    ) -> None:
        self.engine._on_exploration_timer(self.node_id, content_id, event_loop)

    def on_user_request(
        self,
        user_id: str,
        content_id: str,
        event_loop: _SymbolicEventLoop,
    ) -> None:
        self.engine._on_user_request(self.node_id, user_id, content_id, event_loop)

    def on_user_timer(
        self,
        request_id: str,
        event_loop: _SymbolicEventLoop,
    ) -> None:
        self.engine._on_user_timer(request_id, event_loop)

    def on_path_timer(
        self,
        request_id: str,
        path_key: Tuple[str, ...],
        event_loop: _SymbolicEventLoop,
    ) -> None:
        self.engine._on_path_timer(request_id, path_key, event_loop)


class _SymbolicScenario:
    def __init__(
        self,
        *,
        base: BaseTopology,
        active_publishers: Sequence[str],
        content_specs: Sequence[ContentSpec],
        content_publishers: Optional[Dict[str, Sequence[str]]],
        lmm: str,
        chunking_enabled: bool,
        arrival_window: float,
        exploration_window: Optional[float] = None,
        exploration_snapshot: Optional[_ExplorationSnapshot] = None,
    ) -> None:
        self.base = _clone_base_topology(base)
        self.active_publishers = list(active_publishers)
        self.active_publisher_set = set(active_publishers)
        self.content_specs = {content.content_id: content for content in content_specs}
        if content_publishers is None:
            self.content_publishers = {
                content.content_id: list(self.active_publishers)
                for content in content_specs
            }
        else:
            self.content_publishers = {
                content.content_id: list(dict.fromkeys(content_publishers.get(content.content_id, self.active_publishers)))
                for content in content_specs
            }
        self.content_publisher_sets = {
            content_id: set(provider_ids)
            for content_id, provider_ids in self.content_publishers.items()
        }
        self.content_sequence = _build_request_cycle(content_specs)
        self.lmm = lmm
        self.chunking_enabled = chunking_enabled
        self.arrival_window = arrival_window
        self.exploration_window = exploration_window if exploration_window is not None else arrival_window
        self.edge_ids = list(self.base.edge_node_ids) or [self.base.subscriber_id]
        self.primary_edge_id = self.edge_ids[0]
        self.current_round_index = 0
        self.learning_scores: Dict[Tuple[str, str, Tuple[str, ...]], float] = {}
        self.discovered_paths: Dict[Tuple[str, str], Dict[Tuple[str, ...], Tuple[str, List[str], bool]]] = defaultdict(dict)
        self.path_table: Dict[Tuple[str, str], List[PathRecord]] = defaultdict(list)
        self.cache_node_ids: Dict[Tuple[str, str], Optional[str]] = {}
        self.exploration_open: Dict[Tuple[str, str], bool] = {}
        self.inflight_by_content: Dict[Tuple[str, str], str] = {}
        self.requests: Dict[str, _RequestState] = {}
        self.round_user_records: List[Dict[str, float]] = []
        self.request_counter = itertools.count()
        if exploration_snapshot is None:
            self.provider_hops = {
                provider_id: _bfs_hop_distances(self.base.adjacency, provider_id)
                for provider_id in self.active_publishers
            }
        else:
            self.provider_hops = _clone_provider_hops(exploration_snapshot.provider_hops)

        self.nodes: Dict[str, _RuntimeNode] = {
            node_id: _RuntimeNode(self, node_id)
            for node_id in self.base.nodes
        }
        self.edges: Dict[str, _EdgeRuntimeNode] = {}
        for edge_id in self.edge_ids:
            edge_node = _EdgeRuntimeNode(self, edge_id)
            self.edges[edge_id] = edge_node
            self.nodes[edge_id] = edge_node
        self.edge = self.edges[self.primary_edge_id]

        if exploration_snapshot is None:
            self._bootstrap_exploration()
        else:
            self._restore_exploration_snapshot(exploration_snapshot)

    def _bootstrap_exploration(self) -> None:
        loop = _SymbolicEventLoop()
        for edge in self.edges.values():
            for content_id in self.content_specs:
                edge.start_exploration(content_id, loop)
        loop.run()

    def _restore_exploration_snapshot(self, snapshot: _ExplorationSnapshot) -> None:
        self.discovered_paths = _clone_discovered_paths(snapshot.discovered_paths)
        self.path_table = _clone_path_table(snapshot.path_table)
        for edge_id in self.edge_ids:
            for content_id in self.content_specs:
                state_id = _state_key(edge_id, content_id)
                self.exploration_open[state_id] = False
                if self.lmm == "LMM-2":
                    self.cache_node_ids[state_id] = choose_cache_node(
                        self.base,
                        self.path_table.get(state_id, []),
                        edge_id,
                        content=self.content_specs[content_id],
                        round_index=self.current_round_index,
                    )
                else:
                    self.cache_node_ids[state_id] = None

    def _hop_delay(self, node_id: str, *, data_phase: bool) -> float:
        node = self.base.nodes[node_id]
        baseline = 0.55 if data_phase else 0.4
        return max(0.4, baseline + (0.10 * node.response_time))

    def _exploration_timeout(self, edge_id: str, content_id: str) -> float:
        max_hops = max(
            (
                self.provider_hops[provider_id].get(edge_id, 0)
                for provider_id in self.content_publishers.get(content_id, self.active_publishers)
            ),
            default=0,
        )
        return max(12.0, self.exploration_window, 3.0 * max_hops)

    def _register_discovered_path(
        self,
        edge_id: str,
        content_id: str,
        provider_id: str,
        path: Sequence[str],
        *,
        is_cached_provider: bool,
    ) -> None:
        path_list = list(path)
        if len(path_list) < 2:
            return
        path_key = tuple(path_list)
        state_id = _state_key(edge_id, content_id)
        current = self.discovered_paths[state_id].get(path_key)
        if current is None or (is_cached_provider and not current[2]):
            self.discovered_paths[state_id][path_key] = (
                provider_id,
                path_list,
                is_cached_provider,
            )

    def _refresh_path_table(self, edge_id: str, content_id: str) -> None:
        state_id = _state_key(edge_id, content_id)
        raw_paths = list(self.discovered_paths[state_id].values())
        if not raw_paths:
            self.path_table[state_id] = []
            self.cache_node_ids[state_id] = None
            return

        path_records = _path_records_from_raw_paths(self.base, content_id, raw_paths)
        _apply_learning_scores(
            path_records,
            access_node_id=edge_id,
            content_id=content_id,
            learning_scores=self.learning_scores,
        )
        selected_paths = select_multipaths(path_records)
        self.path_table[state_id] = selected_paths
        if self.lmm == "LMM-2":
            self.cache_node_ids[state_id] = choose_cache_node(
                self.base,
                selected_paths,
                edge_id,
                content=self.content_specs[content_id],
                round_index=self.current_round_index,
            )
        else:
            self.cache_node_ids[state_id] = None

    def _request_path_records(self, selected_paths: Sequence[PathRecord]) -> List[PathRecord]:
        if not selected_paths:
            return []
        if self.chunking_enabled:
            return list(selected_paths)
        return [selected_paths[0]]

    def _update_learning_from_path(
        self,
        edge_id: str,
        content_id: str,
        path: Sequence[str],
        *,
        content_received: bool,
    ) -> None:
        path_key = tuple(path)
        record = next(
            (
                item
                for item in self.path_table.get(_state_key(edge_id, content_id), [])
                if tuple(item.path) == path_key
            ),
            None,
        )
        if record is None:
            raw_record = self.discovered_paths.get(_state_key(edge_id, content_id), {}).get(path_key)
            if raw_record is not None:
                single_record = _path_records_from_raw_paths(
                    self.base,
                    content_id,
                    [raw_record],
                )
                record = single_record[0] if single_record else None
        if record is None:
            return

        key = _learning_key(edge_id, content_id, record.path)
        prior_weight = self.learning_scores.get(key, record.instant_weight)
        reward_signal = LEARNING_SIGMA * record.instant_weight * (1.0 if content_received else -1.0)
        updated = ((1.0 - LEARNING_LAMBDA) * prior_weight) + (
            LEARNING_LAMBDA * (prior_weight + reward_signal)
        )
        self.learning_scores[key] = max(0.01, updated)

    def _register_cache_prefix_paths(self, edge_id: str, content_id: str, cache_node_id: str) -> None:
        for record in self.path_table.get(_state_key(edge_id, content_id), []):
            if cache_node_id not in record.path:
                continue
            prefix_path = _prefix_path(record.path, cache_node_id)
            self._register_discovered_path(
                edge_id,
                content_id,
                cache_node_id,
                prefix_path,
                is_cached_provider=True,
            )

    def _start_exploration(self, edge_id: str, content_id: str, event_loop: _SymbolicEventLoop) -> None:
        state_id = _state_key(edge_id, content_id)
        self.exploration_open[state_id] = True
        for provider_id in self.content_publishers.get(content_id, self.active_publishers):
            hops_map = self.provider_hops[provider_id]
            source_hops = hops_map.get(edge_id)
            if source_hops is None:
                continue
            for neighbor_id in self.base.adjacency[edge_id]:
                if hops_map.get(neighbor_id, 10**9) >= source_hops:
                    continue
                msg = _InterestMessage(
                    content_id=content_id,
                    mode="explore",
                    path=[edge_id, neighbor_id],
                    provider_id=provider_id,
                    current_index=1,
                )
                event_loop.schedule(
                    self._hop_delay(neighbor_id, data_phase=False),
                    self.nodes[neighbor_id].on_interest,
                    msg,
                    event_loop,
                )
        event_loop.schedule(
            self._exploration_timeout(edge_id, content_id),
            self.edges[edge_id].on_exploration_timer,
            content_id,
            event_loop,
        )

    def _on_exploration_timer(self, edge_id: str, content_id: str, event_loop: _SymbolicEventLoop) -> None:
        self.exploration_open[_state_key(edge_id, content_id)] = False
        self._refresh_path_table(edge_id, content_id)

    def _make_request_id(self, edge_id: str, content_id: str) -> str:
        return f"{edge_id}-{content_id}-r{self.current_round_index}-{next(self.request_counter)}"

    def _request_timeout(self, selected_paths: Sequence[PathRecord]) -> float:
        if not selected_paths:
            return max(8.0, self.arrival_window / 2.0)
        return max(
            max(record.delay for record in selected_paths) * 1.4,
            self.arrival_window * 0.35,
            8.0,
        )

    def _on_user_request(
        self,
        edge_id: str,
        user_id: str,
        content_id: str,
        event_loop: _SymbolicEventLoop,
    ) -> None:
        state_id = _state_key(edge_id, content_id)
        selected_paths = self._request_path_records(self.path_table.get(state_id, []))
        if self.lmm == "LMM-2":
            inflight_request_id = self.inflight_by_content.get(state_id)
            if inflight_request_id is not None:
                request = self.requests.get(inflight_request_id)
                if request is not None and not request.completed and not request.timed_out:
                    request.user_ids.append(user_id)
                    request.user_started_at[user_id] = event_loop.time
                    return

        request_id = self._make_request_id(edge_id, content_id)
        request_state = _RequestState(
            request_id=request_id,
            edge_id=edge_id,
            content_id=content_id,
            started_at=event_loop.time,
            chunking_enabled=self.chunking_enabled,
            user_ids=[user_id],
            user_started_at={user_id: event_loop.time},
            selected_paths=[list(record.path) for record in selected_paths],
            chunk_count=len(selected_paths),
        )
        self.requests[request_id] = request_state
        if self.lmm == "LMM-2":
            self.inflight_by_content[state_id] = request_id

        timeout = self._request_timeout(selected_paths)
        event_loop.schedule(timeout, self.edges[edge_id].on_user_timer, request_id, event_loop)

        chunk_count = max(1, len(selected_paths))
        for chunk_id, record in enumerate(selected_paths):
            if len(record.path) < 2:
                continue
            msg = _InterestMessage(
                content_id=content_id,
                mode="fetch",
                path=list(record.path),
                provider_id=record.provider_id,
                current_index=1,
                chunk_id=chunk_id,
                chunk_count=chunk_count,
                request_id=request_id,
                user_id=user_id,
                cache_node_id=self.cache_node_ids.get(state_id),
            )
            next_hop_id = record.path[1]
            event_loop.schedule(
                self._hop_delay(next_hop_id, data_phase=False),
                self.nodes[next_hop_id].on_interest,
                msg,
                event_loop,
            )
            event_loop.schedule(
                max(6.0, 1.25 * record.delay),
                self.edges[edge_id].on_path_timer,
                request_id,
                tuple(record.path),
                event_loop,
            )

    def _on_user_timer(self, request_id: str, event_loop: _SymbolicEventLoop) -> None:
        request = self.requests.get(request_id)
        if request is None or request.completed or request.timed_out:
            return

        request.timed_out = True
        state_id = _state_key(request.edge_id, request.content_id)
        if self.inflight_by_content.get(state_id) == request_id:
            self.inflight_by_content.pop(state_id, None)

        fallback_hops = fmean(max(0, len(path) - 1) for path in request.selected_paths) if request.selected_paths else 0.0
        for user_id in request.user_ids:
            delay = event_loop.time - request.user_started_at.get(user_id, request.started_at)
            self.round_user_records.append(
                {
                    "hops": float(fallback_hops),
                    "delay": float(delay),
                    "success_rate": 0.0,
                }
            )

    def _on_path_timer(
        self,
        request_id: str,
        path_key: Tuple[str, ...],
        event_loop: _SymbolicEventLoop,
    ) -> None:
        request = self.requests.get(request_id)
        if request is None or path_key in request.delivered_paths:
            return
        self._update_learning_from_path(
            request.edge_id,
            request.content_id,
            list(path_key),
            content_received=False,
        )
        self._refresh_path_table(request.edge_id, request.content_id)

    def _on_node_interest(
        self,
        node_id: str,
        msg: _InterestMessage,
        event_loop: _SymbolicEventLoop,
    ) -> None:
        if msg.mode == "explore":
            hops_map = self.provider_hops[msg.provider_id]
            current_hops = hops_map.get(node_id)
            if current_hops is None:
                return
            if node_id == msg.provider_id:
                data = _DataMessage(
                    content_id=msg.content_id,
                    mode="explore",
                    path=list(msg.path),
                    provider_id=node_id,
                    current_index=len(msg.path) - 1,
                    chunk_id=msg.chunk_id,
                    chunk_count=msg.chunk_count,
                )
                upstream_id = msg.path[-2]
                event_loop.schedule(
                    self._hop_delay(upstream_id, data_phase=True),
                    self.nodes[upstream_id].on_data,
                    data,
                    event_loop,
                )
                return

            if self.base.nodes[node_id].resource_weight() <= 0.0:
                return

            for neighbor_id in self.base.adjacency[node_id]:
                if neighbor_id in msg.path:
                    continue
                if hops_map.get(neighbor_id, 10**9) >= current_hops:
                    continue
                next_msg = _InterestMessage(
                    content_id=msg.content_id,
                    mode="explore",
                    path=list(msg.path) + [neighbor_id],
                    provider_id=msg.provider_id,
                    current_index=len(msg.path),
                )
                event_loop.schedule(
                    self._hop_delay(neighbor_id, data_phase=False),
                    self.nodes[neighbor_id].on_interest,
                    next_msg,
                    event_loop,
                )
            return

        current_index = msg.current_index
        current_path = list(msg.path)
        can_serve = (
            node_id in self.content_publisher_sets.get(msg.content_id, self.active_publisher_set)
            or msg.content_id in self.base.nodes[node_id].cached_contents
        )
        if can_serve:
            returned_path = current_path[: current_index + 1]
            data = _DataMessage(
                content_id=msg.content_id,
                mode="fetch",
                path=returned_path,
                provider_id=node_id,
                current_index=len(returned_path) - 1,
                chunk_id=msg.chunk_id,
                chunk_count=msg.chunk_count,
                request_id=msg.request_id,
                cache_node_id=msg.cache_node_id,
                cache_hit=(node_id not in self.active_publisher_set),
            )
            upstream_id = returned_path[-2]
            event_loop.schedule(
                self._hop_delay(upstream_id, data_phase=True),
                self.nodes[upstream_id].on_data,
                data,
                event_loop,
            )
            return

        if self.base.nodes[node_id].resource_weight() <= 0.0:
            return

        next_index = current_index + 1
        if next_index >= len(current_path):
            return
        next_hop_id = current_path[next_index]
        next_msg = _InterestMessage(
            content_id=msg.content_id,
            mode="fetch",
            path=current_path,
            provider_id=msg.provider_id,
            current_index=next_index,
            chunk_id=msg.chunk_id,
            chunk_count=msg.chunk_count,
            request_id=msg.request_id,
            user_id=msg.user_id,
            cache_node_id=msg.cache_node_id,
        )
        event_loop.schedule(
            self._hop_delay(next_hop_id, data_phase=False),
            self.nodes[next_hop_id].on_interest,
            next_msg,
            event_loop,
        )

    def _on_node_data(
        self,
        node_id: str,
        msg: _DataMessage,
        event_loop: _SymbolicEventLoop,
    ) -> None:
        edge_id = msg.path[0] if msg.path else self.primary_edge_id
        if msg.mode == "explore":
            if node_id == edge_id:
                if not self.exploration_open.get(_state_key(edge_id, msg.content_id), False):
                    return
                self._register_discovered_path(
                    edge_id,
                    msg.content_id,
                    msg.provider_id,
                    msg.path,
                    is_cached_provider=False,
                )
                return

            upstream_index = msg.current_index - 1
            if upstream_index < 0:
                return
            upstream_id = msg.path[upstream_index]
            next_msg = _DataMessage(
                content_id=msg.content_id,
                mode="explore",
                path=list(msg.path),
                provider_id=msg.provider_id,
                current_index=upstream_index,
                chunk_id=msg.chunk_id,
                chunk_count=msg.chunk_count,
            )
            event_loop.schedule(
                self._hop_delay(upstream_id, data_phase=True),
                self.nodes[upstream_id].on_data,
                next_msg,
                event_loop,
            )
            return

        if self.lmm == "LMM-2" and msg.cache_node_id == node_id:
            _store_in_cache(self.base, node_id, self.content_specs[msg.content_id])
            self._register_discovered_path(
                edge_id,
                msg.content_id,
                node_id,
                msg.path[: msg.current_index + 1],
                is_cached_provider=True,
            )

        if node_id == edge_id:
            user_success = _path_success(self.base, msg.path, exclude_terminal=False)
            user_hops = max(0, len(msg.path) - 1)

            self._register_discovered_path(
                edge_id,
                msg.content_id,
                msg.provider_id,
                msg.path,
                is_cached_provider=msg.cache_hit,
            )
            self._update_learning_from_path(
                edge_id,
                msg.content_id,
                msg.path,
                content_received=True,
            )
            self._refresh_path_table(edge_id, msg.content_id)

            _touch_path_resources(
                self.base,
                msg.path,
                load_scale=1.0,
                cache_hit=msg.cache_hit,
                content_id=msg.content_id,
            )

            request = self.requests.get(msg.request_id or "")
            if request is not None:
                request.delivered_paths.add(tuple(msg.path))
                if msg.chunk_id not in request.delivered_chunk_ids:
                    request.delivered_chunk_ids.add(msg.chunk_id)
                    request.chunk_arrival_times[msg.chunk_id] = event_loop.time
                    request.chunk_metrics[msg.chunk_id] = {
                        "hops": float(user_hops),
                        "delay": float(event_loop.time - request.started_at),
                        "success_rate": float(user_success),
                    }
                if not request.completed and not request.timed_out:
                    all_chunks_received = len(request.delivered_chunk_ids) >= max(1, request.chunk_count)
                    if not all_chunks_received:
                        return
                    request.completed = True
                    state_id = _state_key(request.edge_id, request.content_id)
                    if self.inflight_by_content.get(state_id) == request.request_id:
                        self.inflight_by_content.pop(state_id, None)
                    chunk_ids = sorted(request.chunk_metrics)
                    avg_chunk_hops = fmean(request.chunk_metrics[chunk_id]["hops"] for chunk_id in chunk_ids)
                    request_success = 1.0
                    for chunk_id in chunk_ids:
                        request_success *= request.chunk_metrics[chunk_id]["success_rate"]
                    for user_id in request.user_ids:
                        user_started_at = request.user_started_at.get(user_id, request.started_at)
                        user_delay = fmean(
                            max(0.0, request.chunk_arrival_times[chunk_id] - user_started_at)
                            for chunk_id in chunk_ids
                        )
                        self.round_user_records.append(
                            {
                                "hops": float(avg_chunk_hops),
                                "delay": float(user_delay),
                                "success_rate": float(request_success),
                            }
                        )

                    if self.lmm == "LMM-2":
                        cache_node_id = self.cache_node_ids.get(state_id)
                        if (
                            cache_node_id is not None
                            and request_success >= 0.55
                            and msg.content_id in self.base.nodes[cache_node_id].cached_contents
                        ):
                            self._register_cache_prefix_paths(edge_id, msg.content_id, cache_node_id)
                            self._refresh_path_table(edge_id, msg.content_id)
            return

        upstream_index = msg.current_index - 1
        if upstream_index < 0:
            return
        upstream_id = msg.path[upstream_index]
        next_msg = _DataMessage(
            content_id=msg.content_id,
            mode="fetch",
            path=list(msg.path),
            provider_id=msg.provider_id,
            current_index=upstream_index,
            chunk_id=msg.chunk_id,
            chunk_count=msg.chunk_count,
            request_id=msg.request_id,
            cache_node_id=msg.cache_node_id,
            cache_hit=msg.cache_hit,
        )
        event_loop.schedule(
            self._hop_delay(upstream_id, data_phase=True),
            self.nodes[upstream_id].on_data,
            next_msg,
            event_loop,
        )

    def run_round(self, round_index: int, num_users: int) -> Dict[str, float]:
        self.current_round_index = round_index
        self.round_user_records = []
        self.inflight_by_content = {}
        self.requests = {}

        loop = _SymbolicEventLoop()
        request_spacing = self.arrival_window / max(1, num_users)
        base_offset = (round_index * max(1, num_users)) % len(self.content_sequence)

        for user_index in range(num_users):
            content_id = self.content_sequence[(base_offset + user_index) % len(self.content_sequence)]
            edge_id = self.edge_ids[(round_index + user_index) % len(self.edge_ids)]
            user_id = f"U{round_index + 1}_{user_index + 1}"
            loop.schedule(
                request_spacing * user_index,
                self.edges[edge_id].on_user_request,
                user_id,
                content_id,
                loop,
            )

        loop.run()
        return _summarize_user_metrics(self.round_user_records)


def _build_exploration_snapshot(
    base: BaseTopology,
    active_publishers: Sequence[str],
    content_specs: Sequence[ContentSpec],
    *,
    content_publishers: Optional[Dict[str, Sequence[str]]] = None,
    exploration_window: float,
) -> _ExplorationSnapshot:
    bootstrap_scenario = _SymbolicScenario(
        base=base,
        active_publishers=active_publishers,
        content_specs=content_specs,
        content_publishers=content_publishers,
        lmm="LMM-1",
        chunking_enabled=False,
        arrival_window=exploration_window,
        exploration_window=exploration_window,
    )
    return _ExplorationSnapshot(
        provider_hops=_clone_provider_hops(bootstrap_scenario.provider_hops),
        discovered_paths=_clone_discovered_paths(bootstrap_scenario.discovered_paths),
        path_table=_clone_path_table(bootstrap_scenario.path_table),
    )


def _effective_arrival_window(
    arrival_window: float,
    num_users: int,
    *,
    load_normalized_arrivals: bool,
    reference_user_count: int,
) -> float:
    if not load_normalized_arrivals:
        return arrival_window
    baseline_users = max(1, reference_user_count)
    return arrival_window * (max(1, num_users) / baseline_users)


def _run_dynamic_scenario(
    base: BaseTopology,
    active_publishers: Sequence[str],
    num_users: int,
    *,
    content_specs: Sequence[ContentSpec],
    content_publishers: Optional[Dict[str, Sequence[str]]] = None,
    lmm: str,
    chunking_enabled: bool,
    arrival_window: float,
    exploration_window: Optional[float] = None,
    exploration_snapshot: Optional[_ExplorationSnapshot] = None,
) -> Dict[str, float]:
    if not active_publishers or num_users <= 0 or not content_specs:
        return {
            "avg_hops": 0.0,
            "avg_delay": 0.0,
            "avg_success_rate": 0.0,
        }

    scenario = _SymbolicScenario(
        base=base,
        active_publishers=active_publishers,
        content_specs=content_specs,
        content_publishers=content_publishers,
        lmm=lmm,
        chunking_enabled=chunking_enabled,
        arrival_window=arrival_window,
        exploration_window=exploration_window,
        exploration_snapshot=exploration_snapshot,
    )
    round_summaries: List[Dict[str, float]] = []
    recovery_multiplier = max(0.6, min(1.6, arrival_window / 40.0))
    total_rounds = WARMUP_ROUNDS + MEASUREMENT_ROUNDS

    for round_index in range(total_rounds):
        round_summary = scenario.run_round(round_index, num_users)
        if round_index >= WARMUP_ROUNDS:
            round_summaries.append(round_summary)

        _recover_topology_after_round(
            scenario.base,
            recovery_multiplier=recovery_multiplier,
        )

    return _summarize_rounds(round_summaries)


def simulate_lmm1(
    base: BaseTopology,
    active_publishers: Sequence[str],
    num_users: int,
    *,
    content_specs: Sequence[ContentSpec],
    content_publishers: Optional[Dict[str, Sequence[str]]] = None,
    chunking_enabled: bool = False,
    arrival_window: float = 40.0,
    exploration_window: Optional[float] = None,
    exploration_snapshot: Optional[_ExplorationSnapshot] = None,
) -> Dict[str, float]:
    return _run_dynamic_scenario(
        base,
        active_publishers,
        num_users,
        content_specs=content_specs,
        content_publishers=content_publishers,
        lmm="LMM-1",
        chunking_enabled=chunking_enabled,
        arrival_window=arrival_window,
        exploration_window=exploration_window,
        exploration_snapshot=exploration_snapshot,
    )


def simulate_lmm2(
    base: BaseTopology,
    active_publishers: Sequence[str],
    num_users: int,
    *,
    content_specs: Sequence[ContentSpec],
    content_publishers: Optional[Dict[str, Sequence[str]]] = None,
    chunking_enabled: bool = False,
    arrival_window: float = 40.0,
    exploration_window: Optional[float] = None,
    exploration_snapshot: Optional[_ExplorationSnapshot] = None,
) -> Dict[str, float]:
    return _run_dynamic_scenario(
        base,
        active_publishers,
        num_users,
        content_specs=content_specs,
        content_publishers=content_publishers,
        lmm="LMM-2",
        chunking_enabled=chunking_enabled,
        arrival_window=arrival_window,
        exploration_window=exploration_window,
        exploration_snapshot=exploration_snapshot,
    )


def _evaluate_topology_scenarios(
    *,
    base: BaseTopology,
    topology_seed: int,
    publisher_values: Sequence[int],
    user_values: Sequence[int],
    arrival_window: float,
    content_specs: Sequence[ContentSpec],
    iteration_index: int,
    content_replication_k: int = 2,
    chunking_mode: str = CHUNKING_MODE_WITHOUT,
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
        content_publishers = assign_content_publishers(
            active_publishers,
            content_specs,
            min_publishers_per_content=content_replication_k,
            seed=(topology_seed * 1009) + (num_publishers * 97),
        )
        exploration_snapshot = _build_exploration_snapshot(
            base,
            active_publishers,
            content_specs,
            content_publishers=content_publishers,
            exploration_window=arrival_window,
        )

        for num_users in user_values:
            effective_arrival_window = _effective_arrival_window(
                arrival_window,
                num_users,
                load_normalized_arrivals=load_normalized_arrivals,
                reference_user_count=reference_user_count,
            )
            for chunking_enabled in _enabled_chunking_modes(chunking_mode):
                chunking_label = _chunking_label(chunking_enabled)
                print(
                    f"Iteration - {iteration_index}; Np={num_publishers}; "
                    f"Nu={num_users}; chunking={chunking_label}"
                )
                lmm1 = simulate_lmm1(
                    base,
                    active_publishers,
                    num_users,
                    content_specs=content_specs,
                    content_publishers=content_publishers,
                    chunking_enabled=chunking_enabled,
                    arrival_window=effective_arrival_window,
                    exploration_window=arrival_window,
                    exploration_snapshot=exploration_snapshot,
                )
                lmm2 = simulate_lmm2(
                    base,
                    active_publishers,
                    num_users,
                    content_specs=content_specs,
                    content_publishers=content_publishers,
                    chunking_enabled=chunking_enabled,
                    arrival_window=effective_arrival_window,
                    exploration_window=arrival_window,
                    exploration_snapshot=exploration_snapshot,
                )

                records.append(
                    {
                        "iteration": iteration_index + 1,
                        "seed": topology_seed,
                        "num_publishers": num_publishers,
                        "num_users": num_users,
                        "arrival_window_used": effective_arrival_window,
                        "chunking_mode": chunking_label,
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
                        "arrival_window_used": effective_arrival_window,
                        "chunking_mode": chunking_label,
                        "lmm": "LMM-2",
                        **lmm2,
                    }
                )

    return records


def run_full_experiment(
    *,
    iterations: int,
    publisher_values: Sequence[int],
    user_values: Sequence[int],
    seed_base: int,
    arrival_window: float,
    content_specs: Sequence[ContentSpec],
    content_replication_k: int = 2,
    reuse_topology: bool = True,
    topology_reuse_span: int = 20,
    chunking_mode: str = CHUNKING_MODE_WITHOUT,
    load_normalized_arrivals: bool = False,
    arrival_window_reference_users: Optional[int] = None,
) -> List[Dict[str, Any]]:
    raw_records: List[Dict[str, Any]] = []

    reuse_span = max(1, topology_reuse_span)
    if reuse_topology and reuse_span > 1:
        template_records_by_group: Dict[int, List[Dict[str, Any]]] = {}

        for iteration in range(iterations):
            group_index = iteration // reuse_span
            if group_index not in template_records_by_group:
                topology_seed = seed_base + group_index
                base = build_base_topology(topology_seed)
                template_records_by_group[group_index] = _evaluate_topology_scenarios(
                    base=base,
                    topology_seed=topology_seed,
                    publisher_values=publisher_values,
                    user_values=user_values,
                    arrival_window=arrival_window,
                    content_specs=content_specs,
                    iteration_index=0,
                    content_replication_k=content_replication_k,
                    chunking_mode=chunking_mode,
                    load_normalized_arrivals=load_normalized_arrivals,
                    arrival_window_reference_users=arrival_window_reference_users,
                )

            for row in template_records_by_group[group_index]:
                record = dict(row)
                record["iteration"] = iteration + 1
                raw_records.append(record)
        return raw_records

    for iteration in range(iterations):
        topology_seed = seed_base + iteration
        base = build_base_topology(topology_seed)
        raw_records.extend(
            _evaluate_topology_scenarios(
                base=base,
                topology_seed=topology_seed,
                publisher_values=publisher_values,
                user_values=user_values,
                arrival_window=arrival_window,
                content_specs=content_specs,
                iteration_index=iteration,
                content_replication_k=content_replication_k,
                chunking_mode=chunking_mode,
                load_normalized_arrivals=load_normalized_arrivals,
                arrival_window_reference_users=arrival_window_reference_users,
            )
        )

    return raw_records


def summarize_records(
    records: Sequence[Dict[str, Any]],
    key_fields: Sequence[str],
) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[object, ...], List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = tuple(record[field] for field in key_fields)
        grouped[key].append(record)

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


def write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
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


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
