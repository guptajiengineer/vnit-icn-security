from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Sequence, Tuple
import config
from models import BaseTopology, PathRecord
from content import  content_provider_ids


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


def  path_success(
    base: BaseTopology,
    path: Sequence[str],
    exclude_terminal: bool = False,
) -> float:
    success = 1.0
    end_index = -1 if exclude_terminal and len(path) > 1 else None
    for node_id in path[1:end_index]:
        success *= 1.0 - base.nodes[node_id].packet_loss
    return max(0.0, min(1.0, success))


def  normalizer(values: Sequence[float], floor_max: bool) -> float:
    if not values:
        return 1.0
    max_value = max(values)
    min_value = min(values)
    if floor_max:
        max_value = max(1.0, max_value)
    denom = max_value + min_value
    return denom if denom > 0.0 else 1.0


def  bfs_hop_distances(
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


def  enumerate_provider_paths(
    base: BaseTopology,
    source_id: str,
    provider_id: str,
    max_extra_hops: int,
    max_paths: int,
) -> List[List[str]]:
    shortest_path = bfs_shortest_path(base.adjacency, source_id, provider_id)
    if not shortest_path:
        return []

    shortest_hops = max(0, len(shortest_path) - 1)
    max_hops = shortest_hops + max(0, max_extra_hops)
    hops_to_provider =  bfs_hop_distances(base.adjacency, provider_id)

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


def  path_records_from_raw_paths(
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

    duration_norm =  normalizer(durations, floor_max=False)
    pending_norm =  normalizer(pendings, floor_max=True)
    loss_norm =  normalizer(losses, floor_max=True)
    response_norm =  normalizer(responses, floor_max=True)

    path_records: List[PathRecord] = []
    for provider_id, path, is_cached_provider, duration, pending, loss, response in enriched_rows:
        d_value = duration / duration_norm
        q_value = pending / pending_norm
        l_value = loss / loss_norm
        o_value = response / response_norm
        weight = d_value / (q_value + l_value + o_value + 1e-9)
        hops = max(0, len(path) - 1)
        success_rate = 1.0
        for node_id in path[1:]:
            node = base.nodes[node_id]
            success_rate *= 1.0 - node.packet_loss

        live_delay = 0.85 * hops
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


def  ordered_candidates(path_records: Sequence[PathRecord]) -> List[PathRecord]:
    return sorted(
        path_records,
        key=lambda record: (-record.weight, record.delay, record.hops, -record.success_rate),
    )


def build_provider_paths(
    base: BaseTopology,
    active_publishers: Sequence[str],
    source_id: str,
    content_id: str,
    content_publishers: Optional[Dict[str, Sequence[str]]] = None,
    include_cached_providers: bool = True,
    max_extra_hops: int = 2,
    max_paths_per_provider: int = 6,
) -> List[PathRecord]:
    raw_paths: List[Tuple[str, List[str], bool]] = []

    provider_ids =  content_provider_ids(
        base,
        active_publishers,
        content_id,
        include_cached_providers=include_cached_providers,
        content_publishers=content_publishers,
    )
    active_publisher_set = set(active_publishers)

    for provider_id in provider_ids:
        candidate_paths =  enumerate_provider_paths(
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
    return  path_records_from_raw_paths(base, content_id, raw_paths)


def  overlap_ratio(path_a: Sequence[str], path_b: Sequence[str]) -> float:
    nodes_a = set(path_a[1:-1])
    nodes_b = set(path_b[1:-1])
    if not nodes_a or not nodes_b:
        return 0.0
    return len(nodes_a & nodes_b) / min(len(nodes_a), len(nodes_b))


def select_multipaths(
    path_records: Sequence[PathRecord],
    overlap_threshold: float = 0.0,
    min_weight: float = config.PATH_WEIGHT_THRESHOLD,
) -> List[PathRecord]:
    best_by_provider: Dict[str, PathRecord] = {}
    for record in  ordered_candidates(path_records):
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

    selected =  ordered_candidates(selected)
    index = 0
    while index < len(selected):
        left = selected[index]
        compare_index = index + 1
        while compare_index < len(selected):
            right = selected[compare_index]
            if  overlap_ratio(left.path, right.path) > overlap_threshold:
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


def  prefix_path(path: Sequence[str], node_id: Optional[str]) -> List[str]:
    if node_id is None or node_id not in path:
        return list(path)
    return list(path[: path.index(node_id) + 1])
