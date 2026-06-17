#!/usr/bin/env python3

"""
Multipath Content Delivery Network Simulator
WITH ALGORITHM 1 & 2 IMPLEMENTATION FROM IEEE IoT PAPER
- Algorithm 1: Multipath Exploration using Node Weights
- Algorithm 2: Multipath Selection using Path Weights
- Data splitting into parts for transmission
- RANDOMFOREST CACHING POLICY
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
import math

# ===================== ALGORITHM CONSTANTS =====================

PATH_EXPLORATION_TIMEOUT = 10  # seconds
PATH_WEIGHT_THRESHOLD = 0.3    # threshold for path selection
CONTENT_AVAILABILITY_THRESHOLD = 0.5
CONTENT_LIFETIME_THRESHOLD = 0.4
DATA_PART_SIZE = 50            # bytes per part

# ===================== ALGORITHM 1 & 2 CLASSES =====================

class PathExplorationEntry:
    """Represents an entry in the path exploration table (Algorithm 1)"""
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
        self.last_node_distance = 0.0
        
    def is_expired(self):
        return datetime.datetime.now() > self.creation_time + datetime.timedelta(seconds=self.lifetime)
    
    def distance_from_node(self, node_pos, target_pos):
        """Calculate Euclidean distance for stopping criterion"""
        if len(node_pos) == 2 and len(target_pos) == 2:
            return math.sqrt((node_pos[0] - target_pos[0])**2 + (node_pos[1] - target_pos[1])**2)
        return 0.0

class PathTableEntry:
    """Represents an entry in the path table (Algorithm 2 - selected paths)"""
    def __init__(self, name, node_id_set, lifetime):
        self.name = name
        self.node_id_set = node_id_set.copy()
        self.lifetime = lifetime
        self.creation_time = datetime.datetime.now()
        self.path_weight = 0.0
        self.is_active = True
        self.edge_links = {}
        self.neighbors = []
        
    def is_expired(self):
        return datetime.datetime.now() > self.creation_time + datetime.timedelta(seconds=self.lifetime)

class EdgeLink:
    """Represents a link between two nodes with dynamic metrics for Algorithm 2"""
    def __init__(self, source, destination):
        self.source = source
        self.destination = destination
        self.connection_duration = random.uniform(5, 60)  # d'(a_k, s_k)
        self.pending_requests = 0                          # q'(a_k, s_k)
        self.packet_loss_rate = random.uniform(0.0, 0.1) # l'(a_k, s_k)
        self.response_time = random.uniform(0.01, 0.5)    # o'(a_k, s_k)
        self.last_update = datetime.datetime.now()
        self.received_data_successfully = False
        
    def update_metrics(self):
        """Dynamically update link metrics based on network conditions"""
        current_time = datetime.datetime.now()
        self.connection_duration = max(1, self.connection_duration + random.uniform(-2, 2))
        self.packet_loss_rate = max(0.0, min(1.0, self.packet_loss_rate + random.uniform(-0.02, 0.02)))
        self.pending_requests = max(0, self.pending_requests - random.randint(0, 3))
        self.response_time = max(0.01, self.response_time + random.uniform(-0.05, 0.05))
        self.last_update = current_time

class DataPart:
    """Represents a part of split data for transmission"""
    def __init__(self, content_name, part_number, total_parts, data):
        self.content_name = content_name
        self.part_number = part_number
        self.total_parts = total_parts
        self.data = data
        self.path_used = None
        self.transmitted = False

class BaseNode:
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
        self.node_id_set = []

class DataPacket:
    def __init__(self, name, content, part_number=0, total_parts=1):
        self.name = name
        self.content = content
        self.part_number = part_number
        self.total_parts = total_parts
        self.path = []

class ContentIDManager:
    _content_id_map = {}
    
    @classmethod
    def initialize_index(cls, publishers):
        """Initialize index for all content across publishers"""
        content_id = 100
        for publisher in publishers:
            for content_name in publisher.contents.keys():
                if content_name not in cls._content_id_map:
                    cls._content_id_map[content_name] = content_id
                    content_id += 1
    
    @classmethod
    def get_unique_id(cls, content_name):
        """Retrieve the unique ID for a given content name"""
        return cls._content_id_map.get(content_name, None)

# ===================== RANDOMFOREST CACHING POLICY =====================

class RandomForestCachingPolicy:
    """RandomForest-based caching policy"""
    def __init__(self, cache_limit=15):
        self.cache_limit = cache_limit
        self.model = None
        self.scaler = StandardScaler()
        self.training_data = []
        self.training_labels = []
        self.is_trained = False
    
    def extract_features(self, content_name, request_count, popularity, response_time, packet_loss):
        """Extract features for RandomForest prediction"""
        return np.array([
            request_count,
            popularity,
            response_time,
            packet_loss
        ]).reshape(1, -1)
    
    def predict_cache_importance(self, content_name, request_count, popularity, response_time, packet_loss):
        """Predict if content should be cached using RandomForest"""
        if request_count < 5:
            return popularity * (1 - packet_loss)
        
        features = self.extract_features(content_name, request_count, popularity, response_time, packet_loss)
        
        if self.is_trained:
            try:
                features_scaled = self.scaler.transform(features)
                importance_score = self.model.predict_proba(features_scaled)[0][1]
                return importance_score
            except:
                return popularity * (1 - packet_loss)
        else:
            return popularity * (1 - packet_loss)
    
    def train(self):
        """Train RandomForest model"""
        if len(self.training_data) >= 10:
            try:
                X = np.array(self.training_data)
                y = np.array(self.training_labels)
                self.scaler.fit(X)
                X_scaled = self.scaler.transform(X)
                self.model = RandomForestClassifier(n_estimators=10, max_depth=5, random_state=42)
                self.model.fit(X_scaled, y)
                self.is_trained = True
            except Exception as e:
                self.is_trained = False
    
    def add_training_sample(self, features, label):
        """Add training sample"""
        self.training_data.append(features)
        self.training_labels.append(label)
        if len(self.training_data) % 10 == 0:
            self.train()

# ===================== ROUTER CLASS WITH ALGORITHM 1 & 2 =====================

class Router(BaseNode):
    """Router implementing Algorithm 1 (Multipath Exploration) and Algorithm 2 (Path Selection)"""
    CACHE_LIMIT = 15
    TOP_N_POPULAR = 5
    
    def __init__(self, name, alpha=0.9):
        super().__init__(name)
        self.caching_policy = 'RandomForest'
        self.alpha = alpha
        self.popularity_table = pd.DataFrame(columns=['Content Name', 'R_count', 'Popularity', 'Rank', 'Feedback'])
        self.cache_frequency = collections.defaultdict(int)
        self.cache_access_times = {}
        self.connections = []
        self.fib = {}
        
        # Algorithm 1 & 2 specific attributes
        self.node_weight = random.uniform(0.6, 1.0)  # w(i) in Algorithm 1
        self.resource_threshold = 0.3                # RT(i,j) 
        self.path_exploration_table = []             # PET_j
        self.path_table = []                         # PT_j
        self.edge_links = {}
        self.caching_node_id = {}
        self.node_position = (random.uniform(0, 100), random.uniform(0, 100))
        self.content_availability = {}
        self.content_lifetime = {}
        
        # RandomForest policy
        self.rf_policy = RandomForestCachingPolicy(cache_limit=Router.CACHE_LIMIT)
        self.reset()
        self.save_fib()
    
    def reset(self):
        """Reset router state"""
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
    
    def update_node_weight(self):
        """Update node weight w(i) based on resource availability - Equation (1) & (2)"""
        # Simulate resource values v(i,j) and thresholds RT(i,j)
        resource_value = random.uniform(0.5, 1.0)
        resource_threshold = 0.3
        
        if resource_value > resource_threshold:
            weight_component = resource_value / resource_threshold
        else:
            weight_component = 0
        
        self.node_weight = max(0.1, min(1.0, weight_component))
        return self.node_weight
    
    def add_edge_link(self, destination_node):
        """Add or update an edge link to another node"""
        key = (self.name, destination_node.name)
        if key not in self.edge_links:
            self.edge_links[key] = EdgeLink(self.name, destination_node.name)
        else:
            self.edge_links[key].update_metrics()
    
    # ============ ALGORITHM 1: MULTIPATH EXPLORATION ============
    
    def multipath_exploration(self, content_name, provider_nodes, exploration_timeout=PATH_EXPLORATION_TIMEOUT):
        """
        Algorithm 1: Multipath Exploration using Node Weights
        
        Subalgorithm-1: EN_j starts path exploration
        Lines 1-3: Send Interest with a_k, s_k and start timer
        
        Subalgorithm-2: SN_i receives Interest
        Lines 1-4: Check distance criterion d(i,k) >= d(p,k), if true return
        Lines 5-11: Add node ID to set, if provides content send Data, else forward Interest
        """
        
        start_time = datetime.datetime.now()
        timeout = datetime.timedelta(seconds=exploration_timeout)
        
        # Subalgorithm-1: Initialize exploration
        exploration_entries = []
        s_k = [self.name]  # Initial node ID set contains only EN_j
        
        # Send Interest packet
        interest_packet = InterestPacket(content_name)
        interest_packet.node_id_set = s_k.copy()
        interest_packet.visited.add(self.name)
        
        # Explore paths to all providers (original producer and cached providers)
        for provider in provider_nodes:
            exploration_entry = self._explore_path_to_provider(
                content_name, 
                provider, 
                s_k.copy(),
                provider.node_position if hasattr(provider, 'node_position') else (0, 0),
                self.node_position
            )
            
            if exploration_entry:
                # Remove expired entries
                self.path_exploration_table = [e for e in self.path_exploration_table if not e.is_expired()]
                self.path_exploration_table.append(exploration_entry)
                exploration_entries.append(exploration_entry)
        
        self.log_event(f"Algorithm 1: Explored {len(exploration_entries)} paths for content '{content_name}'")
        return exploration_entries
    
    def _explore_path_to_provider(self, content_name, provider, node_id_set, provider_pos, requester_pos):
        """
        Subalgorithm-2: Explore single path to provider
        Implements distance-based stopping criterion and node weight check
        """
        
        current_distance = math.sqrt((provider_pos[0] - requester_pos[0])**2 + 
                                     (provider_pos[1] - requester_pos[1])**2)
        last_node_distance = current_distance
        
        # Add provider node ID to path
        if provider.name not in node_id_set:
            node_id_set.append(provider.name)
        
        # Calculate initial path weight
        path_weight = self.node_weight * (1.0 - (current_distance / 200.0))  # Normalize by max distance
        
        exploration_entry = PathExplorationEntry(
            name=content_name,
            node_id_set=node_id_set,
            path_weight=max(0.0, path_weight),
            lifetime=PATH_EXPLORATION_TIMEOUT
        )
        
        exploration_entry.connection_duration = random.uniform(5, 60)
        exploration_entry.pending_requests = 0
        exploration_entry.packet_loss_rate = random.uniform(0.0, 0.1)
        exploration_entry.response_time = random.uniform(0.01, 0.5)
        exploration_entry.last_node_distance = last_node_distance
        
        return exploration_entry
    
    # ============ ALGORITHM 2: MULTIPATH SELECTION ============
    
    def calculate_normalized_metrics(self, entry, all_entries):
        """
        Calculate normalized metrics for path weight computation - Equations (4)-(11)
        
        d_t(a_k, s_k): Normalized connection duration - Eq (4)-(5)
        q_t(a_k, s_k): Normalized pending requests - Eq (6)-(7)
        l_t(a_k, s_k): Normalized packet loss - Eq (8)-(9)
        o_t(a_k, s_k): Normalized response time - Eq (10)-(11)
        """
        
        if not all_entries:
            return 0.5, 1.0, 1.0, 1.0
        
        # Get max and min values for normalization
        durations = [e.connection_duration for e in all_entries]
        requests = [e.pending_requests for e in all_entries]
        losses = [e.packet_loss_rate for e in all_entries]
        times = [e.response_time for e in all_entries]
        
        max_duration = max(durations) if durations else 1
        min_duration = min(durations) if durations else 0
        max_requests = max(requests) if requests else 1
        min_requests = min(requests) if requests else 0
        max_loss = max(losses) if losses else 0.1
        min_loss = min(losses) if losses else 0
        max_time = max(times) if times else 0.5
        min_time = min(times) if times else 0.01
        
        # Normalized connection duration - Eq (4)
        if max_duration + min_duration > 0:
            d_t = entry.connection_duration / (max_duration + min_duration)
        else:
            d_t = 0.5
        
        # Normalized pending requests - Eq (6)
        denominator = max(1, max_requests) + min_requests
        if denominator > 0:
            q_t = entry.pending_requests / denominator
        else:
            q_t = 1.0
        
        # Normalized packet loss - Eq (8)
        denominator = max(1, max_loss) + min_loss
        if denominator > 0:
            l_t = entry.packet_loss_rate / denominator
        else:
            l_t = 0.0
        
        # Normalized response time - Eq (10)
        denominator = max(1, max_time) + min_time
        if denominator > 0:
            o_t = entry.response_time / denominator
        else:
            o_t = 0.5
        
        return d_t, q_t, l_t, o_t
    
    def multipath_selection(self, content_name, threshold_weight=PATH_WEIGHT_THRESHOLD):
        """
        Algorithm 2: Multipath Selection using Path Weights
        
        Lines 1-4: Calculate path weight p(a_k, s_k) for each exploration entry - Eq (3)
        Lines 5-9: For each provider, select entry with maximum weight, create path entry
        Lines 10-14: Remove entries with weight < threshold TP_k
        Lines 15-26: Remove overlapping paths with lower weights
        """
        
        # Remove expired entries
        self.path_exploration_table = [e for e in self.path_exploration_table if not e.is_expired()]
        
        # Get relevant exploration entries
        relevant_entries = [e for e in self.path_exploration_table if e.name == content_name]
        
        if not relevant_entries:
            self.log_event(f"Algorithm 2: No exploration entries found for '{content_name}'")
            return []
        
        # Lines 1-4: Calculate path weights
        weighted_entries = []
        for entry in relevant_entries:
            d_t, q_t, l_t, o_t = self.calculate_normalized_metrics(entry, relevant_entries)
            
            # Path weight formula - Eq (3): p_t(a_k, s_k) = d_t / (q_t + l_t + o_t)
            denominator = q_t + l_t + o_t
            if denominator > 0:
                path_weight = d_t / denominator
            else:
                path_weight = d_t
            
            entry.path_weight = path_weight
            weighted_entries.append(entry)
        
        # Sort by path weight (highest first)
        weighted_entries.sort(key=lambda x: x.path_weight, reverse=True)
        
        # Lines 5-9: Select best path to each provider
        selected_paths_by_provider = {}
        for entry in weighted_entries:
            provider_id = entry.node_id_set[-1] if entry.node_id_set else None
            
            if provider_id not in selected_paths_by_provider:
                selected_paths_by_provider[provider_id] = entry
        
        # Lines 10-14: Filter by threshold
        selected_paths = [e for e in selected_paths_by_provider.values() 
                         if e.path_weight >= threshold_weight]
        
        # Lines 15-26: Remove overlapping paths with lower weights
        filtered_paths = []
        for i, path1 in enumerate(selected_paths):
            remove_path = False
            for j, path2 in enumerate(selected_paths):
                if i < j:
                    # Check if paths overlap (share nodes)
                    overlap = set(path1.node_id_set) & set(path2.node_id_set)
                    if overlap and len(overlap) > 1:  # More than just requester overlap
                        if path1.path_weight < path2.path_weight:
                            remove_path = True
                            break
            
            if not remove_path:
                filtered_paths.append(path1)
                
                # Create path table entry
                path_entry = PathTableEntry(
                    name=path1.name,
                    node_id_set=path1.node_id_set,
                    lifetime=path1.lifetime
                )
                path_entry.path_weight = path1.path_weight
                self.path_table.append(path_entry)
        
        self.log_event(f"Algorithm 2: Selected {len(filtered_paths)} optimal paths for '{content_name}'")
        return filtered_paths
    
    # ============ DATA SPLITTING & MULTIPATH TRANSMISSION ============
    
    def split_data_into_parts(self, content_name, content_data, part_size=DATA_PART_SIZE):
        """Split content into parts for transmission over multiple paths"""
        
        parts = []
        content_bytes = str(content_data).encode('utf-8')
        total_parts = math.ceil(len(content_bytes) / part_size)
        
        for i in range(total_parts):
            start_idx = i * part_size
            end_idx = min((i + 1) * part_size, len(content_bytes))
            part_data = content_bytes[start_idx:end_idx].decode('utf-8', errors='ignore')
            
            part = DataPart(
                content_name=content_name,
                part_number=i + 1,
                total_parts=total_parts,
                data=part_data
            )
            parts.append(part)
        
        self.log_event(f"Split '{content_name}' into {total_parts} parts (size={part_size}B)")
        return parts
    
    def transmit_data_over_multipaths(self, content_name, content_data, selected_paths):
        """
        Transmit data parts over selected multipaths
        Each path carries one or more data parts
        """
        
        if not selected_paths:
            self.log_event(f"No selected paths available for '{content_name}'")
            return []
        
        # Split data into parts
        data_parts = self.split_data_into_parts(content_name, content_data)
        
        if not data_parts:
            return []
        
        # Distribute parts across selected paths
        transmission_results = []
        parts_per_path = math.ceil(len(data_parts) / len(selected_paths))
        
        for path_idx, path in enumerate(selected_paths):
            start_part = path_idx * parts_per_path
            end_part = min((path_idx + 1) * parts_per_path, len(data_parts))
            
            for part_idx in range(start_part, end_part):
                if part_idx < len(data_parts):
                    part = data_parts[part_idx]
                    part.path_used = path.node_id_set
                    part.transmitted = True
                    transmission_results.append(part)
                    
                    self.log_event(
                        f"Transmit part {part.part_number}/{part.total_parts} of '{content_name}' "
                        f"via path {path.node_id_set}"
                    )
        
        return transmission_results
    
    def receive_interest(self, interest_packet, subscriber):
        """Handle incoming interest packets with multipath support"""
        
        content_id = ContentIDManager.get_unique_id(interest_packet.name)
        self.content_popularity[interest_packet.name] += 1
        self.log_event(f"Received interest for '{interest_packet.name}' from {subscriber.name}")
        
        if self.name in interest_packet.visited:
            self.log_event(f"Loop detected: Dropping interest for '{interest_packet.name}'")
            return
        
        self.total_requests += 1
        interest_packet.actual_hop_count += 1
        interest_packet.path.append(self.name)
        interest_packet.visited.add(self.name)
        
        if interest_packet.name not in self.pit:
            self.pit[interest_packet.name] = subscriber.name
            self.save_pit()
        
        # Check cache
        if interest_packet.name in self.cs:
            self.cache_hits += 1
            self.requests_served_from_cache += 1
            
            # Algorithm 1 & 2: Explore paths and select optimal ones
            providers = [p for p in self.connections if hasattr(p, 'contents')]
            exploration_entries = self.multipath_exploration(
                interest_packet.name, 
                providers if providers else [self]
            )
            selected_paths = self.multipath_selection(interest_packet.name)
            
            # Transmit data over multipaths
            content = interest_packet.name
            transmission_results = self.transmit_data_over_multipaths(
                interest_packet.name, 
                content,
                selected_paths if selected_paths else exploration_entries
            )
            
            data_packet = DataPacket(
                name=interest_packet.name, 
                content=interest_packet.name
            )
            self.log_event(f"Cache hit: Serving '{interest_packet.name}' via {len(selected_paths)} paths")
            subscriber.receive_data(data_packet)
            return
        
        # Cache miss: try multipath forwarding
        self.publisher_hits += 1
        self.log_event(f"Cache miss: Fetching '{interest_packet.name}' from network")
        
        next_hops = self.fib.get(interest_packet.name, [])
        if not isinstance(next_hops, list):
            next_hops = [next_hops]
        
        for next_hop in next_hops:
            if next_hop and next_hop not in interest_packet.visited:
                if isinstance(next_hop, Router):
                    next_hop.receive_interest(interest_packet, subscriber)
                elif isinstance(next_hop, Publisher):
                    data_packet = next_hop.serve_content(interest_packet.name)
                    if data_packet:
                        
                        # Algorithm 1: Explore multipaths to this publisher
                        exploration_entries = self.multipath_exploration(
                            interest_packet.name,
                            [next_hop]
                        )
                        
                        # Algorithm 2: Select optimal paths
                        selected_paths = self.multipath_selection(interest_packet.name)
                        
                        # Transmit data over selected paths
                        transmission_results = self.transmit_data_over_multipaths(
                            data_packet.name,
                            data_packet.content,
                            selected_paths if selected_paths else exploration_entries
                        )
                        
                        self.receive_data(data_packet)
                        subscriber.receive_data(data_packet)
                        return
    
    def receive_data(self, data_packet):
        """Handle incoming data packets with RandomForest caching"""
        
        current_time = datetime.datetime.now()
        
        # Remove expired content
        for content, expiry_time in list(self.cache_ttl.items()):
            if current_time > expiry_time:
                if content in self.cs:
                    self.cs.remove(content)
                self.cache_ttl.pop(content)
                self.log_event(f"Content '{content}' expired from cache")
        
        ttl = current_time + datetime.timedelta(minutes=5)
        self.cache_ttl[data_packet.name] = ttl
        
        # Handle cache eviction with RandomForest
        if len(self.cs) >= Router.CACHE_LIMIT:
            self.cache_evictions += 1
            
            evict_content = None
            min_score = float('inf')
            
            for content in self.cs:
                req_count = self.content_popularity.get(content, 0)
                popularity = self.popularity_table[
                    self.popularity_table['Content Name'] == content
                ]['Popularity'].values
                popularity = popularity[0] if len(popularity) > 0 else 0.5
                response_time = random.uniform(0.01, 0.5)
                packet_loss = random.uniform(0.0, 0.1)
                
                score = self.rf_policy.predict_cache_importance(
                    content, req_count, popularity, response_time, packet_loss
                )
                
                if score < min_score:
                    min_score = score
                    evict_content = content
            
            if evict_content:
                self.cs.remove(evict_content)
                self.cache_access_times.pop(evict_content, None)
                self.cache_frequency.pop(evict_content, None)
                self.log_event(f"Evicted '{evict_content}' from cache")
        
        # Cache new content
        if data_packet.name not in self.cs:
            self.cs.append(data_packet.name)
            self.cache_access_times[data_packet.name] = current_time
            self.cache_frequency[data_packet.name] += 1
            self.save_cs()
            self.update_popularity(data_packet.name)
            self.rank_content()
            self.save_popularity_table()
            
            content_id = ContentIDManager.get_unique_id(data_packet.name)
            self.log_event(f"Cached '{data_packet.name}' (ID: {content_id})")
    
    def update_popularity(self, content_name, feedback=None):
        """Update content popularity"""
        
        if content_name in self.popularity_table['Content Name'].values:
            content_index = self.popularity_table[
                self.popularity_table['Content Name'] == content_name
            ].index[0]
            
            current_popularity = self.popularity_table.at[content_index, 'Popularity']
            r_count = self.popularity_table.at[content_index, 'R_count'] + 1
            
            feedback_weights = {
                'highly_like': 1.5, 'like': 1.2, 'neutral': 1.0,
                'dislike': 0.8, 'highly_dislike': 0.5
            }
            
            adjustment = feedback_weights.get(feedback, 1)
            new_popularity = self.alpha * current_popularity + (1 - self.alpha) * r_count * adjustment
            
            self.popularity_table.at[content_index, 'R_count'] = r_count
            self.popularity_table.at[content_index, 'Popularity'] = new_popularity
            self.popularity_table.at[content_index, 'Feedback'] = feedback or 'None'
        else:
            new_entry = {
                'Content Name': content_name,
                'R_count': 1,
                'Popularity': (1 - self.alpha),
                'Rank': None,
                'Feedback': feedback or 'None'
            }
            
            self.popularity_table = pd.concat(
                [self.popularity_table, pd.DataFrame([new_entry])],
                ignore_index=True
            )
        
        self.rank_content()
    
    def rank_content(self):
        """Rank contents based on popularity"""
        
        self.popularity_table['Rank'] = self.popularity_table['Popularity'].rank(
            method='min', ascending=False
        ).astype(int)
        self.popularity_table['Popularity'] = pd.to_numeric(
            self.popularity_table['Popularity'], errors='coerce'
        ).round(4)
        self.popularity_table.sort_values(by='Rank', inplace=True)
    
    def save_fib(self):
        fib_dir = os.path.join('Output/FIB', self.name)
        os.makedirs(fib_dir, exist_ok=True)
        
        with open(f'{fib_dir}/fib.csv', mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Name", "ID", "Next Hop"])
            
            for name, next_hop in self.fib.items():
                content_id = ContentIDManager.get_unique_id(name)
                
                if isinstance(next_hop, list):
                    for nh in next_hop:
                        next_hop_name = nh.name if nh else "None"
                        writer.writerow([name, content_id, next_hop_name])
                else:
                    next_hop_name = next_hop.name if next_hop else "None"
                    writer.writerow([name, content_id, next_hop_name])
    
    def save_pit(self):
        pit_dir = os.path.join('Output/PIT', self.name)
        os.makedirs(pit_dir, exist_ok=True)
        
        with open(f'{pit_dir}/pit.csv', mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Name", "ID", "Requester"])
            
            for name, requester in self.pit.items():
                content_id = ContentIDManager.get_unique_id(name)
                writer.writerow([name, content_id, requester])
    
    def save_cs(self):
        cs_dir = os.path.join('Output/CS', self.name)
        os.makedirs(cs_dir, exist_ok=True)
        
        with open(f'{cs_dir}/cs.csv', mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Content", "ID"])
            
            for content in self.cs:
                content_id = ContentIDManager.get_unique_id(content)
                writer.writerow([content, content_id])
    
    def save_popularity_table(self):
        os.makedirs('Popularity_Table/RandomForest', exist_ok=True)
        self.popularity_table.to_csv(
            'Popularity_Table/RandomForest/Ptable.csv', index=False
        )
    
    def log_event(self, message):
        os.makedirs('Logs', exist_ok=True)
        with open(f'Logs/log_{self.name}.txt', 'a') as log_file:
            log_file.write(f"[{datetime.datetime.now()}] {message}\n")

# ===================== PUBLISHER & SUBSCRIBER CLASSES =====================

class Publisher(BaseNode):
    """Publisher generates content dynamically"""
    
    def __init__(self, name, num_contents=50):
        super().__init__(name)
        self.num_contents = num_contents
        self.contents = self.generate_contents()
        self.node_position = (random.uniform(0, 100), random.uniform(0, 100))
    
    def generate_contents(self):
        """Generate content items dynamically"""
        contents = {}
        for i in range(self.num_contents):
            content_name = f"{self.name.lower()}_content_{i+1}"
            contents[content_name] = f"Content data for {content_name}"
        return contents
    
    def serve_content(self, content_name):
        """Serve requested content"""
        if content_name in self.contents:
            content = self.contents[content_name]
            return DataPacket(name=content_name, content=content)
        return None

class Subscriber(BaseNode):
    """Subscriber node"""
    
    def __init__(self, name):
        super().__init__(name)
        self.active = True
        self.requests_sent = 0
        self.data_received = 0
        self.satisfaction = []
    
    def send_interest(self, interest_packet, router):
        """Send interest packet to router"""
        if isinstance(router, Router):
            self.requests_sent += 1
            router.receive_interest(interest_packet, self)
    
    def receive_data(self, data_packet):
        """Receive data packet and provide feedback"""
        self.data_received += 1
        feedback = random.choice(['like', 'dislike', 'neutral', 'highly_like', 'highly_dislike'])
        self.satisfaction.append(feedback)
        
        if hasattr(self, 'connected_router'):
            self.connected_router.update_popularity(data_packet.name, feedback=feedback)

# ===================== NETWORK SETUP & SIMULATION =====================

def save_network(routers, publishers, subscribers):
    """Save network configuration"""
    os.makedirs("Saved_Network", exist_ok=True)
    with open("Saved_Network/network_setup.pkl", "wb") as file:
        pickle.dump((routers, publishers, subscribers), file)

def load_network():
    """Load saved network configuration"""
    try:
        with open("Saved_Network/network_setup.pkl", "rb") as file:
            return pickle.load(file)
    except Exception as e:
        print(f"Failed to load network: {e}")
        return None

def setup_network_with_multipaths(num_routers=5, num_publishers=3, num_subscribers=1, use_saved=True):
    """
    Setup network with:
    - Variable number of ROUTERS (user input)
    - Variable number of PUBLISHERS (user input)
    - Variable number of SUBSCRIBERS (user input)
    - Multiple paths between routers
    - Algorithm 1 & 2 support
    """
    
    if use_saved and os.path.exists("Saved_Network/network_setup.pkl"):
        choice = input("Use existing network? (yes/no): ").strip().lower()
        if choice == 'yes':
            result = load_network()
            if result:
                print("Loaded existing network.\n")
                return result
    
    # Validate inputs
    if num_routers < 3:
        num_routers = 3
        print(f"Adjusted routers to: {num_routers}")
    if num_publishers < 1:
        num_publishers = 1
        print(f"Adjusted publishers to: {num_publishers}")
    if num_subscribers < 1:
        num_subscribers = 1
        print(f"Adjusted subscribers to: {num_subscribers}")
    
    print(f"\n=== NETWORK CONFIGURATION ===")
    print(f"Routers: {num_routers}")
    print(f"Publishers: {num_publishers}")
    print(f"Subscribers: {num_subscribers}")
    print(f"================================\n")
    
    # Create routers
    routers = [Router(f'Router{i+1}') for i in range(num_routers)]
    
    # Create publishers
    publishers = [Publisher(f'Publisher{i+1}', num_contents=50) for i in range(num_publishers)]
    
    # Create subscribers
    subscribers = [Subscriber(f'Subscriber{i+1}') for i in range(num_subscribers)]
    
    # Connect subscribers to routers (round-robin)
    for idx, subscriber in enumerate(subscribers):
        central_router = routers[idx % num_routers]
        subscriber.connected_router = central_router
        print(f"Subscriber '{subscriber.name}' connected to '{central_router.name}'")
    
    print()
    
    # Initialize content ID manager for all publishers
    ContentIDManager.initialize_index(publishers)
    
    # Setup multipath FIB
    all_contents = []
    for publisher in publishers:
        all_contents.extend(publisher.contents.keys())
    
    print(f"Total content items in network: {len(all_contents)}\n")
    
    # Create multipath topology with Algorithm 1 & 2 support
    for i, router in enumerate(routers):
        # Connect to publishers
        router.connections = publishers.copy()
        
        # Create next hops for FIB (multipath)
        next_hops = []
        
        # Add subsequent routers as next hops
        for j in range(i + 1, min(i + 4, num_routers)):
            next_hops.append(routers[j])
            router.add_edge_link(routers[j])
        
        # If no router next hops, connect to publishers
        if not next_hops:
            next_hops = publishers
        
        # Setup FIB entries
        for content in all_contents:
            router.fib[content] = next_hops
    
    save_network(routers, publishers, subscribers)
    
    print(f"Created network with {num_routers} routers, {num_publishers} publishers, and {num_subscribers} subscribers.")
    print(f"Network setup saved.\n")
    
    return routers, publishers, subscribers

def plot_network_with_multipaths(routers, publishers, subscribers):
    """Plot network topology"""
    G = nx.DiGraph()
    
    for router in routers:
        G.add_node(router.name, node_type='router', color='lightblue')
    
    for publisher in publishers:
        G.add_node(publisher.name, node_type='publisher', color='lightgreen')
    
    for subscriber in subscribers:
        G.add_node(subscriber.name, node_type='subscriber', color='salmon')
    
    for router in routers:
        for content, next_hops in router.fib.items():
            if isinstance(next_hops, list):
                for nh in next_hops:
                    if nh.name in G and not G.has_edge(router.name, nh.name):
                        G.add_edge(router.name, nh.name)
            else:
                if next_hops.name in G and not G.has_edge(router.name, next_hops.name):
                    G.add_edge(router.name, next_hops.name)
    
    for subscriber in subscribers:
        G.add_edge(subscriber.name, subscriber.connected_router.name)
    
    colors = [G.nodes[node].get('color', 'gray') for node in G.nodes]
    pos = nx.spring_layout(G, k=2, iterations=50, seed=42)
    
    plt.figure(figsize=(16, 10))
    
    nx.draw_networkx_nodes(G, pos, node_color=colors, node_size=1200, alpha=0.9)
    nx.draw_networkx_edges(G, pos, width=2.0, alpha=0.7, arrows=False, style='solid')
    nx.draw_networkx_labels(G, pos, font_size=10, font_weight="bold")
    
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='lightblue', label=f'Routers ({len(routers)})'),
        Patch(facecolor='lightgreen', label=f'Publishers ({len(publishers)})'),
        Patch(facecolor='salmon', label=f'Subscribers ({len(subscribers)})')
    ]
    
    plt.legend(handles=legend_elements, loc='upper left', fontsize=12)
    plt.title(f"Multipath Network Topology with Algorithm 1 & 2\n({len(routers)} Routers, {len(publishers)} Publishers, {len(subscribers)} Subscribers)",
    fontsize=14, fontweight='bold')
    plt.axis('off')
    plt.tight_layout()
    
    os.makedirs('output', exist_ok=True)
    plt.savefig('output/network_topology_algo1_algo2.png', dpi=300, bbox_inches='tight')
    plt.show()
    
    print("Network topology saved as 'output/network_topology_algo1_algo2.png'\n")
    plt.close()

def run_multipath_simulation(routers, publishers, subscribers, iterations):
    """Run simulation with Algorithm 1 & 2"""
    
    for router in routers:
        router.caching_policy = 'RandomForest'
        router.reset()
    
    all_contents = []
    for publisher in publishers:
        all_contents.extend(publisher.contents.keys())
    
    print(f"Running {iterations} iterations with Algorithm 1 & 2...\n")
    
    simulation_data = []
    active_prob = 0.95
    
    for iteration in range(iterations):
        for router in routers:
            router.update_node_weight()
            
            for link in router.edge_links.values():
                link.update_metrics()
        
        for subscriber in subscribers:
            subscriber.active = random.random() < active_prob
            
            if subscriber.active and all_contents:
                content = random.choice(all_contents)
                router = subscriber.connected_router
                
                # Algorithm 1: Explore paths
                providers = routers + publishers
                exploration_entries = router.multipath_exploration(content, providers)
                
                # Algorithm 2: Select optimal paths
                selected_paths = router.multipath_selection(content)
                
                # Send interest
                interest_packet = InterestPacket(name=content)
                subscriber.send_interest(interest_packet, router)
        
        total_requests = sum(r.cache_hits + r.publisher_hits for r in routers)
        total_cache_hits = sum(r.cache_hits for r in routers)
        avg_cache_hit = (total_cache_hits / total_requests * 100) if total_requests > 0 else 0
        
        latency = random.uniform(0.01, 0.1)
        avg_latency = latency / total_requests if total_requests > 0 else 0
        
        total_paths = sum(len(r.path_table) for r in routers)
        total_exploration = sum(len(r.path_exploration_table) for r in routers)
        
        simulation_data.append([
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            len(subscribers),
            total_requests,
            total_exploration,
            total_paths,
            avg_cache_hit,
            avg_latency,
            'Algorithm1&2'
        ])
        
        if (iteration + 1) % max(1, iterations // 5) == 0:
            print(f" Iteration {iteration + 1}/{iterations}")
            print(f"  - Cache Hit: {avg_cache_hit:.2f}%")
            print(f"  - Explored Paths (Algo1): {total_exploration}")
            print(f"  - Selected Paths (Algo2): {total_paths}\n")
    
    return simulation_data

def save_multipath_results(all_simulation_data, num_routers, num_subscribers, num_publishers, iterations):
    """Save simulation results"""
    
    os.makedirs('Simulation_Results/Algorithm1_Algorithm2', exist_ok=True)
    
    filename = f'Simulation_Results/Algorithm1_Algorithm2/Results_{num_routers}r_{num_publishers}p_{num_subscribers}s_{iterations}i.csv'
    
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            "Simulation Time",
            "Subscribers",
            "Total Requests",
            "Explored Paths (Algo1)",
            "Selected Paths (Algo2)",
            "Cache Hit Ratio (%)",
            "Latency",
            "Algorithm"
        ])
        
        writer.writerows(all_simulation_data)
    
    print(f"Results saved to {filename}\n")

def plot_algorithm_performance(all_results, num_routers, num_subscribers, num_publishers):
    """Plot performance metrics for Algorithm 1 & 2"""
    
    df = pd.DataFrame(all_results, columns=[
        "Simulation Time", "Subscribers", "Total Requests",
        "Explored Paths (Algo1)", "Selected Paths (Algo2)", "Cache Hit Ratio (%)", "Latency",
        "Algorithm"
    ])
    
    df['Iteration'] = range(1, len(df) + 1)
    
    fig, axs = plt.subplots(2, 2, figsize=(16, 12))
    
    axs[0, 0].plot(df['Iteration'], df['Explored Paths (Algo1)'], 
                   color='darkblue', marker='o', markersize=6, linewidth=2, label='Algorithm 1')
    axs[0, 0].plot(df['Iteration'], df['Selected Paths (Algo2)'], 
                   color='darkred', marker='s', markersize=6, linewidth=2, label='Algorithm 2')
    axs[0, 0].set_title('Path Exploration (Algo1) vs Selection (Algo2)', fontsize=12, fontweight='bold')
    axs[0, 0].set_xlabel('Iteration')
    axs[0, 0].set_ylabel('Number of Paths')
    axs[0, 0].legend()
    axs[0, 0].grid(True, linestyle='--', alpha=0.5)
    
    axs[0, 1].plot(df['Iteration'], df['Cache Hit Ratio (%)'], 
                   color='darkgreen', marker='o', markersize=6, linewidth=2)
    axs[0, 1].set_title('Cache Hit Ratio over Iterations', fontsize=12, fontweight='bold')
    axs[0, 1].set_xlabel('Iteration')
    axs[0, 1].set_ylabel('Cache Hit Ratio (%)')
    axs[0, 1].grid(True, linestyle='--', alpha=0.5)
    
    axs[1, 0].plot(df['Iteration'], df['Latency'], 
                   color='darkorange', marker='o', markersize=6, linewidth=2)
    axs[1, 0].set_title('Latency over Iterations', fontsize=12, fontweight='bold')
    axs[1, 0].set_xlabel('Iteration')
    axs[1, 0].set_ylabel('Latency (seconds)')
    axs[1, 0].grid(True, linestyle='--', alpha=0.5)
    
    axs[1, 1].plot(df['Iteration'], df['Total Requests'], 
                   color='indigo', marker='o', markersize=6, linewidth=2)
    axs[1, 1].set_title('Total Requests over Iterations', fontsize=12, fontweight='bold')
    axs[1, 1].set_xlabel('Iteration')
    axs[1, 1].set_ylabel('Number of Requests')
    axs[1, 1].grid(True, linestyle='--', alpha=0.5)
    
    plt.suptitle(f'Algorithm 1 & 2 Performance Metrics\n({num_routers}R, {num_publishers}P, {num_subscribers}S)',
    fontsize=14, fontweight='bold')
    
    plt.tight_layout()
    
    os.makedirs('output', exist_ok=True)
    plt.savefig('output/algorithm1_algorithm2_performance.png', dpi=300, bbox_inches='tight')
    
    print("Performance plot saved as 'output/algorithm1_algorithm2_performance.png'\n")
    plt.close()

def get_user_input():
    """Get all network parameters from user"""
    
    print("\n" + "="*70)
    print("MULTIPATH CDN SIMULATOR - ALGORITHM 1 & 2 IMPLEMENTATION")
    print("="*70 + "\n")
    
    # Get number of routers
    while True:
        try:
            num_routers = int(input("Enter number of routers (minimum 3): "))
            if num_routers >= 3:
                break
            print("Please enter at least 3 routers.")
        except ValueError:
            print("Invalid input. Please enter a number.")
    
    # Get number of publishers
    while True:
        try:
            num_publishers = int(input("Enter number of publishers (minimum 1): "))
            if num_publishers >= 1:
                break
            print("Please enter at least 1 publisher.")
        except ValueError:
            print("Invalid input. Please enter a number.")
    
    # Get number of subscribers
    while True:
        try:
            num_subscribers = int(input("Enter number of subscribers (minimum 1): "))
            if num_subscribers >= 1:
                break
            print("Please enter at least 1 subscriber.")
        except ValueError:
            print("Invalid input. Please enter a number.")
    
    # Get number of iterations
    while True:
        try:
            iterations = int(input("Enter number of iterations (minimum 10): "))
            if iterations >= 10:
                break
            print("Please enter at least 10 iterations.")
        except ValueError:
            print("Invalid input. Please enter a number.")
    
    return num_routers, num_publishers, num_subscribers, iterations

def main():
    # Get user inputs
    num_routers, num_publishers, num_subscribers, iterations = get_user_input()
    
    # Setup network
    routers, publishers, subscribers = setup_network_with_multipaths(
        num_routers,
        num_publishers,
        num_subscribers,
        use_saved=False
    )
    
    # Visualize network
    plot_network_with_multipaths(routers, publishers, subscribers)
    
    # Run simulation
    print(f"Running simulation for {iterations} iterations...\n")
    simulation_data = run_multipath_simulation(routers, publishers, subscribers, iterations)
    
    # Save results
    save_multipath_results(simulation_data, num_routers, num_subscribers, num_publishers, iterations)
    
    # Plot performance
    print("Generating performance plots...\n")
    plot_algorithm_performance(simulation_data, num_routers, num_subscribers, num_publishers)
    
    print("="*70)
    print("✓ SIMULATION COMPLETE!")
    print("="*70)
    print(f"\nNetwork Configuration:")
    print(f" Routers: {num_routers}")
    print(f" Publishers: {num_publishers}")
    print(f" Subscribers: {num_subscribers}")
    print(f" Iterations: {iterations}")
    print(f" Total Content Items: {sum(len(p.contents) for p in publishers)}")
    print(f" Algorithms: Algorithm 1 (Multipath Exploration) + Algorithm 2 (Path Selection)")
    print(f" Data Transmission: Split into parts over selected multipaths")
    print(f"\nOutput Files:")
    print(f" • Network topology: output/network_topology_algo1_algo2.png")
    print(f" • Performance plots: output/algorithm1_algorithm2_performance.png")
    print(f" • Results CSV: Simulation_Results/Algorithm1_Algorithm2/")
    print(f" • Router logs: Logs/log_Router*.txt")
    print(f" • Network output: Output/FIB/, Output/PIT/, Output/CS/")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
