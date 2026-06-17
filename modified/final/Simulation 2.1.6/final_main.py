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

# ============================================================================
# CORE CLASSES FOR ICN NETWORK
# ============================================================================

class Node:
    def __init__(self, name):
        self.name = name
        self.fib = {}
        self.pit = {}
        self.cs = []

class InterestPacket:
    def __init__(self, name, chunk_id=None, packet_id=None):
        self.name = name
        self.chunk_id = chunk_id
        self.packet_id = packet_id
        self.nonce = random.randint(1000, 9999)
        self.visited = set()
        self.path = []
        self.original_hop_count = 0
        self.actual_hop_count = 0
        self.send_time = time.time()
        self.arrival_times = {}
        self.arrival_order = []

class DataPacket:
    def __init__(self, name, content, chunk_id=None):
        self.name = name
        self.content = content
        self.chunk_id = chunk_id
        self.send_time = time.time()

class ContentIDManager:
    _content_id_map = {}
    
    @classmethod
    def initialize_index(cls, publishers):
        image_id = 100
        for publisher in publishers:
            for image_name in publisher.images.keys():
                if image_name not in cls._content_id_map:
                    cls._content_id_map[image_name] = image_id
                    image_id += 1
    
    @classmethod
    def get_unique_id(cls, content_name):
        return cls._content_id_map.get(content_name, None)

# ============================================================================
# PATH DISCOVERY AND GOODPUT TRACKING
# ============================================================================

class PathMonitor:
    """Track paths and goodput based on interest arrivals at producer"""
    
    def __init__(self):
        self.path_arrivals = {}
        self.path_goodputs = {}
        self.content_request_count = 0
        self.discovered_paths = set()
        self.smoothing_factor = 0.2
        self.chunk_size = 8192
        
    def record_interest_arrival(self, path_id, arrival_time, prev_arrival_time=None):
        """Record interest arrival and calculate goodput"""
        if path_id not in self.path_arrivals:
            self.path_arrivals[path_id] = []
            self.discovered_paths.add(path_id)
        
        self.path_arrivals[path_id].append(arrival_time)
        
        if prev_arrival_time is not None and prev_arrival_time < arrival_time:
            inter_arrival_gap = arrival_time - prev_arrival_time
            if inter_arrival_gap > 0:
                instantaneous_goodput = self.chunk_size / inter_arrival_gap
                
                if path_id not in self.path_goodputs:
                    self.path_goodputs[path_id] = instantaneous_goodput
                else:
                    prev_goodput = self.path_goodputs[path_id]
                    smoothed = (1 - self.smoothing_factor) * prev_goodput + self.smoothing_factor * instantaneous_goodput
                    self.path_goodputs[path_id] = smoothed
        elif prev_arrival_time is None:
            if path_id not in self.path_goodputs:
                self.path_goodputs[path_id] = self.chunk_size / (arrival_time + 0.001)
    
    def get_number_of_paths(self):
        """Return number of discovered paths"""
        return len(self.discovered_paths)
    
    def get_path_goodputs(self):
        """Return goodput for all discovered paths"""
        return self.path_goodputs.copy()

# ============================================================================
# ROUTER CLASS
# ============================================================================

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
        self.reset()
        self.pit_entries = {}
        self.cs_chunks = {}
        self.chunk_ttl = {}
    
    def reset(self):
        self.cache_hits = 0
        self.publisher_hits = 0
        self.total_requests = 0
        self.cache_access_times = {}
        self.cache_frequency = collections.defaultdict(int)
        self.cache_ttl = {}
        self.cs = []
        self.pit = {}
    
    def update_popularity(self, content_name, feedback=None):
        if content_name in self.popularity_table['Content Name'].values:
            content_index = self.popularity_table[self.popularity_table['Content Name'] == content_name].index[0]
            r_count = self.popularity_table.at[content_index, 'R_count'] + 1
            current_popularity = self.popularity_table.at[content_index, 'Popularity']
            feedback_weights = {'highly_like': 1.5, 'like': 1.2, 'neutral': 1.0, 'dislike': 0.8, 'highly_dislike': 0.5}
            adjustment = feedback_weights.get(feedback, 1)
            new_popularity = self.alpha * current_popularity + (1 - self.alpha) * r_count * adjustment
            self.popularity_table.at[content_index, 'R_count'] = r_count
            self.popularity_table.at[content_index, 'Popularity'] = new_popularity
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
        if len(self.popularity_table) > 0:
            self.popularity_table['Rank'] = self.popularity_table['Popularity'].rank(method='min', ascending=False).astype(int)
            self.popularity_table['Popularity'] = pd.to_numeric(self.popularity_table['Popularity'], errors='coerce').round(4)
            self.popularity_table.sort_values(by='Rank', inplace=True)
    
    def receive_interest(self, interest_packet, subscriber):
        if self.name in interest_packet.visited:
            return
        
        self.total_requests += 1
        interest_packet.actual_hop_count = getattr(interest_packet, 'actual_hop_count', 0) + 1
        interest_packet.path.append(self.name)
        interest_packet.visited.add(self.name)
        
        path_id = len(interest_packet.arrival_order)
        interest_packet.arrival_times[path_id] = time.time()
        interest_packet.arrival_order.append(path_id)
        
        if interest_packet.name not in self.pit:
            self.pit[interest_packet.name] = subscriber.name
        
        if interest_packet.name in self.cs:
            self.cache_hits += 1
            data_packet = DataPacket(name=interest_packet.name, content=interest_packet.name)
            subscriber.receive_data(data_packet)
            return
        
        self.publisher_hits += 1
        next_hop = self.fib.get(interest_packet.name)
        
        if next_hop:
            if isinstance(next_hop, Router):
                next_hop.receive_interest(interest_packet, subscriber)
            elif isinstance(next_hop, Publisher):
                data_packet = next_hop.serve_content(interest_packet.name)
                if data_packet:
                    self.receive_data(data_packet)
                    subscriber.receive_data(data_packet)
    
    def receive_data(self, data_packet):
        current_time = datetime.datetime.now()
        ttl = current_time + datetime.timedelta(minutes=5)
        self.cache_ttl[data_packet.name] = ttl
        
        if len(self.cs) >= Router.CACHE_LIMIT:
            if self.caching_policy == 'FACR':
                if len(self.popularity_table) > 0:
                    top_5_popular = set(self.popularity_table.head(5)['Content Name'])
                    non_reserved_cache = [item for item in self.cs if item not in top_5_popular]
                    if len(non_reserved_cache) >= (Router.CACHE_LIMIT - Router.TOP_N_POPULAR):
                        to_remove = non_reserved_cache[0]
                        self.cs.remove(to_remove)
                        self.cache_access_times.pop(to_remove, None)
                        self.cache_frequency.pop(to_remove, None)
            else:
                if self.caching_policy == 'LRU' and self.cache_access_times:
                    lru_content = min(self.cache_access_times, key=self.cache_access_times.get)
                    self.cs.remove(lru_content)
                    self.cache_access_times.pop(lru_content)
                elif self.caching_policy == 'LFU' and self.cache_frequency:
                    lfu_content = min(self.cache_frequency, key=self.cache_frequency.get)
                    self.cs.remove(lfu_content)
                    self.cache_frequency.pop(lfu_content)
                elif self.caching_policy == 'FIFO' and self.cs:
                    self.cs.pop(0)
                elif self.caching_policy == 'MRU' and self.cache_access_times:
                    mru_content = max(self.cache_access_times, key=self.cache_access_times.get)
                    self.cs.remove(mru_content)
                    self.cache_access_times.pop(mru_content)
        
        if data_packet.name not in self.cs:
            self.cs.append(data_packet.name)
            
            if self.caching_policy in ['LRU', 'MRU']:
                self.cache_access_times[data_packet.name] = current_time
            elif self.caching_policy == 'LFU':
                self.cache_frequency[data_packet.name] += 1
        
        self.update_popularity(data_packet.name)

# ============================================================================
# PUBLISHER AND SUBSCRIBER
# ============================================================================

class Publisher(Node):
    def __init__(self, name, folder):
        super().__init__(name)
        self.folder = folder
        self.images = self.load_images()
        self.content_chunks = {}
        self.path_monitor = PathMonitor()
        self.received_interests = {}
    
    def load_images(self):
        images = {}
        os.makedirs(self.folder, exist_ok=True)
        for image_name in ['cat_image1.jpg', 'dog_image1.jpg']:
            images[image_name] = os.path.join(self.folder, image_name)
        return images
    
    def receive_interest_at_producer(self, interest_packet, path_id):
        """Track interest arrivals for path discovery"""
        current_time = time.time()
        
        if interest_packet.name not in self.received_interests:
            self.received_interests[interest_packet.name] = []
        
        prev_arrival = None
        if self.received_interests[interest_packet.name]:
            prev_arrival = self.received_interests[interest_packet.name][-1]['arrival_time']
        
        self.received_interests[interest_packet.name].append({
            'path_id': path_id,
            'arrival_time': current_time,
            'packet_id': interest_packet.packet_id
        })
        
        self.path_monitor.record_interest_arrival(path_id, current_time, prev_arrival)
        self.path_monitor.content_request_count += 1
    
    def get_discovered_paths_info(self):
        """Return discovered paths and goodput"""
        num_paths = self.path_monitor.get_number_of_paths()
        goodputs = self.path_monitor.get_path_goodputs()
        return num_paths, goodputs
    
    def serve_content(self, content_name):
        content_data = b"dummy_content_" + content_name.encode() * 100
        return DataPacket(name=content_name, content=content_data)
    
    def split_content_into_chunks(self, content_name, content_data, chunk_size=8192):
        chunks = {}
        num_chunks = (len(content_data) + chunk_size - 1) // chunk_size
        
        for i in range(num_chunks):
            start = i * chunk_size
            end = min(start + chunk_size, len(content_data))
            chunks[i] = content_data[start:end]
        
        self.content_chunks[content_name] = chunks
        return chunks, num_chunks

class Subscriber(Node):
    def __init__(self, name):
        super().__init__(name)
        self.connected_router = None
        self.received_chunks = {}
        self.chunk_assembly_times = {}
    
    def send_interest(self, interest_packet, router):
        interest_packet.send_time = time.time()
        if isinstance(router, Router):
            router.receive_interest(interest_packet, self)
    
    def receive_data(self, data_packet):
        if data_packet.name not in self.received_chunks:
            self.received_chunks[data_packet.name] = {}
        
        if data_packet.chunk_id is not None:
            self.received_chunks[data_packet.name][data_packet.chunk_id] = data_packet.content

# ============================================================================
# NETWORK SETUP - ONE PRODUCER, ONE CONSUMER, MULTIPLE PATHS
# ============================================================================

def get_valid_integer(prompt):
    while True:
        try:
            value = int(input(prompt))
            if value > 0:
                return value
            else:
                print("Please enter a positive integer.")
        except ValueError:
            print("Invalid input. Please enter a valid integer.")

def create_multi_path_topology(routers, publisher, num_paths):
    """
    Create multiple disjoint paths from consumer to producer
    Each path can have different length and characteristics
    """
    if num_paths <= 0:
        num_paths = 1
    
    num_routers = len(routers)
    paths_created = 0
    
    # Create primary linear path
    for i in range(num_routers - 1):
        for j in range(1, 51):
            routers[i].fib[f"cat_image{j}.jpg"] = routers[i + 1]
            routers[i].fib[f"dog_image{j}.jpg"] = routers[i + 1]
    
    # Last router to publisher
    routers[-1].fib[f"cat_image*"] = publisher
    routers[-1].fib[f"dog_image*"] = publisher
    
    # Create alternative paths (skip-hop)
    paths_created = 1
    for i in range(num_routers - 1):
        for skip in range(1, num_paths):
            target_idx = min(i + skip + 1, num_routers - 1)
            if target_idx > i and paths_created < num_paths:
                for j in range(1, 51):
                    routers[i].fib[f"cat_image{j}.jpg_alt{skip}"] = routers[target_idx]
                    routers[i].fib[f"dog_image{j}.jpg_alt{skip}"] = routers[target_idx]
                paths_created += 1

def setup_network():
    """Setup network with one producer, one consumer, multiple paths"""
    
    if os.path.exists("Saved_Network/network_setup.pkl"):
        choice = input("Use existing network setup? (yes/no): ").strip().lower()
        if choice == 'yes':
            try:
                with open("Saved_Network/network_setup.pkl", "rb") as file:
                    routers, publisher, subscriber = pickle.load(file)
                print("Loaded existing network successfully.")
                return routers, publisher, subscriber
            except Exception as e:
                print(f"Error loading network: {e}.")
    
    num_routers = get_valid_integer("Enter the number of routers (intermediate nodes between consumer and producer): ")
    num_paths = get_valid_integer("Enter the number of paths: ")
    
    print(f"\nSetting up network with:")
    print(f"  - Number of routers: {num_routers}")
    print(f"  - Number of paths: {num_paths}")
    print(f"  - One Producer")
    print(f"  - One Consumer")
    print(f"  - Multiple paths with different lengths/characteristics")
    
    routers = [Router(f'Router{i}') for i in range(1, num_routers + 1)]
    publisher = Publisher('Producer', 'content')
    subscriber = Subscriber('Consumer')
    
    # Connect subscriber to first router
    subscriber.connected_router = routers[0]
    
    # Initialize content ID manager
    ContentIDManager.initialize_index([publisher])
    
    # Create multi-path topology
    create_multi_path_topology(routers, publisher, num_paths)
    
    # Save network
    os.makedirs("Saved_Network", exist_ok=True)
    with open("Saved_Network/network_setup.pkl", "wb") as file:
        pickle.dump((routers, publisher, subscriber), file)
    
    print("Network setup created and saved.\n")
    return routers, publisher, subscriber

def load_network():
    try:
        with open("Saved_Network/network_setup.pkl", "rb") as file:
            return pickle.load(file)
    except Exception as e:
        print(f"Failed to load network: {e}")
        return None

# ============================================================================
# ALGORITHM1: PATH DISCOVERY AND CHUNK DISTRIBUTION
# ============================================================================

def calculate_forward_delay(interest_packet):
    """d_i^fwd = t_i^arr - t_consumer^send"""
    forward_delays = {}
    consumer_send_time = interest_packet.send_time
    
    for path_id, arrival_time in interest_packet.arrival_times.items():
        forward_delay = arrival_time - consumer_send_time
        forward_delays[path_id] = forward_delay
    
    return forward_delays

def calculate_rtt(forward_delays):
    """RTT ≈ 2 * d_i^fwd"""
    return {path_id: 2 * fd for path_id, fd in forward_delays.items()}

def calculate_goodput_per_path(forward_delays, chunk_size=8192):
    """g_i = S / r_i"""
    goodputs = {}
    
    for path_id, arrival_delay in forward_delays.items():
        if arrival_delay > 0:
            goodputs[path_id] = chunk_size / arrival_delay
        else:
            goodputs[path_id] = chunk_size / 0.001
    
    return goodputs

def create_chunk_subsets_for_paths(num_paths, num_chunks, goodputs):
    """Create subset C_i: |C_i| = floor((w_i / Σw_j) * K)"""
    total_weight = sum(goodputs.values()) if goodputs else 1
    chunk_subsets = {}
    chunk_index = 0
    
    for path_id in range(num_paths):
        goodput = goodputs.get(path_id, 1)
        weight = goodput / total_weight if total_weight > 0 else 1 / num_paths
        chunks_for_path = max(1, int((weight * num_chunks)))
        
        chunk_subsets[path_id] = []
        for _ in range(chunks_for_path):
            if chunk_index < num_chunks:
                chunk_subsets[path_id].append(chunk_index)
                chunk_index += 1
    
    remaining_chunks = num_chunks - chunk_index
    for path_id in range(num_paths):
        if remaining_chunks > 0:
            chunk_subsets[path_id].append(chunk_index)
            chunk_index += 1
            remaining_chunks -= 1
    
    return chunk_subsets

# ============================================================================
# SIMULATION WITH ORIGINAL METRICS
# ============================================================================

def run_simulation(routers, publisher, subscriber, policy, iterations, num_probes=5):
    """Run simulation maintaining original metrics from main.py"""
    
    for router in routers:
        router.caching_policy = policy
        router.reset()
    
    simulation_data = []
    
    for iteration in range(iterations):
        print(f"\n--- Iteration {iteration + 1}/{iterations} ---")
        
        # Send interest probes for path discovery
        content = 'cat_image1.jpg'
        
        for probe in range(num_probes):
            interest = InterestPacket(name=content, packet_id=f"probe_{probe}")
            path_id = probe
            publisher.receive_interest_at_producer(interest, path_id)
            subscriber.send_interest(interest, subscriber.connected_router)
            time.sleep(0.01)
        
        # Get discovered paths
        num_paths, goodputs = publisher.get_discovered_paths_info()
        
        if num_paths > 0:
            # Run Algorithm1
            interest_packet = InterestPacket(name=content)
            interest_packet.send_time = time.time()
            
            for path_id in range(num_paths):
                interest_packet.arrival_times[path_id] = time.time() + random.uniform(0.001, 0.05)
            
            # Calculate metrics from Algorithm1
            forward_delays = calculate_forward_delay(interest_packet)
            rtt_estimates = calculate_rtt(forward_delays)
            
            if not goodputs:
                goodputs = calculate_goodput_per_path(forward_delays)
            
            content_data = b"dummy_content_" + content.encode() * 100
            chunks, num_chunks = publisher.split_content_into_chunks(content, content_data, 8192)
            chunk_subsets = create_chunk_subsets_for_paths(num_paths, num_chunks, goodputs)
            
            # ORIGINAL METRICS FROM MAIN.PY
            # ================================
            
            # Total requests
            total_requests = sum(router.total_requests for router in routers)
            
            # Cache hits and cache hit ratio
            total_cache_hits = sum(router.cache_hits for router in routers)
            avg_cache_hit = (total_cache_hits / total_requests * 100) if total_requests > 0 else 0
            
            # Latency calculation (multipath aware)
            latencies = {}
            total_latency = 0
            for path_id, chunks_list in chunk_subsets.items():
                rtt = rtt_estimates.get(path_id, 0.01)
                path_latency = rtt * len(chunks_list)
                latencies[path_id] = path_latency
                total_latency = max(total_latency, path_latency)
            
            # Hop reduction
            hop_reduction = 0.5  # Placeholder from original
            
            # Store data in original format
            simulation_data.append([
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                1,  # One consumer
                total_requests,
                hop_reduction,
                avg_cache_hit,
                total_latency,
                num_paths,
                publisher.path_monitor.content_request_count
            ])
            
            print(f"Total Requests: {total_requests}")
            print(f"Cache Hit Ratio: {avg_cache_hit:.2f}%")
            print(f"Latency: {total_latency:.6f}")
            print(f"Paths: {num_paths}, Producer Requests: {publisher.path_monitor.content_request_count}")
    
    return simulation_data

# ============================================================================
# SAVE AND PLOT RESULTS
# ============================================================================

def save_simulation_data(simulation_data, policy):
    """Save to CSV with original format"""
    os.makedirs(f'ML_Training_Data/{policy}', exist_ok=True)
    columns = ['Simulation Time', 'No of Clients', 'Total Requests', 'Hop Reduction', 'Cache Hit Ratio', 'Latency', 'Num Paths', 'Producer Requests']
    df = pd.DataFrame(simulation_data, columns=columns)
    filepath = f'ML_Training_Data/{policy}/features.csv'
    df.to_csv(filepath, index=False)
    print(f"Saved to {filepath}")

def save_results(policy_stats):
    """Save all results"""
    os.makedirs('Simulation_Results', exist_ok=True)
    filename = 'Simulation_Results/policy_comparison.csv'
    
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Policy", "Iteration", "Total Requests", "Cache Hit Ratio", "Latency", "Hop Reduction", "Num Paths"])
        for stat in policy_stats:
            writer.writerow([
                stat["Policy"],
                stat["Iteration"],
                stat["Total Requests"],
                stat["Cache Hit Ratio"],
                stat["Latency"],
                stat["Hop Reduction"],
                stat["Num Paths"]
            ])
    
    print(f"Results saved to {filename}")

def plot_network_graph(routers, publisher, subscriber):
    """Plot network topology"""
    G = nx.Graph()
    
    G.add_node(subscriber.name, color='salmon')
    for router in routers:
        G.add_node(router.name, color='lightblue')
    G.add_node(publisher.name, color='lightgreen')
    
    # Add edges
    if subscriber.connected_router:
        G.add_edge(subscriber.name, subscriber.connected_router.name)
    
    for i, router in enumerate(routers):
        for destination, next_hop in router.fib.items():
            if next_hop and next_hop.name in G and not G.has_edge(router.name, next_hop.name):
                G.add_edge(router.name, next_hop.name)
    
    colors = [G.nodes[node].get('color', 'gray') for node in G.nodes]
    pos = nx.spring_layout(G, seed=42, k=2, iterations=50)
    
    plt.figure(figsize=(12, 8))
    nx.draw_networkx_nodes(G, pos, node_color=colors, node_size=1000, alpha=0.9)
    nx.draw_networkx_edges(G, pos, width=1.5, alpha=0.7)
    nx.draw_networkx_labels(G, pos, font_size=10, font_weight="bold")
    
    plt.title("ICN Network - One Producer, One Consumer, Multiple Paths (Algorithm1)", 
              fontsize=14, fontweight='bold')
    plt.axis('off')
    plt.tight_layout()
    plt.savefig('Network_Topology.png', dpi=300)
    print("Saved Network_Topology.png")
    plt.show()

def plot_simulation_results(all_simulation_data):
    """Plot results with original metrics"""
    fig, axs = plt.subplots(2, 2, figsize=(14, 10))
    
    all_data = []
    for policy_data in all_simulation_data:
        policy = policy_data['Policy']
        data = policy_data['Data']
        for i, row in enumerate(data):
            all_data.append({
                'Policy': policy,
                'Iteration': i + 1,
                'Total Requests': row[2],
                'Cache Hit Ratio': row[4],
                'Latency': row[5],
                'Hop Reduction': row[3],
                'Num Paths': row[6]
            })
    
    df = pd.DataFrame(all_data)
    
    # Plot 1: Cache Hit Ratio
    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]
        axs[0, 0].plot(policy_df['Iteration'], policy_df['Cache Hit Ratio'], label=policy, marker='o')
    axs[0, 0].set_title('Cache Hit Ratio over Iterations', fontweight='bold')
    axs[0, 0].set_xlabel('Iteration')
    axs[0, 0].set_ylabel('Cache Hit Ratio (%)')
    axs[0, 0].legend()
    axs[0, 0].grid(True, alpha=0.5)
    
    # Plot 2: Latency
    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]
        axs[0, 1].plot(policy_df['Iteration'], policy_df['Latency'], label=policy, marker='s')
    axs[0, 1].set_title('Latency over Iterations', fontweight='bold')
    axs[0, 1].set_xlabel('Iteration')
    axs[0, 1].set_ylabel('Latency (ms)')
    axs[0, 1].legend()
    axs[0, 1].grid(True, alpha=0.5)
    
    # Plot 3: Total Requests
    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]
        axs[1, 0].plot(policy_df['Iteration'], policy_df['Total Requests'], label=policy, marker='^')
    axs[1, 0].set_title('Total Requests over Iterations', fontweight='bold')
    axs[1, 0].set_xlabel('Iteration')
    axs[1, 0].set_ylabel('Total Requests')
    axs[1, 0].legend()
    axs[1, 0].grid(True, alpha=0.5)
    
    # Plot 4: Number of Paths
    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]
        axs[1, 1].plot(policy_df['Iteration'], policy_df['Num Paths'], label=policy, marker='d')
    axs[1, 1].set_title('Discovered Paths over Iterations', fontweight='bold')
    axs[1, 1].set_xlabel('Iteration')
    axs[1, 1].set_ylabel('Number of Paths')
    axs[1, 1].legend()
    axs[1, 1].grid(True, alpha=0.5)
    
    plt.suptitle('Algorithm1 - One Producer, One Consumer, Multiple Paths', 
                 fontsize=15, fontweight='bold')
    plt.tight_layout(rect=[0, 0.03, 1, 0.97])
    plt.savefig('Algorithm1_Results.png', dpi=300)
    print("Saved Algorithm1_Results.png")
    plt.show()

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    print("=== ICN NETWORK SIMULATOR ===")
    print("=== One Producer, One Consumer, Multiple Paths ===")
    print("=== Algorithm1 Implementation ===\n")
    
    # Setup network
    routers, publisher, subscriber = setup_network()
    
    # Plot network
    plot_network_graph(routers, publisher, subscriber)
    
    # Get simulation parameters
    iterations = get_valid_integer("Enter the number of simulation iterations: ")
    num_probes = get_valid_integer("Enter the number of interest probes per iteration (for path discovery): ")
    
    # Run simulation for caching policies
    policies = ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR']
    all_simulation_data = []
    policy_stats = []
    
    for policy in policies:
        print(f"\n{'='*70}")
        print(f"Running simulation for {policy} policy...")
        print(f"{'='*70}")
        
        routers, publisher, subscriber = load_network()
        sim_data = run_simulation(routers, publisher, subscriber, policy, iterations, num_probes)
        all_simulation_data.append({'Policy': policy, 'Data': sim_data})
        
        for i, row in enumerate(sim_data):
            policy_stats.append({
                'Policy': policy,
                'Iteration': i + 1,
                'Total Requests': row[2],
                'Cache Hit Ratio': row[4],
                'Latency': row[5],
                'Hop Reduction': row[3],
                'Num Paths': row[6]
            })
        
        save_simulation_data(sim_data, policy)
    
    save_results(policy_stats)
    plot_simulation_results(all_simulation_data)
    
    print("\n=== SIMULATION COMPLETE ===")

if __name__ == "__main__":
    main()
