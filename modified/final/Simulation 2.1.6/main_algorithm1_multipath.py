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
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
import math

# ============================================================================
# CONFIGURATION PARAMETERS (FROM PDF - GOODPUT CALCULATIONS)
# ============================================================================
PROTOCOL_OVERHEAD = 650  # bytes
MTU = 1500  # bytes
PACKET_LOSS_RATE = 0.01
SMOOTHING_FACTOR_C = 0.2
TIME_TO_LIVE = 10  # seconds
CHUNK_SIZE = 8192  # 8KB chunks

# ============================================================================
# CLASSES
# ============================================================================
class Node:
    def __init__(self, name):
        self.name = name
        self.fib = {}
        self.pit = {}
        self.cs = []
        self.log_events = []

    def log_event(self, message):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_events.append(f"[{timestamp}] {message}")
        print(message)

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
        self.arrival_times = {}  # {path_id: arrival_time}

class ChunkPacket:
    def __init__(self, name, chunk_id, chunk_data, total_chunks):
        self.name = name
        self.chunk_id = chunk_id
        self.chunk_data = chunk_data
        self.total_chunks = total_chunks
        self.is_last_chunk = (chunk_id == total_chunks - 1)
        self.arrival_time = None
        self.send_time = time.time()

class DataPacket:
    def __init__(self, name, content=None, chunks=None):
        self.name = name
        self.content = content
        self.chunks = chunks or []
        self.is_chunked = len(self.chunks) > 0

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
# ROUTER CLASS WITH ALGORITHM 1 & MULTIPATH SUPPORT
# ============================================================================
class Router(Node):
    CACHE_LIMIT = 15
    TOP_N_POPULAR = 5
    NUM_CHUNKS = 4

    def __init__(self, name, caching_policy='LRU', alpha=0.9):
        super().__init__(name)
        self.caching_policy = caching_policy
        self.alpha = alpha
        self.popularity_table = pd.DataFrame(columns=['Content Name', 'R_count', 'Popularity', 'Rank', 'Feedback'])
        self.cache_frequency = collections.defaultdict(int)
        self.cache_access_times = {}
        self.connections = []
        self.chunk_cache = {}
        self.pending_chunks = {}
        self.path_performance = {}
        self.forward_delays = {}
        self.goodput_values = {}
        self.reset()

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
        self.chunk_cache = {}
        self.pending_chunks = {}

    def calculate_forward_delay(self, num_hops):
        """Calculate forward delay: d_i_fwd = num_hops * hop_delay"""
        hop_delay = 0.002  # 2ms per hop
        return num_hops * hop_delay

    def calculate_goodput(self, chunk_size, inter_arrival_gap, rtt):
        """
        Calculate goodput from PDF:
        g_i = (S * (t_i_arr^k - t_i_arr^{k-1})) / (1 - c*b_i)
        """
        if inter_arrival_gap <= 0:
            inter_arrival_gap = 0.001

        instantaneous_goodput = chunk_size / inter_arrival_gap if inter_arrival_gap > 0 else 0
        smoothed_goodput = instantaneous_goodput * SMOOTHING_FACTOR_C

        return {
            'instantaneous': instantaneous_goodput,
            'smoothed': smoothed_goodput,
            'inter_arrival_gap': inter_arrival_gap
        }

    def allocate_chunks_multipath(self, content_name, total_chunks, paths_info):
        """
        Allocate chunks based on path goodput (Algorithm 1, Step 8)
        w_i = goodput_i / forward_delay_i
        """
        if not paths_info:
            return {0: list(range(total_chunks))}

        weights = {}
        for path_id, info in paths_info.items():
            goodput = info.get('goodput', 1)
            forward_delay = info.get('forward_delay', 1)
            if forward_delay <= 0:
                forward_delay = 0.001
            weight = (goodput / forward_delay) if goodput > 0 else 0.1
            weights[path_id] = weight

        total_weight = sum(weights.values())
        if total_weight == 0:
            total_weight = 1

        normalized_weights = {pid: w / total_weight for pid, w in weights.items()}

        allocation = {}
        chunks_allocated = 0

        for path_id, normalized_weight in sorted(normalized_weights.items()):
            num_chunks_for_path = max(1, int(total_chunks * normalized_weight))
            if chunks_allocated + num_chunks_for_path > total_chunks:
                num_chunks_for_path = total_chunks - chunks_allocated

            start_chunk = chunks_allocated
            end_chunk = min(chunks_allocated + num_chunks_for_path, total_chunks)
            allocation[path_id] = list(range(start_chunk, end_chunk))
            chunks_allocated = end_chunk

        return allocation

# ============================================================================
# PUBLISHER CLASS
# ============================================================================
class Publisher(Node):
    def __init__(self, name, folder):
        super().__init__(name)
        self.folder = folder
        self.images = self.load_images()
        self.interest_arrival_table = {}
        self.forward_delay_table = {}

    def load_images(self):
        images = {}
        for i in range(1, 51):
            images[f"cat_image{i}.jpg"] = f"Mock data for cat_image{i}.jpg" * 100
            images[f"dog_image{i}.jpg"] = f"Mock data for dog_image{i}.jpg" * 100
        return images

    def serve_content(self, content_name, num_chunks=4):
        """Algorithm 1, Step 7: Split content into chunks"""
        if content_name not in self.images:
            return []

        content = self.images[content_name]
        chunk_size = len(content) // num_chunks
        chunks = []

        for chunk_id in range(num_chunks):
            start = chunk_id * chunk_size
            end = start + chunk_size if chunk_id < num_chunks - 1 else len(content)
            chunk_data = content[start:end]
            chunk = ChunkPacket(content_name, chunk_id, chunk_data, num_chunks)
            chunks.append(chunk)

        return chunks

# ============================================================================
# SUBSCRIBER CLASS
# ============================================================================
class Subscriber(Node):
    def __init__(self, name):
        super().__init__(name)
        self.connected_router = None
        self.active = True
        self.received_chunks = {}
        self.request_send_time = {}
        self.last_interest_packet = None

    def send_interest(self, interest_packet, router):
        """Send interest to router"""
        self.last_interest_packet = interest_packet
        if isinstance(router, Router):
            router.receive_interest_multipath(interest_packet, self)

# ============================================================================
# NETWORK SETUP FUNCTION (WITH MULTIPATH SUPPORT)
# ============================================================================
def setup_network_multipath():
    """
    Set up network with:
    - User input for number of routers
    - 1 Producer, 1 Consumer
    - Multiple overlapping paths with shared routers
    """
    print("\n" + "="*80)
    print("SETUP NETWORK WITH MULTIPATH TOPOLOGY")
    print("="*80)

    num_routers = int(input("\nEnter the number of routers (min 3): "))
    if num_routers < 3:
        num_routers = 3

    print(f"\n[SETUP] Creating network with {num_routers} routers, 1 producer, 1 consumer")

    # Initialize nodes
    producer = Publisher('Producer', 'content')
    subscriber = Subscriber('Consumer')
    routers = [Router(f'Router{i}') for i in range(1, num_routers + 1)]

    # Connect subscriber to first router
    subscriber.connected_router = routers[0]
    print(f"[SETUP] Consumer connected to {routers[0].name}")

    # Build ring topology with additional connections for multipath
    print(f"[SETUP] Building multi-path topology...")

    for i in range(num_routers):
        router = routers[i]
        router.connections = []

        # Ring connections
        next_idx = (i + 1) % num_routers
        prev_idx = (i - 1) % num_routers

        router.connections.append(routers[next_idx])  # Next
        router.connections.append(routers[prev_idx])  # Previous

        # Skip-2 connection for path diversity
        skip_idx = (i + 2) % num_routers
        if routers[skip_idx] not in router.connections:
            router.connections.append(routers[skip_idx])

        # Set FIB to reach producer
        for content_name in producer.images.keys():
            router.fib[content_name] = producer

    # Last routers connect directly to producer
    for i in range(max(1, num_routers - 2), num_routers):
        routers[i].fib_publisher = producer

    print(f"[SETUP] Network created successfully!")
    print(f"[SETUP] Routers: {len(routers)}")
    print(f"[SETUP] Total paths available: Multiple (depends on topology)")

    return subscriber, producer, routers

def find_multiple_paths(start_router, end_producer, max_paths=5):
    """Find multiple paths from start_router to producer using BFS"""
    paths = []
    queue = [([start_router], set([start_router]))]

    while queue and len(paths) < max_paths:
        current_path, visited = queue.pop(0)
        current_router = current_path[-1]

        # Check if we can reach producer
        if end_producer in current_router.connections or hasattr(current_router, 'fib_publisher'):
            if current_path not in paths:
                paths.append(current_path)

        # Explore neighbors
        for neighbor in current_router.connections:
            if neighbor not in visited:
                new_visited = visited.copy()
                new_visited.add(neighbor)
                queue.append((current_path + [neighbor], new_visited))

    if not paths:
        paths.append([start_router])

    return paths[:max_paths]

# ============================================================================
# ALGORITHM 1 IMPLEMENTATION
# ============================================================================
def algorithm_1_transmission(subscriber, producer, routers, content_name, num_chunks=4):
    """
    Algorithm 1: Multipath Content Backtracking
    Steps 1-12: Interest forwarding, path discovery, goodput calculation, chunk allocation
    """

    print(f"\n[ALGO1] Starting content transmission for {content_name}")
    print(f"[ALGO1] Step 1-3: Create Interest entries for all paths")

    consumer_send_time = time.time()
    interest = InterestPacket(content_name)
    interest.send_time = consumer_send_time

    starting_router = subscriber.connected_router

    # Step 2: Discover paths
    print(f"[ALGO1] Step 2: Discovering multiple paths from {starting_router.name} to Producer")
    paths = find_multiple_paths(starting_router, producer, max_paths=5)

    path_performance = {}
    for path_id, path_routers in enumerate(paths):
        path_str = " -> ".join([r.name for r in path_routers] + [producer.name])
        print(f"[ALGO1]   Path {path_id}: {path_str} ({len(path_routers) + 1} hops)")

        # Step 3-5: Calculate forward delay
        num_hops = len(path_routers) + 1
        forward_delay = starting_router.calculate_forward_delay(num_hops)

        # Step 6: Calculate goodput
        inter_arrival_gap = 0.05
        goodput_calc = starting_router.calculate_goodput(CHUNK_SIZE, inter_arrival_gap, forward_delay)

        path_performance[path_id] = {
            'path': path_routers,
            'num_hops': num_hops,
            'forward_delay': forward_delay,
            'instantaneous_goodput': goodput_calc['instantaneous'],
            'smoothed_goodput': goodput_calc['smoothed'],
            'chunks_allocated': 0,
            'arrival_time': consumer_send_time + forward_delay
        }

        print(f"[ALGO1]   Path {path_id}: forward_delay={forward_delay:.4f}s, " 
              f"goodput={goodput_calc['smoothed']:.2f} bytes/sec")

    # Step 7-8: Split content and allocate chunks
    print(f"\n[ALGO1] Step 7-8: Splitting content into {num_chunks} chunks and allocating")

    chunks = producer.serve_content(content_name, num_chunks)

    # Create allocation dict
    allocation_dict = {}
    for path_id in path_performance:
        allocation_dict[path_id] = {
            'forward_delay': path_performance[path_id]['forward_delay'],
            'goodput': path_performance[path_id]['smoothed_goodput']
        }

    chunk_allocation = starting_router.allocate_chunks_multipath(content_name, num_chunks, allocation_dict)

    for path_id, chunk_ids in chunk_allocation.items():
        path_performance[path_id]['chunks_allocated'] = len(chunk_ids)
        print(f"[ALGO1]   Path {path_id}: allocate {len(chunk_ids)} chunks {chunk_ids}")

    # Step 9-12: Transmit and receive chunks
    print(f"\n[ALGO1] Step 9-12: Transmitting chunks via allocated paths")

    subscriber.received_chunks[content_name] = {}

    for path_id, chunk_ids in chunk_allocation.items():
        for chunk_id in chunk_ids:
            chunk = chunks[chunk_id]
            chunk.arrival_time = path_performance[path_id]['arrival_time']
            subscriber.received_chunks[content_name][chunk_id] = chunk
            print(f"[ALGO1]   Path {path_id}: transmitted chunk {chunk_id}")

    received_count = len(subscriber.received_chunks[content_name])
    print(f"\n[ALGO1] Consumer received {received_count}/{num_chunks} chunks")

    if received_count == num_chunks:
        print(f"[ALGO1] SUCCESS: Content reassembled from {len(paths)} paths!")

    return path_performance, chunk_allocation

# ============================================================================
# MULTIPATH RECEIVER - AGGREGATE CHUNKS
# ============================================================================
def aggregate_chunks_at_consumer(subscriber, content_name):
    """Aggregate chunks received at consumer from multiple paths"""
    if content_name not in subscriber.received_chunks:
        return None

    chunks = subscriber.received_chunks[content_name]
    sorted_chunks = sorted(chunks.items(), key=lambda x: x[0])

    aggregated_content = b''
    for chunk_id, chunk in sorted_chunks:
        aggregated_content += chunk.chunk_data.encode() if isinstance(chunk.chunk_data, str) else chunk.chunk_data

    return aggregated_content

# ============================================================================
# CSV DATA EXPORT (ALGORITHM 1 RESULTS)
# ============================================================================
def save_multipath_performance_csv(path_performance, content_name, policy='Multipath'):
    """Save path performance metrics to CSV"""
    os.makedirs('MultiPathResults', exist_ok=True)

    filename = f'MultiPathResults/multipath_performance_{policy}_{content_name}_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['Path_ID', 'Num_Hops', 'Forward_Delay_s', 'Instantaneous_Goodput_bytes_s', 
                      'Smoothed_Goodput_bytes_s', 'Chunks_Allocated', 'Arrival_Time']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for path_id, perf in path_performance.items():
            writer.writerow({
                'Path_ID': path_id,
                'Num_Hops': perf['num_hops'],
                'Forward_Delay_s': f"{perf['forward_delay']:.6f}",
                'Instantaneous_Goodput_bytes_s': f"{perf['instantaneous_goodput']:.2f}",
                'Smoothed_Goodput_bytes_s': f"{perf['smoothed_goodput']:.2f}",
                'Chunks_Allocated': perf['chunks_allocated'],
                'Arrival_Time': f"{perf['arrival_time']:.6f}"
            })

    print(f"[CSV] Multipath performance saved to {filename}")
    return filename

def save_simulation_results_csv(results_list, policy='Multipath'):
    """Save all simulation results to CSV"""
    os.makedirs('SimulationResults', exist_ok=True)

    filename = f'SimulationResults/simulation_results_{policy}_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['Iteration', 'Content_Name', 'Num_Routers', 'Num_Paths', 'Num_Chunks', 
                      'Total_Forward_Delay_s', 'Average_Goodput_bytes_s', 'Chunks_Received', 'Success']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for result in results_list:
            writer.writerow(result)

    print(f"[CSV] Simulation results saved to {filename}")
    return filename

# ============================================================================
# NETWORK VISUALIZATION
# ============================================================================
def plot_network_topology(subscriber, producer, routers):
    """Plot network topology"""
    G = nx.DiGraph()

    # Add nodes
    G.add_node('Consumer', node_type='consumer')
    G.add_node('Producer', node_type='producer')
    for router in routers:
        G.add_node(router.name, node_type='router')

    # Add edges
    G.add_edge('Consumer', routers[0].name)
    for router in routers:
        for neighbor in router.connections:
            G.add_edge(router.name, neighbor.name)
        if hasattr(router, 'fib_publisher'):
            G.add_edge(router.name, 'Producer')

    # Draw
    plt.figure(figsize=(14, 10))
    pos = nx.spring_layout(G, k=2, iterations=50, seed=42)

    node_colors = []
    for node in G.nodes():
        if 'Consumer' in node:
            node_colors.append('lightgreen')
        elif 'Producer' in node:
            node_colors.append('lightcoral')
        else:
            node_colors.append('lightblue')

    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=800, ax=plt.gca())
    nx.draw_networkx_labels(G, pos, font_size=9, font_weight='bold', ax=plt.gca())
    nx.draw_networkx_edges(G, pos, edge_color='gray', arrows=True, arrowsize=20, ax=plt.gca())

    plt.title("Multipath Network Topology (Algorithm 1)", fontsize=14, fontweight='bold')
    plt.axis('off')
    plt.tight_layout()
    plt.savefig('multipath_network_topology.png', dpi=150, bbox_inches='tight')
    print("[VIZ] Network topology saved as 'multipath_network_topology.png'")
    plt.show()

# ============================================================================
# MAIN FUNCTION
# ============================================================================
def main():
    print("\n" + "="*80)
    print("ALGORITHM 1 MULTIPATH CONTENT TRANSMISSION WITH GOODPUT CALCULATION")
    print("="*80)

    # Set up network
    subscriber, producer, routers = setup_network_multipath()

    # Visualize
    plot_network_topology(subscriber, producer, routers)

    # Initialize content manager
    ContentIDManager.initialize_index([producer])

    # Run simulations
    results = []

    iterations = 3  # Number of iterations
    contents = ['cat_image1.jpg', 'cat_image2.jpg', 'dog_image1.jpg']

    for iteration in range(iterations):
        for content_name in contents:
            print(f"\n[ITERATION {iteration+1}] Processing {content_name}...")

            # Run Algorithm 1
            path_performance, chunk_allocation = algorithm_1_transmission(
                subscriber, 
                producer, 
                routers, 
                content_name, 
                num_chunks=4
            )

            # Aggregate chunks
            aggregated = aggregate_chunks_at_consumer(subscriber, content_name)

            # Calculate metrics
            total_delay = sum(p['forward_delay'] for p in path_performance.values())
            avg_goodput = sum(p['smoothed_goodput'] for p in path_performance.values()) / len(path_performance)
            chunks_received = len(subscriber.received_chunks.get(content_name, {}))
            success = chunks_received == 4

            # Save results
            result = {
                'Iteration': iteration + 1,
                'Content_Name': content_name,
                'Num_Routers': len(routers),
                'Num_Paths': len(path_performance),
                'Num_Chunks': 4,
                'Total_Forward_Delay_s': f"{total_delay:.6f}",
                'Average_Goodput_bytes_s': f"{avg_goodput:.2f}",
                'Chunks_Received': chunks_received,
                'Success': 'Yes' if success else 'No'
            }
            results.append(result)

            # Save path performance
            save_multipath_performance_csv(path_performance, content_name, f'Iteration{iteration+1}')

    # Save all results
    save_simulation_results_csv(results, 'Multipath_Algorithm1')

    # Print summary
    print("\n" + "="*80)
    print("SIMULATION SUMMARY")
    print("="*80)
    df = pd.DataFrame(results)
    print(df.to_string(index=False))

if __name__ == "__main__":
    main()
