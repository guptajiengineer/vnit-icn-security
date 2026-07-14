from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


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

    def consume(self, amount: float) :
        self.remaining = max(0.0, self.remaining - amount)

    def recover(self, multiplier: float = 1.0) :
        self.remaining = min(
            self.capacity,
            self.remaining + (self.capacity * self.recovery_rate * multiplier),
        )

    def release(self, amount: float) :
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

    def refresh_dynamic_metrics(self) :
        #recomputes: response time; packet loss & active duration based on system stress
        queue_pressure = min(1.5, self.pending_requests / max(1.0, self.queue_capacity))
        cpu_stress = self.resource_utilization("cpu")
        bandwidth_stress = self.resource_utilization("bandwidth")
        cache_stress = self.resource_utilization("cache")
        energy_stress = self.resource_utilization("energy")

        self.response_time = max(0.8, self.base_response_time)

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


@dataclass
class  InterestMessage:
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
class  DataMessage:
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
    # -----------------------------------------------------------------------
    # Obj2 additions — cryptographic authentication fields.
    # Both are Optional so existing code that builds DataMessage without these
    # fields continues to work unchanged (default = None).
    # -----------------------------------------------------------------------
    chunk_hash: Optional[str] = None       # SHA-256 hex of the plaintext chunk
    merkle_proof: Optional[list] = None    # Sibling-path proof: [str(leaf_index), sib_0, ...]
    chunk_signature: Optional[bytes] = None  # Ed25519 signature over chunk_hash (Step 4)


@dataclass
class  RequestState:
    request_id: str
    edge_id: str
    content_id: str
    started_at: float
    chunking_enabled: bool
    user_ids: List[str]
    user_started_at: Dict[str, float]
    selected_paths: List[List[str]]
    chunk_count: int
    delivered_chunk_ids: Set[int] = field(default_factory=set)
    chunk_arrival_times: Dict[int, float] = field(default_factory=dict)
    chunk_metrics: Dict[int, Dict[str, float]] = field(default_factory=dict)
    delivered_paths: Set[Tuple[str, ...]] = field(default_factory=set)
    completed: bool = False
    timed_out: bool = False


@dataclass
class  ExplorationSnapshot:
    provider_hops: Dict[str, Dict[str, int]]
    discovered_paths: Dict[Tuple[str, str], Dict[Tuple[str, ...], Tuple[str, List[str], bool]]]
    path_table: Dict[Tuple[str, str], List[PathRecord]]


# ---------------------------------------------------------------------------
# Obj2 new dataclass — ChunkRecord
# ---------------------------------------------------------------------------

@dataclass
class ChunkRecord:
    """
    Stores all per-chunk cryptographic material produced by publish_content().

    Fields
    ------
    chunk_id      : int   — zero-based index of this chunk within the content.
    chunk_hash    : str   — SHA-256 hex digest of the plaintext chunk bytes.
    chunk_locator : str   — content-addressed locator: "{content_id}:{chunk_id}".
                            Deliberately NOT a physical path (multipath is dynamic).
    chunk_key     : bytes — 32-byte AES-256 key used to encrypt this chunk.
    nonce         : bytes — 12-byte AES-GCM nonce used to encrypt this chunk.
    ciphertext    : bytes — AES-256-GCM authenticated ciphertext of the chunk.
    """
    chunk_id        : int
    chunk_hash      : str
    chunk_locator   : str
    chunk_key       : bytes
    nonce           : bytes
    ciphertext      : bytes
    chunk_signature : Optional[bytes] = None  # Ed25519 signature over chunk_hash (Step 4)
