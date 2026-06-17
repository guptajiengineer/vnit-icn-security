from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ResourceBudget:
    capacity: float
    remaining: float
    threshold: float
    recovery_rate: float = 0.05

    def weight(self) -> float:
        if self.remaining <= self.threshold:
            return 0.0
        return self.remaining / self.threshold

    def available_ratio(self) -> float:
        if self.capacity <= 0.0:
            return 0.0
        return max(0.0, min(1.0, self.remaining / self.capacity))

    def utilization(self) -> float:
        return 1.0 - self.available_ratio()

    def consume(self, amount: float) -> None:
        self.remaining = max(0.0, self.remaining - amount)

    def recover(self, multiplier: float = 1.0) -> None:
        self.remaining = min(
            self.capacity,
            self.remaining + (self.capacity * self.recovery_rate * multiplier),
        )

    def release(self, amount: float) -> None:
        self.remaining = min(self.capacity, self.remaining + amount)


@dataclass
class SimNode:
    node_id: str
    x: float
    y: float
    kind: str = "router"
    active_duration: float = 10.0
    pending_requests: int = 0
    packet_loss: float = 0.0
    response_time: float = 2.0
    resources: Dict[str, ResourceBudget] = field(default_factory=dict)
    base_active_duration: float = 10.0
    base_packet_loss: float = 0.0
    base_response_time: float = 2.0
    queue_capacity: float = 10.0
    cached_contents: Dict[str, "CachedContentState"] = field(default_factory=dict)

    def distance_to(self, other: "SimNode") -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        return (dx * dx + dy * dy) ** 0.5

    def resource(self, name: str) -> Optional[ResourceBudget]:
        return self.resources.get(name)

    def resource_utilization(self, name: str) -> float:
        resource = self.resource(name)
        if resource is None:
            return 0.0
        return resource.utilization()

    def resource_available_ratio(self, name: str) -> float:
        resource = self.resource(name)
        if resource is None:
            return 1.0
        return resource.available_ratio()

    def resource_weight(self) -> float:
        if not self.resources:
            return 1.0
        weight = 1.0
        for budget in self.resources.values():
            score = budget.weight()
            if score == 0.0:
                return 0.0
            weight *= score
        return weight

    def refresh_dynamic_metrics(self) -> None:
        queue_pressure = min(1.5, self.pending_requests / max(1.0, self.queue_capacity))
        cpu_stress = self.resource_utilization("cpu")
        bandwidth_stress = self.resource_utilization("bandwidth")
        cache_stress = self.resource_utilization("cache")
        energy_stress = self.resource_utilization("energy")

        self.response_time = max(
            0.8,
            self.base_response_time
            * (
                1.0
                + 0.95 * queue_pressure
                + 0.45 * cpu_stress
                + 0.38 * bandwidth_stress
                + 0.18 * cache_stress
                + 0.36 * energy_stress
            ),
        )

        self.packet_loss = max(
            0.0001,
            min(
                0.35,
                self.base_packet_loss
                + 0.02 * queue_pressure
                + 0.018 * bandwidth_stress
                + 0.012 * cpu_stress
                + 0.01 * energy_stress
                + 0.006 * cache_stress,
            ),
        )

        self.active_duration = max(
            2.0,
            self.base_active_duration
            * (
                1.0
                - 0.18 * cpu_stress
                - 0.16 * bandwidth_stress
                - 0.14 * energy_stress
            ),
        )


@dataclass
class PathRecord:
    provider_id: str
    path: List[str]
    content_id: str = ""
    weight: float = 0.0
    instant_weight: float = 0.0
    learned_weight: float = 0.0
    hops: int = 0
    delay: float = 0.0
    success_rate: float = 0.0
    is_cached_provider: bool = False


@dataclass
class CachedContentState:
    cache_cost: float
    rounds_remaining: int


@dataclass
class ContentSpec:
    content_id: str
    generation_round: int = 0
    lifespan_rounds: int = 12
    cache_cost: float = 8.0
    availability_threshold: float = 0.25
    lifetime_threshold: float = 0.0
    popularity: float = 1.0

    def normalized_lifetime(self, round_index: int) -> float:
        if self.lifespan_rounds <= 0:
            return 0.0
        age = max(0, round_index - self.generation_round)
        return max(0.0, min(1.0, age / self.lifespan_rounds))


@dataclass
class BaseTopology:
    nodes: Dict[str, SimNode]
    adjacency: Dict[str, List[str]]
    subscriber_id: str
    publisher_candidates: List[str]
    edge_node_ids: List[str] = field(default_factory=list)
