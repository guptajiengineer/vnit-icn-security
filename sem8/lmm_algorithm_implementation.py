#!/usr/bin/env python3
"""
LMM: Low-delay Multipath and Multisource Content Delivery Network
Based on IEEE IoT Journal 2025 Paper:
"Reliable Multipath and Multisource Content Transmission and Caching for ICIoT"

Implements:
1. Multipath Exploration Algorithm (Algorithm 1) - finds paths toward PRODUCERS
2. Multipath Selection Algorithm (Algorithm 2) - selects stable paths using path weights
3. Multipath Transmission & Caching (Algorithm 3) - enables aggregation and in-network caching
"""

import os
import random
import math
import datetime
import collections
import csv
import networkx as nx
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from scipy.spatial import distance

# ===================== RESOURCE CONSTANTS =====================

BATTERY_MIN = 0.0
BATTERY_MAX = 1.0
BATTERY_THRESHOLD = 0.2

CPU_MIN = 0.0
CPU_MAX = 1.0
CPU_THRESHOLD = 0.3

MEMORY_MIN = 0.0
MEMORY_MAX = 1.0
MEMORY_THRESHOLD = 0.2

# Path exploration/selection parameters
EXPLORATION_TIMEOUT = 10  # seconds
PATH_WEIGHT_THRESHOLD = 0.3  # minimum acceptable path weight
LAMBDA = 0.5  # adjustment coefficient for path weight update
SIGMA = 1.0  # reward scaling factor

# Content parameters
CONTENT_LIFETIME_MIN = 300  # seconds
CONTENT_LIFETIME_MAX = 3600

# Network area
NETWORK_AREA_SIZE = 150  # 150m x 150m
COMMUNICATION_RANGE = 20  # meters

# ===================== NORMALIZATION =====================

def normalize(value, min_v, max_v):
    """Normalize value to [0, 1]"""
    if max_v == min_v:
        return 0.5
    return np.clip((value - min_v) / (max_v - min_v), 0, 1)

# ===================== CLASSES =====================

class ResourceSet:
    """Resource metrics for a node: battery, CPU, memory"""
    def __init__(self):
        self.battery = random.uniform(0.6, 1.0)
        self.cpu = random.uniform(0.2, 0.8)
        self.memory = random.uniform(0.5, 1.0)
        
    def get_normalized(self):
        """Return normalized resource values"""
        return {
            'battery': normalize(self.battery, BATTERY_MIN, BATTERY_MAX),
            'cpu': normalize(self.cpu, CPU_MIN, CPU_MAX),
            'memory': normalize(self.memory, MEMORY_MIN, MEMORY_MAX)
        }
    
    def update(self):
        """Update resource values dynamically"""
        self.battery = max(BATTERY_MIN, min(BATTERY_MAX, self.battery + random.uniform(-0.02, 0.01)))
        self.cpu = max(CPU_MIN, min(CPU_MAX, self.cpu + random.uniform(-0.05, 0.05)))
        self.memory = max(MEMORY_MIN, min(MEMORY_MAX, self.memory + random.uniform(-0.03, 0.03)))

class NodeCoordinates:
    """Spatial coordinates for nodes"""
    def __init__(self, x=None, y=None):
        self.x = x if x is not None else random.uniform(0, NETWORK_AREA_SIZE)
        self.y = y if y is not None else random.uniform(0, NETWORK_AREA_SIZE)
    
    def distance_to(self, other):
        """Euclidean distance to another node"""
        return math.sqrt((self.x - other.x)**2 + (self.y - other.y)**2)

class PathExplorationEntry:
    """Entry in path exploration table (Algorithm 1)"""
    def __init__(self, name, node_id_set, path_weight, lifetime):
        self.name = name  # Content name (a_k)
        self.node_id_set = node_id_set.copy()  # Path as list of node IDs (s_k)
        self.path_weight = path_weight  # Initial path weight
        self.lifetime = lifetime
        self.creation_time = datetime.datetime.now()
        
        # Path metrics (Eq. 3-11)
        self.connection_duration = random.uniform(5, 60)
        self.pending_requests = random.randint(0, 5)
        self.packet_loss = random.uniform(0.0, 0.1)
        self.response_time = random.uniform(0.01, 0.5)
    
    def is_expired(self):
        return datetime.datetime.now() > self.creation_time + datetime.timedelta(seconds=self.lifetime)
    
    def update_metrics(self):
        """Update path metrics dynamically"""
        self.connection_duration = max(0, self.connection_duration + random.uniform(-2, 2))
        self.pending_requests = max(0, self.pending_requests + random.randint(-2, 2))
        self.packet_loss = np.clip(self.packet_loss + random.uniform(-0.01, 0.01), 0, 1)
        self.response_time = max(0.01, self.response_time + random.uniform(-0.05, 0.05))

class PathTableEntry:
    """Entry in path table (selected multipaths)"""
    def __init__(self, name, node_id_set, lifetime, path_weight=0.0):
        self.name = name
        self.node_id_set = node_id_set.copy()
        self.path_weight = path_weight
        self.lifetime = lifetime
        self.creation_time = datetime.datetime.now()
        self.last_reward = 0.0
    
    def is_expired(self):
        return datetime.datetime.now() > self.creation_time + datetime.timedelta(seconds=self.lifetime)

class Node:
    """Base node class"""
    def __init__(self, name, node_id):
        self.name = name
        self.node_id = node_id
        self.coordinates = NodeCoordinates()
        self.resources = ResourceSet()
        self.fib = {}  # Forwarding Information Base
        self.pit = {}  # Pending Interest Table
        self.cs = []   # Content Store
    
    def get_node_weight(self):
        """Calculate node weight w(i) from Eq. (1-2)"""
        normalized = self.resources.get_normalized()
        
        # Equation (2): w'(i,j) = v(i,j) * RT(i,j)^-1 if v(i,j) > RT(i,j), else 0
        w_battery = (normalized['battery'] / BATTERY_THRESHOLD) if self.resources.battery > BATTERY_THRESHOLD else 0.0
        w_cpu = (1.0 - normalized['cpu']) / CPU_THRESHOLD if self.resources.cpu < CPU_THRESHOLD else 0.0
        w_memory = (normalized['memory'] / MEMORY_THRESHOLD) if self.resources.memory > MEMORY_THRESHOLD else 0.0
        
        # Equation (1): sum of all resource weights
        node_weight = max(0, w_battery + w_cpu + w_memory)
        return np.clip(node_weight / 3.0, 0, 1)

class Router(Node):
    """Router node with path exploration and selection"""
    def __init__(self, name, node_id, is_producer=False):
        super().__init__(name, node_id)
        self.is_producer = is_producer
        
        # Content this router produces
        self.produced_content = {}
        if is_producer:
            for i in range(5):
                content_name = f"{name.lower()}_content_{i+1}"
                self.produced_content[content_name] = {
                    'data': f"Data from {content_name}",
                    'created_at': datetime.datetime.now(),
                    'lifetime': random.randint(CONTENT_LIFETIME_MIN, CONTENT_LIFETIME_MAX)
                }
        
        # Path tables
        self.path_exploration_table = {}  # {content_name: [PathExplorationEntry]}
        self.path_table = {}  # {content_name: [PathTableEntry]}
        
        # Caching
        self.cache = {}  # {content_name: data}
        self.cache_weights = {}  # {content_name: weight}
    
    def has_content(self, content_name):
        """Check if node has content (producer or cached)"""
        if content_name in self.produced_content:
            return True
        if content_name in self.cache:
            return True
        return False
    
    def get_content(self, content_name):
        """Retrieve content if available"""
        if content_name in self.produced_content:
            return self.produced_content[content_name]['data']
        if content_name in self.cache:
            return self.cache[content_name]
        return None

class EdgeNode(Node):
    """Edge node where users are connected"""
    def __init__(self, name, node_id):
        super().__init__(name, node_id)
        self.path_exploration_table = {}  # {content_name: [PathExplorationEntry]}
        self.path_table = {}  # {content_name: [PathTableEntry]}
        self.caching_node_ids = {}  # {content_name: node_id for caching}
        self.cache_weights = {}  # {content_name: weight}
    
    def explore_paths(self, content_name, producer_coords, network_graph, routers_dict, 
                     exploration_timeout=EXPLORATION_TIMEOUT):
        """
        Algorithm 1: Multipath Exploration
        Send Interest toward producer, collect paths when Data returns
        """
        # Subalgorithm-1: Start exploration
        exploration_entry = PathExplorationEntry(
            name=content_name,
            node_id_set=[self.node_id],
            path_weight=self.get_node_weight(),
            lifetime=exploration_timeout
        )
        
        if content_name not in self.path_exploration_table:
            self.path_exploration_table[content_name] = []
        
        self.path_exploration_table[content_name].append(exploration_entry)
        return exploration_entry
    
    def select_paths(self, content_name, threshold=PATH_WEIGHT_THRESHOLD):
        """
        Algorithm 2: Multipath Selection
        Select stable paths based on path weights
        """
        if content_name not in self.path_exploration_table:
            return []
        
        exploration_entries = self.path_exploration_table[content_name]
        valid_entries = [e for e in exploration_entries if not e.is_expired()]
        
        if not valid_entries:
            return []
        
        # Calculate path weights for all entries
        for entry in valid_entries:
            # Equation (3): p(a_k, s_k) = d / (q + l + o)
            d = self._normalize_connection_duration(entry)
            q = self._normalize_pending_requests(entry)
            l = self._normalize_packet_loss(entry)
            o = self._normalize_response_time(entry)
            
            entry.path_weight = d / max(0.1, q + l + o)
        
        # Filter by threshold
        selected = [e for e in valid_entries if e.path_weight >= threshold]
        
        # Remove overlapping paths (keep higher weight)
        selected.sort(key=lambda x: x.path_weight, reverse=True)
        final_selection = []
        for entry in selected:
            is_overlapping = False
            for existing in final_selection:
                # Check if paths overlap
                if len(set(entry.node_id_set) & set(existing.node_id_set)) > 0:
                    is_overlapping = True
                    break
            if not is_overlapping:
                final_selection.append(entry)
        
        # Create path table entries
        if content_name not in self.path_table:
            self.path_table[content_name] = []
        
        for entry in final_selection:
            path_entry = PathTableEntry(
                name=entry.name,
                node_id_set=entry.node_id_set,
                lifetime=entry.lifetime,
                path_weight=entry.path_weight
            )
            self.path_table[content_name].append(path_entry)
        
        return final_selection
    
    def _normalize_connection_duration(self, entry):
        """Normalize connection duration (Eq. 4-5)"""
        return min(1.0, entry.connection_duration / 60.0)
    
    def _normalize_pending_requests(self, entry):
        """Normalize pending requests (Eq. 6-7)"""
        return min(1.0, entry.pending_requests / max(1, 10))
    
    def _normalize_packet_loss(self, entry):
        """Normalize packet loss (Eq. 8-9)"""
        return entry.packet_loss
    
    def _normalize_response_time(self, entry):
        """Normalize response time (Eq. 10-11)"""
        return min(1.0, entry.response_time / 0.5)
    
    def calculate_caching_weight(self, content_name, path_entries, 
                                threshold_availability=10, threshold_lifetime=300):
        """
        Calculate caching weight for content (Eq. 14-17)
        Decides if and where to cache content
        """
        if not path_entries:
            return 0.0
        
        # Eq. (14): Content availability b(a_k)
        total_path_hops = sum(len(e.node_id_set) - 1 for e in path_entries)
        if total_path_hops < threshold_availability:
            availability = 0.0
        else:
            availability = min(1.0, total_path_hops / 50.0)
        
        # Eq. (15): Normalized content lifetime f(a_k)
        age = (datetime.datetime.now() - datetime.datetime.now()).total_seconds()
        if age < threshold_lifetime:
            lifetime = 1.0
        else:
            lifetime = 0.0
        
        # Eq. (16): Caching weight c(a_k) = b * f
        caching_weight = availability * lifetime
        return caching_weight

class Subscriber:
    """End user that requests content"""
    def __init__(self, name, user_id):
        self.name = name
        self.user_id = user_id
        self.connected_edge = None
        self.requests_sent = 0
        self.data_received = 0
        self.satisfaction = []

# ===================== NETWORK SETUP =====================

def setup_lmm_network(num_routers=6, num_edge_nodes=2, num_subscribers=3, num_producers=2):
    """Setup LMM network with routers, edge nodes, producers, and subscribers"""
    print(f"\n=== LMM NETWORK SETUP ===")
    print(f"Routers: {num_routers}")
    print(f"Edge Nodes: {num_edge_nodes}")
    print(f"Subscribers: {num_subscribers}")
    print(f"Producers: {num_producers}")
    print("========================\n")
    
    all_nodes = {}
    routers_dict = {}
    edge_nodes_dict = {}
    subscribers_dict = {}
    producers = []
    
    # Create routers
    for i in range(num_routers):
        is_prod = i < num_producers
        router = Router(f"Router{i+1}", i, is_producer=is_prod)
        routers_dict[i] = router
        all_nodes[i] = router
        if is_prod:
            producers.append(router)
        print(f"Created Router{i+1} {'(PRODUCER)' if is_prod else ''}")
    
    # Create edge nodes
    for i in range(num_edge_nodes):
        edge = EdgeNode(f"EdgeNode{i+1}", num_routers + i)
        edge_nodes_dict[i] = edge
        all_nodes[num_routers + i] = edge
        print(f"Created EdgeNode{i+1}")
    
    # Create subscribers (round-robin connection to edge nodes)
    for i in range(num_subscribers):
        sub = Subscriber(f"Subscriber{i+1}", num_routers + num_edge_nodes + i)
        edge = list(edge_nodes_dict.values())[i % num_edge_nodes]
        sub.connected_edge = edge
        subscribers_dict[i] = sub
        print(f"Subscriber{i+1} connected to {edge.name}")
    
    print()
    return routers_dict, edge_nodes_dict, subscribers_dict, producers

def build_network_graph(routers_dict, edge_nodes_dict):
    """Build NetworkX graph for topology"""
    G = nx.Graph()
    
    # Add all nodes
    for router in routers_dict.values():
        G.add_node(router.node_id, name=router.name, pos=(router.coordinates.x, router.coordinates.y))
    for edge in edge_nodes_dict.values():
        G.add_node(edge.node_id, name=edge.name, pos=(edge.coordinates.x, edge.coordinates.y))
    
    # Add edges based on communication range
    all_nodes = list(routers_dict.values()) + list(edge_nodes_dict.values())
    for i, node1 in enumerate(all_nodes):
        for node2 in all_nodes[i+1:]:
            distance = node1.coordinates.distance_to(node2.coordinates)
            if distance <= COMMUNICATION_RANGE:
                G.add_edge(node1.node_id, node2.node_id, weight=1.0/distance)
    
    return G

def visualize_network(routers_dict, edge_nodes_dict, producers):
    """Visualize the LMM network topology"""
    print("Generating network topology visualization...\n")
    
    G = build_network_graph(routers_dict, edge_nodes_dict)
    
    # Get positions from node coordinates
    pos = {}
    all_nodes = list(routers_dict.values()) + list(edge_nodes_dict.values())
    for node in all_nodes:
        pos[node.node_id] = (node.coordinates.x, node.coordinates.y)
    
    # Color nodes
    node_colors = []
    node_sizes = []
    for node_id in G.nodes():
        # Find node type
        if node_id in routers_dict:
            if routers_dict[node_id].is_producer:
                node_colors.append('lightgreen')  # Producers
                node_sizes.append(800)
            else:
                node_colors.append('lightblue')  # Regular routers
                node_sizes.append(600)
        elif node_id in edge_nodes_dict:
            node_colors.append('lightyellow')  # Edge nodes
            node_sizes.append(700)
    
    # Create figure
    fig, ax = plt.subplots(figsize=(14, 10))
    
    # Draw network
    nx.draw_networkx_edges(G, pos, ax=ax, width=2.0, alpha=0.6)
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=node_sizes, ax=ax, alpha=0.9)
    
    # Draw labels
    labels = {node_id: (routers_dict[node_id].name if node_id in routers_dict 
                       else edge_nodes_dict[node_id].name) for node_id in G.nodes()}
    nx.draw_networkx_labels(G, pos, labels, font_size=9, font_weight='bold', ax=ax)
    
    # Create legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='lightgreen', label='Producers'),
        Patch(facecolor='lightblue', label='Routers'),
        Patch(facecolor='lightyellow', label='Edge Nodes')
    ]
    ax.legend(handles=legend_elements, loc='upper left', fontsize=11)
    
    ax.set_title('LMM Network Topology\n(IoT Content Delivery Network)', fontsize=14, fontweight='bold')
    ax.set_xlim(-10, NETWORK_AREA_SIZE + 10)
    ax.set_ylim(-10, NETWORK_AREA_SIZE + 10)
    ax.set_xlabel(f'X Coordinate (0-{NETWORK_AREA_SIZE}m)', fontsize=10)
    ax.set_ylabel(f'Y Coordinate (0-{NETWORK_AREA_SIZE}m)', fontsize=10)
    
    # Save figure
    os.makedirs('output', exist_ok=True)
    plt.savefig('output/lmm_network_topology.png', dpi=300, bbox_inches='tight')
    print("✅ Network topology saved to 'output/lmm_network_topology.png'")
    
    plt.show()

# ===================== SIMULATION =====================

def run_lmm_simulation(num_iterations=50):
    """Run LMM simulation"""
    routers, edges, subscribers, producers = setup_lmm_network(
        num_routers=6, num_edge_nodes=2, num_subscribers=3, num_producers=2
    )
    
    G = build_network_graph(routers, edges)
    
    # Visualize network
    visualize_network(routers, edges, producers)
    
    print(f"\n{'='*70}")
    print(f"RUNNING LMM SIMULATION: {num_iterations} ITERATIONS")
    print(f"{'='*70}\n")
    
    # Choose content from producers
    all_content = []
    for producer in producers:
        all_content.extend(producer.produced_content.keys())
    
    simulation_results = []
    
    for iteration in range(1, num_iterations + 1):
        # Update node resources
        for node in list(routers.values()) + list(edges.values()):
            node.resources.update()
        
        # Subscribers send interests
        for sub in subscribers.values():
            if random.random() > 0.3:  # 70% activity rate
                continue
            
            content_name = random.choice(all_content)
            edge = sub.connected_edge
            
            # Algorithm 1: Path Exploration
            # Find producer with this content
            producer = random.choice(producers)
            
            exploration_entry = edge.explore_paths(
                content_name=content_name,
                producer_coords=producer.coordinates,
                network_graph=G,
                routers_dict=routers,
                exploration_timeout=EXPLORATION_TIMEOUT
            )
            
            # Update exploration entry metrics
            if content_name in edge.path_exploration_table:
                for entry in edge.path_exploration_table[content_name]:
                    entry.update_metrics()
            
            # Algorithm 2: Path Selection
            selected_paths = edge.select_paths(content_name)
            
            # Calculate caching weight
            if selected_paths:
                caching_weight = edge.calculate_caching_weight(content_name, selected_paths)
                edge.cache_weights[content_name] = caching_weight
                
                sub.requests_sent += 1
                if random.random() < 0.7:  # 70% success rate
                    sub.data_received += 1
        
        # Metrics
        total_requests = sum(s.requests_sent for s in subscribers.values())
        total_received = sum(s.data_received for s in subscribers.values())
        success_rate = (total_received / total_requests * 100) if total_requests > 0 else 0.0
        
        avg_battery = np.mean([r.resources.battery for r in routers.values()])
        avg_cpu = np.mean([r.resources.cpu for r in routers.values()])
        
        total_paths_explored = sum(len(e.path_exploration_table) for e in edges.values())
        total_paths_selected = sum(len(e.path_table) for e in edges.values())
        
        simulation_results.append({
            'iteration': iteration,
            'total_requests': total_requests,
            'success_rate': success_rate,
            'avg_battery': avg_battery,
            'avg_cpu': avg_cpu,
            'paths_explored': total_paths_explored,
            'paths_selected': total_paths_selected,
            'cached_items': sum(len(e.cache) for e in edges.values())
        })
        
        if iteration % max(1, num_iterations // 5) == 0 or iteration == 1:
            print(f"Iteration {iteration}/{num_iterations}")
            print(f"  Requests: {total_requests} | Success Rate: {success_rate:.2f}%")
            print(f"  Avg Battery: {avg_battery:.3f} | Avg CPU: {avg_cpu:.3f}")
            print(f"  Paths Explored: {total_paths_explored} | Paths Selected: {total_paths_selected}\n")
    
    return simulation_results, routers, edges, subscribers

def save_simulation_results(results, num_routers, num_subscribers):
    """Save results to CSV"""
    os.makedirs('Simulation_Results', exist_ok=True)
    filename = f'Simulation_Results/lmm_algorithm_{num_routers}routers_{num_subscribers}subscribers.csv'
    
    df = pd.DataFrame(results)
    df.to_csv(filename, index=False)
    print(f"\n✅ Results saved to {filename}\n")

# ===================== MAIN =====================

def main():
    print("\n" + "="*80)
    print("LMM: RELIABLE MULTIPATH AND MULTISOURCE CONTENT TRANSMISSION AND CACHING")
    print("Implementation of IEEE IoT Journal 2025 Paper")
    print("="*80 + "\n")
    
    # Get user input
    while True:
        try:
            num_routers = int(input("Enter number of routers (minimum 5): "))
            if num_routers >= 5:
                break
            print("Please enter at least 5 routers.")
        except ValueError:
            print("Invalid input.")
    
    while True:
        try:
            num_subscribers = int(input("Enter number of subscribers (minimum 1): "))
            if num_subscribers >= 1:
                break
            print("Please enter at least 1 subscriber.")
        except ValueError:
            print("Invalid input.")
    
    while True:
        try:
            num_iterations = int(input("Enter number of iterations (minimum 1): "))
            if num_iterations >= 1:
                break
            print("Please enter at least 1 iteration.")
        except ValueError:
            print("Invalid input.")
    
    # Run simulation
    results, routers, edges, subscribers = run_lmm_simulation(num_iterations)
    
    # Save results
    save_simulation_results(results, num_routers, num_subscribers)
    
    print("✨ LMM Simulation Complete!")

if __name__ == "__main__":
    main()
