from __future__ import annotations

import heapq
import itertools
from statistics import fmean
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, TYPE_CHECKING

import config
import crypto_auth
from models import (BaseTopology, ChunkRecord, ContentSpec, PathRecord, DataMessage,
                    ExplorationSnapshot, InterestMessage, RequestState,)
from content import build_request_cycle
from learning import apply_learning_scores, learning_key
from metrics import (empty_summary, make_user_record, summarize_rounds, summarize_user_metrics,)
from paths import (bfs_hop_distances, path_records_from_raw_paths, path_success, prefix_path, select_multipaths,)
from resources import (
    has_cached_content,
    recover_topology_after_round,
    store_in_cache,
    touch_path_resources,
)
from state import (clone_base_topology, clone_discovered_paths, clone_path_table, clone_provider_hops,)
from network import choose_cache_node, expand_user_edge_nodes

if TYPE_CHECKING:
    from chain import Ledger


def state_key(edge_id: str, content_id: str) -> Tuple[str, str]:
    return edge_id, content_id


# This event loop is intentionally tiny. It is just enough for request/data replay.
class EventLoop:
    def __init__(self):
        self.time = 0.0
        self.queue: List[Tuple[float, int, Any, Tuple[Any, ...]]] = []
        self.counter = itertools.count()

    def schedule(self, delay: float, callback: Any, *args: Any) :
        heapq.heappush(
            self.queue,
            (self.time + max(0.0, delay), next(self.counter), callback, args),
        )

    def run(self) :
        while self.queue:
            event_time, _, callback, args = heapq.heappop(self.queue)
            self.time = event_time
            callback(*args)


class RuntimeNode:
    def __init__(self, scenario: "NetworkScenario", node_id: str):
        self.scenario = scenario
        self.node_id = node_id

    def on_interest(self, msg: InterestMessage, event_loop: EventLoop) :
        self.scenario.on_node_interest(self.node_id, msg, event_loop)

    def on_data(self, msg: DataMessage, event_loop: EventLoop):
        self.scenario.on_node_data(self.node_id, msg, event_loop)


class EdgeRuntimeNode(RuntimeNode):
    def start_exploration(self, content_id: str, event_loop: EventLoop):
        self.scenario.start_exploration(self.node_id, content_id, event_loop)

    def on_exploration_timer( self, content_id: str, event_loop: EventLoop):
        self.scenario.on_exploration_timer(self.node_id, content_id, event_loop)

    def on_user_request(self, user_id: str, content_id: str, event_loop: EventLoop):
        self.scenario.on_user_request(self.node_id, user_id, content_id, event_loop)

    def on_user_timer(self,request_id: str, event_loop: EventLoop):
        self.scenario.on_user_timer(request_id, event_loop)

    def on_path_timer(self, request_id: str, path_key: Tuple[str, ...], event_loop: EventLoop):
        self.scenario.on_path_timer(request_id, path_key, event_loop)


class NetworkScenario:
    def __init__(
        self,
        base: BaseTopology,
        active_publishers: Sequence[str],
        access_node_ids: Optional[Sequence[str]],
        content_specs: Sequence[ContentSpec],
        content_publishers: Optional[Dict[str, Sequence[str]]],
        lmm: str,
        chunking_enabled: bool,
        arrival_window: float,
        exploration_window: Optional[float] = None,
        exploration_snapshot: Optional[ExplorationSnapshot] = None,
        # -------------------------------------------------------------------
        # Obj2 additions — auth layer parameters.
        # All are Optional/False-default so existing call sites that don't
        # pass them continue to work without any change.
        # -------------------------------------------------------------------
        auth_enabled: bool = False,
        ledger: Optional["Ledger"] = None,
        chunk_records_map: Optional[Dict[str, List[ChunkRecord]]] = None,
    ) :
        self.base = clone_base_topology(base)
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
        self.content_sequence = build_request_cycle(content_specs)
        self.lmm = lmm
        self.chunking_enabled = chunking_enabled
        self.arrival_window = arrival_window
        self.exploration_window = exploration_window if exploration_window is not None else arrival_window
        requested_access_ids = list(access_node_ids or [])
        self.user_access_ids = requested_access_ids or list(self.base.edge_node_ids) or [self.base.subscriber_id]
        self.edge_ids = list(dict.fromkeys(self.user_access_ids))
        self.primary_edge_id = self.edge_ids[0]
        self.current_round_index = 0
        self.learning_scores: Dict[Tuple[str, str, Tuple[str, ...]], float] = {}
        self.discovered_paths: Dict[Tuple[str, str], Dict[Tuple[str, ...], Tuple[str, List[str], bool]]] = {}#path_exploration_table
        self.path_table: Dict[Tuple[str, str], List[PathRecord]] = {}
        self.cache_node_ids: Dict[Tuple[str, str], Optional[str]] = {}
        self.exploration_open: Dict[Tuple[str, str], bool] = {}
        self.inflight_by_content: Dict[Tuple[str, str], str] = {}
        self.requests: Dict[str, RequestState] = {}
        self.round_user_records: List[Dict[str, float]] = []
        self.measurement_load_events: List[Dict[str, Any]] = []
        self.measurement_cache_events: List[Tuple[str, str]] = []
        self.request_counter = itertools.count()
        self.content_request_counter = 0

        # -------------------------------------------------------------------
        # Obj2: store auth layer state on the scenario instance.
        # -------------------------------------------------------------------
        self.auth_enabled: bool = auth_enabled
        self.ledger: Optional["Ledger"] = ledger
        # chunk_records_map: content_id -> List[ChunkRecord] (indexed by chunk_id)
        self.chunk_records_map: Dict[str, List[ChunkRecord]] = chunk_records_map or {}

        if exploration_snapshot is None:
            self.provider_hops = {
                provider_id: bfs_hop_distances(self.base.adjacency, provider_id)
                for provider_id in self.active_publishers
            }
        else:
            self.provider_hops = clone_provider_hops(exploration_snapshot.provider_hops)

        self.nodes: Dict[str, RuntimeNode] = {
            node_id: RuntimeNode(self, node_id)
            for node_id in self.base.nodes
        }
        self.edges: Dict[str, EdgeRuntimeNode] = {}
        for edge_id in self.edge_ids:
            edge_node = EdgeRuntimeNode(self, edge_id)
            self.edges[edge_id] = edge_node
            self.nodes[edge_id] = edge_node

        if exploration_snapshot is None:
            self.bootstrap_exploration()
        else:
            self.restore_exploration_snapshot(exploration_snapshot)

    def bootstrap_exploration(self):
        loop = EventLoop()
        for edge in self.edges.values():
            for content_id in self.content_specs:
                edge.start_exploration(content_id, loop)
        loop.run()

    def restore_exploration_snapshot(self, snapshot: ExplorationSnapshot) :
        self.discovered_paths = clone_discovered_paths(snapshot.discovered_paths)#path_exploratio_table
        self.path_table = clone_path_table(snapshot.path_table)
        for edge_id in self.edge_ids:
            for content_id in self.content_specs:
                state_id = state_key(edge_id, content_id)
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

    def hop_delay(self, node_id: str, *, data_phase: bool) -> float:
        #del node_id
        return 0.55 if data_phase else 0.4

    def exploration_timeout(self, edge_id: str, content_id: str) -> float:
        max_hops = max(
            (
                self.provider_hops[provider_id].get(edge_id, 0)
                for provider_id in self.content_publishers.get(content_id, self.active_publishers)
            ),
            default=0,
        )
        return max(12.0, self.exploration_window, 3.0 * max_hops)

    def register_discovered_path(
        self,
        edge_id: str,
        content_id: str,
        provider_id: str,
        path: Sequence[str],
        is_cached_provider: bool,
    ) :
        path_list = list(path)
        if len(path_list) < 2:
            return
        path_key = tuple(path_list)
        state_id = state_key(edge_id, content_id)
        current = self.discovered_paths.setdefault(state_id, {}).get(path_key)
        if current is None or (is_cached_provider and not current[2]):
            self.discovered_paths.setdefault(state_id, {})[path_key] = (
                provider_id,
                path_list,
                is_cached_provider,
            )

    def refresh_path_table(self, edge_id: str, content_id: str) :
        state_id = state_key(edge_id, content_id)
        raw_paths = list(self.discovered_paths.get(state_id, {}).values())
        if not raw_paths:
            self.path_table[state_id] = []
            self.cache_node_ids[state_id] = None
            return

        path_records = path_records_from_raw_paths(self.base, content_id, raw_paths)
        apply_learning_scores(
            path_records,
            access_node_id=edge_id,
            content_id=content_id,
            learning_scores=self.learning_scores,
        )  # assigns or modifies weight
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

    def request_path_records(self, selected_paths: Sequence[PathRecord]) -> List[PathRecord]:
        if not selected_paths:
            return []
        if self.chunking_enabled:
            return list(selected_paths)
        return [selected_paths[0]]

    def update_learning_from_path(
        self,
        edge_id: str,
        content_id: str,
        path: Sequence[str],
        content_received: bool,
    ) :
        path_key = tuple(path)
        #search for the path in PT and PET
        record = next(
            (
                item
                for item in self.path_table.get(state_key(edge_id, content_id), [])
                if tuple(item.path) == path_key
            ),
            None,
        )
        if record is None:
            raw_record = self.discovered_paths.get(state_key(edge_id, content_id), {}).get(path_key)
            if raw_record is not None:
                single_record = path_records_from_raw_paths(
                    self.base,
                    content_id,
                    [raw_record],
                )
                record = single_record[0] if single_record else None
        if record is None:
            return
        #calculates reward
        key = learning_key(edge_id, content_id, record.path)
        prior_weight = self.learning_scores.get(key, record.instant_weight)
        reward_signal = config.LEARNING_SIGMA * record.instant_weight * (1.0 if content_received else -1.0)
        updated = ((1.0 - config.LEARNING_LAMBDA) * prior_weight) + (
            config.LEARNING_LAMBDA * (prior_weight + reward_signal)
        )
        self.learning_scores[key] = max(0.01, updated)

    def register_cache_prefix_paths(self, edge_id: str, content_id: str, cache_node_id: str) :
        for record in self.path_table.get(state_key(edge_id, content_id), []):
            if cache_node_id not in record.path:
                continue
            path_prefix = prefix_path(record.path, cache_node_id)
            self.register_discovered_path(
                edge_id,
                content_id,
                cache_node_id,
                path_prefix,
                is_cached_provider=True,
            )

    def start_exploration(self, edge_id: str, content_id: str, event_loop: EventLoop) :
        state_id = state_key(edge_id, content_id)
        self.exploration_open[state_id] = True
        for provider_id in self.content_publishers.get(content_id, self.active_publishers):
            hops_map = self.provider_hops[provider_id]
            source_hops = hops_map.get(edge_id)
            if source_hops is None:
                continue
            for neighbor_id in self.base.adjacency[edge_id]:
                if hops_map.get(neighbor_id, 10**9) >= source_hops:
                    continue
                msg = InterestMessage(
                    content_id=content_id,
                    mode="explore",
                    path=[edge_id, neighbor_id],
                    provider_id=provider_id,
                    current_index=1,
                )
                event_loop.schedule(
                    self.hop_delay(neighbor_id, data_phase=False),
                    self.nodes[neighbor_id].on_interest,
                    msg,
                    event_loop,
                )
        event_loop.schedule(
            self.exploration_timeout(edge_id, content_id),
            self.edges[edge_id].on_exploration_timer,
            content_id,
            event_loop,
        )

    def on_exploration_timer(self, edge_id: str, content_id: str, event_loop: EventLoop) :
        del event_loop
        self.exploration_open[state_key(edge_id, content_id)] = False
        self.refresh_path_table(edge_id, content_id)

    def make_request_id(self, edge_id: str, content_id: str) -> str:
        return f"{edge_id}-{content_id}-r{self.current_round_index}-{next(self.request_counter)}"

    def next_content_id(self) -> str:
        content_id = self.content_sequence[self.content_request_counter % len(self.content_sequence)]
        self.content_request_counter += 1
        return content_id

    def user_arrival_offset(self, user_index: int, user_count: int) -> float:
        if user_count <= 1:
            return 0.0
        window = (self.arrival_window / max(1, user_count)) * user_index
        return window

    def request_timeout(self, selected_paths: Sequence[PathRecord]) -> float:
        if not selected_paths:
            return max(8.0, self.arrival_window / 2.0)
        return max(
            max(record.delay for record in selected_paths) * 1.4,
            self.arrival_window * 0.35,
            8.0,
        )

    def reset_measurement_state(self) :
        self.round_user_records = []
        self.inflight_by_content = {}
        self.requests = {}
        self.measurement_load_events = []
        self.measurement_cache_events = []

    def record_user_result(self, *, hops: float, delay: float, success_rate: float) :
        self.round_user_records.append(make_user_record(hops, delay, success_rate))

    def average_hops_for_paths(self, paths: Sequence[Sequence[str]]) -> float:
        if not paths:
            return 0.0
        return fmean(max(0, len(path) - 1) for path in paths)

    def try_join_inflight_request(
        self,
        state_id: Tuple[str, str],
        user_id: str,
        event_time: float,
    ) -> bool:
        if self.lmm != "LMM-2":
            return False

        inflight_request_id = self.inflight_by_content.get(state_id)
        if inflight_request_id is None:
            return False

        request = self.requests.get(inflight_request_id)
        if request is None or request.completed or request.timed_out:
            return False

        request.user_ids.append(user_id)
        request.user_started_at[user_id] = event_time
        return True

    def clear_inflight_request(self, request: RequestState) :
        state_id = state_key(request.edge_id, request.content_id)
        if self.inflight_by_content.get(state_id) == request.request_id:
            self.inflight_by_content.pop(state_id, None)

    def write_completed_request_metrics(self, request: RequestState) -> float:
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
            self.record_user_result(
                hops=avg_chunk_hops,
                delay=user_delay,
                success_rate=request_success,
            )

        return request_success

    def run_isolated_request(
        self,
        edge_id: str,
        user_id: str,
        content_id: str,
    ) -> Tuple[List[Dict[str, float]], List[Dict[str, Any]], List[Tuple[str, str]]]:
        self.reset_measurement_state()

        loop = EventLoop()
        loop.schedule(
            0.0,
            self.edges[edge_id].on_user_request,
            user_id,
            content_id,
            loop,
        )
        loop.run()

        return (
            list(self.round_user_records),
            [dict(event) for event in self.measurement_load_events],
            list(self.measurement_cache_events),
        )

    def path_delivery_delay(self, path: Sequence[str]) -> float:
        if len(path) < 2:
            return 0.0
        interest_delay = sum(
            self.hop_delay(node_id, data_phase=False)
            for node_id in path[1:]
        )
        data_delay = sum(
            self.hop_delay(node_id, data_phase=True)
            for node_id in reversed(path[:-1])
        )
        return interest_delay + data_delay

    def path_can_deliver(self, path: Sequence[str]) -> bool:
        return all(
            self.base.nodes[node_id].resource_weight() > 0.0
            for node_id in path[1:-1]
        )

    def on_user_request(
        self,
        edge_id: str,
        user_id: str,
        content_id: str,
        event_loop: EventLoop,
    ) :
        state_id = state_key(edge_id, content_id)
        selected_paths = self.request_path_records(self.path_table.get(state_id, []))
        if self.try_join_inflight_request(state_id, user_id, event_loop.time):
            return

        request_id = self.make_request_id(edge_id, content_id)
        request_state = RequestState(
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

        timeout = self.request_timeout(selected_paths)
        event_loop.schedule(timeout, self.edges[edge_id].on_user_timer, request_id, event_loop)

        chunk_count = max(1, len(selected_paths))
        for chunk_id, record in enumerate(selected_paths):
            if len(record.path) < 2:
                continue
            msg = InterestMessage(
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
                self.hop_delay(next_hop_id, data_phase=False),
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

    def on_user_timer(self, request_id: str, event_loop: EventLoop) :
        request = self.requests.get(request_id)
        if request is None or request.completed or request.timed_out:
            return

        request.timed_out = True
        self.clear_inflight_request(request)

        fallback_hops = self.average_hops_for_paths(request.selected_paths)
        for user_id in request.user_ids:
            delay = event_loop.time - request.user_started_at.get(user_id, request.started_at)
            self.record_user_result(
                hops=fallback_hops,
                delay=delay,
                success_rate=0.0,
            )

    def on_path_timer(
        self,
        request_id: str,
        path_key: Tuple[str, ...],
        event_loop: EventLoop,
    ) :
        del event_loop
        request = self.requests.get(request_id)
        if request is None or path_key in request.delivered_paths:
            return
        self.update_learning_from_path(
            request.edge_id,
            request.content_id,
            list(path_key),
            content_received=False,
        )
        self.refresh_path_table(request.edge_id, request.content_id)

    # ------------------------------------------------------------------
    # Obj2 helper: retrieve Merkle proof for a chunk from the ledger tree.
    # ------------------------------------------------------------------
    def _get_merkle_proof_for_chunk(
        self, content_id: str, chunk_id: int
    ) -> Optional[List[str]]:
        """
        Return the Merkle sibling-path proof for *chunk_id* within *content_id*.

        The Merkle tree levels are stored on the ledger object under
        ``_merkle_trees`` by ``publish_content()`` in content.py.  If auth is
        not enabled or the tree is missing, returns None.
        """
        if self.ledger is None:
            return None
        merkle_trees = getattr(self.ledger, "_merkle_trees", {})
        tree_levels = merkle_trees.get(content_id)
        if tree_levels is None:
            return None
        return crypto_auth.get_merkle_proof(tree_levels, chunk_id)

    # ------------------------------------------------------------------
    # Obj2 helper: verify a Merkle proof against the ledger root.
    # Returns True if valid OR if auth is disabled / root not found.
    # Returns False only when auth IS enabled AND proof verification fails.
    # ------------------------------------------------------------------
    def _verify_chunk_proof(
        self, content_id: str, chunk_hash: Optional[str], proof: Optional[list]
    ) -> bool:
        """
        Verify the Merkle proof for a chunk.

        Design: if auth is disabled, or no root is registered (e.g. during
        exploration phase), always return True — no disruption to normal flow.
        Only return False when auth IS on AND the proof is present AND it fails.
        """
        if not self.auth_enabled or self.ledger is None:
            return True
        if not chunk_hash or not proof:
            # Auth is on but message carries no proof — treat as unverifiable;
            # allow through to avoid breaking non-auth messages (e.g. explore mode).
            return True
        try:
            root = self.ledger.get_content_root(content_id)
        except KeyError:
            # Root not registered yet (e.g. content not published via publish_content).
            return True
        return crypto_auth.verify_merkle_proof(chunk_hash, proof, root)

    def on_node_interest(
        self,
        node_id: str,
        msg: InterestMessage,
        event_loop: EventLoop,
    ) :
        if msg.mode == "explore":
            hops_map = self.provider_hops[msg.provider_id]
            current_hops = hops_map.get(node_id)
            if current_hops is None:
                return
            if node_id == msg.provider_id:
                data = DataMessage(
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
                    self.hop_delay(upstream_id, data_phase=True),
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
                next_msg = InterestMessage(
                    content_id=msg.content_id,
                    mode="explore",
                    path=list(msg.path) + [neighbor_id],
                    provider_id=msg.provider_id,
                    current_index=len(msg.path),
                )
                event_loop.schedule(
                    self.hop_delay(neighbor_id, data_phase=False),
                    self.nodes[neighbor_id].on_interest,
                    next_msg,
                    event_loop,
                )
            return

        current_index = msg.current_index
        current_path = list(msg.path)
        # check if a producer or aggregator
        can_serve = (
            node_id in self.content_publisher_sets.get(msg.content_id, self.active_publisher_set)
            or has_cached_content(
                self.base,
                node_id,
                msg.content_id,
                chunking_enabled=self.chunking_enabled,
                chunk_id=msg.chunk_id,
            )
        )
        if can_serve:
            returned_path = current_path[: current_index + 1]
            data = DataMessage(
                content_id=msg.content_id,
                mode="fetch",
                path=returned_path,
                provider_id=node_id,
                current_index=len(returned_path) - 1,
                chunk_id=msg.chunk_id,
                chunk_count=msg.chunk_count,
                request_id=msg.request_id,
                cache_node_id=msg.cache_node_id,
                cache_hit=(
                    node_id
                    not in self.content_publisher_sets.get(
                        msg.content_id,
                        self.active_publisher_set,
                    )
                ),
            )

            # -------------------------------------------------------------------
            # Obj2: attach chunk_hash and merkle_proof to outgoing DataMessage.
            # Surgical addition — only runs when auth_enabled is True.
            # Does NOT modify any existing DataMessage fields.
            # -------------------------------------------------------------------
            if self.auth_enabled:
                records = self.chunk_records_map.get(msg.content_id, [])
                if msg.chunk_id < len(records):
                    record = records[msg.chunk_id]
                    data.chunk_hash = record.chunk_hash
                    data.merkle_proof = self._get_merkle_proof_for_chunk(
                        msg.content_id, msg.chunk_id
                    )

            upstream_id = returned_path[-2]
            event_loop.schedule(
                self.hop_delay(upstream_id, data_phase=True),
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
        next_msg = InterestMessage(
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
            self.hop_delay(next_hop_id, data_phase=False),
            self.nodes[next_hop_id].on_interest,
            next_msg,
            event_loop,
        )

    def on_node_data(
        self,
        node_id: str,
        msg: DataMessage,
        event_loop: EventLoop,
    ) :
        edge_id = msg.path[0] if msg.path else self.primary_edge_id
        if msg.mode == "explore":
            if node_id == edge_id:
                if not self.exploration_open.get(state_key(edge_id, msg.content_id), False):
                    return
                self.register_discovered_path(
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
            next_msg = DataMessage(
                content_id=msg.content_id,
                mode="explore",
                path=list(msg.path),
                provider_id=msg.provider_id,
                current_index=upstream_index,
                chunk_id=msg.chunk_id,
                chunk_count=msg.chunk_count,
            )
            event_loop.schedule(
                self.hop_delay(upstream_id, data_phase=True),
                self.nodes[upstream_id].on_data,
                next_msg,
                event_loop,
            )
            return

        if self.lmm == "LMM-2" and msg.cache_node_id == node_id:
            # -------------------------------------------------------------------
            # Obj2: verify Merkle proof BEFORE caching (cache-poisoning defence).
            # If auth is enabled and proof is invalid, DROP the data message —
            # do not cache, log the rejection, and return.
            # If auth is disabled or no root registered, proceed normally.
            # -------------------------------------------------------------------
            if not self._verify_chunk_proof(msg.content_id, msg.chunk_hash, msg.merkle_proof):
                print(
                    f"[AUTH] Cache-store REJECTED: invalid Merkle proof "
                    f"for content={msg.content_id!r} chunk={msg.chunk_id} "
                    f"at cache-node={node_id!r}. Message dropped."
                )
                # Treat as failed delivery: don't store, don't forward.
                # The request will time out naturally -> success_rate = 0.
                return

            store_in_cache(
                self.base,
                node_id,
                self.content_specs[msg.content_id],
                chunking_enabled=self.chunking_enabled,
                chunk_id=msg.chunk_id,
                chunk_count=msg.chunk_count,
            )
            if has_cached_content(
                self.base,
                node_id,
                msg.content_id,
                chunking_enabled=self.chunking_enabled,
                chunk_id=msg.chunk_id,
            ):
                self.measurement_cache_events.append((node_id, msg.content_id))
            if not self.chunking_enabled:
                self.register_discovered_path(
                    edge_id,
                    msg.content_id,
                    node_id,
                    msg.path[: msg.current_index + 1],
                    is_cached_provider=True,
                )

        if node_id == edge_id:
            user_success = path_success(self.base, msg.path, exclude_terminal=False)
            user_hops = max(0, len(msg.path) - 1)

            # -------------------------------------------------------------------
            # Obj2: verify Merkle proof at the final consumer (edge node).
            # If auth is enabled and proof is invalid, DROP — skip marking
            # this chunk as delivered so the request times out -> success_rate=0.
            # This is the cache-poisoning detection at the consumer side.
            # -------------------------------------------------------------------
            if not self._verify_chunk_proof(msg.content_id, msg.chunk_hash, msg.merkle_proof):
                print(
                    f"[AUTH] Consumer delivery REJECTED: invalid Merkle proof "
                    f"for content={msg.content_id!r} chunk={msg.chunk_id} "
                    f"at edge={node_id!r}. Chunk dropped."
                )
                # Do NOT mark chunk as delivered. Request times out = failure in metrics.
                return

            if not (self.chunking_enabled and msg.cache_hit):
                self.register_discovered_path(
                    edge_id,
                    msg.content_id,
                    msg.provider_id,
                    msg.path,
                    is_cached_provider=msg.cache_hit,
                )
            #calculates reward for the path if data received -> calculates learning scores
            self.update_learning_from_path(
                edge_id,
                msg.content_id,
                msg.path,
                content_received=True,
            )
            self.refresh_path_table(edge_id, msg.content_id)#applies learning score and updates PT & updates cacheID
            
            #simulates node resources consumption
            touch_path_resources(
                self.base,
                msg.path,
                load_scale=1.0,
                cache_hit=msg.cache_hit,
                content_id=msg.content_id,
                chunking_enabled=self.chunking_enabled,
                chunk_id=msg.chunk_id,
            )
            self.measurement_load_events.append(
                {
                    "path": list(msg.path),
                    "cache_hit": bool(msg.cache_hit),
                    "content_id": msg.content_id,
                }
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
                    state_id = state_key(request.edge_id, request.content_id)
                    self.clear_inflight_request(request)
                    request_success = self.write_completed_request_metrics(request)

                    if self.lmm == "LMM-2" and not self.chunking_enabled:
                        cache_node_id = self.cache_node_ids.get(state_id)
                        if (
                            cache_node_id is not None
                            and request_success >= 0.55
                            and has_cached_content(
                                self.base,
                                cache_node_id,
                                msg.content_id,
                            )
                        ):
                            self.register_cache_prefix_paths(edge_id, msg.content_id, cache_node_id)
                            self.refresh_path_table(edge_id, msg.content_id)
            return

        # if not edge id, forward to next node
        upstream_index = msg.current_index - 1
        if upstream_index < 0:
            return
        upstream_id = msg.path[upstream_index]
        next_msg = DataMessage(
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
            # Obj2: propagate auth fields through the forwarding chain.
            chunk_hash=msg.chunk_hash,
            merkle_proof=msg.merkle_proof,
        )
        event_loop.schedule(
            self.hop_delay(upstream_id, data_phase=True),
            self.nodes[upstream_id].on_data,
            next_msg,
            event_loop,
        )

    def run_round(self, round_index: int, num_users: int) -> Dict[str, float]:
        self.current_round_index = round_index
        if num_users <= 0 or not self.user_access_ids:
            return empty_summary()

        access_offset = round_index % len(self.user_access_ids)
        ordered_edge_ids = list(self.user_access_ids[access_offset:]) + list(self.user_access_ids[:access_offset])
        if len(ordered_edge_ids) < num_users:
            round_edge_ids = expand_user_edge_nodes(ordered_edge_ids, num_users)
        else:
            round_edge_ids = ordered_edge_ids[:num_users]
        user_count = len(round_edge_ids)
        self.reset_measurement_state()

        # Multi-user rounds must replay in one continuation so later users can
        # observe in-flight aggregation and any cache state created earlier.

        loop = EventLoop()
        for user_index, edge_id in enumerate(round_edge_ids):
            user_id = f"U{round_index + 1}_{user_index + 1}"
            content_id = self.next_content_id()
            loop.schedule(
                self.user_arrival_offset(user_index, user_count),
                self.edges[edge_id].on_user_request,
                user_id,
                content_id,
                loop,
            )

        loop.run()
        return summarize_user_metrics(self.round_user_records)


def build_exploration_snapshot(
    base: BaseTopology,
    active_publishers: Sequence[str],
    access_node_ids: Optional[Sequence[str]],
    content_specs: Sequence[ContentSpec],
    exploration_window: float,
    content_publishers: Optional[Dict[str, Sequence[str]]] = None,
) -> ExplorationSnapshot:
    scenario = NetworkScenario(
        base=base,
        active_publishers=active_publishers,
        access_node_ids=access_node_ids,
        content_specs=content_specs,
        content_publishers=content_publishers,
        lmm="LMM-1",
        chunking_enabled=False,#does not matter
        arrival_window=exploration_window,
        exploration_window=exploration_window,
        # auth not needed during path exploration
        auth_enabled=False,
    )
    return ExplorationSnapshot(
        provider_hops= clone_provider_hops(scenario.provider_hops),
        discovered_paths= clone_discovered_paths(scenario.discovered_paths),
        path_table= clone_path_table(scenario.path_table),
    )


def run_dynamic_scenario(
    base: BaseTopology,
    active_publishers: Sequence[str],
    access_node_ids: Sequence[str],
    num_users: int,
    lmm: str,
    chunking_enabled: bool,
    arrival_window: float,
    content_specs: Sequence[ContentSpec],
    content_publishers: Optional[Dict[str, Sequence[str]]] = None,
    exploration_window: Optional[float] = None,
    exploration_snapshot: Optional[ExplorationSnapshot] = None,
    # Obj2: auth layer parameters (all optional, default to off).
    auth_enabled: bool = False,
    ledger: Optional["Ledger"] = None,
    chunk_records_map: Optional[Dict[str, List[ChunkRecord]]] = None,
) -> Dict[str, float]:
    if not active_publishers or num_users <= 0 or not content_specs:
        return empty_summary()

    scenario = NetworkScenario(
        base=base,
        active_publishers=active_publishers,
        access_node_ids=access_node_ids,
        content_specs=content_specs,
        content_publishers=content_publishers,
        lmm=lmm,
        chunking_enabled=chunking_enabled,
        arrival_window=arrival_window,
        exploration_window=exploration_window,
        exploration_snapshot=exploration_snapshot,
        auth_enabled=auth_enabled,
        ledger=ledger,
        chunk_records_map=chunk_records_map,
    )
    round_summaries: List[Dict[str, float]] = []
    #recovery_multiplier = max(0.6, min(1.6, arrival_window / 40.0))
    total_rounds = config.WARMUP_ROUNDS + config.MEASUREMENT_ROUNDS

    for round_index in range(total_rounds):
        round_summary = scenario.run_round(round_index, num_users)
        if round_index >= config.WARMUP_ROUNDS:
            round_summaries.append(round_summary)

        # recover_topology_after_round(
        #     scenario.base,
        #     recovery_multiplier=recovery_multiplier,
        # )

    return summarize_rounds(round_summaries)


def simulate_lmm1(
    base: BaseTopology,
    active_publishers: Sequence[str],
    access_node_ids: Sequence[str],
    num_users: int,
    content_specs: Sequence[ContentSpec],
    content_publishers: Optional[Dict[str, Sequence[str]]] = None,
    chunking_enabled: bool = False,
    arrival_window: float = 40.0,
    exploration_window: Optional[float] = None,
    exploration_snapshot: Optional[ExplorationSnapshot] = None,
    auth_enabled: bool = False,
    ledger: Optional["Ledger"] = None,
    chunk_records_map: Optional[Dict[str, List[ChunkRecord]]] = None,
) -> Dict[str, float]:
    return run_dynamic_scenario(
        base,
        active_publishers,
        access_node_ids,
        num_users,
        lmm="LMM-1",
        chunking_enabled=chunking_enabled,
        arrival_window=arrival_window,
        content_specs=content_specs,
        content_publishers=content_publishers,
        exploration_window=exploration_window,
        exploration_snapshot=exploration_snapshot,
        auth_enabled=auth_enabled,
        ledger=ledger,
        chunk_records_map=chunk_records_map,
    )


def simulate_lmm2(
    base: BaseTopology,
    active_publishers: Sequence[str],
    access_node_ids: Sequence[str],
    num_users: int,
    content_specs: Sequence[ContentSpec],
    content_publishers: Optional[Dict[str, Sequence[str]]] = None,
    chunking_enabled: bool = False,
    arrival_window: float = 40.0,
    exploration_window: Optional[float] = None,
    exploration_snapshot: Optional[ExplorationSnapshot] = None,
    auth_enabled: bool = False,
    ledger: Optional["Ledger"] = None,
    chunk_records_map: Optional[Dict[str, List[ChunkRecord]]] = None,
) -> Dict[str, float]:
    return run_dynamic_scenario(
        base,
        active_publishers,
        access_node_ids,
        num_users,
        lmm="LMM-2",
        chunking_enabled=chunking_enabled,
        arrival_window=arrival_window,
        content_specs=content_specs,
        content_publishers=content_publishers,
        exploration_window=exploration_window,
        exploration_snapshot=exploration_snapshot,
        auth_enabled=auth_enabled,
        ledger=ledger,
        chunk_records_map=chunk_records_map,
    )
