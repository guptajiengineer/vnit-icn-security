from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any, Dict, List, Tuple
from models import (
    BaseTopology,
    CachedContentState,
    PathRecord,
    ResourceBudget,
    SimNode,
)


def clone_base_topology(base: BaseTopology) -> BaseTopology:
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


def clone_provider_hops(
    provider_hops: Dict[str, Dict[str, int]],
) -> Dict[str, Dict[str, int]]:
    return {
        provider_id: dict(hops_map)
        for provider_id, hops_map in provider_hops.items()
    }


def clone_discovered_paths(
    discovered_paths: Dict[Tuple[str, str], Dict[Tuple[str, ...], Tuple[str, List[str], bool]]],
) -> Dict[Tuple[str, str], Dict[Tuple[str, ...], Tuple[str, List[str], bool]]]:
    cloned: Dict[Tuple[str, str], Dict[Tuple[str, ...], Tuple[str, List[str], bool]]] = defaultdict(dict)
    for state_id, content_paths in discovered_paths.items():
        cloned[state_id] = {
            path_key: (provider_id, list(path), is_cached_provider)
            for path_key, (provider_id, path, is_cached_provider) in content_paths.items()
        }
    return cloned


def clone_path_record(record: PathRecord) -> PathRecord:
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


def clone_path_table(
    path_table: Dict[Tuple[str, str], List[PathRecord]],
) -> Dict[Tuple[str, str], List[PathRecord]]:
    return {
        state_id: [clone_path_record(record) for record in records]
        for state_id, records in path_table.items()
    }


def snapshot_dynamic_state(base: BaseTopology) -> Dict[str, Dict[str, Any]]:
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


def restore_dynamic_state(
    base: BaseTopology,
    snapshot: Dict[str, Dict[str, Any]],
) :
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
