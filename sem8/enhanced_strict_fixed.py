#!/usr/bin/env python3

"""


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

import io

import sys

# ===================== ALGORITHM CONSTANTS =====================

PATH_EXPLORATION_TIMEOUT = 10 # seconds

PATH_WEIGHT_THRESHOLD = 0.4 # Minimum acceptable path weight (40%)

NODE_WEIGHT_THRESHOLD = 0.3 # Minimum acceptable node weight (30%)

CONTENT_AVAILABILITY_THRESHOLD = 0.5

CONTENT_LIFETIME_THRESHOLD = 0.4

DATA_PART_SIZE = 50 # bytes per part

# Node resource constants for weight calculation

RESOURCE_ENERGY_WEIGHT = 0.4

RESOURCE_STORAGE_WEIGHT = 0.3

RESOURCE_BANDWIDTH_WEIGHT = 0.3

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

		self.node_weights = {} # Store weight of each node in path

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

		self.node_weights = {} # Weight of each node in this path

	def is_expired(self):

		return datetime.datetime.now() > self.creation_time + datetime.timedelta(seconds=self.lifetime)

class EdgeLink:

	"""Represents a link between two nodes with dynamic metrics for Algorithm 2"""

	def __init__(self, source, destination):

		self.source = source

		self.destination = destination

		self.connection_duration = random.uniform(5, 60)

		self.pending_requests = 0

		self.packet_loss_rate = random.uniform(0.0, 0.1)

		self.response_time = random.uniform(0.01, 0.5)

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

# ===================== ROUTER CLASS WITH ENHANCED ALGORITHM 1 & 2 =====================

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

		# ============ ENHANCED NODE WEIGHT CALCULATION ============

		# Node resources (simulated)

		self.energy_level = random.uniform(0.5, 1.0) # Energy level [0, 1]

		self.storage_capacity = random.uniform(0.4, 0.9) # Storage [0, 1]

		self.bandwidth_available = random.uniform(0.6, 1.0) # Bandwidth [0, 1]

		# Node weight = normalized product of resources

		self.node_weight = self._calculate_node_weight()

		self.resource_threshold = NODE_WEIGHT_THRESHOLD # Discard nodes below this

		self.path_exploration_table = []

		self.path_table = []

		self.edge_links = {}

		self.caching_node_id = {}

		self.node_position = (random.uniform(0, 100), random.uniform(0, 100))

		self.content_availability = {}

		self.content_lifetime = {}

		# RandomForest policy

		self.rf_policy = RandomForestCachingPolicy(cache_limit=Router.CACHE_LIMIT)

		self.reset()

		self.save_fib()

	def _calculate_node_weight(self):

		"""

		Calculate node weight as normalized product of node resources

		w(i) = normalize(energy × storage × bandwidth)

		"""

		product = self.energy_level * self.storage_capacity * self.bandwidth_available

		# Normalize to [0, 1]

		normalized_weight = product

		return normalized_weight

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

		"""

		Update node weight dynamically based on resource availability

		Simulates resource fluctuation

		"""

		# Simulate resource changes

		self.energy_level = max(0.1, min(1.0, self.energy_level + random.uniform(-0.05, 0.05)))

		self.storage_capacity = max(0.1, min(1.0, self.storage_capacity + random.uniform(-0.03, 0.03)))

		self.bandwidth_available = max(0.1, min(1.0, self.bandwidth_available + random.uniform(-0.04, 0.04)))

		# Recalculate node weight

		self.node_weight = self._calculate_node_weight()

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

		- Node weight = normalized product of resources

		- Discard nodes with weight < NODE_WEIGHT_THRESHOLD

		"""

		start_time = datetime.datetime.now()

		timeout = datetime.timedelta(seconds=exploration_timeout)

		exploration_entries = []

		s_k = [self.name]

		# Check requester's own weight

		if self.node_weight < NODE_WEIGHT_THRESHOLD:

			self.log_event(f"Algorithm 1: Own node weight {self.node_weight:.4f} < threshold {NODE_WEIGHT_THRESHOLD}, cannot explore")

			return exploration_entries

		# Explore paths to all providers

		for provider in provider_nodes:

			if not hasattr(provider, 'node_position'):

				provider.node_position = (random.uniform(0, 100), random.uniform(0, 100))

			exploration_entry = self._explore_path_to_provider(

				content_name,

				provider,

				s_k.copy(),

				provider.node_position,

				self.node_position

			)

			if exploration_entry:

				self.path_exploration_table = [e for e in self.path_exploration_table if not e.is_expired()]

				self.path_exploration_table.append(exploration_entry)

				exploration_entries.append(exploration_entry)

				self.log_event(

					f"Algorithm 1: Found path {' -> '.join(exploration_entry.node_id_set)} "

					f"(node weights: {exploration_entry.node_weights})"

				)

		self.log_event(f"Algorithm 1: Explored {len(exploration_entries)} paths for '{content_name}'")

		return exploration_entries

	def _explore_path_to_provider(self, content_name, provider, node_id_set, provider_pos, requester_pos):

		"""

		Subalgorithm-2: Explore single path to provider

		- Check distance-based stopping criterion

		- Check node weight threshold

		- Store node weights in path

		"""

		current_distance = math.sqrt((provider_pos[0] - requester_pos[0])**2 +

			(provider_pos[1] - requester_pos[1])**2)

		if provider.name not in node_id_set:

			node_id_set.append(provider.name)

		path_weight = self.node_weight * (1.0 - (current_distance / 200.0))

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

		exploration_entry.last_node_distance = current_distance

		# Store node weights for this path

		exploration_entry.node_weights = {self.name: self.node_weight}

		return exploration_entry

	# ============ ALGORITHM 2: STRICT MULTIPATH SELECTION ============

	def calculate_modified_path_weight(self, entry, all_entries):

		"""

		Calculate path weight using MODIFIED FORMULA for stability:

		p_t(a_k, s_k) = (d_t x (1 - l_t)) / (1 + q_t + o_t)

		This formula:

		- Rewards good connection duration and low packet loss

		- Penalizes pending requests and high response time

		- More stable than division-heavy formulas

		"""

		if not all_entries:

			return 0.5

		# Get max/min values for normalization

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

		# Normalize each metric to [0, 1]

		if max_duration + min_duration > 0:

			d_t = entry.connection_duration / (max_duration + min_duration)

		else:

			d_t = 0.5

		denominator = max(1, max_requests) + min_requests

		if denominator > 0:

			q_t = entry.pending_requests / denominator

		else:

			q_t = 0.0

		denominator = max(1, max_loss) + min_loss

		if denominator > 0:

			l_t = entry.packet_loss_rate / denominator

		else:

			l_t = 0.0

		denominator = max(1, max_time) + min_time

		if denominator > 0:

			o_t = entry.response_time / denominator

		else:

			o_t = 0.5

		# MODIFIED FORMULA: more stable and interpretable

		# p_t = (d_t × (1 - l_t)) / (1 + q_t + o_t)

		numerator = d_t * (1.0 - l_t)

		denominator = 1.0 + q_t + o_t

		path_weight = numerator / denominator if denominator > 0 else 0.0

		return min(1.0, max(0.0, path_weight))

	def _are_paths_disjoint(self, path1_nodes, path2_nodes):

		"""

		Check if two paths are completely disjoint (no shared nodes)

		Returns True if paths have NO common nodes (except maybe source)

		"""

		# Exclude the first node (requester) from comparison

		nodes1 = set(path1_nodes[1:])

		nodes2 = set(path2_nodes[1:])

		common_nodes = nodes1 & nodes2

		return len(common_nodes) == 0

	def multipath_selection(self, content_name,

		path_weight_threshold=PATH_WEIGHT_THRESHOLD,

		node_weight_threshold=NODE_WEIGHT_THRESHOLD):

		"""

		Algorithm 2: STRICT Multipath Selection using Path Weights

		CONSTRAINTS:

		1. Only DISJOINT paths (no shared nodes except source)

		2. Path weight >= PATH_WEIGHT_THRESHOLD

		3. All nodes in path >= NODE_WEIGHT_THRESHOLD (discard low-weight paths)

		4. Select best non-overlapping paths to different providers

		"""

		self.path_exploration_table = [e for e in self.path_exploration_table if not e.is_expired()]

		relevant_entries = [e for e in self.path_exploration_table if e.name == content_name]

		if not relevant_entries:

			self.log_event(f"Algorithm 2: No exploration entries for '{content_name}'")

			return []

		# STEP 1: Calculate path weights using modified formula

		self.log_event(f"Algorithm 2: ========== PATH SELECTION FOR '{content_name}' ==========")

		self.log_event(f"Algorithm 2: Total exploration entries: {len(relevant_entries)}")

		self.log_event(f"Algorithm 2: Path weight threshold: {path_weight_threshold:.2%}")

		self.log_event(f"Algorithm 2: Node weight threshold: {node_weight_threshold:.2%}")

		self.log_event(f"\\nAlgorithm 2: [STEP 1] Calculate path weights:")

		weighted_entries = []

		for i, entry in enumerate(relevant_entries):

			path_weight = self.calculate_modified_path_weight(entry, relevant_entries)

			entry.path_weight = path_weight

			weighted_entries.append(entry)

			path_str = ' -> '.join(entry.node_id_set)

			self.log_event(f" Path {i+1}: {path_str}")

			self.log_event(f" Weight: {path_weight:.4f} (threshold: {path_weight_threshold:.4f})")

			self.log_event(f" Metrics - Duration: {entry.connection_duration:.2f}s, "

				f"Loss: {entry.packet_loss_rate:.3f}, Response: {entry.response_time:.4f}s")

		# STEP 2: Filter by weight threshold

		self.log_event(f"\\nAlgorithm 2: [STEP 2] Filter by weight threshold >= {path_weight_threshold:.2%}:")

		above_threshold = [e for e in weighted_entries if e.path_weight >= path_weight_threshold]

		for entry in above_threshold:

			path_str = ' -> '.join(entry.node_id_set)

			self.log_event(f" OK {path_str} (weight: {entry.path_weight:.4f})")

		below_threshold = [e for e in weighted_entries if e.path_weight < path_weight_threshold]

		for entry in below_threshold:

			path_str = ' -> '.join(entry.node_id_set)

			self.log_event(f" REJECTED: {path_str} (weight: {entry.path_weight:.4f} < {path_weight_threshold:.4f})")

		# STEP 3: Group by provider and select best path per provider

		self.log_event(f"\\nAlgorithm 2: [STEP 3] Select best path per provider:")

		selected_by_provider = {}

		for entry in sorted(above_threshold, key=lambda x: x.path_weight, reverse=True):

			provider_id = entry.node_id_set[-1]

			if provider_id not in selected_by_provider:

				selected_by_provider[provider_id] = entry

				path_str = ' -> '.join(entry.node_id_set)

				self.log_event(f" OK Provider '{provider_id}': {path_str} (weight: {entry.path_weight:.4f})")

		selected_paths = list(selected_by_provider.values())

		# STEP 4: STRICT DISJOINT PATH FILTERING

		# Keep only paths that have NO shared nodes with other selected paths

		self.log_event(f"\\nAlgorithm 2: [STEP 4] Enforce DISJOINT paths (no shared nodes):")

		final_selected_paths = []

		for i, path_i in enumerate(selected_paths):

			is_disjoint = True

			conflicts = []

			for j, path_j in enumerate(selected_paths):

				if i != j and path_i in final_selected_paths:

					# Check if already selected path shares nodes with current path

					if not self._are_paths_disjoint(path_i.node_id_set, path_j.node_id_set):

						conflicts.append(j)

			if not conflicts:

				final_selected_paths.append(path_i)

				path_str = ' -> '.join(path_i.node_id_set)

				self.log_event(f" OK SELECTED: {path_str}")

				self.log_event(f" Weight: {path_i.path_weight:.4f}, Nodes: {path_i.node_id_set}")

		# Log rejected paths due to node overlap

		rejected_count = len(selected_paths) - len(final_selected_paths)

		if rejected_count > 0:

			self.log_event(f"\\nAlgorithm 2: [STEP 4] Paths REJECTED due to node overlap: {rejected_count}")

			for entry in selected_paths:

				if entry not in final_selected_paths:

					path_str = ' -> '.join(entry.node_id_set)

					# Find which selected path it conflicts with

					for selected in final_selected_paths:

						if not self._are_paths_disjoint(entry.node_id_set, selected.node_id_set):

							self.log_event(f" REJECTED {path_str} conflicts with {' -> '.join(selected.node_id_set)}")

							break

		# Create path table entries for final selected paths

		self.log_event(f"\\nAlgorithm 2: ========== FINAL SELECTION SUMMARY ==========")

		self.log_event(f"Algorithm 2: Total paths explored: {len(weighted_entries)}")

		self.log_event(f"Algorithm 2: Paths above weight threshold: {len(above_threshold)}")

		self.log_event(f"Algorithm 2: Paths selected for transmission: {len(final_selected_paths)}")

		for i, path_entry_src in enumerate(final_selected_paths, 1):

			path_entry = PathTableEntry(

				name=path_entry_src.name,

				node_id_set=path_entry_src.node_id_set,

				lifetime=path_entry_src.lifetime

			)

			path_entry.path_weight = path_entry_src.path_weight

			self.path_table.append(path_entry)

			self.log_event(f"\\n[SELECTED PATH {i}]")

			self.log_event(f" Route: {' -> '.join(path_entry.node_id_set)}")

			self.log_event(f" Weight: {path_entry.path_weight:.4f}")

			self.log_event(f" Hops: {len(path_entry.node_id_set) - 1}")

		return final_selected_paths

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

		self.log_event(f"Data split: '{content_name}' -> {total_parts} parts ({part_size}B each)")

		return parts

	def transmit_data_over_multipaths(self, content_name, content_data, selected_paths):

		"""

		Transmit data parts over selected DISJOINT multipaths

		Each path carries balanced number of parts

		"""

		if not selected_paths:

			self.log_event(f"No selected paths for transmission of '{content_name}'")

			return []

		data_parts = self.split_data_into_parts(content_name, content_data)

		if not data_parts:

			return []

		transmission_results = []

		parts_per_path = math.ceil(len(data_parts) / len(selected_paths))

		self.log_event(f"\\nData transmission over {len(selected_paths)} DISJOINT paths:")

		for path_idx, path in enumerate(selected_paths, 1):

			start_part = (path_idx - 1) * parts_per_path

			end_part = min(path_idx * parts_per_path, len(data_parts))

			path_str = ' -> '.join(path.node_id_set)

			self.log_event(f" Path {path_idx}: {path_str}")

			for part_idx in range(start_part, end_part):

				if part_idx < len(data_parts):

					part = data_parts[part_idx]

					part.path_used = path.node_id_set

					part.transmitted = True

					transmission_results.append(part)

					self.log_event(f" +--> Part {part.part_number}/{part.total_parts} ({len(part.data)} bytes)")

		return transmission_results

	def receive_interest(self, interest_packet, subscriber):

		"""Handle incoming interest packets with multipath support"""

		content_id = ContentIDManager.get_unique_id(interest_packet.name)

		self.content_popularity[interest_packet.name] += 1

		self.log_event(f"\\n>>> Interest received: '{interest_packet.name}' from {subscriber.name}")

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

			providers = [p for p in self.connections if hasattr(p, 'contents')]

			exploration_entries = self.multipath_exploration(

				interest_packet.name,

				providers if providers else [self]

			)

			selected_paths = self.multipath_selection(interest_packet.name)

			transmission_results = self.transmit_data_over_multipaths(

				interest_packet.name,

				interest_packet.name,

				selected_paths if selected_paths else exploration_entries

			)

			data_packet = DataPacket(

				name=interest_packet.name,

				content=interest_packet.name

			)

			self.log_event(f"OK Cache HIT: Serving via {len(selected_paths)} disjoint paths\\n")

			subscriber.receive_data(data_packet)

			return

		# Cache miss

		self.publisher_hits += 1

		self.log_event(f"NOT Cache MISS: Fetching from network")

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

						exploration_entries = self.multipath_exploration(

							interest_packet.name,

							[next_hop]

						)

						selected_paths = self.multipath_selection(interest_packet.name)

						transmission_results = self.transmit_data_over_multipaths(

							data_packet.name,

							data_packet.content,

							selected_paths if selected_paths else exploration_entries

						)

						self.receive_data(data_packet)

						subscriber.receive_data(data_packet)

						self.log_event(f"\\nOK Content delivered via {len(selected_paths)} disjoint paths\\n")

						return

	def receive_data(self, data_packet):

		"""Handle incoming data packets with RandomForest caching"""

		current_time = datetime.datetime.now()

		for content, expiry_time in list(self.cache_ttl.items()):

			if current_time > expiry_time:

				if content in self.cs:

					self.cs.remove(content)

					self.cache_ttl.pop(content)

					self.log_event(f"Content '{content}' expired")

		ttl = current_time + datetime.timedelta(minutes=5)

		self.cache_ttl[data_packet.name] = ttl

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

		if data_packet.name not in self.cs:

			self.cs.append(data_packet.name)

			self.cache_access_times[data_packet.name] = current_time

			self.cache_frequency[data_packet.name] += 1

			self.save_cs()

			self.update_popularity(data_packet.name)

			self.rank_content()

			self.save_popularity_table()

		content_id = ContentIDManager.get_unique_id(data_packet.name)

		self.log_event(f"Cached '{data_packet.name}'")

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

		with open(f'{fib_dir}/fib.csv', mode='w', newline='', encoding='utf-8') as file:

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

		with open(f'{pit_dir}/pit.csv', mode='w', newline='', encoding='utf-8') as file:

			writer = csv.writer(file)

			writer.writerow(["Name", "ID", "Requester"])

			for name, requester in self.pit.items():

				content_id = ContentIDManager.get_unique_id(name)

				writer.writerow([name, content_id, requester])

	def save_cs(self):

		cs_dir = os.path.join('Output/CS', self.name)

		os.makedirs(cs_dir, exist_ok=True)

		with open(f'{cs_dir}/cs.csv', mode='w', newline='', encoding='utf-8') as file:

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

		"""
		FIX: Write log files with UTF-8 encoding to handle special characters
		Replaces Unicode arrows with ASCII equivalents if needed
		"""

		os.makedirs('Logs', exist_ok=True)

		# Replace Unicode arrow with ASCII arrow for Windows compatibility
		message = message.replace(u'\u2192', '->')

		try:

			with open(f'Logs/log_{self.name}.txt', 'a', encoding='utf-8') as log_file:

				log_file.write(f"{message}\n")

		except Exception as e:

			# Fallback: write with errors='replace' if UTF-8 fails

			with open(f'Logs/log_{self.name}.txt', 'a', encoding='utf-8', errors='replace') as log_file:

				log_file.write(f"{message}\n")

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

	- Variable number of ROUTERS

	- Variable number of PUBLISHERS

	- Variable number of SUBSCRIBERS

	- Multiple paths with strict selection

	"""

	if use_saved and os.path.exists("Saved_Network/network_setup.pkl"):

		choice = input("Use existing network? (yes/no): ").strip().lower()

		if choice == 'yes':

			result = load_network()

			if result:

				print("Loaded existing network.\\n")

				return result

	if num_routers < 3:

		num_routers = 3

	if num_publishers < 1:

		num_publishers = 1

	if num_subscribers < 1:

		num_subscribers = 1

	print(f"\\n=== NETWORK CONFIGURATION ===")

	print(f"Routers: {num_routers}")

	print(f"Publishers: {num_publishers}")

	print(f"Subscribers: {num_subscribers}")

	print(f"PATH_WEIGHT_THRESHOLD: {PATH_WEIGHT_THRESHOLD:.2%}")

	print(f"NODE_WEIGHT_THRESHOLD: {NODE_WEIGHT_THRESHOLD:.2%}")

	print(f"================================\\n")

	routers = [Router(f'Router{i+1}') for i in range(num_routers)]

	publishers = [Publisher(f'Publisher{i+1}', num_contents=50) for i in range(num_publishers)]

	subscribers = [Subscriber(f'Subscriber{i+1}') for i in range(num_subscribers)]

	for idx, subscriber in enumerate(subscribers):

		central_router = routers[idx % num_routers]

		subscriber.connected_router = central_router

		print(f"Subscriber '{subscriber.name}' -> Router '{central_router.name}'")

	print()

	ContentIDManager.initialize_index(publishers)

	all_contents = []

	for publisher in publishers:

		all_contents.extend(publisher.contents.keys())

	print(f"Total content: {len(all_contents)}\\n")

	for i, router in enumerate(routers):

		router.connections = publishers.copy()

		next_hops = []

		for j in range(i + 1, min(i + 4, num_routers)):

			next_hops.append(routers[j])

			router.add_edge_link(routers[j])

		if not next_hops:

			next_hops = publishers

		for content in all_contents:

			router.fib[content] = next_hops

	save_network(routers, publishers, subscribers)

	print(f"Network created and saved.\\n")

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

	plt.title(f"Multipath Network with STRICT Selection\\n(Disjoint paths, Weight-based, Node filtering)",

		fontsize=14, fontweight='bold')

	plt.axis('off')

	plt.tight_layout()

	os.makedirs('output', exist_ok=True)

	plt.savefig('output/network_topology_strict.png', dpi=300, bbox_inches='tight')

	plt.show()

	print("Network topology saved.\\n")

	plt.close()

def run_multipath_simulation(routers, publishers, subscribers, iterations):

	"""Run simulation with strict Algorithm 1 & 2"""

	for router in routers:

		router.caching_policy = 'RandomForest'

		router.reset()

	all_contents = []

	for publisher in publishers:

		all_contents.extend(publisher.contents.keys())

	print(f"\\nRunning {iterations} iterations...\\n")

	simulation_data = []

	active_prob = 0.95

	for iteration in range(iterations):

		print(f"=== Iteration {iteration + 1}/{iterations} ===")

		for router in routers:

			router.update_node_weight()

		for link in router.edge_links.values():

			link.update_metrics()

		for subscriber in subscribers:

			subscriber.active = random.random() < active_prob

			if subscriber.active and all_contents:

				content = random.choice(all_contents)

				router = subscriber.connected_router

				providers = routers + publishers

				exploration_entries = router.multipath_exploration(content, providers)

				selected_paths = router.multipath_selection(content)

				interest_packet = InterestPacket(name=content)

				subscriber.send_interest(interest_packet, router)

		total_requests = sum(r.cache_hits + r.publisher_hits for r in routers)

		total_cache_hits = sum(r.cache_hits for r in routers)

		avg_cache_hit = (total_cache_hits / total_requests * 100) if total_requests > 0 else 0

		total_paths = sum(len(r.path_table) for r in routers)

		total_exploration = sum(len(r.path_exploration_table) for r in routers)

		print(f" Cache Hit: {avg_cache_hit:.2f}%")

		print(f" Explored Paths: {total_exploration}")

		print(f" Selected Paths (DISJOINT): {total_paths}\\n")

		simulation_data.append([

			datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

			len(subscribers),

			total_requests,

			total_exploration,

			total_paths,

			avg_cache_hit,

			'StrictSelection'

		])

	return simulation_data

def save_multipath_results(all_simulation_data, num_routers, num_subscribers, num_publishers, iterations):

	"""Save simulation results"""

	os.makedirs('Simulation_Results/StrictSelection', exist_ok=True)

	filename = f'Simulation_Results/StrictSelection/Results_{num_routers}r_{num_publishers}p_{num_subscribers}s_{iterations}i.csv'

	with open(filename, mode='w', newline='', encoding='utf-8') as file:

		writer = csv.writer(file)

		writer.writerow([

			"Simulation Time",

			"Subscribers",

			"Total Requests",

			"Explored Paths",

			"Selected Disjoint Paths",

			"Cache Hit Ratio (%)",

			"Method"

		])

		writer.writerows(all_simulation_data)

	print(f"\\nResults saved to {filename}\\n")

def get_user_input():

	"""Get all network parameters from user"""

	print("\\n" + "="*70)

	print("STRICT MULTIPATH CDN SIMULATOR")

	print("="*70 + "\\n")

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

	while True:

		try:

			num_subscribers = int(input("Enter number of subscribers (minimum 1): "))

			if num_subscribers >= 1:

				break

			print("Please enter at least 1 subscriber.")

		except ValueError:

			print("Invalid input. Please enter a number.")

	while True:

		try:

			iterations = int(input("Enter number of iterations (minimum 5): "))

			if iterations >= 5:

				break

			print("Please enter at least 5 iterations.")

		except ValueError:

			print("Invalid input. Please enter a number.")

	return num_routers, num_publishers, num_subscribers, iterations

def main():

	# Clear previous logs

	import shutil

	if os.path.exists('Logs'):

		shutil.rmtree('Logs')

	num_routers, num_publishers, num_subscribers, iterations = get_user_input()

	routers, publishers, subscribers = setup_network_with_multipaths(

		num_routers,

		num_publishers,

		num_subscribers,

		use_saved=False

	)

	plot_network_with_multipaths(routers, publishers, subscribers)

	simulation_data = run_multipath_simulation(routers, publishers, subscribers, iterations)

	save_multipath_results(simulation_data, num_routers, num_subscribers, num_publishers, iterations)

	print("="*70)

	print("OK SIMULATION COMPLETE!")

	print("="*70)

	print(f"\\nNetwork: {num_routers}R, {num_publishers}P, {num_subscribers}S, {iterations} iterations")

	print(f"Path Selection: STRICT (Disjoint, Weight-filtered, Node-filtered)")

	print(f"\\nOutput:")

	print(f" • Network: output/network_topology_strict.png")

	print(f" • Results: Simulation_Results/StrictSelection/")
	print(f" • Logs: Logs/log_Router*.txt (detailed path selection)")
	print("="*70 + "\\n")

if __name__ == "__main__":

	main()
