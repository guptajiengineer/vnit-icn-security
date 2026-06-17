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
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier

# ===================== ENHANCED MULTIPATH CLASSES =====================

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
        self.weight = random.uniform(0.5, 1.0)  # Dynamic weight between 0.5 and 1.0
        self.connection_duration = random.uniform(5, 60)  # in seconds
        self.packet_loss_rate = random.uniform(0.0, 0.1)  # 0-10% loss
        self.pending_requests = 0
        self.response_time = random.uniform(0.01, 0.5)  # in seconds
        self.last_update = datetime.datetime.now()

    def update_weight(self):
        """Dynamically update link weight based on network conditions"""
        current_time = datetime.datetime.now()
        time_diff = (current_time - self.last_update).total_seconds()

        # Update metrics with some variation
        self.weight = max(0.1, self.weight + random.uniform(-0.1, 0.1))
        self.packet_loss_rate = max(0.0, min(1.0, self.packet_loss_rate + random.uniform(-0.02, 0.02)))
        self.pending_requests = max(0, self.pending_requests - random.randint(0, 3))
        self.response_time = max(0.01, self.response_time + random.uniform(-0.05, 0.05))
        self.last_update = current_time

    def get_normalized_weight(self):
        """Normalize weight to 0-1 scale"""
        return np.clip(self.weight, 0, 1)

# Base classes for Network elements
class Node:
    def __init__(self, name):
        self.name = name
        self.fib = {}  # Forwarding Information Base
        self.pit = {}  # Pending Interest Table
        self.cs = []   # Content Store

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
    def initialize_index(cls, publishers):
        """Initialize index for all images across publishers"""
        image_id = 100
        for publisher in publishers:
            for image_name in publisher.images.keys():
                if image_name not in cls._content_id_map:
                    cls._content_id_map[image_name] = image_id
                    image_id += 1

    @classmethod
    def get_unique_id(cls, content_name):
        """Retrieve the unique ID for a given content name"""
        return cls._content_id_map.get(content_name, None)

# ===================== ENHANCED ROUTER CLASS =====================

class Router(Node):
    CACHE_LIMIT = 15
    TOP_N_POPULAR = 5

    def __init__(self, name, caching_policy='LRU', alpha=0.9):
        super().__init__(name)
        self.caching_policy = caching_policy
        self.alpha = alpha
        self.popularity_table = pd.DataFrame(columns=['Content Name', 'R_count', 'Popularity', 'Rank', 'Feedback'])
        self.cache_frequency = collections.defaultdict(int)
        self.cache_access_times = {}
        self.connections = []
        self.fib = {}

        # NEW: Multipath & Resource tracking
        self.node_weight = random.uniform(0.6, 1.0)  # Node resource availability
        self.resource_threshold = 0.3  # Minimum resource threshold
        self.path_exploration_table = []  # PET: stores path exploration entries
        self.path_table = []  # PT: stores selected paths
        self.edge_links = {}  # Maps (source, dest) to EdgeLink objects
        self.caching_node_id = {}  # Tracks where content should be cached

        self.reset()
        self.save_fib()

    def reset(self):
        """Reset the router's cache and statistics"""
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
        """Update node weight based on resource availability"""
        self.node_weight = max(0.1, self.node_weight + random.uniform(-0.1, 0.1))
        return self.node_weight

    def add_edge_link(self, destination_node):
        """Add or update an edge link to another node"""
        key = (self.name, destination_node.name)
        if key not in self.edge_links:
            self.edge_links[key] = EdgeLink(self.name, destination_node.name)
        else:
            self.edge_links[key].update_weight()

    def multipath_exploration(self, content_name, exploration_timeout=10):
        """
        Algorithm 1: Multipath Exploration using Node Weights
        Discovers multiple paths to content providers
        """
        start_time = datetime.datetime.now()
        timeout = datetime.timedelta(seconds=exploration_timeout)

        interest_packet = InterestPacket(content_name)
        interest_packet.visited.add(self.name)

        # Create exploration entry with initial node weight
        exploration_entry = PathExplorationEntry(
            name=content_name,
            node_id_set=[self.name],
            path_weight=self.node_weight,
            lifetime=exploration_timeout
        )

        self.path_exploration_table.append(exploration_entry)
        return exploration_entry

    def multipath_selection(self, content_name, threshold_weight=0.3):
        """
        Algorithm 2: Multipath Selection using Path Weights
        Selects optimal paths based on normalized path weights
        """
        # Find all exploration entries for this content
        relevant_entries = [
            e for e in self.path_exploration_table 
            if e.name == content_name and not e.is_expired()
        ]

        if not relevant_entries:
            return []

        # Calculate path weights for each entry
        weighted_entries = []
        for entry in relevant_entries:
            # Normalize metrics (equations 4-11 from paper)
            d_t = self._normalize_connection_duration(entry)
            q_t = self._normalize_pending_requests(entry)
            l_t = self._normalize_packet_loss(entry)
            o_t = self._normalize_response_time(entry)

            # Combined path weight (equation 3)
            path_weight = d_t + q_t + l_t + o_t
            entry.path_weight = path_weight / 4.0  # Normalize to 0-1
            weighted_entries.append(entry)

        # Sort by path weight (highest first) and filter by threshold
        weighted_entries.sort(key=lambda x: x.path_weight, reverse=True)
        selected_paths = [
            e for e in weighted_entries 
            if e.path_weight >= threshold_weight
        ]

        # Create path table entries
        for entry in selected_paths:
            path_entry = PathTableEntry(
                name=entry.name,
                node_id_set=entry.node_id_set,
                lifetime=entry.lifetime
            )
            path_entry.path_weight = entry.path_weight
            self.path_table.append(path_entry)

        return selected_paths

    def calculate_caching_weight(self, content_name, path_set, content_lifetime=300):
        """
        Algorithm 3: Calculate caching weight based on:
        - Content availability across multiple paths
        - Content lifetime characteristics
        """
        # Calculate content availability (equation 14)
        num_paths = len(path_set)
        if num_paths == 0:
            return 0.0

        availability = num_paths / max(1, num_paths)  # Simplified: more paths = better availability

        # Normalize content lifetime (equation 15)
        current_time = datetime.datetime.now().timestamp()
        lifetime_factor = min(1.0, content_lifetime / 300.0)  # Normalize to 300s default

        # Caching weight (equation 16)
        caching_weight = availability * lifetime_factor
        return caching_weight

    def _normalize_connection_duration(self, entry):
        """Normalize connection duration (equations 4-5)"""
        if entry.connection_duration == 0:
            return 0.5
        return min(1.0, entry.connection_duration / 60.0)

    def _normalize_pending_requests(self, entry):
        """Normalize pending requests (equations 6-7)"""
        if entry.pending_requests == 0:
            return 1.0
        return min(1.0, 1.0 / (1.0 + entry.pending_requests))

    def _normalize_packet_loss(self, entry):
        """Normalize packet loss rate (equations 8-9)"""
        return max(0.0, 1.0 - entry.packet_loss_rate)

    def _normalize_response_time(self, entry):
        """Normalize response time (equations 10-11)"""
        if entry.response_time == 0:
            return 1.0
        return min(1.0, 0.5 / entry.response_time)

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

    def receive_interest(self, interest_packet, subscriber):
        """Handle incoming interest packets with multipath support"""
        content_id = ContentIDManager.get_unique_id(interest_packet.name)
        self.content_popularity[interest_packet.name] += 1
        self.log_event(f"Received interest for {interest_packet.name} from {subscriber.name}")

        if self.name in interest_packet.visited:
            self.log_event(f"Loop detected: Dropping interest for {interest_packet.name}")
            return

        self.total_requests += 1

        if not hasattr(interest_packet, 'actual_hop_count'):
            interest_packet.actual_hop_count = 0

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
            data_packet = DataPacket(name=interest_packet.name, content=interest_packet.name)
            self.log_event(f"Cache hit: Serving {interest_packet.name}")
            subscriber.receive_data(data_packet)
            return

        # Cache miss: try multipath forwarding
        self.publisher_hits += 1
        self.log_event(f"Cache miss: Fetching {interest_packet.name}")

        # Use path table for multipath forwarding
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
                        self.receive_data(data_packet)
                        subscriber.receive_data(data_packet)
                        return

    def receive_data(self, data_packet):
        """Handle incoming data packets"""
        current_time = datetime.datetime.now()

        # Remove expired content
        for content, expiry_time in list(self.cache_ttl.items()):
            if current_time > expiry_time:
                if content in self.cs:
                    self.cs.remove(content)
                self.cache_ttl.pop(content)
                self.log_event(f"Content {content} expired")

        ttl = current_time + datetime.timedelta(minutes=5)
        self.cache_ttl[data_packet.name] = ttl

        # Handle cache eviction
        if len(self.cs) >= Router.CACHE_LIMIT:
            self.cache_evictions += 1
            if self.caching_policy == 'FACR':
                top_5_popular = set(self.popularity_table.head(5)['Content Name'])
                non_reserved_cache = [item for item in self.cs if item not in top_5_popular]
                if non_reserved_cache:
                    to_remove = non_reserved_cache[0]
                    self.cs.remove(to_remove)
                    self.cache_access_times.pop(to_remove, None)
                    self.cache_frequency.pop(to_remove, None)
            elif self.caching_policy == 'LRU':
                if self.cache_access_times:
                    lru_content = min(self.cache_access_times, key=self.cache_access_times.get)
                    self.cs.remove(lru_content)
                    self.cache_access_times.pop(lru_content)
            elif self.caching_policy == 'LFU':
                if self.cache_frequency:
                    lfu_content = min(self.cache_frequency, key=self.cache_frequency.get)
                    self.cs.remove(lfu_content)
                    self.cache_frequency.pop(lfu_content)
            elif self.caching_policy == 'FIFO' and self.cs:
                self.cs.pop(0)
            elif self.caching_policy == 'MRU':
                if self.cache_access_times:
                    mru_content = max(self.cache_access_times, key=self.cache_access_times.get)
                    self.cs.remove(mru_content)
                    self.cache_access_times.pop(mru_content)

        # Cache new content
        if data_packet.name not in self.cs:
            self.cs.append(data_packet.name)

            if self.caching_policy in ['LRU', 'MRU']:
                self.cache_access_times[data_packet.name] = current_time
            elif self.caching_policy == 'LFU':
                self.cache_frequency[data_packet.name] += 1

        self.save_cs()
        self.update_popularity(data_packet.name)
        self.rank_content()
        self.save_popularity_table(self.caching_policy)

        content_id = ContentIDManager.get_unique_id(data_packet.name)
        self.log_event(f"Cached {data_packet.name} (ID: {content_id})")

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

    def save_popularity_table(self, policy):
        os.makedirs(f'Popularity_Table/{policy}', exist_ok=True)
        self.popularity_table.to_csv(
            f'Popularity_Table/{policy}/Ptable.csv', index=False
        )

    def log_event(self, message):
        os.makedirs('Logs', exist_ok=True)
        with open(f'Logs/log_{self.name}.txt', 'a') as log_file:
            log_file.write(f"[{datetime.datetime.now()}] {message}\n")

# ===================== PUBLISHER & SUBSCRIBER CLASSES =====================

class Publisher(Node):
    def __init__(self, name, folder):
        super().__init__(name)
        self.folder = folder
        self.images = self.load_images()

    def load_images(self):
        images = {}
        os.makedirs(self.folder, exist_ok=True)
        image_files = [f for f in os.listdir(self.folder) if os.path.isfile(os.path.join(self.folder, f))]
        for image_name in image_files:
            file_path = os.path.join(self.folder, image_name)
            images[image_name] = file_path
        return images

    def serve_content(self, content_name):
        if content_name in self.images:
            file_path = self.images[content_name]
            with open(file_path, 'rb') as img_file:
                content = img_file.read()
            return DataPacket(name=content_name, content=content)
        return None

class Subscriber(Node):
    def __init__(self, name):
        super().__init__(name)
        self.active = True

    def send_interest(self, interest_packet, router):
        if isinstance(router, Router):
            router.receive_interest(interest_packet, self)

    def receive_data(self, data_packet):
        feedback = random.choice(['like', 'dislike', 'neutral', 'highly_like', 'highly_dislike'])
        if hasattr(self, 'connected_router'):
            self.connected_router.update_popularity(data_packet.name, feedback=feedback)

# ===================== NETWORK SETUP & SIMULATION =====================

def save_network(routers, publishers, subscribers):
    os.makedirs("Saved_Network", exist_ok=True)
    with open("Saved_Network/network_setup.pkl", "wb") as file:
        pickle.dump((routers, publishers, subscribers), file)

def load_network():
    try:
        with open("Saved_Network/network_setup.pkl", "rb") as file:
            return pickle.load(file)
    except Exception as e:
        print(f"Failed to load network: {e}")
        return None

def setup_network_with_multipaths(num_routers=5, num_subscribers=3, use_saved=True):
    """
    Setup network with multiple paths between routers
    Each router connects to multiple next-hop routers (multipath)
    """
    if use_saved and os.path.exists("Saved_Network/network_setup.pkl"):
        choice = input("Use existing network? (yes/no): ").strip().lower()
        if choice == 'yes':
            result = load_network()
            if result:
                print("Loaded existing network.")
                return result

    routers = [Router(f'Router{i}') for i in range(1, num_routers + 1)]
    publisher1 = Publisher('Publisher1', 'cats')
    publisher2 = Publisher('Publisher2', 'dogs')
    publishers = [publisher1, publisher2]
    subscribers = [Subscriber(f'Subscriber{i}') for i in range(1, num_subscribers + 1)]

    # Connect subscribers to routers
    for i, subscriber in enumerate(subscribers):
        router_index = i % len(routers)
        subscriber.connected_router = routers[router_index]

    # Initialize content ID manager
    ContentIDManager.initialize_index(publishers)

    # Setup multipath FIB - each router has multiple next-hops
    contents = [f"cat_image{j}.jpg" for j in range(1, 51)] + [f"dog_image{j}.jpg" for j in range(1, 51)]

    for i, router in enumerate(routers):
        next_hops = []

        # Connect to multiple routers (create redundant paths)
        for j in range(i + 1, min(i + 4, len(routers))):  # Connect to next 3 routers
            next_hops.append(routers[j])
            router.add_edge_link(routers[j])

        # If no next hops (last router), connect to publishers
        if not next_hops:
            next_hops = [publisher1, publisher2]

        # Assign next hops to all contents
        for content in contents:
            router.fib[content] = next_hops

    save_network(routers, publishers, subscribers)
    print(f"Created new network with {num_routers} routers and {num_subscribers} subscribers.")
    return routers, publishers, subscribers

def plot_network_with_multipaths(routers, publishers, subscribers):
    """Plot network with multipath visualization"""
    G = nx.DiGraph()

    # Add nodes
    for router in routers:
        G.add_node(router.name, node_type='router', color='lightblue')
    for publisher in publishers:
        G.add_node(publisher.name, node_type='publisher', color='lightgreen')
    for subscriber in subscribers:
        G.add_node(subscriber.name, node_type='subscriber', color='salmon')

    # Add edges (including multiple paths)
    for router in routers:
        for content, next_hops in router.fib.items():
            if isinstance(next_hops, list):
                for nh in next_hops:
                    if nh.name in G and not G.has_edge(router.name, nh.name):
                        G.add_edge(router.name, nh.name)
            else:
                if next_hops.name in G and not G.has_edge(router.name, next_hops.name):
                    G.add_edge(router.name, next_hops.name)

    # Subscriber to router edges
    for subscriber in subscribers:
        if hasattr(subscriber, 'connected_router'):
            G.add_edge(subscriber.name, subscriber.connected_router.name)

    # Draw
    colors = [G.nodes[node].get('color', 'gray') for node in G.nodes]
    pos = nx.spring_layout(G, k=2, iterations=50, seed=42)

    plt.figure(figsize=(14, 10))
    nx.draw_networkx_nodes(G, pos, node_color=colors, node_size=1000, alpha=0.9)

    # Draw edges with different styles for multiple paths
    edges = G.edges()
    nx.draw_networkx_edges(G, pos, width=2.0, alpha=0.7, arrows=False, style='solid')

    nx.draw_networkx_labels(G, pos, font_size=9, font_weight="bold")

    plt.title("Network Topology with Multipath Routing (LMM Algorithm)", fontsize=14, fontweight='bold')
    plt.axis('off')
    plt.tight_layout()
    plt.savefig('network_topology_multipath.png', dpi=300, bbox_inches='tight')
    plt.show()
    print("Network topology saved as 'network_topology_multipath.png'")

def run_multipath_simulation(routers, publishers, subscribers, policy, iterations):
    """
    Run simulation with multipath routing and LMM algorithms
    """
    for router in routers:
        router.caching_policy = policy
        router.reset()

    contents = [f"cat_image{i}.jpg" for i in range(1, 51)] + [f"dog_image{i}.jpg" for i in range(1, 51)]

    simulation_data = []
    active_prob = 0.85

    for iteration in range(iterations):
        # Update node weights and edge links dynamically
        for router in routers:
            router.update_node_weight()
            for link in router.edge_links.values():
                link.update_weight()

        # Set subscriber activity
        for subscriber in subscribers:
            subscriber.active = random.random() < active_prob

        active_subscribers = [s for s in subscribers if s.active]

        if active_subscribers:
            subscriber = random.choice(active_subscribers)
            content = random.choice(contents)

            # Run multipath exploration and selection
            if hasattr(subscriber, 'connected_router'):
                router = subscriber.connected_router

                # Algorithm 1: Multipath Exploration
                exploration_entry = router.multipath_exploration(content)

                # Algorithm 2: Multipath Selection
                selected_paths = router.multipath_selection(content)

                # Send interest through multipath
                interest_packet = InterestPacket(name=content)
                subscriber.send_interest(interest_packet, router)

                subscriber.last_interest_packet = interest_packet

        # Calculate metrics
        total_requests = sum(router.cache_hits + router.publisher_hits for router in routers)
        total_cache_hits = sum(router.cache_hits for router in routers)
        avg_cache_hit = (total_cache_hits / total_requests) * 100 if total_requests > 0 else 0

        latency = random.uniform(0.01, 0.1)
        avg_latency = latency / total_requests if total_requests > 0 else 0

        hop_reduction_ratios = []
        for subscriber in subscribers:
            if hasattr(subscriber, 'last_interest_packet'):
                pkt = subscriber.last_interest_packet
                if hasattr(pkt, 'original_hop_count') and pkt.original_hop_count > 0:
                    reduction = max(0, (pkt.original_hop_count - len(pkt.path)) / pkt.original_hop_count)
                    hop_reduction_ratios.append(reduction)

        total_hop_reduction = sum(hop_reduction_ratios) / len(hop_reduction_ratios) if hop_reduction_ratios else 0

        # Count active paths
        active_paths = sum(len(router.path_table) for router in routers)

        simulation_data.append([
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            len(active_subscribers),
            total_requests,
            total_hop_reduction,
            avg_cache_hit,
            avg_latency,
            active_paths,
            policy
        ])

    return simulation_data

def save_multipath_results(all_simulation_data, policy):
    """Save simulation results in CSV format"""
    os.makedirs('Simulation_Results/Multipath', exist_ok=True)

    filename = f'Simulation_Results/Multipath/{policy}_multipath_results.csv'

    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            "Simulation Time",
            "Active Subscribers",
            "Total Requests",
            "Hop Reduction Ratio",
            "Cache Hit Ratio (%)",
            "Latency",
            "Active Paths",
            "Policy"
        ])
        writer.writerows(all_simulation_data)

    print(f"Results saved to {filename}")

def compare_policies_multipath(routers, publishers, subscribers, iterations):
    """Run simulation for all policies and compare"""
    policies = ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR']
    all_results = []

    for policy in policies:
        print(f"\n=== Running simulation for {policy} policy ===")
        routers, publishers, subscribers = load_network()

        data = run_multipath_simulation(routers, publishers, subscribers, policy, iterations)
        all_results.extend(data)

        # Save individual policy results
        save_multipath_results(data, policy)

    # Save combined results
    os.makedirs('Simulation_Results/Multipath', exist_ok=True)
    combined_filename = 'Simulation_Results/Multipath/combined_multipath_results.csv'

    with open(combined_filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            "Simulation Time",
            "Active Subscribers",
            "Total Requests",
            "Hop Reduction Ratio",
            "Cache Hit Ratio (%)",
            "Latency",
            "Active Paths",
            "Policy"
        ])
        writer.writerows(all_results)

    print(f"\nCombined results saved to {combined_filename}")
    return all_results

def plot_multipath_comparison(all_results):
    """Plot comparison of multipath policies"""
    df = pd.DataFrame(all_results, columns=[
        "Simulation Time", "Active Subscribers", "Total Requests",
        "Hop Reduction Ratio", "Cache Hit Ratio (%)", "Latency", 
        "Active Paths", "Policy"
    ])

    df['Iteration'] = df.groupby('Policy').cumcount() + 1

    fig, axs = plt.subplots(2, 2, figsize=(16, 12))

    policies = df['Policy'].unique()
    colors = {'LRU': 'navy', 'LFU': 'darkgreen', 'FIFO': 'darkorange', 'MRU': 'indigo', 'FACR': 'saddlebrown'}

    for policy in policies:
        policy_data = df[df['Policy'] == policy]

        axs[0, 0].plot(policy_data['Iteration'], policy_data['Cache Hit Ratio (%)'],
                      label=policy, color=colors.get(policy, 'gray'), marker='o', markersize=4)
        axs[0, 1].plot(policy_data['Iteration'], policy_data['Latency'],
                      label=policy, color=colors.get(policy, 'gray'), marker='o', markersize=4)
        axs[1, 0].plot(policy_data['Iteration'], policy_data['Hop Reduction Ratio'],
                      label=policy, color=colors.get(policy, 'gray'), marker='o', markersize=4)
        axs[1, 1].plot(policy_data['Iteration'], policy_data['Active Paths'],
                      label=policy, color=colors.get(policy, 'gray'), marker='o', markersize=4)

    axs[0, 0].set_title('Cache Hit Ratio over Iterations', fontsize=12, fontweight='bold')
    axs[0, 0].set_xlabel('Iteration')
    axs[0, 0].set_ylabel('Cache Hit Ratio (%)')
    axs[0, 0].legend()
    axs[0, 0].grid(True, linestyle='--', alpha=0.5)

    axs[0, 1].set_title('Latency over Iterations', fontsize=12, fontweight='bold')
    axs[0, 1].set_xlabel('Iteration')
    axs[0, 1].set_ylabel('Latency')
    axs[0, 1].legend()
    axs[0, 1].grid(True, linestyle='--', alpha=0.5)

    axs[1, 0].set_title('Hop Reduction Ratio over Iterations', fontsize=12, fontweight='bold')
    axs[1, 0].set_xlabel('Iteration')
    axs[1, 0].set_ylabel('Hop Reduction Ratio')
    axs[1, 0].legend()
    axs[1, 0].grid(True, linestyle='--', alpha=0.5)

    axs[1, 1].set_title('Active Paths over Iterations', fontsize=12, fontweight='bold')
    axs[1, 1].set_xlabel('Iteration')
    axs[1, 1].set_ylabel('Number of Active Paths')
    axs[1, 1].legend()
    axs[1, 1].grid(True, linestyle='--', alpha=0.5)

    plt.suptitle('Multipath Routing Performance Comparison (LMM Algorithms)', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('multipath_comparison.png', dpi=300, bbox_inches='tight')
    plt.show()
    print("Comparison plot saved as 'multipath_comparison.png'")

def main():
    print("=" * 60)
    print("Multipath Content Delivery Network Simulator")
    print("Based on: Reliable Multipath and Multisource Content Transmission")
    print("=" * 60)
    num_routers=input("Enter number of routers (e.g., 5): ")
    num_routers=int(num_routers)
    num_subscribers=input("Enter number of subscribers (e.g., 3): ")
    num_subscribers=int(num_subscribers)    
    # Setup network with multiple paths
    routers, publishers, subscribers = setup_network_with_multipaths(
        num_routers,
        num_subscribers,
        use_saved=False
    )

    # Visualize network topology
    plot_network_with_multipaths(routers, publishers, subscribers)

    # Run simulation
    iterations = 50  # Number of simulation iterations
    print(f"\nRunning simulation for {iterations} iterations...")

    all_results = compare_policies_multipath(routers, publishers, subscribers, iterations)

    # Plot comparison
    print("\nGenerating comparison plots...")
    plot_multipath_comparison(all_results)

    print("\nSimulation complete!")
    print("Results saved in: Simulation_Results/Multipath/")

if __name__ == "__main__":
    main()
