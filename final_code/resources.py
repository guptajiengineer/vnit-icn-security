from __future__ import annotations

from typing import Dict, List, Optional, Sequence
from models import BaseTopology, CachedContentState, ContentSpec, PathRecord
from paths import path_success


def cache_entry_key(
    content_id: str,
    *,
    chunking_enabled: bool = False,
    chunk_id: int = 0,
) -> str:
    if not chunking_enabled:
        return content_id
    return f"{content_id}::chunk::{max(0, chunk_id)}"


def has_cached_content(
    base: BaseTopology,
    node_id: str,
    content_id: str,
    *,
    chunking_enabled: bool = False,
    chunk_id: int = 0,
) -> bool:
    return (
        cache_entry_key(
            content_id,
            chunking_enabled=chunking_enabled,
            chunk_id=chunk_id,
        )
        in base.nodes[node_id].cached_contents
    )


def cache_cost_for_request(
    content: ContentSpec,
    *,
    chunking_enabled: bool = False,
    chunk_count: int = 1,
) -> float:
    if not chunking_enabled:
        return content.cache_cost
    return content.cache_cost / max(1, chunk_count)


def touch_path_resources(
    base: BaseTopology,
    path: Sequence[str],
    load_scale: float,
    cache_hit: bool,
    content_id: Optional[str] = None,
    *,
    chunking_enabled: bool = False,
    chunk_id: int = 0,
) :
    #consumes node resources & recomputes: response time; packet loss & active duration based on system stress

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

        if (
            cache_hit
            and content_id is not None
            and has_cached_content(
                base,
                node_id,
                content_id,
                chunking_enabled=chunking_enabled,
                chunk_id=chunk_id,
            )
        ):
            cache_resource = node.resource("cache")
            if cache_resource is not None:
                cache_resource.consume(0.015 * request_scale)

        node.refresh_dynamic_metrics() #recomputes: response time; packet loss & active duration based on system stress

def store_in_cache(
    base: BaseTopology,
    cache_node_id: str,
    content: ContentSpec,
    *,
    chunking_enabled: bool = False,
    chunk_id: int = 0,
    chunk_count: int = 1,
) :
    node = base.nodes[cache_node_id]
    cache_resource = node.resource("cache")
    cache_key = cache_entry_key(
        content.content_id,
        chunking_enabled=chunking_enabled,
        chunk_id=chunk_id,
    )
    cached_state = node.cached_contents.get(cache_key)
    cache_rounds = max(2, min(6, content.lifespan_rounds))
    cache_cost = cache_cost_for_request(
        content,
        chunking_enabled=chunking_enabled,
        chunk_count=chunk_count,
    )

    if cached_state is not None:
        cached_state.rounds_remaining = max(cached_state.rounds_remaining, cache_rounds)
        if cache_resource is not None:
            cache_resource.consume(0.2)
        node.refresh_dynamic_metrics()
        return

    if cache_resource is not None:
        if cache_resource.remaining < cache_cost:
            return
        cache_resource.consume(cache_cost)

    node.cached_contents[cache_key] = CachedContentState(
        cache_cost=cache_cost,
        rounds_remaining=cache_rounds,
    )
    node.refresh_dynamic_metrics()


def recover_topology_after_round(base: BaseTopology,recovery_multiplier: float,) :
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
