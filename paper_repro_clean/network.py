from __future__ import annotations

import random
from collections import deque
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    from .models import BaseTopology, ResourceBudget, SimNode
except ImportError:  # pragma: no cover
    from models import BaseTopology, ResourceBudget, SimNode


DEFAULT_AREA_SIZE = 150.0
DEFAULT_COMMUNICATION_RANGE = 20.0
DEFAULT_TOTAL_NODES = 120
DEFAULT_MIN_SPACING = 3.0
DEFAULT_MAX_PUBLISHERS = 10


def _make_router_resources(rng: random.Random) -> Dict[str, ResourceBudget]:
    profiles = {
        "cpu": (30.0, 2.1, 0.08),
        "cache": (100.0, 2.5, 0.03),
        "bandwidth": (20.0, 2.2, 0.10),
        "energy": (40.0, 3.0, 0.0),
    }
    budgets: Dict[str, ResourceBudget] = {}
    for name, (threshold, capacity_factor, recovery_rate) in profiles.items():
        capacity = threshold * rng.uniform(capacity_factor * 0.9, capacity_factor * 1.1)
        budgets[name] = ResourceBudget(
            capacity=capacity,
            remaining=capacity,
            threshold=threshold,
            recovery_rate=recovery_rate,
        )
    return budgets


def _sample_router(node_id: str, x: float, y: float, rng: random.Random) -> SimNode:
    return SimNode(
        node_id=node_id,
        x=x,
        y=y,
        kind="router",
        active_duration=rng.uniform(9.0, 12.0),
        pending_requests=rng.randint(0, 3),
        packet_loss=rng.uniform(0.001, 0.01),
        response_time=rng.uniform(1.5, 4.5),
        resources=_make_router_resources(rng),
    )


def _shape_metrics_by_distance(
    edge_nodes: List[SimNode],
    service_nodes: List[SimNode],
    rng: random.Random,
) -> None:
    if not edge_nodes:
        return

    max_distance = max(
        min(edge.distance_to(node) for edge in edge_nodes)
        for node in service_nodes
    )
    if max_distance <= 0.0:
        return

    for node in service_nodes:
        distance_ratio = min(edge.distance_to(node) for edge in edge_nodes) / max_distance
        cpu_resource = node.resource("cpu")
        bandwidth_resource = node.resource("bandwidth")
        cache_resource = node.resource("cache")
        energy_resource = node.resource("energy")

        if cpu_resource is not None:
            cpu_resource.remaining = cpu_resource.capacity * max(
                0.45,
                min(0.92, 0.86 - 0.18 * distance_ratio + rng.uniform(-0.04, 0.04)),
            )
        if bandwidth_resource is not None:
            bandwidth_resource.remaining = bandwidth_resource.capacity * max(
                0.4,
                min(0.94, 0.88 - 0.24 * distance_ratio + rng.uniform(-0.04, 0.04)),
            )
        if cache_resource is not None:
            cache_resource.remaining = cache_resource.capacity * max(
                0.55,
                min(0.96, 0.9 - 0.10 * distance_ratio + rng.uniform(-0.03, 0.03)),
            )
        if energy_resource is not None:
            energy_resource.remaining = energy_resource.capacity * max(
                0.35,
                min(0.97, 0.93 - 0.32 * distance_ratio + rng.uniform(-0.03, 0.03)),
            )

        node.base_active_duration = max(
            7.0,
            11.5 - (1.5 * distance_ratio) + rng.uniform(-0.25, 0.25),
        )
        node.pending_requests = max(
            0,
            min(4, round(distance_ratio * 3 + rng.uniform(-0.4, 0.4))),
        )
        node.base_packet_loss = max(
            0.0005,
            min(0.012, 0.001 + (0.0075 * distance_ratio) + rng.uniform(0.0, 0.0015)),
        )
        node.base_response_time = max(
            1.2,
            1.8 + (2.2 * distance_ratio) + rng.uniform(-0.2, 0.3),
        )
        node.queue_capacity = max(
            6.0,
            14.0 - (3.5 * distance_ratio) + rng.uniform(-0.4, 0.4),
        )
        node.refresh_dynamic_metrics()


def _too_close(
    x: float,
    y: float,
    positions: Iterable[Tuple[float, float]],
    min_spacing: float,
) -> bool:
    for px, py in positions:
        dx = x - px
        dy = y - py
        if (dx * dx + dy * dy) ** 0.5 < min_spacing:
            return True
    return False


def _connect(adjacency: Dict[str, Set[str]], a: str, b: str) -> None:
    adjacency[a].add(b)
    adjacency[b].add(a)


def _ensure_connected(nodes: Dict[str, SimNode], adjacency: Dict[str, Set[str]]) -> None:
    def component(start: str, unseen: Set[str]) -> Set[str]:
        queue: deque[str] = deque([start])
        comp: Set[str] = set()
        while queue:
            node_id = queue.popleft()
            if node_id not in unseen:
                continue
            unseen.remove(node_id)
            comp.add(node_id)
            queue.extend(adjacency[node_id])
        return comp

    for _ in range(len(nodes)):
        unseen = set(nodes)
        components: List[Set[str]] = []
        while unseen:
            seed = next(iter(unseen))
            components.append(component(seed, unseen))

        if len(components) == 1:
            break

        components.sort(key=len, reverse=True)
        main = components[0]
        best_pair: Optional[Tuple[str, str]] = None
        best_distance = float("inf")

        for other in components[1:]:
            for node_a in main:
                for node_b in other:
                    distance = nodes[node_a].distance_to(nodes[node_b])
                    if distance < best_distance:
                        best_distance = distance
                        best_pair = (node_a, node_b)

        if best_pair is None:
            break

        _connect(adjacency, best_pair[0], best_pair[1])


def _bfs_hops(adjacency: Dict[str, Set[str]], start: str) -> Dict[str, int]:
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

#todo
def _pick_publisher_candidates(
    nodes: Dict[str, SimNode],
    adjacency: Dict[str, Set[str]],
    edge_node_ids: Sequence[str],
    max_publishers: int,
    communication_range: float,
) -> List[str]:
    edge_hop_maps = [_bfs_hops(adjacency, edge_id) for edge_id in edge_node_ids]

    candidates = [
        node_id
        for node_id, node in nodes.items()
        if (
            node.kind == "router"
            and any(node_id in hop_map for hop_map in edge_hop_maps)
            and min(hop_map.get(node_id, 10**9) for hop_map in edge_hop_maps) >= 2
        )
    ]

    candidates.sort(
        key=lambda node_id: (
            min(hop_map.get(node_id, 10**9) for hop_map in edge_hop_maps),
            min(nodes[edge_id].distance_to(nodes[node_id]) for edge_id in edge_node_ids),
        ),
        reverse=True,
    )

    selected: List[str] = []
    min_separation = communication_range * 1.5

    for node_id in candidates:
        node = nodes[node_id]
        if min(nodes[edge_id].distance_to(node) for edge_id in edge_node_ids) <= communication_range * 1.25:
            continue
        if all(node.distance_to(nodes[other_id]) >= min_separation for other_id in selected):
            selected.append(node_id)
        if len(selected) == max_publishers:
            break

    if len(selected) < max_publishers:
        for node_id in candidates:
            if node_id not in selected:
                selected.append(node_id)
            if len(selected) == max_publishers:
                break

    selected.sort(
        key=lambda node_id: (
            min(hop_map.get(node_id, 10**9) for hop_map in edge_hop_maps),
            min(nodes[edge_id].distance_to(nodes[node_id]) for edge_id in edge_node_ids),
        ),
        reverse=True,
    )
    return selected[:max_publishers]


def build_base_topology(
    seed: int,
    *,
    area_size: float = DEFAULT_AREA_SIZE,
    communication_range: float = DEFAULT_COMMUNICATION_RANGE,
    total_nodes: int = DEFAULT_TOTAL_NODES,
    min_spacing: float = DEFAULT_MIN_SPACING,
    max_publishers: int = DEFAULT_MAX_PUBLISHERS,
    edge_node_count: int = 2,
) -> BaseTopology:
    if edge_node_count <= 0:
        raise ValueError("edge_node_count must be > 0")
    if total_nodes <= max_publishers + edge_node_count:
        raise ValueError("total_nodes must leave room for routers and edge nodes")

    rng = random.Random(seed)
    nodes: Dict[str, SimNode] = {}
    edge_positions = [
        (12.0, 12.0),
        (12.0, max(12.0, area_size - 12.0)),
        (max(12.0, area_size - 12.0), 12.0),
        (max(12.0, area_size - 12.0), max(12.0, area_size - 12.0)),
    ]
    if edge_node_count > len(edge_positions):
        raise ValueError(f"edge_node_count must be <= {len(edge_positions)}")

    edge_nodes: List[SimNode] = []
    positions: List[Tuple[float, float]] = []
    for edge_index in range(edge_node_count):
        x, y = edge_positions[edge_index]
        edge_node = SimNode(
            node_id=f"EN{edge_index}",
            x=x,
            y=y,
            kind="subscriber",
            active_duration=10.0,
            pending_requests=0,
            packet_loss=0.0,
            response_time=2.0,
            resources={},
            base_active_duration=10.0,
            base_packet_loss=0.0,
            base_response_time=2.0,
            queue_capacity=20.0,
        )
        nodes[edge_node.node_id] = edge_node
        edge_nodes.append(edge_node)
        positions.append((x, y))

    service_count = total_nodes - edge_node_count

    anchor_positions: List[Tuple[float, float]] = []
    for edge_node in edge_nodes:
        anchor_positions.extend(
            [
                (min(area_size, edge_node.x + 16.0), edge_node.y),
                (edge_node.x, max(0.0, min(area_size, edge_node.y + (16.0 if edge_node.y <= area_size / 2.0 else -16.0)))),
                (
                    min(area_size, edge_node.x + 14.0),
                    max(0.0, min(area_size, edge_node.y + (12.0 if edge_node.y <= area_size / 2.0 else -12.0))),
                ),
            ]
        )

    service_nodes: List[SimNode] = []

    for anchor_index, (x, y) in enumerate(anchor_positions):
        node_id = f"R{anchor_index}"
        node = _sample_router(node_id, x, y, rng)
        nodes[node_id] = node
        service_nodes.append(node)
        positions.append((x, y))

    next_index = len(service_nodes)
    attempts = 0
    while len(service_nodes) < service_count:
        attempts += 1
        if attempts > 50000:
            raise RuntimeError("failed to place all service nodes; try a different seed")
        x = rng.uniform(0.0, area_size)
        y = rng.uniform(0.0, area_size)
        if _too_close(x, y, positions, min_spacing):
            continue
        node_id = f"R{next_index}"
        next_index += 1
        node = _sample_router(node_id, x, y, rng)
        nodes[node_id] = node
        service_nodes.append(node)
        positions.append((x, y))

    _shape_metrics_by_distance(edge_nodes, service_nodes, rng)

    adjacency: Dict[str, Set[str]] = {node_id: set() for node_id in nodes}
    all_node_ids = list(nodes)

    for idx, node_a_id in enumerate(all_node_ids):
        node_a = nodes[node_a_id]
        for node_b_id in all_node_ids[idx + 1 :]:
            node_b = nodes[node_b_id]
            if node_a.distance_to(node_b) <= communication_range:
                _connect(adjacency, node_a_id, node_b_id)

    _ensure_connected(nodes, adjacency)

    publisher_candidates = _pick_publisher_candidates(
        nodes,
        adjacency,
        [node.node_id for node in edge_nodes],
        max_publishers=max_publishers,
        communication_range=communication_range,
    )
    if len(publisher_candidates) < max_publishers:
        raise RuntimeError("could not identify enough publisher candidates in the generated topology")

    adjacency_lists = {
        node_id: sorted(neighbors)
        for node_id, neighbors in adjacency.items()
    }

    return BaseTopology(
        nodes=nodes,
        adjacency=adjacency_lists,
        subscriber_id=edge_nodes[0].node_id,
        publisher_candidates=publisher_candidates,
        edge_node_ids=[node.node_id for node in edge_nodes],
    )
