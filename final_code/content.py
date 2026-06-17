from __future__ import annotations

import random
from typing import Dict, List, Optional, Sequence, Set
from models import BaseTopology, ContentSpec


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


def content_provider_ids(
    base: BaseTopology,
    active_publishers: Sequence[str],
    content_id: str,
    include_cached_providers: bool,
    content_publishers: Optional[Dict[str, Sequence[str]]] = None,
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
    min_publishers_per_content: int,
    seed: int,
) -> Dict[str, List[str]]:
    if min_publishers_per_content <= 0:
        raise ValueError("min_publishers_per_content must be > 0")

    provider_ids = list(dict.fromkeys(active_publishers))
    ordered_contents = sorted(content_specs, key=lambda item: item.content_id)
    if not ordered_contents:
        return {}
    if not provider_ids:
        return {content.content_id: [] for content in ordered_contents}

    min_k = min(len(provider_ids) - 1, max(1, min_publishers_per_content))
    rng = random.Random(seed)
    content_publishers: Dict[str, Set[str]] = {
        content.content_id: set()
        for content in ordered_contents
    }
    content_ids = [content.content_id for content in ordered_contents]

    # Give every active producer at least one randomly chosen content first.
    shuffled_providers = list(provider_ids)
    rng.shuffle(shuffled_providers)
    for provider_id in shuffled_providers:
        chosen_content_id = content_ids[rng.randrange(len(content_ids))]
        content_publishers[chosen_content_id].add(provider_id)

    for content in ordered_contents:
        assigned_providers = content_publishers[content.content_id]
        while len(assigned_providers) < min_k:
            remaining = [
                provider_id
                for provider_id in provider_ids
                if provider_id not in assigned_providers
            ]
            if not remaining:
                break
            assigned_providers.add(rng.choice(remaining))

        remaining = [
            provider_id
            for provider_id in provider_ids
            if provider_id not in assigned_providers
        ]
        if remaining:
            extra_replicas = rng.randint(0, len(remaining))
            rng.shuffle(remaining)
            assigned_providers.update(remaining[:extra_replicas])

    return {
        content_id: sorted(provider_ids_for_content)
        for content_id, provider_ids_for_content in content_publishers.items()
    }

#tosee
def build_request_cycle(content_specs: Sequence[ContentSpec]) -> List[str]:
    weighted_cycle: List[str] = []
    for content in sorted(content_specs, key=lambda item: (-item.popularity, item.content_id)):
        repeats = max(1, round(content.popularity * 4))
        weighted_cycle.extend([content.content_id] * repeats)
    weighted_cycle = ["a1", "a2"]
    return weighted_cycle
