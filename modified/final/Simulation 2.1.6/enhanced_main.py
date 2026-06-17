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
        self.fib = {}  # Forwarding Information Base
        self.pit = {}  # Pending Interest Table
        self.cs = []   # Content Store

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
# INTELLIGENT PATH DISCOVERY AND GOODPUT TRACKING
# ============================================================================

class PathMonitor:
    """Monitor paths and track goodput based on interest arrivals at producer"""
    
    def __init__(self):
        self.path_arrivals = {}
        self.path_goodputs = {}
        self.content_request_count = 0
        self.discovered_paths = set()
        self.smoothing_factor = 0.2
        self.chunk_size = 8192
        
    def record_interest_arrival(self, path_id, arrival_time, prev_arrival_time=None):
        """Record interest packet arrival at producer and calculate goodput"""
        if path_id not in self.path_arrivals:
            self.path_arrivals[path_id] = []
            self.discovered_paths.add(path_id)
        
        self.path_arrivals[path_id].append(arrival_time)
        
        # Calculate goodput based on inter-arrival gap
        if prev_arrival_time is not None and prev_arrival_time < arrival_time:
            inter_arrival_gap = arrival_time - prev_arrival_time
            if inter_arrival_gap > 0:
                instantaneous_goodput = self.chunk_size / inter_arrival_gap
                
                # Update smoothed goodput: g_i_bar = (1-c)*prev_g_i + c*g_i
                if path_id not in self.path_goodputs:
                    self.path_goodputs[path_id] = instantaneous_goodput
                else:
                    prev_goodput = self.path_goodputs[path_id]
                    smoothed = (1 - self.smoothing_factor) * prev_goodput + self.smoothing_factor * instantaneous_goodput
                    self.path_goodputs[path_id] = smoothed
        elif prev_arrival_time is None:
            # First arrival on this path
            if path_id not in self.path_goodputs:
                self.path_goodputs[path_id] = self.chunk_size / (arrival_time + 0.001)
    
    def get_number_of_paths(self):
        """Number of paths = count of unique path IDs from interest arrivals"""
        return len(self.discovered_paths)
    
    def get_path_goodputs(self):
        """Return goodput for all discovered paths"""
        return self.path_goodputs.copy()

# ============================================================================
# ROUTER CLASS WITH MULTI-PATH SUPPORT
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
            self.popularity_table.at[content_index, 'Feedback'] = feedback or 'None'
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
        self.popularity_table['Rank'] = self.popularity_table['Popularity'].rank(method='min', ascending=False).astype(int)
        self.popularity_table['Popularity'] = pd.to_numeric(self.popularity_table['Popularity'], errors='coerce').round(4)
        self.popularity_table.sort_values(by='Rank', inplace=True)
    
    def receive_interest(self, interest_packet, subscriber):
        content_id = ContentIDManager.get_unique_id(interest_packet.name)
        
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
            if interest_packet.name not in self.pit_entries:
                self.pit_entries[interest_packet.name] = {}
            self.pit_entries[interest_packet.name][path_id] = subscriber.name
        
        if interest_packet.name in self.cs:
            self.cache_hits += 1
            data_packet = DataPacket(name=interest_packet.name, content=interest_packet.name, chunk_id=interest_packet.chunk_id)
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
        self.rank_content()

# ============================================================================
# PUBLISHER AND SUBSCRIBER CLASSES
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
        image_files = [f for f in os.listdir(self.folder) if os.path.isfile(os.path.join(self.folder, f))]
        for image_name in image_files:
            file_path = os.path.join(self.folder, image_name)
            images[image_name] = file_path
        return images
    
    def receive_interest_at_producer(self, interest_packet, path_id):
        """Track interest arrivals to discover paths and calculate goodput"""
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
        
        print(f"[Producer {self.name}] Path {path_id}: Interest for {interest_packet.name}")
        print(f"  Paths discovered: {self.path_monitor.get_number_of_paths()}")
        print(f"  Goodputs: {self.path_monitor.get_path_goodputs()}")
    
    def get_discovered_paths_info(self):
        """Get number of paths and their goodput"""
        num_paths = self.path_monitor.get_number_of_paths()
        goodputs = self.path_monitor.get_path_goodputs()
        return num_paths, goodputs
    
    def serve_content(self, content_name):
        if content_name in self.images:
            file_path = self.images[content_name]
            with open(file_path, 'rb') as img_file:
                content = img_file.read()
            return DataPacket(name=content_name, content=content)
        return None
    
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
        self.active = True
        self.connected_router = None
        self.received_chunks = {}
        self.chunk_assembly_times = {}
        self.interest_send_times = {}
    
    def send_interest(self, interest_packet, router):
        interest_packet.send_time = time.time()
        
        if interest_packet.name not in self.interest_send_times:
            self.interest_send_times[interest_packet.name] = interest_packet.send_time
        
        if isinstance(router, Router):
            router.receive_interest(interest_packet, self)
    
    def receive_data(self, data_packet):
        if data_packet.name not in self.received_chunks:
            self.received_chunks[data_packet.name] = {}
            self.chunk_assembly_times[data_packet.name] = {}
        
        if data_packet.chunk_id is not None:
            self.received_chunks[data_packet.name][data_packet.chunk_id] = data_packet.content
            self.chunk_assembly_times[data_packet.name][data_packet.chunk_id] = time.time()

# ============================================================================
# NETWORK SETUP
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

def create_multi_path_topology(routers, num_additional_paths=None):
    """Create multiple interconnected paths in network"""
    num_routers = len(routers)
    
    if num_additional_paths is None:
        num_additional_paths = max(1, (num_routers - 1) // 2)
    
    # Linear path
    for i in range(num_routers - 1):
        for j in range(1, 51):
            routers[i].fib[f"cat_image{j}.jpg"] = routers[i + 1]
            routers[i].fib[f"dog_image{j}.jpg"] = routers[i + 1]
    
    # Alternative skip-hop paths
    for i in range(num_routers - 1):
        for skip in range(1, num_additional_paths + 1):
            target_idx = min(i + skip + 1, num_routers - 1)
            if target_idx > i:
                for j in range(1, 51):
                    routers[i].fib[f"cat_image{j}.jpg_alt{skip}"] = routers[target_idx]
                    routers[i].fib[f"dog_image{j}.jpg_alt{skip}"] = routers[target_idx]

def setup_network():
    """
    Setup network with:
    1. Configurable number of routers
    2. Multi-path topology
    3. Path discovery through interest tracking
    4. Goodput calculation from producer arrivals
    """
    if os.path.exists("Saved_Network/network_setup.pkl"):
        choice = input("Use existing network setup? (yes/no): ").strip().lower()
        if choice == 'yes':
            try:
                routers, publishers, subscribers = load_network()
                print("Loaded existing network successfully.")
                return routers, publishers, subscribers
            except Exception as e:
                print(f"Error loading network: {e}. Creating new...")
    
    num_routers = get_valid_integer("Enter the number of routers: ")
    
    print(f"\nSetting up network with {num_routers} routers...")
    print("Configuration:")
    print("  - Primary path: Router1 -> Router2 -> ... -> Router{n}")
    print("  - Alternative paths: Skip-hop for redundancy")
    print("  - Paths discovered from interest arrivals at producer")
    print("  - Goodput calculated from inter-arrival gaps")
    
    routers = [Router(f'Router{i}') for i in range(1, num_routers + 1)]
    
    publisher1 = Publisher('Publisher1', 'cats')
    publisher2 = Publisher('Publisher2', 'dogs')
    publishers = [publisher1, publisher2]
    
    num_subscribers = get_valid_integer("Enter the number of subscribers: ")
    subscribers = [Subscriber(f'Subscriber{i}') for i in range(1, num_subscribers + 1)]
    
    for i, subscriber in enumerate(subscribers):
        router_index = i % len(routers)
        subscriber.connected_router = routers[router_index]
    
    ContentIDManager.initialize_index(publishers)
    
    num_alt_paths = max(1, (num_routers - 1) // 2)
    print(f"\nCreating {num_alt_paths} alternative paths...")
    create_multi_path_topology(routers, num_alt_paths)
    
    for j in range(1, 51):
        routers[-1].fib[f"cat_image{j}.jpg"] = publisher1
        routers[-1].fib[f"dog_image{j}.jpg"] = publisher2
    
    save_network(routers, publishers, subscribers)
    
    print(f"\nNetwork Summary:")
    print(f"  Routers: {len(routers)}")
    print(f"  Publishers: {len(publishers)}")
    print(f"  Subscribers: {len(subscribers)}")
    print(f"  Paths will be discovered during interest propagation")
    
    return routers, publishers, subscribers

def save_network(routers, publishers, subscribers):
    os.makedirs("Saved_Network", exist_ok=True)
    with open("Saved_Network/network_setup.pkl", "wb") as file:
        pickle.dump((routers, publishers, subscribers), file)
    print("Network saved.")

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

def calculate_goodput_per_path(forward_delays, chunk_size=8192, smoothing_factor=0.2):
    """g_i = S / r_i with smoothing"""
    goodputs = {}
    
    for path_id, arrival_delay in forward_delays.items():
        if arrival_delay > 0:
            instantaneous_goodput = chunk_size / arrival_delay
            smoothed = (1 - smoothing_factor) * instantaneous_goodput + smoothing_factor * instantaneous_goodput
            goodputs[path_id] = smoothed
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
    
    # Distribute remaining chunks
    remaining_chunks = num_chunks - chunk_index
    for path_id in range(num_paths):
        if remaining_chunks > 0:
            chunk_subsets[path_id].append(chunk_index)
            chunk_index += 1
            remaining_chunks -= 1
    
    return chunk_subsets

def implement_algorithm1(interest_packet, publisher, num_paths, goodputs, chunk_size=8192):
    """Full Algorithm1 with discovered paths"""
    print(f"\n=== ALGORITHM1 EXECUTION ===")
    print(f"Content: {interest_packet.name}")
    print(f"Paths Discovered: {num_paths}")
    print(f"Producer Requests Received: {publisher.path_monitor.content_request_count}")
    
    forward_delays = calculate_forward_delay(interest_packet)
    rtt_estimates = calculate_rtt(forward_delays)
    
    if not goodputs:
        goodputs = calculate_goodput_per_path(forward_delays, chunk_size)
    
    print(f"Forward Delays: {forward_delays}")
    print(f"Goodputs (bytes/sec): {goodputs}")
    
    content_data = b"dummy_content_" + interest_packet.name.encode() * 100
    chunks, num_chunks = publisher.split_content_into_chunks(interest_packet.name, content_data, chunk_size)
    
    chunk_subsets = create_chunk_subsets_for_paths(num_paths, num_chunks, goodputs)
    
    print(f"Content split into {num_chunks} chunks")
    for path_id, chunks_list in chunk_subsets.items():
        print(f"  Path {path_id}: {len(chunks_list)} chunks")
    
    return {
        'content_name': interest_packet.name,
        'num_paths': num_paths,
        'total_chunks': num_chunks,
        'forward_delays': forward_delays,
        'goodputs': goodputs,
        'chunk_distribution': chunk_subsets,
        'producer_requests': publisher.path_monitor.content_request_count
    }, chunk_subsets

# ============================================================================
# PERFORMANCE METRICS
# ============================================================================

def calculate_latency_multipath(chunk_subsets, rtt_estimates):
    """Total latency = max across paths"""
    latencies = {}
    total_latency = 0
    
    for path_id, chunks in chunk_subsets.items():
        rtt = rtt_estimates.get(path_id, 0.01)
        path_latency = rtt * len(chunks)
        latencies[path_id] = path_latency
        total_latency = max(total_latency, path_latency)
    
    return latencies, total_latency

def calculate_cache_hit_ratio_multipath(routers):
    """Cache hit ratio across all routers"""
    total_requests = sum(router.total_requests for router in routers)
    total_hits = sum(router.cache_hits for router in routers)
    
    return (total_hits / total_requests * 100) if total_requests > 0 else 0

def calculate_goodput_statistics(goodputs):
    """Goodput statistics"""
    if not goodputs:
        return 0, 0, 0
    
    values = list(goodputs.values())
    return np.mean(values), np.min(values), np.max(values)

# ============================================================================
# SIMULATION
# ============================================================================

def run_simulation(routers, publishers, subscribers, policy, iterations, num_probes=5):
    """Run simulation with path discovery"""
    for router in routers:
        router.caching_policy = policy
        router.reset()
    
    contents = [f"cat_image{i}.jpg" for i in range(1, 11)] + [f"dog_image{i}.jpg" for i in range(1, 11)]
    simulation_data = []
    
    for iteration in range(iterations):
        print(f"\n--- Iteration {iteration + 1}/{iterations} ---")
        
        for subscriber in subscribers:
            subscriber.active = random.random() < 0.9
        
        active_subscribers = [s for s in subscribers if s.active]
        
        if active_subscribers:
            subscriber = random.choice(active_subscribers)
            content = random.choice(contents)
            publisher = publishers[0]
            
            # Send interest probes for path discovery
            for probe in range(num_probes):
                interest = InterestPacket(name=content, packet_id=f"{content}_probe_{probe}")
                path_id = probe
                publisher.receive_interest_at_producer(interest, path_id)
                subscriber.send_interest(interest, subscriber.connected_router)
                time.sleep(0.01)
            
            # Get discovered paths
            num_paths, goodputs = publisher.get_discovered_paths_info()
            
            if num_paths > 0:
                # Run Algorithm1
                interest = InterestPacket(name=content)
                interest.send_time = time.time()
                
                for path_id in range(num_paths):
                    interest.arrival_times[path_id] = time.time() + random.uniform(0.001, 0.05)
                
                trans_data, chunk_subsets = implement_algorithm1(interest, publisher, num_paths, goodputs)
                
                forward_delays = trans_data['forward_delays']
                final_goodputs = trans_data['goodputs']
                producer_requests = trans_data['producer_requests']
                
                rtt_est = {pid: 2 * fd for pid, fd in forward_delays.items()}
                latencies, total_latency = calculate_latency_multipath(chunk_subsets, rtt_est)
                cache_hit = calculate_cache_hit_ratio_multipath(routers)
                avg_goodput, min_goodput, max_goodput = calculate_goodput_statistics(final_goodputs)
                
                simulation_data.append([
                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    len(active_subscribers),
                    producer_requests,
                    num_paths,
                    avg_goodput,
                    0.5,
                    cache_hit,
                    total_latency
                ])
    
    return simulation_data

# ============================================================================
# RESULTS AND VISUALIZATION
# ============================================================================

def save_simulation_data(simulation_data, policy):
    """Save to CSV"""
    os.makedirs(f'ML_Training_Data/{policy}', exist_ok=True)
    columns = ['Time', 'Clients', 'Producer Requests', 'Num Paths', 'Avg Goodput', 'Hop Reduction', 'Cache Hit', 'Latency']
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
        writer.writerow(["Policy", "Iteration", "Producer Requests", "Num Paths", "Goodput", "Latency", "Cache Hit"])
        for stat in policy_stats:
            writer.writerow([stat["Policy"], stat["Iteration"], stat["Producer Requests"], 
                           stat["Num Paths"], stat["Goodput"], stat["Latency"], stat["Cache Hit"]])
    
    print(f"Results saved to {filename}")

def plot_network_graph(routers, publishers, subscribers):
    """Plot network topology"""
    G = nx.Graph()
    
    for router in routers:
        G.add_node(router.name, color='lightblue')
    for publisher in publishers:
        G.add_node(publisher.name, color='lightgreen')
    for subscriber in subscribers:
        G.add_node(subscriber.name, color='salmon')
    
    for router in routers:
        for _, next_hop in router.fib.items():
            if next_hop and next_hop.name in G and not G.has_edge(router.name, next_hop.name):
                G.add_edge(router.name, next_hop.name)
    
    for subscriber in subscribers:
        if subscriber.connected_router:
            G.add_edge(subscriber.name, subscriber.connected_router.name)
    
    colors = [G.nodes[node].get('color', 'gray') for node in G.nodes]
    pos = nx.spring_layout(G, seed=42, k=2, iterations=50)
    
    plt.figure(figsize=(14, 10))
    nx.draw_networkx_nodes(G, pos, node_color=colors, node_size=800, alpha=0.9)
    nx.draw_networkx_edges(G, pos, width=1.2, alpha=0.7)
    nx.draw_networkx_labels(G, pos, font_size=9, font_weight="bold")
    
    plt.title("Multi-Path ICN Network with Algorithm1 - Path Discovery", fontsize=14, fontweight='bold')
    plt.axis('off')
    plt.tight_layout()
    plt.savefig('Network_Topology.png', dpi=300)
    print("Saved Network_Topology.png")
    plt.show()

def plot_algorithm1_results(all_simulation_data):
    """Plot results"""
    fig, axs = plt.subplots(2, 2, figsize=(15, 10))
    
    all_data = []
    for policy_data in all_simulation_data:
        policy = policy_data['Policy']
        data = policy_data['Data']
        for i, row in enumerate(data):
            all_data.append({
                'Policy': policy,
                'Iteration': i + 1,
                'Producer Requests': row[2],
                'Num Paths': row[3],
                'Goodput': row[4],
                'Latency': row[7],
                'Cache Hit': row[6]
            })
    
    df = pd.DataFrame(all_data)
    
    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]
        axs[0, 0].plot(policy_df['Iteration'], policy_df['Producer Requests'], label=policy, marker='o')
    axs[0, 0].set_title('Producer Requests', fontweight='bold')
    axs[0, 0].set_xlabel('Iteration')
    axs[0, 0].legend()
    axs[0, 0].grid(True, alpha=0.5)
    
    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]
        axs[0, 1].plot(policy_df['Iteration'], policy_df['Num Paths'], label=policy, marker='s')
    axs[0, 1].set_title('Discovered Paths', fontweight='bold')
    axs[0, 1].set_xlabel('Iteration')
    axs[0, 1].legend()
    axs[0, 1].grid(True, alpha=0.5)
    
    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]
        axs[1, 0].plot(policy_df['Iteration'], policy_df['Goodput'], label=policy, marker='^')
    axs[1, 0].set_title('Goodput', fontweight='bold')
    axs[1, 0].set_xlabel('Iteration')
    axs[1, 0].legend()
    axs[1, 0].grid(True, alpha=0.5)
    
    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]
        axs[1, 1].plot(policy_df['Iteration'], policy_df['Cache Hit'], label=policy, marker='d')
    axs[1, 1].set_title('Cache Hit Ratio', fontweight='bold')
    axs[1, 1].set_xlabel('Iteration')
    axs[1, 1].legend()
    axs[1, 1].grid(True, alpha=0.5)
    
    plt.suptitle('Algorithm1 - Path Discovery & Chunk Distribution Performance', fontsize=15, fontweight='bold')
    plt.tight_layout(rect=[0, 0.03, 1, 0.97])
    plt.savefig('Algorithm1_Results.png', dpi=300)
    print("Saved Algorithm1_Results.png")
    plt.show()

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=== ICN MULTI-PATH NETWORK SIMULATOR ===")
    print("=== WITH INTELLIGENT PATH DISCOVERY ===\n")
    
    routers, publishers, subscribers = setup_network()
    plot_network_graph(routers, publishers, subscribers)
    
    iterations = get_valid_integer("\nEnter simulation iterations: ")
    probes = get_valid_integer("Enter interest probes per content (for path discovery): ")
    
    policies = ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR']
    all_simulation_data = []
    policy_stats = []
    
    for policy in policies:
        print(f"\n{'='*70}")
        print(f"Running {policy} policy...")
        print(f"{'='*70}")
        
        routers, publishers, subscribers = load_network()
        sim_data = run_simulation(routers, publishers, subscribers, policy, iterations, probes)
        all_simulation_data.append({'Policy': policy, 'Data': sim_data})
        
        for i, row in enumerate(sim_data):
            policy_stats.append({
                'Policy': policy,
                'Iteration': i + 1,
                'Producer Requests': row[2],
                'Num Paths': row[3],
                'Goodput': row[4],
                'Latency': row[7],
                'Cache Hit': row[6]
            })
        
        save_simulation_data(sim_data, policy)
    
    save_results(policy_stats)
    plot_algorithm1_results(all_simulation_data)
    
    print("\n=== SIMULATION COMPLETE ===")

if __name__ == "__main__":
    main()
