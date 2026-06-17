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
        self.cs = []   # Content Store with limited cache size

class InterestPacket:
    def __init__(self, name, chunk_id=None):
        self.name = name
        self.chunk_id = chunk_id
        self.nonce = random.randint(1000, 9999)
        self.visited = set()
        self.path = []
        self.original_hop_count = 0
        self.actual_hop_count = 0
        self.send_time = time.time()
        self.arrival_times = {}  # Track arrival times at each router {path_id: time}
        self.arrival_order = []  # Track order of arrivals

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
# ROUTER CLASS WITH MULTI-PATH SUPPORT AND ALGORITHM1 IMPLEMENTATION
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
        self.connections = []
        self.fib = {}
        self.reset()
        self.save_fib()
        
        # Algorithm1-specific attributes
        self.path_id = None  # Identifier for the path this router belongs to
        self.pit_entries = {}  # Extended PIT: {content_name: {path_id: subscriber_info}}
        self.cs_chunks = {}  # Content Store with chunk tracking: {content_name: {chunk_id: data}}
        self.chunk_ttl = {}  # TTL for chunks: {(content_name, chunk_id): expiry_time}
    
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
    
    def update_popularity(self, content_name, feedback=None):
        if content_name in self.popularity_table['Content Name'].values:
            content_index = self.popularity_table[self.popularity_table['Content Name'] == content_name].index[0]
            current_popularity = self.popularity_table.at[content_index, 'Popularity']
            r_count = self.popularity_table.at[content_index, 'R_count'] + 1
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
    
    def register_pit_entry(self, content_name, path_id, subscriber_info):
        """Register PIT entry for a specific path and subscriber"""
        if content_name not in self.pit_entries:
            self.pit_entries[content_name] = {}
        self.pit_entries[content_name][path_id] = subscriber_info
    
    def store_chunk_in_cs(self, content_name, chunk_id, chunk_data, ttl_seconds=300):
        """Store chunk in content store with TTL"""
        if content_name not in self.cs_chunks:
            self.cs_chunks[content_name] = {}
        
        self.cs_chunks[content_name][chunk_id] = chunk_data
        expiry_time = datetime.datetime.now() + datetime.timedelta(seconds=ttl_seconds)
        self.chunk_ttl[(content_name, chunk_id)] = expiry_time
    
    def retrieve_chunk_from_cs(self, content_name, chunk_id):
        """Retrieve chunk from content store if available and not expired"""
        current_time = datetime.datetime.now()
        
        # Check TTL
        if (content_name, chunk_id) in self.chunk_ttl:
            if current_time > self.chunk_ttl[(content_name, chunk_id)]:
                # TTL expired
                if content_name in self.cs_chunks and chunk_id in self.cs_chunks[content_name]:
                    del self.cs_chunks[content_name][chunk_id]
                del self.chunk_ttl[(content_name, chunk_id)]
                return None
        
        # Check availability
        if content_name in self.cs_chunks and chunk_id in self.cs_chunks[content_name]:
            return self.cs_chunks[content_name][chunk_id]
        return None
    
    def receive_interest(self, interest_packet, subscriber):
        content_id = ContentIDManager.get_unique_id(interest_packet.name)
        self.content_popularity[interest_packet.name] += 1
        
        self.log_event(f"Received interest for {interest_packet.name} with ID {content_id} from {subscriber.name}")
        
        if self.name in interest_packet.visited:
            self.log_event(f"Loop detected: Dropping interest for {interest_packet.name} at {self.name}")
            return
        
        self.total_requests += 1
        
        if not hasattr(interest_packet, 'actual_hop_count'):
            interest_packet.actual_hop_count = 0
        interest_packet.actual_hop_count += 1
        
        interest_packet.path.append(self.name)
        interest_packet.visited.add(self.name)
        
        # Record arrival time for Algorithm1
        path_id = len(interest_packet.arrival_order)
        interest_packet.arrival_times[path_id] = time.time()
        interest_packet.arrival_order.append(path_id)
        
        if interest_packet.name not in self.pit:
            self.pit[interest_packet.name] = subscriber.name
            self.register_pit_entry(interest_packet.name, path_id, subscriber.name)
        
        if interest_packet.name in self.cs:
            self.cache_hits += 1
            self.requests_served_from_cache += 1
            data_packet = DataPacket(name=interest_packet.name, content=interest_packet.name, chunk_id=interest_packet.chunk_id)
            self.log_event(f"Cache hit for {interest_packet.name}")
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
        
        for content, expiry_time in list(self.cache_ttl.items()):
            if current_time > expiry_time:
                if content[0] in self.cs_chunks and content[1] in self.cs_chunks[content[0]]:
                    del self.cs_chunks[content[0]][content[1]]
                self.chunk_ttl.pop(content)
                self.log_event(f"Content {content} expired and removed from cache")
        
        ttl = current_time + datetime.timedelta(minutes=5)
        self.cache_ttl[data_packet.name] = ttl
        
        if len(self.cs) >= Router.CACHE_LIMIT:
            self.cache_evictions += 1
            
            if self.caching_policy == 'FACR':
                top_5_popular = set(self.popularity_table.head(5)['Content Name'])
                non_reserved_cache = [item for item in self.cs if item not in top_5_popular]
                if len(non_reserved_cache) >= (Router.CACHE_LIMIT - Router.TOP_N_POPULAR):
                    to_remove = non_reserved_cache[0]
                    self.cs.remove(to_remove)
                    self.cache_access_times.pop(to_remove, None)
                    self.cache_frequency.pop(to_remove, None)
            else:
                if self.caching_policy == 'LRU':
                    lru_content = min(self.cache_access_times, key=self.cache_access_times.get)
                    self.cs.remove(lru_content)
                    self.cache_access_times.pop(lru_content)
                elif self.caching_policy == 'LFU':
                    lfu_content = min(self.cache_frequency, key=self.cache_frequency.get)
                    self.cs.remove(lfu_content)
                    self.cache_frequency.pop(lfu_content)
                elif self.caching_policy == 'FIFO':
                    self.cs.pop(0)
                elif self.caching_policy == 'MRU':
                    mru_content = max(self.cache_access_times, key=self.cache_access_times.get)
                    self.cs.remove(mru_content)
                    self.cache_access_times.pop(mru_content)
        
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
        self.log_event(f"Cached {data_packet.name} with ID {content_id}")
    
    def save_fib(self):
        fib_dir = os.path.join('Output/FIB', self.name)
        os.makedirs(fib_dir, exist_ok=True)
        with open(f'{fib_dir}/fib.csv', mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Name", "ID", "Next Hop"])
            for name, next_hop in self.fib.items():
                content_id = ContentIDManager.get_unique_id(name)
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
        self.popularity_table.to_csv(f'Popularity_Table/{policy}/Ptable.csv', index=False)
    
    def log_event(self, message):
        os.makedirs('Logs', exist_ok=True)
        with open(f'Logs/log_{self.name}.txt', 'a') as log_file:
            log_file.write(f"[{datetime.datetime.now()}] {message}\n")

# ============================================================================
# PUBLISHER AND SUBSCRIBER CLASSES
# ============================================================================

class Publisher(Node):
    def __init__(self, name, folder):
        super().__init__(name)
        self.folder = folder
        self.images = self.load_images()
        self.content_chunks = {}  # Store chunks for multipath transmission
    
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
    
    def split_content_into_chunks(self, content_name, content_data, chunk_size=8192):
        """Split content into chunks according to Algorithm1"""
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
        self.received_chunks = {}  # Track received chunks: {content_name: {chunk_id: data}}
        self.chunk_assembly_times = {}  # Track when chunks arrive
    
    def send_interest(self, interest_packet, router):
        if isinstance(router, Router):
            router.receive_interest(interest_packet, self)
    
    def receive_data(self, data_packet):
        print(f"Subscriber {self.name} received data for {data_packet.name}")
        
        if data_packet.name not in self.received_chunks:
            self.received_chunks[data_packet.name] = {}
            self.chunk_assembly_times[data_packet.name] = {}
        
        if data_packet.chunk_id is not None:
            self.received_chunks[data_packet.name][data_packet.chunk_id] = data_packet.content
            self.chunk_assembly_times[data_packet.name][data_packet.chunk_id] = time.time()
        
        feedback = random.choice(['like', 'dislike', 'neutral', 'highly_like', 'highly_dislike'])
        print(f"Subscriber {self.name} provided feedback: {feedback} for {data_packet.name}")

# ============================================================================
# NETWORK SETUP WITH MULTIPLE PATHS
# ============================================================================

def get_valid_integer(prompt):
    """Get validated integer input from user"""
    while True:
        try:
            value = int(input(prompt))
            if value > 0:
                return value
            else:
                print("Please enter a positive integer.")
        except ValueError:
            print("Invalid input. Please enter a valid integer.")

def setup_network():
    """Set up network with configurable number of routers and multiple paths"""
    if os.path.exists("Saved_Network/network_setup.pkl"):
        choice = input("Use existing network setup? (yes/no): ").strip().lower()
        if choice == 'yes':
            try:
                routers, publishers, subscribers = load_network()
                print("Loaded existing network successfully.")
                return routers, publishers, subscribers
            except Exception as e:
                print(f"Error loading network: {e}. Creating a new network setup...")
    
    num_routers = get_valid_integer("Enter the number of routers: ")
    
    routers = [Router(f'Router{i}') for i in range(1, num_routers + 1)]
    
    # Publishers
    publisher1 = Publisher('Publisher1', 'cats')
    publisher2 = Publisher('Publisher2', 'dogs')
    publishers = [publisher1, publisher2]
    
    # Subscribers
    num_subscribers = get_valid_integer("Enter the number of subscribers: ")
    subscribers = [Subscriber(f'Subscriber{i}') for i in range(1, num_subscribers + 1)]
    
    # Connect subscribers to routers
    for i, subscriber in enumerate(subscribers):
        router_index = i % len(routers)
        subscriber.connected_router = routers[router_index]
    
    # Initialize content ID manager
    ContentIDManager.initialize_index(publishers)
    
    # Setup FIB with multiple paths
    for i, router in enumerate(routers):
        if i < len(routers) - 1:
            router.fib.update({f"cat_image{j}.jpg": routers[i + 1] for j in range(1, 51)})
            router.fib.update({f"dog_image{j}.jpg": routers[i + 1] for j in range(1, 51)})
        
        # Add alternative paths
        for j in range(i + 2, min(i + 4, len(routers))):
            router.fib.update({f"cat_image{k}.jpg": routers[j] for k in range(1, 51)})
            router.fib.update({f"dog_image{k}.jpg": routers[j] for k in range(1, 51)})
    
    # Last router connects to publishers
    routers[-1].fib.update({f"cat_image{j}.jpg": publisher1 for j in range(1, 51)})
    routers[-1].fib.update({f"dog_image{j}.jpg": publisher2 for j in range(1, 51)})
    
    save_network(routers, publishers, subscribers)
    print("New network setup created and saved.")
    
    return routers, publishers, subscribers

def save_network(routers, publishers, subscribers):
    """Save network configuration"""
    os.makedirs("Saved_Network", exist_ok=True)
    with open("Saved_Network/network_setup.pkl", "wb") as file:
        pickle.dump((routers, publishers, subscribers), file)
    print("Network setup saved successfully.")

def load_network():
    """Load network configuration"""
    try:
        with open("Saved_Network/network_setup.pkl", "rb") as file:
            return pickle.load(file)
    except Exception as e:
        print(f"Failed to load the network: {e}")
        return None

# ============================================================================
# ALGORITHM1: MULTI-PATH CHUNK DISTRIBUTION
# ============================================================================

def calculate_forward_delay(interest_packet, routers):
    """
    Algorithm1 Step 4: Calculate forward delay for each path
    d_i^fwd = t_i^arr - t_consumer^send
    """
    forward_delays = {}
    consumer_send_time = interest_packet.send_time
    
    for path_id, arrival_time in interest_packet.arrival_times.items():
        forward_delay = arrival_time - consumer_send_time
        forward_delays[path_id] = forward_delay
    
    return forward_delays

def calculate_rtt(forward_delays):
    """
    Algorithm1 Step 5: Calculate RTT estimation
    Expected RTT ≈ 2 * d_i^fwd
    """
    rtt_estimates = {}
    for path_id, fwd_delay in forward_delays.items():
        rtt_estimates[path_id] = 2 * fwd_delay
    return rtt_estimates

def calculate_goodput_per_path(forward_delays, chunk_size=8192, smoothing_factor=0.2):
    """
    Algorithm1 Step 6: Calculate goodput for each path
    g_i = S / r_i (instantaneous goodput)
    smoothed: g_i_bar = (1 - c) * g_i_bar + c * g_i
    """
    goodputs = {}
    
    for path_id, arrival_delay in forward_delays.items():
        if arrival_delay > 0:
            instantaneous_goodput = chunk_size / arrival_delay  # bytes per second
            smoothed_goodput = (1 - smoothing_factor) * instantaneous_goodput + smoothing_factor * instantaneous_goodput
            goodputs[path_id] = smoothed_goodput
        else:
            goodputs[path_id] = 0
    
    return goodputs

def create_chunk_subsets_for_paths(num_paths, num_chunks, goodputs):
    """
    Algorithm1 Step 8: Create subset C_i for each path
    |C_i| = floor((w_i / sum(w_j)) * K)
    where w_i = 1 / d_i^fwd or w_i = g_i_bar / r_i
    """
    # Calculate weights based on goodput
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

def implement_algorithm1(interest_packet, publisher, num_paths, chunk_size=8192):
    """
    Full Algorithm1 implementation:
    1. Create IP entries for content N
    2. For each path i, store arrival time
    3. Calculate forward delay
    4. Build performance table
    5. Calculate goodput for each path
    6. Split content into chunks
    7. Create subsets for paths
    8-11. Transmit chunks and store in CS
    12. Consumer receives chunks from multiple paths
    """
    print(f"\n=== ALGORITHM1 EXECUTION ===")
    print(f"Content: {interest_packet.name}")
    print(f"Number of Paths: {num_paths}")
    
    # Step 1-3: Already tracked in interest packet
    # Step 4: Calculate forward delays
    forward_delays = calculate_forward_delay(interest_packet, num_paths)
    print(f"Forward Delays per path: {forward_delays}")
    
    # Step 5: Calculate RTT
    rtt_estimates = calculate_rtt(forward_delays)
    print(f"RTT Estimates per path: {rtt_estimates}")
    
    # Step 6: Calculate goodput
    goodputs = calculate_goodput_per_path(forward_delays, chunk_size)
    print(f"Goodput per path (bytes/sec): {goodputs}")
    
    # Step 7: Split content into chunks
    content_data = b"dummy_content_" + interest_packet.name.encode() * 100
    chunks, num_chunks = publisher.split_content_into_chunks(interest_packet.name, content_data, chunk_size)
    print(f"Content split into {num_chunks} chunks of size {chunk_size} bytes")
    
    # Step 8: Create subset C_i for each path
    chunk_subsets = create_chunk_subsets_for_paths(num_paths, num_chunks, goodputs)
    print(f"Chunk distribution per path:")
    for path_id, chunks_list in chunk_subsets.items():
        print(f"  Path {path_id}: {len(chunks_list)} chunks - {chunks_list}")
    
    # Step 9-11: Transmit chunks (simulated)
    # In real scenario, would transmit chunks and store in CS of intermediate routers
    
    # Step 12: Consumer receives chunks
    transmission_data = {
        'content_name': interest_packet.name,
        'num_paths': num_paths,
        'total_chunks': num_chunks,
        'forward_delays': forward_delays,
        'goodputs': goodputs,
        'chunk_distribution': chunk_subsets
    }
    
    return transmission_data, chunk_subsets

# ============================================================================
# PERFORMANCE METRICS CALCULATION
# ============================================================================

def calculate_latency_multipath(chunk_subsets, rtt_estimates):
    """Calculate latency considering multipath transmission"""
    latencies = {}
    total_latency = 0
    
    for path_id, chunks in chunk_subsets.items():
        rtt = rtt_estimates.get(path_id, 0.01)
        path_latency = rtt * len(chunks)
        latencies[path_id] = path_latency
        total_latency = max(total_latency, path_latency)  # Overall latency is max across paths
    
    return latencies, total_latency

def calculate_cache_hit_ratio_multipath(routers):
    """Calculate overall cache hit ratio"""
    total_requests = sum(router.total_requests for router in routers)
    total_hits = sum(router.cache_hits for router in routers)
    
    if total_requests > 0:
        cache_hit_ratio = (total_hits / total_requests) * 100
    else:
        cache_hit_ratio = 0
    
    return cache_hit_ratio

def calculate_goodput_statistics(goodputs):
    """Calculate statistics on goodput across paths"""
    if not goodputs:
        return 0, 0, 0
    
    goodput_values = list(goodputs.values())
    avg_goodput = np.mean(goodput_values)
    min_goodput = np.min(goodput_values)
    max_goodput = np.max(goodput_values)
    
    return avg_goodput, min_goodput, max_goodput

# ============================================================================
# SIMULATION RUNNER
# ============================================================================

def run_simulation(routers, publishers, subscribers, policy, iterations, num_paths=3):
    """Run simulation with Algorithm1 integration"""
    for router in routers:
        router.caching_policy = policy
        router.reset()
    
    contents = [f"cat_image{i}.jpg" for i in range(1, 51)] + [f"dog_image{i}.jpg" for i in range(1, 51)]
    simulation_data = []
    
    active_prob = 0.9
    rtt_estimates = {}
    
    for iteration in range(iterations):
        for subscriber in subscribers:
            subscriber.active = random.random() < active_prob
        
        active_subscribers = [s for s in subscribers if s.active]
        
        if active_subscribers:
            subscriber = random.choice(active_subscribers)
            content_to_request = random.choice(contents)
            interest_packet = InterestPacket(name=content_to_request)
            
            # Simulate multiple paths
            for path_id in range(num_paths):
                interest_packet.arrival_times[path_id] = time.time() + random.uniform(0.001, 0.05)
                interest_packet.arrival_order.append(path_id)
            
            # Implement Algorithm1
            transmission_data, chunk_subsets = implement_algorithm1(
                interest_packet, 
                publishers[0],
                num_paths
            )
            
            subscriber.send_interest(interest_packet, subscriber.connected_router)
            
            # Calculate metrics
            forward_delays = transmission_data['forward_delays']
            goodputs = transmission_data['goodputs']
            
            # Calculate RTT from forward delays
            rtt_est = {pid: 2 * fd for pid, fd in forward_delays.items()}
            rtt_estimates.update(rtt_est)
            
            latencies, total_latency = calculate_latency_multipath(chunk_subsets, rtt_est)
            cache_hit_ratio = calculate_cache_hit_ratio_multipath(routers)
            avg_goodput, min_goodput, max_goodput = calculate_goodput_statistics(goodputs)
            
            hop_reduction = 0.5  # Placeholder
            
            simulation_data.append([
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                len(active_subscribers),
                sum(router.total_requests for router in routers),
                hop_reduction,
                cache_hit_ratio,
                total_latency,
                avg_goodput
            ])
    
    return simulation_data

# ============================================================================
# RESULTS SAVING AND VISUALIZATION
# ============================================================================

def save_simulation_data(simulation_data, policy):
    """Save simulation data to CSV"""
    os.makedirs(f'ML_Training_Data/{policy}', exist_ok=True)
    columns = ['Simulation Time', 'No of Clients', 'Total Requests', 'Hop Reduction', 'Cache Hit Ratio', 'Latency', 'Avg Goodput']
    df = pd.DataFrame(simulation_data, columns=columns)
    df.to_csv(f'ML_Training_Data/{policy}/features.csv', mode='a', header=not os.path.exists(f'ML_Training_Data/{policy}/features.csv'), index=False)
    print(f"Data for {policy} policy saved successfully.")

def save_results(policy_stats):
    """Save all results"""
    os.makedirs('Simulation_Results', exist_ok=True)
    filename = 'Simulation_Results/policy_comparison.csv'
    
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Policy", "Iteration", "Cache Hit Ratio", "Latency", "Hop Reduction", "Goodput"])
        
        for stat in policy_stats:
            writer.writerow([
                stat["Policy"],
                stat["Iteration"],
                stat["Cache Hit Ratio"],
                stat["Latency"],
                stat["Hop Reduction"],
                stat["Goodput"]
            ])
    
    print(f"Results saved to {filename}.")

def plot_network_graph(routers, publishers, subscribers):
    """Plot network topology"""
    G = nx.Graph()
    
    for router in routers:
        G.add_node(router.name, label='Router', color='lightblue')
    
    for publisher in publishers:
        G.add_node(publisher.name, label='Publisher', color='lightgreen')
    
    for subscriber in subscribers:
        G.add_node(subscriber.name, label='Subscriber', color='salmon')
    
    for router in routers:
        for destination, next_hop in router.fib.items():
            if next_hop and next_hop.name in G:
                G.add_edge(router.name, next_hop.name)
    
    for subscriber in subscribers:
        if subscriber.connected_router:
            G.add_edge(subscriber.name, subscriber.connected_router.name)
    
    colors = [G.nodes[node]['color'] for node in G.nodes]
    pos = nx.spring_layout(G, seed=42)
    
    plt.figure(figsize=(14, 10))
    nx.draw_networkx_nodes(G, pos, node_color=colors, node_size=800, alpha=0.9)
    nx.draw_networkx_edges(G, pos, width=1.2, alpha=0.7)
    nx.draw_networkx_labels(G, pos, font_size=9, font_family="sans-serif", font_weight="bold")
    
    plt.title("Multi-Path ICN Network Topology with Algorithm1", fontsize=14, fontweight='bold')
    plt.axis('off')
    plt.tight_layout()
    plt.savefig('Network_Topology.png', dpi=300)
    print("Network topology saved as Network_Topology.png")
    plt.show()

def plot_algorithm1_results(all_simulation_data):
    """Plot Algorithm1 simulation results"""
    fig, axs = plt.subplots(2, 2, figsize=(15, 10))
    
    all_data = []
    for policy_data in all_simulation_data:
        policy = policy_data['Policy']
        data = policy_data['Data']
        for i, row in enumerate(data):
            all_data.append({
                'Policy': policy,
                'Iteration': i + 1,
                'Clients': row[1],
                'Requests': row[2],
                'Latency': row[5],
                'Goodput': row[6],
                'Cache Hit': row[4]
            })
    
    df = pd.DataFrame(all_data)
    
    # Plot 1: Latency
    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]
        axs[0, 0].plot(policy_df['Iteration'], policy_df['Latency'], label=policy, marker='o', markersize=4)
    axs[0, 0].set_title('Latency over Iterations', fontweight='bold')
    axs[0, 0].set_xlabel('Iteration')
    axs[0, 0].set_ylabel('Latency (ms)')
    axs[0, 0].legend()
    axs[0, 0].grid(True, linestyle='--', alpha=0.5)
    
    # Plot 2: Goodput
    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]
        axs[0, 1].plot(policy_df['Iteration'], policy_df['Goodput'], label=policy, marker='o', markersize=4)
    axs[0, 1].set_title('Goodput over Iterations', fontweight='bold')
    axs[0, 1].set_xlabel('Iteration')
    axs[0, 1].set_ylabel('Goodput (bytes/sec)')
    axs[0, 1].legend()
    axs[0, 1].grid(True, linestyle='--', alpha=0.5)
    
    # Plot 3: Cache Hit Ratio
    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]
        axs[1, 0].plot(policy_df['Iteration'], policy_df['Cache Hit'], label=policy, marker='o', markersize=4)
    axs[1, 0].set_title('Cache Hit Ratio over Iterations', fontweight='bold')
    axs[1, 0].set_xlabel('Iteration')
    axs[1, 0].set_ylabel('Cache Hit Ratio (%)')
    axs[1, 0].legend()
    axs[1, 0].grid(True, linestyle='--', alpha=0.5)
    
    # Plot 4: Total Requests
    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]
        axs[1, 1].plot(policy_df['Iteration'], policy_df['Requests'], label=policy, marker='o', markersize=4)
    axs[1, 1].set_title('Total Requests over Iterations', fontweight='bold')
    axs[1, 1].set_xlabel('Iteration')
    axs[1, 1].set_ylabel('Total Requests')
    axs[1, 1].legend()
    axs[1, 1].grid(True, linestyle='--', alpha=0.5)
    
    plt.suptitle('Algorithm1 Multi-Path Content Distribution - Performance Metrics', fontsize=15, fontweight='bold')
    plt.tight_layout(rect=[0, 0.03, 1, 0.97])
    plt.savefig('Algorithm1_Results.png', dpi=300)
    print("Algorithm1 results saved as Algorithm1_Results.png")
    plt.show()

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    print("=== ICN MULTI-PATH NETWORK SIMULATOR WITH ALGORITHM1 ===\n")
    
    # Setup network with user input
    routers, publishers, subscribers = setup_network()
    print(f"\nNetwork configured with:")
    print(f"  Routers: {len(routers)}")
    print(f"  Publishers: {len(publishers)}")
    print(f"  Subscribers: {len(subscribers)}")
    
    # Plot network topology
    plot_network_graph(routers, publishers, subscribers)
    
    # Get simulation parameters
    iterations = get_valid_integer("\nEnter the number of content requests in the simulation: ")
    num_paths = get_valid_integer("Enter the number of paths for multi-path transmission: ")
    
    # Run simulation for multiple caching policies
    policies = ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR']
    all_simulation_data = []
    policy_stats = []
    
    for policy in policies:
        print(f"\nRunning simulation for {policy} policy...")
        routers, publishers, subscribers = load_network()
        
        sim_data = run_simulation(routers, publishers, subscribers, policy, iterations, num_paths)
        all_simulation_data.append({'Policy': policy, 'Data': sim_data})
        
        # Extract stats
        for i, row in enumerate(sim_data):
            policy_stats.append({
                'Policy': policy,
                'Iteration': i + 1,
                'Cache Hit Ratio': row[4],
                'Latency': row[5],
                'Hop Reduction': row[3],
                'Goodput': row[6]
            })
        
        save_simulation_data(sim_data, policy)
    
    # Save and plot results
    save_results(policy_stats)
    plot_algorithm1_results(all_simulation_data)
    
    print("\n=== SIMULATION COMPLETE ===")

if __name__ == "__main__":
    main()
