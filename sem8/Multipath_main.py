#!/usr/bin/env python3

"""
INTEGRATED Multipath Content Delivery Network Simulator
Implementing Algorithm 1 (Multipath Exploration) and Algorithm 2 (Multipath Selection)
from: Reliable Multipath and Multisource Content Transmission and Caching for ICN-IoT

COMPLETE INTEGRATION - Ready to run with user input
"""

import os
import random
import datetime
import time
import collections
import csv
import networkx as nx
import matplotlib.pyplot as plt
import pickle
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from collections import defaultdict
import heapq

# ===================== NODE RESOURCES =====================

class NodeResource:
    """Represents node resources for Algorithm 1 node weight calculation"""
    def __init__(self, energy=100.0, bandwidth=1000.0, storage=500.0):
        self.energy = energy
        self.bandwidth = bandwidth
        self.storage = storage
        self.energy_threshold = 20.0
        self.bandwidth_threshold = 100.0
        self.storage_threshold = 50.0
    
    def update(self):
        """Update resources dynamically"""
        self.energy = max(0, self.energy + random.uniform(-2, 1))
        self.bandwidth = max(0, self.bandwidth + random.uniform(-50, 50))
        self.storage = max(0, self.storage + random.uniform(-10, 10))

# ===================== PATH ENTRIES =====================

class PathExplorationEntry:
    """Path exploration table entry (Algorithm 1 output)"""
    def __init__(self, name, node_id_set, path_weight, lifetime):
        self.name = name
        self.node_id_set = node_id_set.copy()
        self.path_weight = path_weight
        self.lifetime = lifetime
        self.creation_time = datetime.datetime.now()
        self.connection_duration = random.uniform(5, 60)
        self.pending_requests = random.randint(0, 10)
        self.packet_loss_rate = random.uniform(0.0, 0.1)
        self.response_time = random.uniform(0.01, 0.5)
    
    def is_expired(self):
        return datetime.datetime.now() > self.creation_time + datetime.timedelta(seconds=self.lifetime)
    
    def __repr__(self):
        return f"PE({self.name}:path={self.node_id_set},weight={self.path_weight:.4f})"

class PathTableEntry:
    """Path table entry (Algorithm 2 output)"""
    def __init__(self, name, node_id_set, lifetime):
        self.name = name
        self.node_id_set = node_id_set.copy()
        self.lifetime = lifetime
        self.creation_time = datetime.datetime.now()
        self.path_weight = 0.0
        self.is_active = True
    
    def is_expired(self):
        return datetime.datetime.now() > self.creation_time + datetime.timedelta(seconds=self.lifetime)
    
    def __repr__(self):
        return f"PT({self.name}:path={self.node_id_set},weight={self.path_weight:.4f})"

class EdgeLink:
    """Link between two nodes"""
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
        self.weight = max(0.1, self.weight + random.uniform(-0.1, 0.1))
        self.packet_loss_rate = max(0.0, min(1.0, self.packet_loss_rate + random.uniform(-0.02, 0.02)))
        self.pending_requests = max(0, self.pending_requests - random.randint(0, 3))
        self.response_time = max(0.01, self.response_time + random.uniform(-0.05, 0.05))

# ===================== BASE NODES =====================

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

class DataPacket:
    def __init__(self, name, content):
        self.name = name
        self.content = content

# ===================== ALGORITHM 1: MULTIPATH EXPLORATION =====================

class Algorithm1_MultiPathExploration:
    """Algorithm 1: Multipath Exploration using Node Weights"""
    
    @staticmethod
    def calculate_node_weight(node):
        """
        Calculate node weight w(i) using Formula (1) & (2)
        w(i) = sum of w'(i,j) for all resources j
        w'(i,j) = v(i,j) * RT(i,j)^-1 if v(i,j) > RT(i,j), else 0
        """
        if not hasattr(node, 'resources'):
            node.resources = NodeResource()
        
        resources = [
            ('energy', node.resources.energy, node.resources.energy_threshold),
            ('bandwidth', node.resources.bandwidth, node.resources.bandwidth_threshold),
            ('storage', node.resources.storage, node.resources.storage_threshold)
        ]
        
        node_weight = 0.0
        for res_name, value, threshold in resources:
            if value > threshold:
                weight_component = value * (threshold ** -1)
                node_weight += weight_component
        
        return max(0, node_weight)
    
    @staticmethod
    def explore_paths_dfs(subscriber_node, publisher_name, all_nodes, max_depth=5):
        """
        Explore all paths from subscriber to publisher using DFS with node weights
        Implements Algorithm 1, Sub-algorithm 1 & 2
        """
        exploration_entries = []
        stack = [(subscriber_node, [subscriber_node.name], 0.0, {subscriber_node.name})]
        
        while stack:
            current_node, path, accumulated_weight, visited_on_path = stack.pop()
            
            if len(path) > max_depth:
                continue
            
            node_weight = Algorithm1_MultiPathExploration.calculate_node_weight(current_node)
            
            # Check if node can provide content
            if hasattr(current_node, 'can_provide_content') and \
               current_node.can_provide_content(publisher_name):
                new_weight = accumulated_weight + node_weight
                path_entry = PathExplorationEntry(
                    name=publisher_name,
                    node_id_set=path.copy(),
                    path_weight=new_weight / len(path) if len(path) > 0 else new_weight,
                    lifetime=300
                )
                exploration_entries.append(path_entry)
                continue
            
            # If node weight > 0, explore neighbors
            if node_weight > 0:
                neighbors = []
                
                if hasattr(current_node, 'fib') and publisher_name in current_node.fib:
                    fib_hops = current_node.fib[publisher_name]
                    neighbors = fib_hops if isinstance(fib_hops, list) else [fib_hops]
                else:
                    for node_name, node in all_nodes.items():
                        if node_name not in visited_on_path:
                            neighbors.append(node)
                
                for neighbor in neighbors:
                    if neighbor and neighbor.name not in visited_on_path:
                        new_path = path + [neighbor.name]
                        new_visited = visited_on_path.copy()
                        new_visited.add(neighbor.name)
                        new_weight = accumulated_weight + node_weight
                        stack.append((neighbor, new_path, new_weight, new_visited))
        
        return exploration_entries

# ===================== ALGORITHM 2: MULTIPATH SELECTION =====================

class Algorithm2_MultiPathSelection:
    """Algorithm 2: Multipath Selection using Path Weights"""
    
    @staticmethod
    def calculate_normalized_connection_duration(entry, all_entries):
        """Calculate normalized connection duration dt(ak, sk) - Formula (4) & (5)"""
        if not all_entries:
            return 0.5
        durations = [e.connection_duration for e in all_entries]
        max_duration = max(durations) if durations else 60
        min_duration = min(durations) if durations else 5
        normalized = entry.connection_duration / (max_duration + min_duration) if (max_duration + min_duration) > 0 else 0.5
        return np.clip(normalized, 0, 1)
    
    @staticmethod
    def calculate_normalized_pending_requests(entry, all_entries):
        """Calculate normalized pending requests qt(ak, sk) - Formula (6) & (7)"""
        if not all_entries:
            return 0.5
        requests = [e.pending_requests for e in all_entries]
        max_requests = max(requests) if requests else 10
        min_requests = min(requests) if requests else 0
        denominator = max(1, max_requests) + min_requests
        normalized = entry.pending_requests / denominator if denominator > 0 else 0.5
        return np.clip(normalized, 0, 1)
    
    @staticmethod
    def calculate_normalized_packet_loss(entry, all_entries):
        """Calculate normalized packet loss lt(ak, sk) - Formula (8) & (9)"""
        if not all_entries:
            return 0.5
        losses = [e.packet_loss_rate for e in all_entries]
        max_loss = max(losses) if losses else 0.1
        min_loss = min(losses) if losses else 0.0
        denominator = max(1, max_loss) + min_loss
        normalized = entry.packet_loss_rate / denominator if denominator > 0 else 0.5
        return np.clip(normalized, 0, 1)
    
    @staticmethod
    def calculate_normalized_response_time(entry, all_entries):
        """Calculate normalized response time ot(ak, sk) - Formula (10) & (11)"""
        if not all_entries:
            return 0.5
        times = [e.response_time for e in all_entries]
        max_time = max(times) if times else 0.5
        min_time = min(times) if times else 0.01
        denominator = max(1, max_time) + min_time
        normalized = entry.response_time / denominator if denominator > 0 else 0.5
        return np.clip(normalized, 0, 1)
    
    @staticmethod
    def calculate_path_weight(entry, all_entries):
        """
        Calculate path weight pt(ak, sk) - Formula (3)
        pt(ak, sk) = dt(ak, sk) / [qt(ak, sk) + lt(ak, sk) + ot(ak, sk)]
        """
        d_t = Algorithm2_MultiPathSelection.calculate_normalized_connection_duration(entry, all_entries)
        q_t = Algorithm2_MultiPathSelection.calculate_normalized_pending_requests(entry, all_entries)
        l_t = Algorithm2_MultiPathSelection.calculate_normalized_packet_loss(entry, all_entries)
        o_t = Algorithm2_MultiPathSelection.calculate_normalized_response_time(entry, all_entries)
        
        denominator = q_t + l_t + o_t
        path_weight = d_t / denominator if denominator > 0 else d_t
        
        return np.clip(path_weight, 0, 1)
    
    @staticmethod
    def select_multipaths(exploration_entries, content_name, threshold_weight=0.3):
        """
        Select optimal multipaths from exploration entries
        Implements Algorithm 2 from paper - Lines 1-26
        """
        relevant_entries = [e for e in exploration_entries if e.name == content_name and not e.is_expired()]
        
        if not relevant_entries:
            return []
        
        # Lines 1-4: Calculate path weights
        weighted_entries = []
        for entry in relevant_entries:
            weight = Algorithm2_MultiPathSelection.calculate_path_weight(entry, relevant_entries)
            entry.path_weight = weight
            weighted_entries.append(entry)
        
        # Lines 5-9: For each provider, select best path
        path_table_entries = []
        providers_seen = {}
        
        for entry in sorted(weighted_entries, key=lambda x: x.path_weight, reverse=True):
            provider = entry.node_id_set[-1] if entry.node_id_set else None
            
            if provider not in providers_seen:
                # Lines 10-14: Check threshold
                if entry.path_weight >= threshold_weight:
                    path_entry = PathTableEntry(
                        name=entry.name,
                        node_id_set=entry.node_id_set,
                        lifetime=entry.lifetime
                    )
                    path_entry.path_weight = entry.path_weight
                    path_table_entries.append(path_entry)
                    providers_seen[provider] = entry.path_weight
        
        # Lines 15-26: Remove overlapping paths
        final_paths = []
        for i, path1 in enumerate(path_table_entries):
            keep_path = True
            for j, path2 in enumerate(path_table_entries):
                if i != j:
                    set1 = set(path1.node_id_set)
                    set2 = set(path2.node_id_set)
                    if set1 & set2:
                        if path1.path_weight < path2.path_weight:
                            keep_path = False
                            break
            if keep_path:
                final_paths.append(path1)
        
        return final_paths

# ===================== ROUTER CLASS =====================

class Router(Node):
    """Enhanced Router with Algorithm 1 & 2"""
    
    def __init__(self, name, alpha=0.9):
        super().__init__(name)
        self.resources = NodeResource()
        self.node_weight = Algorithm1_MultiPathExploration.calculate_node_weight(self)
        self.path_exploration_table = []
        self.path_table = []
        self.connections = []
        self.edge_links = {}
        self.caching_policy = 'RandomForest'
        self.alpha = alpha
        self.cs = []
        self.cache_hits = 0
        self.publisher_hits = 0
        self.total_requests = 0
    
    def can_provide_content(self, content_name):
        return content_name in self.cs or content_name in self.fib
    
    def update_node_weight(self):
        self.resources.update()
        self.node_weight = Algorithm1_MultiPathExploration.calculate_node_weight(self)
        return self.node_weight
    
    def algorithm1_multipath_exploration(self, content_name, all_nodes, timeout=10):
        """Execute Algorithm 1: Multipath Exploration"""
        print(f"\n{'='*70}")
        print(f"ALGORITHM 1: Multipath Exploration")
        print(f"{'='*70}")
        print(f"Router: {self.name} | Content: {content_name}")
        print(f"Starting from: {self.name}")
        
        exploration_entries = Algorithm1_MultiPathExploration.explore_paths_dfs(
            self, content_name, all_nodes, max_depth=5
        )
        
        self.path_exploration_table.extend(exploration_entries)
        
        print(f"\n✓ Found {len(exploration_entries)} paths to '{content_name}'")
        for i, entry in enumerate(exploration_entries, 1):
            path_str = ' → '.join(entry.node_id_set)
            print(f"  Path {i}: {path_str}")
            print(f"     Weight: {entry.path_weight:.4f} | Duration: {entry.connection_duration:.2f}s | "
                  f"Loss: {entry.packet_loss_rate:.3f} | Response: {entry.response_time:.3f}s")
        
        return exploration_entries
    
    def algorithm2_multipath_selection(self, content_name, threshold_weight=0.3):
        """Execute Algorithm 2: Multipath Selection"""
        print(f"\n{'='*70}")
        print(f"ALGORITHM 2: Multipath Selection")
        print(f"{'='*70}")
        print(f"Router: {self.name} | Content: {content_name}")
        print(f"Threshold Weight: {threshold_weight}")
        
        exploration_entries = [e for e in self.path_exploration_table if e.name == content_name]
        
        if not exploration_entries:
            print(f"✗ No exploration entries found for '{content_name}'")
            return []
        
        selected_paths = Algorithm2_MultiPathSelection.select_multipaths(
            self.path_exploration_table,
            content_name,
            threshold_weight
        )
        
        self.path_table.extend(selected_paths)
        
        print(f"\n✓ Selected {len(selected_paths)} optimal paths (from {len(exploration_entries)} explored)")
        for i, path_entry in enumerate(selected_paths, 1):
            path_str = ' → '.join(path_entry.node_id_set)
            print(f"  Selected Path {i}: {path_str}")
            print(f"     Weight: {path_entry.path_weight:.4f}")
        
        return selected_paths

class Publisher(Node):
    """Publisher node"""
    def __init__(self, name, num_contents=20):
        super().__init__(name)
        self.num_contents = num_contents
        self.contents = self.generate_contents()
    
    def generate_contents(self):
        contents = {}
        for i in range(self.num_contents):
            content_name = f"{self.name.lower()}_content_{i+1}"
            contents[content_name] = f"Data for {content_name}"
        return contents
    
    def can_provide_content(self, content_name):
        return content_name in self.contents

class Subscriber(Node):
    """Subscriber node"""
    def __init__(self, name):
        super().__init__(name)
        self.connected_router = None

# ===================== NETWORK SETUP =====================

def setup_network(num_routers=5, num_publishers=2):
    """Setup network topology"""
    routers = [Router(f'Router{i+1}') for i in range(num_routers)]
    publishers = [Publisher(f'Pub{i+1}', num_contents=10) for i in range(num_publishers)]
    subscriber = Subscriber('Sub1')
    
    subscriber.connected_router = routers[0]
    
    # Setup FIB
    all_content = {}
    for pub in publishers:
        all_content.update(pub.contents)
    
    for router in routers:
        router.fib = all_content.copy()
    
    # Connect routers
    for i in range(len(routers) - 1):
        routers[i].connections.append(routers[i + 1])
    
    all_nodes = {r.name: r for r in routers}
    all_nodes.update({p.name: p for p in publishers})
    all_nodes[subscriber.name] = subscriber
    
    return routers, publishers, subscriber, all_nodes

# ===================== SAVE RESULTS =====================

def save_results(router, content_name, exploration_entries, selected_paths):
    """Save Algorithm 1 & 2 results"""
    os.makedirs('Results', exist_ok=True)
    
    # Save exploration results
    with open('Results/Algorithm1_Exploration.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Content', 'Path', 'Path_Weight', 'Connection_Duration', 'Packet_Loss', 'Response_Time'])
        for entry in exploration_entries:
            writer.writerow([
                entry.name,
                '→'.join(entry.node_id_set),
                f"{entry.path_weight:.4f}",
                f"{entry.connection_duration:.2f}",
                f"{entry.packet_loss_rate:.3f}",
                f"{entry.response_time:.3f}"
            ])
    
    # Save selection results
    with open('Results/Algorithm2_Selection.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Content', 'Selected_Path', 'Path_Weight'])
        for entry in selected_paths:
            writer.writerow([
                entry.name,
                '→'.join(entry.node_id_set),
                f"{entry.path_weight:.4f}"
            ])
    
    print(f"\n✓ Results saved to Results/ directory")

# ===================== MAIN EXECUTION =====================

def main():
    """Main execution function"""
    print("\n" + "="*80)
    print(" INTEGRATED MULTIPATH ALGORITHM SIMULATOR")
    print(" Implementing Algorithm 1 & 2 from IEEE Research Paper")
    print("="*80)
    
    # Get user input
    print("\n📋 NETWORK CONFIGURATION:")
    while True:
        try:
            num_routers = int(input("Enter number of routers (minimum 3): "))
            if num_routers >= 3:
                break
            print("Please enter at least 3 routers.")
        except ValueError:
            print("Invalid input. Please enter a number.")
    
    while True:
        try:
            num_publishers = int(input("Enter number of publishers (minimum 1): "))
            if num_publishers >= 1:
                break
            print("Please enter at least 1 publisher.")
        except ValueError:
            print("Invalid input. Please enter a number.")
    
    # Setup network
    routers, publishers, subscriber, all_nodes = setup_network(num_routers, num_publishers)
    
    print(f"\n✓ Network created with {num_routers} routers and {num_publishers} publishers")
    print(f"  Routers: {[r.name for r in routers]}")
    print(f"  Publishers: {[p.name for p in publishers]}")
    
    # Update node weights
    print(f"\n📊 NODE WEIGHTS (Algorithm 1 Input):")
    for router in routers:
        router.update_node_weight()
        print(f"  {router.name}: Weight={router.node_weight:.4f}, Energy={router.resources.energy:.1f}%")
    
    # Select content
    sample_content = list(publishers[0].contents.keys())[0]
    print(f"\n🎯 Selected content: {sample_content}")
    
    # Execute Algorithm 1
    exploration_entries = routers[0].algorithm1_multipath_exploration(
        sample_content,
        all_nodes,
        timeout=10
    )
    
    # Execute Algorithm 2
    selected_paths = routers[0].algorithm2_multipath_selection(
        sample_content,
        threshold_weight=0.25
    )
    
    # Save results
    save_results(routers[0], sample_content, exploration_entries, selected_paths)
    
    print(f"\n{'='*80}")
    print(f"✓ SIMULATION COMPLETE!")
    print(f"{'='*80}")
    print(f"Algorithm 1 Results: {len(exploration_entries)} paths discovered")
    print(f"Algorithm 2 Results: {len(selected_paths)} optimal paths selected")
    print(f"Files saved to: Results/ directory")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
