#!/usr/bin/env python3
"""
Enhanced Multipath Content Delivery Network Simulator
WITH RESOURCE-AWARE NODE WEIGHTS

- Every node is a Router with battery, latency, and variable cache size
- Node weights calculated using all resource metrics
- Based on: LMM (Reliable Multipath and Multisource Content Transmission and Caching for ICIoT)
- IEEE IoT Journal 2025
"""

import os
import random
import datetime
import collections
import csv
import networkx as nx
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# ===================== RESOURCE METRICS CONSTANTS =====================

# Battery constants
BATTERY_MIN = 0.0
BATTERY_MAX = 1.0
BATTERY_THRESHOLD = 0.2  # Minimum required for caching/transmission
BATTERY_DRAIN_CACHE_HIT = 0.02  # Battery drain per cache hit
BATTERY_DRAIN_TRANSMISSION = 0.01  # Battery drain per transmission
BATTERY_DRAIN_CACHE_MISS = 0.015  # Battery drain per cache miss

# Latency constants
LATENCY_MIN_MS = 0.1  # milliseconds
LATENCY_MAX_MS = 0.5  # milliseconds

# Cache size constants
CACHE_SIZE_MIN = 5
CACHE_SIZE_MAX = 50

# CPU/Processing capacity
CPU_THRESHOLD = 0.1

# Memory (RAM) constants
MEMORY_MIN = 0.0
MEMORY_MAX = 1.0
MEMORY_THRESHOLD = 0.15

# Thermal (Temperature) constants
THERMAL_MIN = 20.0  # Celsius
THERMAL_MAX = 80.0  # Celsius
THERMAL_THRESHOLD = 70.0  # Optimal threshold

# ===================== NORMALIZATION FUNCTIONS =====================

def normalize_value(value, min_val, max_val):
    """Normalize a value to [0, 1] range"""
    if max_val == min_val:
        return 0.5
    return np.clip((value - min_val) / (max_val - min_val), 0, 1)

def normalize_battery(battery_level):
    """Normalize battery level - higher is better"""
    return normalize_value(battery_level, BATTERY_MIN, BATTERY_MAX)

def normalize_latency(latency_ms):
    """Normalize latency - lower is better, so invert it"""
    normalized = normalize_value(latency_ms, LATENCY_MIN_MS, LATENCY_MAX_MS)
    return 1.0 - normalized  # low latency -> high weight

def normalize_cache_size(cache_size):
    """Normalize cache size - higher is better"""
    return normalize_value(cache_size, CACHE_SIZE_MIN, CACHE_SIZE_MAX)

def normalize_cpu(cpu_usage):
    """Normalize CPU - lower usage is better, so invert it"""
    normalized = normalize_value(cpu_usage, 0, 1)
    return 1.0 - normalized

def normalize_memory(memory_available):
    """Normalize memory - higher is better"""
    return normalize_value(memory_available, MEMORY_MIN, MEMORY_MAX)

def normalize_thermal(temperature):
    """Normalize thermal - closer to threshold is better"""
    distance_from_optimal = abs(temperature - THERMAL_THRESHOLD)
    return max(0, 1.0 - (distance_from_optimal / (THERMAL_MAX - THERMAL_MIN)))

# ===================== ENHANCED MULTIPATH CLASSES =====================

class ResourceMetrics:
    """Represents resource metrics of a router"""
    def __init__(self, battery=1.0, latency_ms=None, cache_size=None,
                 cpu_usage=0.3, memory_available=0.8, temperature=30.0):
        self.battery = battery
        self.latency_ms = latency_ms or random.uniform(LATENCY_MIN_MS, LATENCY_MAX_MS)
        self.cache_size = cache_size or random.randint(CACHE_SIZE_MIN, CACHE_SIZE_MAX)
        self.cpu_usage = cpu_usage
        self.memory_available = memory_available
        self.temperature = temperature

        self.battery_threshold = BATTERY_THRESHOLD
        self.cpu_threshold = CPU_THRESHOLD
        self.memory_threshold = MEMORY_THRESHOLD
        self.thermal_threshold = THERMAL_THRESHOLD

    def drain_battery(self, amount):
        self.battery = max(BATTERY_MIN, self.battery - amount)

    def update_cpu(self):
        self.cpu_usage = max(0, min(1.0, self.cpu_usage + random.uniform(-0.1, 0.1)))

    def update_memory(self):
        self.memory_available = max(0, min(1.0, self.memory_available + random.uniform(-0.05, 0.05)))

    def update_thermal(self):
        activity_factor = random.uniform(0, 1)
        self.temperature += activity_factor * random.uniform(-2, 5)
        self.temperature = np.clip(self.temperature, THERMAL_MIN, THERMAL_MAX)

    def get_normalized_metrics(self):
        return {
            'battery': normalize_battery(self.battery),
            'latency': normalize_latency(self.latency_ms),
            'cache_size': normalize_cache_size(self.cache_size),
            'cpu': normalize_cpu(self.cpu_usage),
            'memory': normalize_memory(self.memory_available),
            'thermal': normalize_thermal(self.temperature)
        }

class PathExplorationEntry:
    """Represents an entry in the path exploration table"""
    def __init__(self, name, node_id_set, path_weight, lifetime):
        self.name = name
        self.node_id_set = node_id_set.copy()
        self.path_weight = path_weight
        self.lifetime = lifetime
        self.creation_time = datetime.datetime.now()

        self.connection_duration = 0.0
        self.pending_requests = 0
        self.packet_loss_rate = 0.0
        self.response_time = 0.0

    def is_expired(self):
        return datetime.datetime.now() > self.creation_time + datetime.timedelta(seconds=self.lifetime)

class PathTableEntry:
    """Represents an entry in the path table (selected paths)"""
    def __init__(self, name, node_id_set, lifetime):
        self.name = name
        self.node_id_set = node_id_set.copy()
        self.lifetime = lifetime
        self.creation_time = datetime.datetime.now()
        self.path_weight = 0.0
        self.is_active = True

    def is_expired(self):
        return datetime.datetime.now() > self.creation_time + datetime.timedelta(seconds=self.lifetime)

class EdgeLink:
    """Represents a link between two nodes with dynamic weight"""
    def __init__(self, source, destination):
        self.source = source
        self.destination = destination
        self.weight = random.uniform(0.5, 1.0)
        self.connection_duration = random.uniform(5, 60)
        self.packet_loss_rate = random.uniform(0.0, 0.1)
        self.pending_requests = 0
        self.response_time = random.uniform(0.01, 0.5)
        self.last_update = datetime.datetime.now()

    def update_weight(self):
        current_time = datetime.datetime.now()
        self.weight = max(0.1, self.weight + random.uniform(-0.1, 0.1))
        self.packet_loss_rate = max(0.0, min(1.0, self.packet_loss_rate + random.uniform(-0.02, 0.02)))
        self.pending_requests = max(0, self.pending_requests - random.randint(0, 3))
        self.response_time = max(0.01, self.response_time + random.uniform(-0.05, 0.05))
        self.last_update = current_time

    def get_normalized_weight(self):
        return np.clip(self.weight, 0, 1)

# ===================== BASE CLASSES =====================

class Node:
    def __init__(self, name):
        self.name = name
        self.fib = {}
        self.pit = {}
        self.cs = []

class InterestPacket:
    def __init__(self, name):
        self.name = name
        self.nonce = random.randint(1000, 9999)
        self.visited = set()
        self.path = []
        self.original_hop_count = 0
        self.actual_hop_count = 0

class DataPacket:
    def __init__(self, name, content):
        self.name = name
        self.content = content

class ContentIDManager:
    _content_id_map = {}

    @classmethod
    def initialize_index(cls, routers):
        content_id = 100
        for router in routers:
            if hasattr(router, 'contents'):
                for content_name in router.contents.keys():
                    if content_name not in cls._content_id_map:
                        cls._content_id_map[content_name] = content_id
                        content_id += 1

    @classmethod
    def get_unique_id(cls, content_name):
        return cls._content_id_map.get(content_name, None)

# ===================== ROUTER CLASS =====================

class Router(Node):
    """Router with resource-aware node weight calculation"""
    TOP_N_POPULAR = 5

    def __init__(self, name, caching_policy='LRU', alpha=0.9):
        super().__init__(name)
        self.caching_policy = caching_policy
        self.alpha = alpha

        # Resource metrics
        self.resources = ResourceMetrics()

        # Content management
        self.contents = self._generate_contents()
        self.popularity_table = pd.DataFrame(columns=['Content Name', 'R_count', 'Popularity', 'Rank', 'Feedback'])

        self.cache_frequency = collections.defaultdict(int)
        self.cache_access_times = {}
        self.connections = []
        self.fib = {}

        # Multipath tracking
        self.path_exploration_table = []
        self.path_table = []
        self.edge_links = {}
        self.caching_node_id = {}
        self.neighbors = []  # IMPORTANT (needed by add_edge_link)

        self.reset()
        self.save_fib()

    def _generate_contents(self):
        contents = {}
        for i in range(50):
            content_name = f"{self.name.lower()}_content_{i+1}"
            contents[content_name] = f"Data from {content_name}"
        return contents

    def reset(self):
        self.cache_hits = 0
        self.publisher_hits = 0
        self.requests_served_from_cache = 0
        self.requests_served_from_publisher = 0
        self.cache_evictions = 0
        self.cache_access_times = {}
        self.cache_frequency = collections.defaultdict(int)
        self.total_cache_access_time = 0
        self.total_requests = 0
        self.content_popularity = collections.defaultdict(int)
        self.cache_ttl = {}
        self.cs = []
        self.pit = {}

    def calculate_node_weight(self):
        # Update dynamic resources
        self.resources.update_cpu()
        self.resources.update_memory()
        self.resources.update_thermal()

        metrics = self.resources.get_normalized_metrics()
        weights = {}

        # Battery
        weights['battery'] = metrics['battery'] if self.resources.battery > self.resources.battery_threshold else 0.0

        # Latency (already inverted)
        weights['latency'] = metrics['latency']

        # Cache size
        weights['cache_size'] = (self.resources.cache_size / CACHE_SIZE_MAX) * metrics['cache_size']

        # CPU (inverted)
        weights['cpu'] = metrics['cpu'] if self.resources.cpu_usage < self.resources.cpu_threshold else 0.0

        # Memory
        weights['memory'] = metrics['memory'] if self.resources.memory_available > self.resources.memory_threshold else 0.0

        # Thermal
        weights['thermal'] = metrics['thermal']

        node_weight = (
            0.25 * weights['battery'] +
            0.25 * weights['latency'] +
            0.25 * weights['cache_size'] +
            0.10 * weights['cpu'] +
            0.10 * weights['memory'] +
            0.05 * weights['thermal']
        )

        return np.clip(node_weight, 0, 1), weights, metrics

    def add_edge_link(self, destination_router):
        """Create a bidirectional edge link to another router."""
        if destination_router not in self.neighbors:
            edge_link = EdgeLink(self.name, destination_router.name)
            self.edge_links[destination_router.name] = edge_link
            self.neighbors.append(destination_router)

            reverse_edge_link = EdgeLink(destination_router.name, self.name)
            destination_router.edge_links[self.name] = reverse_edge_link
            if self not in destination_router.neighbors:
                destination_router.neighbors.append(self)

    def multipath_exploration(self, content_name, exploration_timeout=10):
        interest_packet = InterestPacket(content_name)
        interest_packet.visited.add(self.name)
        node_weight, _, _ = self.calculate_node_weight()

        exploration_entry = PathExplorationEntry(
            name=content_name,
            node_id_set=[self.name],
            path_weight=node_weight,
            lifetime=exploration_timeout
        )
        self.path_exploration_table.append(exploration_entry)
        return exploration_entry

    def multipath_selection(self, content_name, threshold_weight=0.3):
        relevant_entries = [e for e in self.path_exploration_table if e.name == content_name and not e.is_expired()]
        if not relevant_entries:
            return []

        weighted_entries = []
        for entry in relevant_entries:
            d_t = self._normalize_connection_duration(entry)
            q_t = self._normalize_pending_requests(entry)
            l_t = self._normalize_packet_loss(entry)
            o_t = self._normalize_response_time(entry)
            entry.path_weight = (d_t + q_t + l_t + o_t) / 4.0
            weighted_entries.append(entry)

        weighted_entries.sort(key=lambda x: x.path_weight, reverse=True)
        selected = [e for e in weighted_entries if e.path_weight >= threshold_weight]

        for entry in selected:
            path_entry = PathTableEntry(name=entry.name, node_id_set=entry.node_id_set, lifetime=entry.lifetime)
            path_entry.path_weight = entry.path_weight
            self.path_table.append(path_entry)

        return selected

    def _normalize_connection_duration(self, entry):
        if entry.connection_duration == 0:
            return 0.5
        return min(1.0, entry.connection_duration / 60.0)

    def _normalize_pending_requests(self, entry):
        if entry.pending_requests == 0:
            return 1.0
        return min(1.0, 1.0 / (1.0 + entry.pending_requests))

    def _normalize_packet_loss(self, entry):
        return max(0.0, 1.0 - entry.packet_loss_rate)

    def _normalize_response_time(self, entry):
        if entry.response_time == 0:
            return 1.0
        return min(1.0, 0.5 / entry.response_time)

    def update_popularity(self, content_name, feedback=None):
        if content_name in self.popularity_table['Content Name'].values:
            idx = self.popularity_table[self.popularity_table['Content Name'] == content_name].index[0]
            current_popularity = float(self.popularity_table.at[idx, 'Popularity']) if pd.notna(self.popularity_table.at[idx, 'Popularity']) else 0.0
            r_count = int(self.popularity_table.at[idx, 'R_count']) + 1 if pd.notna(self.popularity_table.at[idx, 'R_count']) else 1

            feedback_weights = {
                'highly_like': 1.5, 'like': 1.2, 'neutral': 1.0,
                'dislike': 0.8, 'highly_dislike': 0.5
            }
            adjustment = feedback_weights.get(feedback, 1.0)
            new_popularity = self.alpha * current_popularity + (1 - self.alpha) * r_count * adjustment

            self.popularity_table.at[idx, 'R_count'] = r_count
            self.popularity_table.at[idx, 'Popularity'] = new_popularity
            self.popularity_table.at[idx, 'Feedback'] = feedback or 'None'
        else:
            new_entry = {
                'Content Name': content_name,
                'R_count': 1,
                'Popularity': (1 - self.alpha),
                'Rank': None,
                'Feedback': feedback or 'None'
            }
            self.popularity_table = pd.concat([self.popularity_table, pd.DataFrame([new_entry])], ignore_index=True)

        self.rank_content()

    def rank_content(self):
        if len(self.popularity_table) == 0:
            return
        self.popularity_table['Popularity'] = pd.to_numeric(self.popularity_table['Popularity'], errors='coerce').fillna(0.0)
        self.popularity_table['Rank'] = self.popularity_table['Popularity'].rank(method='min', ascending=False).astype(int)
        self.popularity_table.sort_values(by='Rank', inplace=True)

    def receive_interest(self, interest_packet, subscriber):
        # loop protection
        if self.name in interest_packet.visited:
            return

        self.total_requests = getattr(self, 'total_requests', 0) + 1
        interest_packet.actual_hop_count += 1
        interest_packet.path.append(self.name)
        interest_packet.visited.add(self.name)

        if interest_packet.name not in self.pit:
            self.pit[interest_packet.name] = subscriber.name

        # Cache hit
        if interest_packet.name in self.cs:
            self.cache_hits += 1
            self.requests_served_from_cache += 1
            self.resources.drain_battery(BATTERY_DRAIN_CACHE_HIT)
            data_packet = DataPacket(name=interest_packet.name, content=interest_packet.name)
            subscriber.receive_data(data_packet)
            return

        # Cache miss
        self.publisher_hits += 1
        self.resources.drain_battery(BATTERY_DRAIN_CACHE_MISS)

        next_hops = self.fib.get(interest_packet.name, [])
        if not isinstance(next_hops, list):
            next_hops = [next_hops]

        for nh in next_hops:
            if nh and nh not in interest_packet.visited and isinstance(nh, Router):
                nh.receive_interest(interest_packet, subscriber)
                return

    def receive_data(self, data_packet):
        current_time = datetime.datetime.now()

        # Expire old
        for content, expiry_time in list(self.cache_ttl.items()):
            if current_time > expiry_time:
                if content in self.cs:
                    self.cs.remove(content)
                self.cache_ttl.pop(content, None)

        ttl = current_time + datetime.timedelta(minutes=5)
        self.cache_ttl[data_packet.name] = ttl

        # Evict if full
        if len(self.cs) >= self.resources.cache_size:
            self.cache_evictions += 1
            if self.caching_policy == 'LRU' and self.cache_access_times:
                lru = min(self.cache_access_times, key=self.cache_access_times.get)
                if lru in self.cs:
                    self.cs.remove(lru)
                self.cache_access_times.pop(lru, None)
            elif self.caching_policy == 'LFU' and self.cache_frequency:
                lfu = min(self.cache_frequency, key=self.cache_frequency.get)
                if lfu in self.cs:
                    self.cs.remove(lfu)
                self.cache_frequency.pop(lfu, None)
            elif self.caching_policy == 'FIFO' and self.cs:
                self.cs.pop(0)
            elif self.caching_policy == 'MRU' and self.cache_access_times:
                mru = max(self.cache_access_times, key=self.cache_access_times.get)
                if mru in self.cs:
                    self.cs.remove(mru)
                self.cache_access_times.pop(mru, None)

        if data_packet.name not in self.cs:
            self.cs.append(data_packet.name)

        if self.caching_policy in ['LRU', 'MRU']:
            self.cache_access_times[data_packet.name] = current_time
        elif self.caching_policy == 'LFU':
            self.cache_frequency[data_packet.name] += 1

        self.update_popularity(data_packet.name)

    def save_fib(self):
        fib_dir = os.path.join('Output', 'FIB', self.name)
        os.makedirs(fib_dir, exist_ok=True)
        with open(os.path.join(fib_dir, 'fib.csv'), mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Name", "ID", "Next Hop"])
            for name, next_hop in self.fib.items():
                content_id = ContentIDManager.get_unique_id(name)
                if isinstance(next_hop, list):
                    for nh in next_hop:
                        writer.writerow([name, content_id, nh.name if nh else "None"])
                else:
                    writer.writerow([name, content_id, next_hop.name if next_hop else "None"])

# ===================== SUBSCRIBER CLASS =====================

class Subscriber(Node):
    def __init__(self, name):
        super().__init__(name)
        self.active = True
        self.requests_sent = 0
        self.data_received = 0
        self.satisfaction = []
        self.connected_router = None
        self.last_interest_packet = None

    def send_interest(self, interest_packet, router):
        if isinstance(router, Router):
            self.requests_sent += 1
            router.receive_interest(interest_packet, self)

    def receive_data(self, data_packet):
        self.data_received += 1
        feedback = random.choice(['like', 'dislike', 'neutral', 'highly_like', 'highly_dislike'])
        self.satisfaction.append(feedback)
        if self.connected_router is not None:
            self.connected_router.update_popularity(data_packet.name, feedback=feedback)

# ===================== NETWORK SETUP =====================

def setup_network_with_multipaths(num_routers=5, num_subscribers=1):
    """Setup network with variable number of consumers (subscribers) and round-robin connections."""
    print(f"\n=== NETWORK CONFIGURATION ===")
    print(f"Routers (with resources): {num_routers}")
    print(f"Consumers/Subscribers: {num_subscribers}")
    print("================================\n")

    routers = [Router(f'Router{i+1}') for i in range(num_routers)]
    subscribers = [Subscriber(f"Subscriber{i+1}") for i in range(num_subscribers)]

    # round-robin connection
    for i, sub in enumerate(subscribers):
        sub.connected_router = routers[i % num_routers]
        print(f"Subscriber '{sub.name}' connected to '{sub.connected_router.name}'")
    print()

    ContentIDManager.initialize_index(routers)

    all_contents = []
    for router in routers:
        all_contents.extend(router.contents.keys())
    print(f"Total content items in network: {len(all_contents)}\n")

    # Setup multipath FIB (simple forward edges to next 3 routers)
    for i, router in enumerate(routers):
        next_hops = []
        for j in range(i + 1, min(i + 4, num_routers)):
            next_hops.append(routers[j])
            router.add_edge_link(routers[j])
        if not next_hops:
            next_hops = [routers[(i + 1) % num_routers]]

        for content in all_contents:
            router.fib[content] = next_hops

    print(f"Created network with {num_routers} resource-aware routers.\n")
    return routers, subscribers

def build_graph_from_network(routers, subscribers):
    """Create a NetworkX graph using router FIBs and subscriber connections."""
    G = nx.DiGraph()

    for r in routers:
        G.add_node(r.name)

    for s in subscribers:
        G.add_node(s.name)

    for r in routers:
        for _, next_hops in r.fib.items():
            if isinstance(next_hops, list):
                for nh in next_hops:
                    if nh:
                        G.add_edge(r.name, nh.name)
            else:
                nh = next_hops
                if nh:
                    G.add_edge(r.name, nh.name)

    for s in subscribers:
        if s.connected_router is not None:
            G.add_edge(s.name, s.connected_router.name)

    return G

def plot_network_with_resources(routers, subscribers):
    """Plot network topology with resource information (supports N subscribers)."""
    G = build_graph_from_network(routers, subscribers)

    # Node colors
    for r in routers:
        b = r.resources.battery
        if b > 0.7:
            G.nodes[r.name]['color'] = 'lightgreen'
        elif b > 0.4:
            G.nodes[r.name]['color'] = 'lightyellow'
        else:
            G.nodes[r.name]['color'] = 'lightcoral'

    for s in subscribers:
        G.nodes[s.name]['color'] = 'salmon'

    colors = [G.nodes[n].get('color', 'gray') for n in G.nodes]
    pos = nx.spring_layout(G, k=2, iterations=50, seed=42)

    plt.figure(figsize=(16, 10))
    nx.draw_networkx_nodes(G, pos, node_color=colors, node_size=1200, alpha=0.9)
    nx.draw_networkx_edges(G, pos, width=2.0, alpha=0.7, arrows=False)
    nx.draw_networkx_labels(G, pos, font_size=10, font_weight="bold")

    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='lightgreen', label='High Battery (>70%)'),
        Patch(facecolor='lightyellow', label='Medium Battery (40-70%)'),
        Patch(facecolor='lightcoral', label='Low Battery (<40%)'),
        Patch(facecolor='salmon', label=f'Subscribers ({len(subscribers)})')
    ]
    plt.legend(handles=legend_elements, loc='upper left', fontsize=12)
    plt.title(f"Resource-Aware Multipath Network\n({len(routers)} Routers, {len(subscribers)} Subscribers)",
              fontsize=14, fontweight='bold')
    plt.axis('off')
    plt.tight_layout()

    os.makedirs('output', exist_ok=True)
    plt.savefig('output/network_topology_resources.png', dpi=300, bbox_inches='tight')
    print("Network topology saved as 'output/network_topology_resources.png'\n")
    plt.close()

# ===================== PATH DISCOVERY + WEIGHTS =====================

def discover_all_paths(subscriber, routers, network_graph):
    """Discover all possible paths from subscriber to each router (simple-path search)."""
    all_paths = {}
    for router in routers:
        try:
            paths = list(nx.all_simple_paths(network_graph, source=subscriber.name, target=router.name, cutoff=10))
            if paths:
                all_paths[router.name] = paths
                print(f"  ✓ Router {router.name}: {len(paths)} path(s) found")
        except nx.NetworkXNoPath:
            print(f"  ✗ Router {router.name}: No path found")
            continue
    return all_paths

def calculate_path_weight(path, routers_dict):
    """Calculate path weight using router resources (no missing attributes)."""
    if not path or len(path) < 2:
        return 0.0

    hop_weight = 1.0 / len(path)

    resource_weight = 0.0
    valid = 0
    for node_name in path:
        if node_name in routers_dict:
            r = routers_dict[node_name]
            battery_quality = r.resources.battery
            latency_quality = 1.0 - min(1.0, r.resources.latency_ms / LATENCY_MAX_MS)
            cache_quality = r.resources.cache_size / float(CACHE_SIZE_MAX)
            router_quality = (battery_quality * 0.5 + latency_quality * 0.3 + cache_quality * 0.2)
            resource_weight += router_quality
            valid += 1

    avg_resource = (resource_weight / valid) if valid > 0 else 0.5
    path_weight = (hop_weight * 0.4 + avg_resource * 0.6)
    return max(0.0, min(1.0, path_weight))

def filter_paths_by_weight(all_paths, routers_dict, top_k=3):
    """Filter paths by weight, keeping only top K paths per router."""
    weighted_paths = {}
    total_selected = 0

    for router_id, paths in all_paths.items():
        path_weights = []
        for path in paths:
            w = calculate_path_weight(path, routers_dict)
            path_weights.append((w, path))

        path_weights.sort(key=lambda x: x[0], reverse=True)
        selected = path_weights[:top_k]
        weighted_paths[router_id] = selected
        total_selected += len(selected)

        print(f"  Router {router_id}: Selected {len(selected)} path(s)")
        for w, p in selected:
            print(f"   - Weight: {w:.4f}, Hops: {len(p)-1}")

    return weighted_paths

# ===================== MULTIPATH TRANSMISSION =====================

def execute_multipath_transmission(best_paths, routers, subscriber, policy, iteration, G, num_routers):
    """Execute multipath transmission using weighted filtered paths (simple dispatch)."""
    for r in routers:
        r.caching_policy = policy

    for r in routers:
        r.calculate_node_weight()

    # choose content
    all_contents = []
    for r in routers:
        all_contents.extend(r.contents.keys())
    if not all_contents:
        return

    if random.random() > 0.95:
        return

    content = random.choice(all_contents)
    interest_packet = InterestPacket(name=content)

    # default route
    start_router = subscriber.connected_router

    # try best path: pick highest-weight router path entry (if any)
    best_choice = None
    for _, path_list in best_paths.items():
        if not path_list:
            continue
        w, path = path_list[0]
        if best_choice is None or w > best_choice[0]:
            best_choice = (w, path)

    if best_choice is not None:
        _, path = best_choice
        interest_packet.original_hop_count = len(path)
        # send to subscriber's connected router first (more consistent)
        subscriber.send_interest(interest_packet, start_router)
    else:
        interest_packet.original_hop_count = 1
        subscriber.send_interest(interest_packet, start_router)

    subscriber.last_interest_packet = interest_packet

# ===================== SIMULATION =====================

def run_multipath_simulation(routers, subscribers, policy, iterations, best_paths, G):
    """Run simulation with multiple subscribers."""
    for r in routers:
        r.caching_policy = policy
        r.reset()

    all_contents = []
    for r in routers:
        all_contents.extend(r.contents.keys())

    print(f"Running {iterations} iterations with {policy} caching policy...")
    print("Resource metrics tracked: Battery, Latency, Cache Size, CPU, Memory, Temperature\n")

    simulation_data = []
    active_prob = 0.95

    for it in range(1, iterations + 1):
        # update resources + links
        for r in routers:
            r.calculate_node_weight()
            for link in r.edge_links.values():
                link.update_weight()

        # each subscriber may generate an interest
        for sub in subscribers:
            sub.active = (random.random() < active_prob)
            if not sub.active or not all_contents:
                continue
            execute_multipath_transmission(best_paths, routers, sub, policy, it, G, len(routers))

        total_requests = sum(r.cache_hits + r.publisher_hits for r in routers)
        total_cache_hits = sum(r.cache_hits for r in routers)
        avg_cache_hit = (total_cache_hits / total_requests * 100) if total_requests > 0 else 0.0

        avg_battery = float(np.mean([r.resources.battery for r in routers]))
        avg_latency = float(np.mean([r.resources.latency_ms for r in routers]))
        avg_cache_used = float(np.mean([(len(r.cs) / r.resources.cache_size) for r in routers if r.resources.cache_size > 0]) * 100.0)
        avg_cpu = float(np.mean([r.resources.cpu_usage for r in routers]))

        # hop reduction (average over subscribers that sent at least one)
        reductions = []
        for sub in subscribers:
            pkt = getattr(sub, "last_interest_packet", None)
            if pkt and pkt.original_hop_count > 0:
                reductions.append(max(0, (pkt.original_hop_count - len(pkt.path)) / pkt.original_hop_count))
        hop_reduction = float(np.mean(reductions)) if reductions else 0.0

        # active paths
        active_paths = sum(len(r.path_table) for r in routers)

        simulation_data.append([
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            len(subscribers),
            total_requests,
            hop_reduction,
            avg_cache_hit,
            random.uniform(0.01, 0.1) / total_requests if total_requests > 0 else 0.0,
            active_paths,
            policy,
            len(routers),
            f"{avg_battery:.3f}",
            f"{avg_latency:.3f}",
            f"{avg_cache_used:.1f}",
            f"{avg_cpu:.3f}"
        ])

        if it % max(1, iterations // 5) == 0:
            print(f" Iteration {it}/{iterations}")
            print(f" Cache Hit: {avg_cache_hit:.2f}% | Avg Battery: {avg_battery:.3f} | Avg Latency: {avg_latency:.3f}ms")
            print(f" Avg Cache Used: {avg_cache_used:.1f}% | Avg CPU: {avg_cpu:.3f}\n")

    return simulation_data

def save_multipath_results(all_simulation_data, policy, num_routers):
    os.makedirs('Simulation_Results/Multipath_Resources', exist_ok=True)
    filename = f'Simulation_Results/Multipath_Resources/{policy}_multipath_{num_routers}routers_results.csv'

    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            "Simulation Time", "Subscribers", "Total Requests", "Hop Reduction Ratio",
            "Cache Hit Ratio (%)", "Latency", "Active Paths", "Policy", "Routers",
            "Avg Battery", "Avg Latency (ms)", "Avg Cache Used (%)", "Avg CPU Usage"
        ])
        writer.writerows(all_simulation_data)

    print(f"Results saved to {filename}\n")

def compare_policies_multipath(routers, subscribers, iterations, best_paths, G):
    policies = ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR']
    all_results = []
    num_routers = len(routers)

    for policy in policies:
        print(f"\n{'='*70}")
        print(f"Running simulation for {policy} policy ({num_routers} routers, {len(subscribers)} subscribers)...")
        print(f"{'='*70}")

        data = run_multipath_simulation(routers, subscribers, policy, iterations, best_paths, G)
        all_results.extend(data)
        save_multipath_results(data, policy, num_routers)

    combined_filename = f'Simulation_Results/Multipath_Resources/combined_multipath_{num_routers}routers_results.csv'
    with open(combined_filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            "Simulation Time", "Subscribers", "Total Requests", "Hop Reduction Ratio",
            "Cache Hit Ratio (%)", "Latency", "Active Paths", "Policy", "Routers",
            "Avg Battery", "Avg Latency (ms)", "Avg Cache Used (%)", "Avg CPU Usage"
        ])
        writer.writerows(all_results)

    print(f"\nCombined results saved to {combined_filename}\n")
    return all_results

# ===================== MAIN =====================

def main():
    print("\n" + "="*80)
    print("RESOURCE-AWARE MULTIPATH CONTENT DELIVERY NETWORK SIMULATOR")
    print("Every Node is a Router with Dynamic Resources")
    print("Based on: LMM (IEEE IoT Journal 2025)")
    print("="*80 + "\n")

    # routers input
    while True:
        try:
            num_routers = int(input("Enter number of routers (minimum 5): "))
            if num_routers >= 5:
                break
            print("Please enter at least 5 routers.")
        except ValueError:
            print("Invalid input. Please enter a number.")

    # subscribers input
    while True:
        try:
            num_subscribers = int(input("Enter number of consumers/subscribers (minimum 1): "))
            if num_subscribers >= 1:
                break
            print("Please enter at least 1 subscriber.")
        except ValueError:
            print("Invalid input. Please enter a number.")

    # iterations input
    while True:
        try:
            iterations = int(input("Enter number of iterations (minimum 1): "))
            if iterations >= 1:
                break
            print("Please enter at least 1 iteration.")
        except ValueError:
            print("Invalid input. Please enter a number.")

    routers, subscribers = setup_network_with_multipaths(num_routers=num_routers, num_subscribers=num_subscribers)

    # graph for path discovery
    G = build_graph_from_network(routers, subscribers)

    # visualize (correct signature now)
    plot_network_with_resources(routers, subscribers)

    # routers dict for weights
    routers_dict = {r.name: r for r in routers}

    # Path discovery: do it from Subscriber1 only (consistent with your earlier design),
    # but simulation still uses all subscribers.
    print("Discovering all possible paths (from Subscriber1)...")
    all_paths = discover_all_paths(subscribers[0], routers, G)
    total_paths = sum(len(p) for p in all_paths.values())
    print(f"Total paths discovered: {total_paths}\n")

    # Filter by weight
    print("Calculating path weights and filtering...")
    best_paths = filter_paths_by_weight(all_paths, routers_dict, top_k=3)
    total_selected = sum(len(p) for p in best_paths.values())
    print(f"Total selected paths: {total_selected}\n")

    print("Starting simulation with path-weighted multipath routing...\n")
    compare_policies_multipath(routers, subscribers, iterations, best_paths, G)

if __name__ == "__main__":
    main()
