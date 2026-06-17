"""
================================================================================
INFORMATION-CENTRIC NETWORKING SIMULATION WITH ALGORITHM 1
Multi-Path Chunk Distribution with Goodput-Based Assignment
================================================================================

This implementation integrates Algorithm 1 for optimal chunk distribution across
multiple network paths using goodput-based metrics.

KEY FEATURES:
1. Multi-path chunk distribution based on path performance
2. Goodput calculation using formula: Goodput = chunk_size / delay
3. EWMA smoothing for goodput estimation
4. Dynamic chunk allocation proportional to path goodput
5. Performance metrics exported to CSV

ALGORITHM 1 IMPLEMENTATION:
- MultiPathChunkDistributor class handles chunk distribution logic
- Router.receive_interest_multipath() implements multi-path forwarding
- Path performance tracked via arrival times and delays
- Chunk allocation based on smoothed goodput weights

USAGE:
Run the simulation with multipath enabled (default). Performance data will be
saved to 'multipath_performance_<policy>.csv' containing:
- content_name: Requested content
- path: Path identifier
- forward_delay: Measured forward delay (seconds)
- instantaneous_goodput: Instantaneous goodput value
- smoothed_goodput: EWMA-smoothed goodput
- allocated_chunks: Number of chunks assigned to path
- total_chunks: Total chunks for content
- chunk_size_bytes: Size of each chunk in bytes

================================================================================
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
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
import math

# Base classes for Network elements(routers, publishers, subscribers)
class Node:
    def __init__(self, name):
        self.name = name
        self.fib = {} # Forwarding Information Base
        self.pit = {} # Pending Interest Table
        self.cs = [] # Content Store with limited cache size (15 images)

class InterestPacket:
    def __init__(self, name, chunk_id=None):
        self.name = name
        self.chunk_id = chunk_id  # Added for chunk support
        self.nonce = random.randint(1000, 9999) # Unique identifier to prevent loops
        self.visited = set() # Track visited routers to prevent loops
        self.path = [] # Track the path taken by the packet
        self.original_hop_count = 0 # Original hop count from subscriber to publisher
        self.actual_hop_count = 0 # Actual hop count taken by the packet

class ChunkPacket:
    """Represents individual chunks of data"""
    def __init__(self, name, chunk_id, chunk_data, total_chunks):
        self.name = name
        self.chunk_id = chunk_id
        self.chunk_data = chunk_data
        self.total_chunks = total_chunks
        self.is_last_chunk = (chunk_id == total_chunks - 1)

class DataPacket: # Data packet containing the requested content
    def __init__(self, name, content=None, chunks=None):
        self.name = name
        self.content = content
        self.chunks = chunks or []  # List of ChunkPacket objects
        self.is_chunked = len(self.chunks) > 0

class ContentIDManager: # Manages unique IDs for content items across the network.
    _content_id_map = {}

    @classmethod
    def initialize_index(cls, publishers):
        """Initialize index for all images across publishers"""
        image_id = 100 # Starting ID range from 100
        for publisher in publishers:
            for image_name in publisher.images.keys():
                if image_name not in cls._content_id_map: # Avoid duplicates
                    cls._content_id_map[image_name] = image_id # Assign unique ID
                    image_id += 1

    @classmethod
    def get_unique_id(cls, content_name):
        """Retrieve the unique ID for a given content name."""
        return cls._content_id_map.get(content_name, None)

# Router class with caching policies and FIB, PIT, CS functionality with chunking support
class Router(Node):
    CACHE_LIMIT = 15 # Cache size limit
    TOP_N_POPULAR = 5 # Reserve top 5 for most popular items
    NUM_CHUNKS = 4  # Number of chunks to divide data into

    def __init__(self, name, caching_policy='LRU', alpha=0.9):
        super().__init__(name)
        self.caching_policy = caching_policy # Store the caching policy
        self.alpha = alpha # Smoothing factor for EWMA (for calculating popularity)
        self.popularity_table = pd.DataFrame(columns=['Content Name', 'R_count', 'Popularity', 'Rank', 'Feedback'])
        self.cache_frequency = collections.defaultdict(int) # Frequency for LFU policy
        self.cache_access_times = {} # Access times for LRU and MRU policies
        self.connections = [] # Store connections to other routers or nodes
        self.fib = {}
        
        # Chunk management
        self.chunk_cache = {}  # Store individual chunks {content_name: {chunk_id: ChunkPacket}}
        self.pending_chunks = {}  # Track incomplete chunk sets
        
        # Multi-path tracking for Algorithm 1
        self.available_paths = []  # List of available paths (routers)
        self.path_arrival_times = {}  # Track arrival times per path
        self.path_performance = {}  # Performance metrics per path
        self.use_multipath = True  # Enable multi-path chunk distribution

        self.reset() # Initialize or reset all internal state variables
        self.save_fib() # save initial fib

    def reset(self):
        """Reset the router's cache, tables, and statistics."""
        self.cache_hits = 0
        self.publisher_hits = 0
        self.requests_served_from_cache = 0
        self.requests_served_from_publisher = 0
        self.cache_evictions = 0
        self.cache_access_times = {} # Store the last access time for cache entries (for LRU/MRU)
        self.cache_frequency = collections.defaultdict(int) # Frequency of accesses (for LFU)
        self.total_cache_access_time = 0
        self.total_requests = 0
        self.content_popularity = collections.defaultdict(int) # Track how often each content is requested
        self.cache_ttl = {} # Store time-to-live (TTL) for cache entries
        self.cs = [] # Clear the content store (cache)
        self.pit = {} # Clear the pending interest table (PIT)
        
        # Reset chunk management
        self.chunk_cache = {}
        self.pending_chunks = {}

    def update_popularity(self, content_name, feedback=None):
        """Update the request count and popularity score for content based on requests and feedback."""
        # Check if the content already exists in the popularity table
        if content_name in self.popularity_table['Content Name'].values:
            # Update existing entry
            content_index = self.popularity_table[self.popularity_table['Content Name'] == content_name].index[0]
            current_popularity = self.popularity_table.at[content_index, 'Popularity']
            r_count = self.popularity_table.at[content_index, 'R_count'] + 1

            # Adjust popularity based on feedback
            feedback_weights = {'highly_like': 1.5,'like': 1.2,'neutral': 1.0,'dislike': 0.8,'highly_dislike': 0.5} # Weights for feedback
            adjustment = feedback_weights.get(feedback, 1) # Default adjustment is 1 (no feedback)

            # Apply EWMA with feedback adjustment
            new_popularity = self.alpha * current_popularity + (1 - self.alpha) * r_count * adjustment
            self.popularity_table.at[content_index, 'R_count'] = r_count
            self.popularity_table.at[content_index, 'Popularity'] = new_popularity
            self.popularity_table.at[content_index, 'Feedback'] = feedback or 'None'
        else:
            # Add new content entry with initial values if it doesn't exist
            new_entry = {
                'Content Name': content_name,
                'R_count': 1,
                'Popularity': (1 - self.alpha),
                'Rank': None, # Rank will be updated later
                'Feedback': feedback or 'None'
            }
            self.popularity_table = pd.concat([self.popularity_table, pd.DataFrame([new_entry])], ignore_index=True)

        # Re-rank content after updating popularity
        self.rank_content()

    def rank_content(self):
        """Rank contents based on their popularity scores as integers and limit decimal points."""
        # Rank in descending order of popularity, converting rank to integers
        self.popularity_table['Rank'] = self.popularity_table['Popularity'].rank(method='min', ascending=False).astype(int)
        # Round the 'Popularity' column to 4 decimal places
        self.popularity_table['Popularity'] = pd.to_numeric(self.popularity_table['Popularity'], errors='coerce').round(4)
        # Sort values by rank
        self.popularity_table.sort_values(by='Rank', inplace=True)

    def receive_interest(self, interest_packet, subscriber): # Handle incoming interest packets with chunk support
        content_id = ContentIDManager.get_unique_id(interest_packet.name)
        self.content_popularity[interest_packet.name] += 1

        # Log the interest received
        self.log_event(f"Received interest for {interest_packet.name} with ID {content_id} from Subscriber {subscriber.name}")

        access_time = random.uniform(0.01, 0.1)
        self.total_cache_access_time += access_time

        # Prevent loops by checking if this router has already been visited
        if self.name in interest_packet.visited:
            self.log_event(f"Loop detected: Dropping interest for {interest_packet.name} at {self.name}")
            return

        # No loop only increment total_requests
        self.total_requests += 1

        # hop count tracking
        if not hasattr(interest_packet, 'actual_hop_count'):
            interest_packet.actual_hop_count = 0
        interest_packet.actual_hop_count += 1

        # Add this router to the packet's path
        interest_packet.path.append(self.name)
        interest_packet.visited.add(self.name)

        if interest_packet.name not in self.pit:
            self.pit[interest_packet.name] = subscriber.name
            self.save_pit()

        # Check if content is fully cached (all chunks available)
        if self._is_content_fully_cached(interest_packet.name):
            # Cache hit
            self.cache_hits += 1
            self.requests_served_from_cache += 1
            self.log_event(f"Cache hit: Serving {interest_packet.name} with ID {content_id} from cache (all chunks available)")
            
            # Send all chunks to subscriber
            cached_chunks = self._get_cached_chunks(interest_packet.name)
            for chunk in cached_chunks:
                subscriber.receive_chunk(chunk)
            return
        else:
            # Cache miss: Fetch content from publisher or next-hop router
            self.publisher_hits += 1
            self.log_event(f"Cache miss: Fetching {interest_packet.name} with ID {content_id} from Publisher or other routers")
            next_hop = self.fib.get(interest_packet.name)

            if next_hop:
                if isinstance(next_hop, Router):
                    next_hop.receive_interest(interest_packet, subscriber)
                elif isinstance(next_hop, Publisher):
                    chunks = next_hop.serve_content_chunks(interest_packet.name)
                    if chunks:
                        # Cache chunks and forward to subscriber
                        for chunk in chunks:
                            self.receive_chunk(chunk)
                            subscriber.receive_chunk(chunk)
            else:
                self.log_event(f"No route found in FIB for {interest_packet.name}")

            self.requests_served_from_publisher += 1

    def _is_content_fully_cached(self, content_name):
        """Check if all chunks for content are cached"""
        return (content_name in self.chunk_cache and 
                len(self.chunk_cache[content_name]) == self.NUM_CHUNKS)

    def _get_cached_chunks(self, content_name):
        """Retrieve all cached chunks for content in order"""
        if content_name in self.chunk_cache:
            return [self.chunk_cache[content_name][i] for i in range(self.NUM_CHUNKS)]
        return []

    def receive_chunk(self, chunk):
        """Handle incoming chunk packets"""
        content_name = chunk.name
        
        # Initialize chunk storage for this content
        if content_name not in self.chunk_cache:
            self.chunk_cache[content_name] = {}
        
        # Store the chunk
        self.chunk_cache[content_name][chunk.chunk_id] = chunk
        
        self.log_event(f"Received chunk {chunk.chunk_id + 1}/{chunk.total_chunks} for {content_name}")
        
        # Check if all chunks are received
        if len(self.chunk_cache[content_name]) == chunk.total_chunks:
            self.log_event(f"All chunks received for {content_name}, adding to content store")
            
            # Add to content store for caching policy management
            if content_name not in self.cs:
                self._manage_cache_eviction()
                self.cs.append(content_name)
                
                # Update cache metadata based on policy
                current_time = datetime.datetime.now()
                if self.caching_policy in ['LRU', 'MRU']:
                    self.cache_access_times[content_name] = current_time
                elif self.caching_policy == 'LFU':
                    self.cache_frequency[content_name] += 1
                
                # Set TTL
                ttl = current_time + datetime.timedelta(minutes=5)
                self.cache_ttl[content_name] = ttl
                
                self.save_cs()
                
                # Update popularity
                self.update_popularity(content_name)
                self.rank_content()
                self.save_popularity_table(self.caching_policy)

    def _manage_cache_eviction(self):
        """Handle cache evictions when cache is full"""
        if len(self.cs) >= Router.CACHE_LIMIT:
            self.cache_evictions += 1
            
            if self.caching_policy == 'FACR':
                # Identify top 5 popular content by rank in popularity_table
                top_5_popular = set(self.popularity_table.head(5)['Content Name'])
                non_reserved_cache = [item for item in self.cs if item not in top_5_popular]

                # Check if non-reserved cache space is full
                if len(non_reserved_cache) >= (Router.CACHE_LIMIT - Router.TOP_N_POPULAR):
                    to_remove = non_reserved_cache[0] # Evict the oldest in non-reserved
                    self._remove_from_cache(to_remove)
            else:
                if self.caching_policy == 'LRU':
                    lru_content = min(self.cache_access_times, key=self.cache_access_times.get)
                    self._remove_from_cache(lru_content)
                elif self.caching_policy == 'LFU':
                    lfu_content = min(self.cache_frequency, key=self.cache_frequency.get)
                    self._remove_from_cache(lfu_content)
                elif self.caching_policy == 'FIFO':
                    to_remove = self.cs[0]
                    self._remove_from_cache(to_remove)
                elif self.caching_policy == 'MRU':
                    mru_content = max(self.cache_access_times, key=self.cache_access_times.get)
                    self._remove_from_cache(mru_content)

    def _remove_from_cache(self, content_name):
        """Remove content and its chunks from cache"""
        if content_name in self.cs:
            self.cs.remove(content_name)
        if content_name in self.chunk_cache:
            del self.chunk_cache[content_name]
        self.cache_access_times.pop(content_name, None)
        self.cache_frequency.pop(content_name, None)
        self.cache_ttl.pop(content_name, None)
        self.log_event(f"Evicted {content_name} and its chunks from cache")

    def save_popularity_table(self, policy):
        """Save the popularity table to a policy-specific CSV, including feedback."""
        os.makedirs(f'Popularity_Table/{policy}', exist_ok=True)
        self.popularity_table.to_csv(f'Popularity_Table/{policy}/Ptable.csv', index=False)
        # print(f"Popularity table saved with feedback for {policy}.")

    def receive_data(self, data_packet): # Handle incoming data packets (legacy support)
        if data_packet.is_chunked:
            for chunk in data_packet.chunks:
                self.receive_chunk(chunk)
        else:
            # Handle non-chunked data (legacy support)
            current_time = datetime.datetime.now()
            
            # Remove expired content from the cache
            for content, expiry_time in list(self.cache_ttl.items()):
                if current_time > expiry_time:
                    self._remove_from_cache(content)
                    self.log_event(f"Content {content} expired and removed from cache")

            self._manage_cache_eviction()

            # Cache the new content
            if data_packet.name not in self.cs:
                self.cs.append(data_packet.name)

            if self.caching_policy in ['LRU', 'MRU']:
                self.cache_access_times[data_packet.name] = current_time
            elif self.caching_policy == 'LFU':
                self.cache_frequency[data_packet.name] += 1

            ttl = current_time + datetime.timedelta(minutes=5)
            self.cache_ttl[data_packet.name] = ttl

            self.save_cs()

            # Update popularity metrics for the content
            self.update_popularity(data_packet.name)
            self.rank_content()
            self.save_popularity_table(self.caching_policy)

            # Log caching event
            content_id = ContentIDManager.get_unique_id(data_packet.name)
            self.log_event(f"Cached {data_packet.name} with ID {content_id} in {self.name}'s Content Store with TTL of 5 minutes")

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


    def save_multipath_performance(self, filename='multipath_performance.csv'):
        """Save multi-path performance metrics to CSV"""
        if not hasattr(self, 'multipath_performance_data'):
            return

        if not self.multipath_performance_data:
            return

        import csv
        with open(filename, 'w', newline='') as csvfile:
            fieldnames = ['content_name', 'path', 'forward_delay', 'instantaneous_goodput', 
                         'smoothed_goodput', 'allocated_chunks', 'total_chunks', 'chunk_size_bytes']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in self.multipath_performance_data:
                writer.writerow(row)

        self.log_event(f"[MULTIPATH] Performance data saved to {filename}")

    def receive_interest_multipath(self, interest_packet, subscriber, available_paths=None):
        """
        Handle interest with multi-path chunk distribution using Algorithm 1.
        This method implements the chunked algorithm with goodput-based path selection.
        """
        content_id = ContentIDManager.get_unique_id(interest_packet.name)
        self.content_popularity[interest_packet.name] += 1

        consumer_send_time = time.time()  # Track when consumer sends request

        self.log_event(f"[MULTIPATH] Received interest for {interest_packet.name} from Subscriber {subscriber.name}")

        # Prevent loops
        if self.name in interest_packet.visited:
            self.log_event(f"Loop detected: Dropping interest for {interest_packet.name}")
            return

        self.total_requests += 1
        interest_packet.visited.add(self.name)
        interest_packet.path.append(self.name)

        # Register in PIT
        if interest_packet.name not in self.pit:
            self.pit[interest_packet.name] = subscriber.name
            self.save_pit()

        # Check if content is fully cached
        if self._is_content_fully_cached(interest_packet.name):
            self.cache_hits += 1
            self.requests_served_from_cache += 1
            self.log_event(f"[MULTIPATH] Cache hit: Serving from cache")

            cached_chunks = self._get_cached_chunks(interest_packet.name)
            for chunk in cached_chunks:
                subscriber.receive_chunk(chunk)
            return

        # Cache miss - fetch from publisher via multiple paths
        self.publisher_hits += 1
        self.log_event(f"[MULTIPATH] Cache miss: Fetching via multiple paths")

        # Discover available paths to publisher
        if available_paths is None:
            available_paths = self._discover_paths_to_publisher(interest_packet.name)

        if not available_paths:
            # Fallback to single path
            self.log_event(f"[MULTIPATH] No multiple paths found, using FIB")
            next_hop = self.fib.get(interest_packet.name)
            if next_hop and isinstance(next_hop, Publisher):
                chunks = next_hop.serve_content_chunks(interest_packet.name)
                if chunks:
                    for chunk in chunks:
                        self.receive_chunk(chunk)
                        subscriber.receive_chunk(chunk)
            self.requests_served_from_publisher += 1
            return

        # Get content from publisher to determine chunk info
        next_hop = self.fib.get(interest_packet.name)
        if not isinstance(next_hop, Publisher):
            self.log_event(f"[MULTIPATH] No publisher in FIB")
            self.requests_served_from_publisher += 1
            return

        chunks = next_hop.serve_content_chunks(interest_packet.name)
        if not chunks:
            self.log_event(f"[MULTIPATH] Content not found at publisher")
            return

        num_chunks = len(chunks)
        chunk_size = len(chunks[0].chunk_data) if chunks else 1024

        # Simulate arrival times for each path (in real scenario, measure actual times)
        arrival_time_table = {}
        for path_idx, path_router in enumerate(available_paths):
            # Simulate arrival time based on path characteristics
            # In production, this would be measured from actual packet arrivals
            base_delay = 0.01 * (path_idx + 1)  # Simulated delays
            arrival_time = consumer_send_time + base_delay
            path_id = f"path_{path_idx}_{path_router.name if hasattr(path_router, 'name') else path_idx}"
            arrival_time_table[path_id] = [arrival_time]

        # Use Algorithm 1 to distribute chunks
        distributor = MultiPathChunkDistributor(
            arrival_time_table=arrival_time_table,
            consumer_send_time=consumer_send_time,
            chunk_size=chunk_size,
            num_chunks=num_chunks,
            smooth_c=0.2
        )

        allocation = distributor.distribute_chunks()
        performance_log = distributor.get_performance_table()

        # Log the allocation decision
        self.log_event(f"[MULTIPATH] Chunk allocation: {allocation}")
        for perf in performance_log:
            self.log_event(f"[MULTIPATH] Path {perf['path']}: delay={perf['forward_delay']:.4f}s, "
                          f"goodput={perf['smooth_goodput']:.2f}, chunks={perf['allocated_chunks']}")

        # Distribute chunks according to allocation
        chunk_idx = 0
        for path_id, num_alloc in allocation.items():
            for _ in range(num_alloc):
                if chunk_idx < len(chunks):
                    chunk = chunks[chunk_idx]
                    # Cache and forward chunk
                    self.receive_chunk(chunk)
                    subscriber.receive_chunk(chunk)
                    chunk_idx += 1

        self.requests_served_from_publisher += 1

        # Store performance data for CSV export
        if not hasattr(self, 'multipath_performance_data'):
            self.multipath_performance_data = []

        for perf in performance_log:
            self.multipath_performance_data.append({
                'content_name': interest_packet.name,
                'path': perf['path'],
                'forward_delay': perf['forward_delay'],
                'instantaneous_goodput': perf['inst_goodput'],
                'smoothed_goodput': perf['smooth_goodput'],
                'allocated_chunks': perf['allocated_chunks'],
                'total_chunks': num_chunks,
                'chunk_size_bytes': chunk_size
            })

    def _discover_paths_to_publisher(self, content_name):
        """
        Discover multiple paths to publisher.
        In this simulation, we return connected routers as potential paths.
        """
        paths = []
        # Use connections as potential paths
        if hasattr(self, 'connections'):
            for conn in self.connections:
                if isinstance(conn, Router):
                    paths.append(conn)
        return paths[:3]  # Limit to top 3 paths for efficiency

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
            writer.writerow(["Content", "ID", "Chunks Cached"])
            for content in self.cs:
                content_id = ContentIDManager.get_unique_id(content)
                chunk_count = len(self.chunk_cache.get(content, {}))
                writer.writerow([content, content_id, chunk_count])

    def log_event(self, message):
        os.makedirs('Logs', exist_ok=True)
        with open(f'Logs/log_{self.name}.txt', 'a') as log_file:
            log_file.write(f"[{datetime.datetime.now()}] {message}\n")

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
        """Legacy method - serves complete content"""
        if content_name in self.images:
            file_path = self.images[content_name]
            with open(file_path, 'rb') as img_file:
                content = img_file.read()
            return DataPacket(name=content_name, content=content)
        return None

    def serve_content_chunks(self, content_name):
        """Serve content divided into chunks"""
        if content_name in self.images:
            file_path = self.images[content_name]
            with open(file_path, 'rb') as img_file:
                content = img_file.read()
            
            # Divide content into chunks
            return self._create_chunks(content_name, content)
        return None

    def _create_chunks(self, content_name, content_data):
        """Create 4 chunks from content data"""
        chunks = []
        total_size = len(content_data)
        num_chunks = 4  # Fixed to 4 chunks
        chunk_size = math.ceil(total_size / num_chunks)
        
        for i in range(num_chunks):
            start_pos = i * chunk_size
            end_pos = min(start_pos + chunk_size, total_size)
            chunk_data = content_data[start_pos:end_pos]
            
            chunk = ChunkPacket(
                name=content_name,
                chunk_id=i,
                chunk_data=chunk_data,
                total_chunks=num_chunks
            )
            chunks.append(chunk)
        
        print(f"Publisher {self.name} created {num_chunks} chunks for {content_name} (total size: {total_size} bytes)")
        return chunks

class Subscriber(Node):
    def __init__(self, name):
        super().__init__(name)
        self.active = True
        self.pending_chunks = {}  # Track incoming chunks {content_name: {chunk_id: ChunkPacket}}

    def send_interest(self, interest_packet, router, use_multipath=True):
        """Send interest packet to router, optionally using multipath"""
        if isinstance(router, Router):
            if use_multipath and hasattr(router, 'use_multipath') and router.use_multipath:
                # Use Algorithm 1 multipath distribution
                router.receive_interest_multipath(interest_packet, self)
            else:
                # Use traditional single-path forwarding
                router.receive_interest(interest_packet, self)

    def receive_chunk(self, chunk):
        """Receive individual chunks and assemble when complete"""
        content_name = chunk.name
        
        if content_name not in self.pending_chunks:
            self.pending_chunks[content_name] = {}
        
        # Store the chunk
        self.pending_chunks[content_name][chunk.chunk_id] = chunk
        
        print(f"Subscriber {self.name} received chunk {chunk.chunk_id + 1}/{chunk.total_chunks} for {content_name}")
        
        # Check if all chunks received - ONLY process when ALL chunks are received
        if len(self.pending_chunks[content_name]) == chunk.total_chunks:
            print(f"Subscriber {self.name}: All chunks received for {content_name}! Assembling content...")
            self._assemble_and_process_content(content_name)


    def _assemble_and_process_content(self, content_name):
        """Assemble chunks and process complete content - ONLY called when all chunks received"""
        chunk_dict = self.pending_chunks[content_name]
        
        # Assemble chunks in order
        assembled_content = b""
        for i in range(len(chunk_dict)):
            assembled_content += chunk_dict[i].chunk_data
        
        # Clean up pending chunks
        del self.pending_chunks[content_name]
        
        print(f"✓ Subscriber {self.name} successfully assembled complete content for {content_name} ({len(assembled_content)} bytes)")
        
        # Create complete data packet for processing
        complete_data = DataPacket(name=content_name, content=assembled_content)
        self.receive_data(complete_data)

    def provide_feedback(self, router, content_name, feedback):
        """Provide feedback on the content after receiving it."""
        print(f"Providing feedback: {feedback} for {content_name} via {router.name}")
        if feedback in ['like', 'dislike', 'neutral', 'highly_like', 'highly_dislike']:
            router.update_popularity(content_name, feedback=feedback)
        else:
            router.update_popularity(content_name, feedback='None')

    def receive_data(self, data_packet):
        """Process complete data and provide feedback - ONLY called after all chunks assembled"""
        print(f" Subscriber {self.name} received COMPLETE data for {data_packet.name}")
        # Assign feedback based on random or behavior-driven logic
        feedback = random.choice(['like', 'dislike', 'neutral', 'highly_like', 'highly_dislike'])
        print(f" Subscriber {self.name} provided feedback: {feedback} for {data_packet.name}")
        self.provide_feedback(self.connected_router, data_packet.name, feedback)

# Network management functions
def save_network(routers, publishers, subscribers):
    """Save the network setup to a file."""
    os.makedirs("Saved_Network", exist_ok=True)
    with open("Saved_Network/network_setup.pkl", "wb") as file:
        pickle.dump((routers, publishers, subscribers), file)
    print("Network setup saved successfully.")

def load_network():
    """Load the network setup from a saved file."""
    try:
        with open("Saved_Network/network_setup.pkl", "rb") as file:
            return pickle.load(file) # Ensure it returns a tuple
    except Exception as e:
        print(f"Failed to load the network: {e}")
        return None

def setup_network():
    """Set up the network or reuse an existing one."""
    if os.path.exists("Saved_Network/network_setup.pkl"):
        choice = input("Use existing network setup? (yes/no): ").strip().lower()
        if choice == 'yes':
            try:
                routers, publishers, subscribers = load_network() # Proper unpacking
                print("Loaded existing network successfully.")
                return routers, publishers, subscribers
            except Exception as e:
                print(f"Error loading network: {e}. Creating a new network setup...")

    # Helper function to get a valid integer input
    def get_valid_integer(prompt):
        """Prompt user for a positive integer and handle invalid inputs."""
        while True:
            try:
                value = int(input(prompt))
                if value > 0:
                    return value
                else:
                    print("Please enter a positive integer.")
            except ValueError:
                print("Invalid input. Please enter a valid integer.")

    # Get the number of routers with input validation
    num_routers = get_valid_integer("Enter the number of routers: ")
    routers = [Router(f'Router{i}') for i in range(1, num_routers + 1)] # Initialize routers here

    # Initialize publishers
    publisher1 = Publisher('Publisher1', 'cats')
    publisher2 = Publisher('Publisher2', 'dogs')
    publishers = [publisher1, publisher2]

    # Get the number of subscribers with input validation
    num_subscribers = get_valid_integer("Enter the number of subscribers: ")
    subscribers = [Subscriber(f'Subscriber{i}') for i in range(1, num_subscribers + 1)]

    # Connect subscribers to routers in a round-robin fashion
    for i, subscriber in enumerate(subscribers):
        router_index = i % len(routers)
        subscriber.connected_router = routers[router_index]

    # Initialize the content ID manager with the publishers' data
    ContentIDManager.initialize_index(publishers)

    # Set up the Forwarding Information Base (FIB) with multiple paths
    for i, router in enumerate(routers):
        # Connect to the next router in sequence
        if i < len(routers) - 1:
            router.fib.update({f"cat_image{j}.jpg": routers[i + 1] for j in range(1, 51)})
            router.fib.update({f"dog_image{j}.jpg": routers[i + 1] for j in range(1, 51)})

        # Add additional paths (loops) to other non-adjacent routers
        for j in range(i + 2, min(i + 4, len(routers))): # Avoid connecting directly adjacent routers
            router.fib.update({f"cat_image{k}.jpg": routers[j] for k in range(1, 51)})
            router.fib.update({f"dog_image{k}.jpg": routers[j] for k in range(1, 51)})

    # The last router connects directly to publishers
    routers[-1].fib.update({f"cat_image{j}.jpg": publisher1 for j in range(1, 51)})
    routers[-1].fib.update({f"dog_image{j}.jpg": publisher2 for j in range(1, 51)})

    # Save the new network setup to a file
    save_network(routers, publishers, subscribers)

    print("New network setup created and saved.")
    return routers, publishers, subscribers # Return the new network components

def estimate_max_possible_hops(routers, starting_router):
    """Estimate the maximum possible hops from starting router to publisher."""
    return len(routers) # Simple assumption for now, improves real behavior

import numpy as np
from sklearn.preprocessing import StandardScaler


# ============================================================================
# ALGORITHM 1: Multi-Path Chunk Distribution with Goodput-based Assignment
# ============================================================================

class MultiPathChunkDistributor:
    """
    Implements Algorithm 1 with Goodput formula assignment for multi-path chunk distribution.
    Based on the formula: Goodput = chunk_size / delay
    Uses EWMA smoothing for goodput estimation.
    """
    def __init__(self, arrival_time_table, consumer_send_time, chunk_size, num_chunks, smooth_c=0.2):
        """
        :param arrival_time_table: dict, path -> list of arrival times [float]
        :param consumer_send_time: float
        :param chunk_size: int/float (bytes)
        :param num_chunks: int
        :param smooth_c: float (smoothing factor c in [0,1])
        """
        self.arrival_time_table = arrival_time_table
        self.consumer_send_time = consumer_send_time
        self.chunk_size = chunk_size
        self.num_chunks = num_chunks
        self.smooth_c = smooth_c
        self.paths = list(arrival_time_table.keys())
        self.num_paths = len(self.paths)
        self.smooth_goodputs = {path: 0.0 for path in self.paths}
        self.path_performance_log = []  # Track performance metrics

    def calculate_forward_delays(self, arrival_times):
        """Calculate forward delays: d_i^fwd = t_i^arr - t_consumer^send"""
        return [t - self.consumer_send_time for t in arrival_times]

    def calculate_path_goodput(self, delays):
        """Calculate instantaneous goodput: g_i = chunk_size / delay"""
        return [self.chunk_size/d if d > 0 else 0.0 for d in delays]

    def smooth_goodput(self, path, inst_goodput):
        """Apply EWMA smoothing: g_smooth = (1-c)*g_prev + c*g_inst"""
        prev_g = self.smooth_goodputs[path]
        smoothed = (1-self.smooth_c)*prev_g + self.smooth_c*inst_goodput
        self.smooth_goodputs[path] = smoothed
        return smoothed

    def distribute_chunks(self):
        """
        Distribute chunks across paths based on smoothed goodput weights.
        Returns allocation dict: {path_id: num_chunks}
        """
        # Calculate delays and instantaneous goodput for each path
        inst_delays = []
        for path in self.paths:
            if len(self.arrival_time_table[path]) > 0:
                inst_delays.append(self.calculate_forward_delays(self.arrival_time_table[path])[0])
            else:
                inst_delays.append(float('inf'))  # No arrival yet

        inst_goodputs = self.calculate_path_goodput(inst_delays)

        # Update EWMA (smoothed) goodput
        for path, g in zip(self.paths, inst_goodputs):
            self.smooth_goodput(path, g)

        # Use smoothed goodput as weights
        weights = [self.smooth_goodputs[path] for path in self.paths]
        sum_w = sum(weights)

        if sum_w == 0:
            # Equal distribution if no data
            allocation = [self.num_chunks // self.num_paths] * self.num_paths
            remainder = self.num_chunks % self.num_paths
            for i in range(remainder):
                allocation[i] += 1
        else:
            # Proportional allocation based on weights
            allocation = [int(np.floor((w/sum_w)*self.num_chunks)) for w in weights]
            remainder = self.num_chunks - sum(allocation)

            # Distribute the remainder to paths with highest fractional parts
            while remainder > 0:
                fracs = [((w/sum_w)*self.num_chunks) - a for w, a in zip(weights, allocation)]
                idx = np.argmax(fracs)
                allocation[idx] += 1
                remainder -= 1

        allocations = {path: allocation[i] for i, path in enumerate(self.paths)}

        # Log performance data
        for i, path in enumerate(self.paths):
            self.path_performance_log.append({
                'path': path,
                'forward_delay': inst_delays[i] if inst_delays[i] != float('inf') else None,
                'inst_goodput': inst_goodputs[i],
                'smooth_goodput': self.smooth_goodputs[path],
                'allocated_chunks': allocations[path]
            })

        return allocations

    def get_performance_table(self):
        """Return performance metrics for all paths"""
        return self.path_performance_log



def predict_policy(model, simulation_data):

    # Use the simulation data to predict the next policy
    last_data = simulation_data[-1]  # Get the last entry from the simulation data
    
    # Extract the relevant numerical features for prediction.   
    # We need to extract the features that correspond to the model's training data.
    # No of Clients, Total Requests, Hop Reduction, Cache Hit Ratio, Latency
    feature_data = last_data[1:6]  
    
    print(f"Feature data for prediction: {feature_data}")

    scaler = StandardScaler()
    # The scaler expects a 2D array, so we reshape the feature data.
    feature_data_scaled = scaler.fit_transform(np.array(feature_data).reshape(1, -1))  
    
    print(f"Scaled feature data: {feature_data_scaled}")

    
    # We need to handle the case where the feedback score is missing.
    # We will use a try-except block to safely access the feedback score,
    # and if it's not present, we will assume a default value (e.g., 0 for neutral).
    try:
        
        feedback_score = last_data[6]
    except IndexError:
 
        feedback_score = 0
    
    # We need to convert this single value into a one-hot encoded vector.
    # The training data shows many one-hot encoded columns (x0_... to x7_...).
    # This implies there are more categorical features than just the feedback score.
    # However, based on the provided `simulation_data` format, `Feedback Score` is the
    # only one we can derive. We will assume the model expects a feature vector
    # of a specific length and fill in the missing one-hot encoded parts with zeros.
    
    # Let's assume the feedback score is mapped to the first set of one-hot encoded
    # features (x0_...).
    
    # Create the one-hot encoded vector for the feedback score.
    # We'll assume 5 categories for the feedback: 0, 1, 2, 3, 4.
    one_hot_feedback = np.zeros(5) # 5 categories for feedback score
    try:
        feedback_index = int(feedback_score)
        if 0 <= feedback_index < 5:
            one_hot_feedback[feedback_index] = 1.0
    except (ValueError, IndexError):
        # Handle cases where feedback score is not a valid integer or out of expected range.
        pass
    
    # The model input is a flat array of 45 elements:
    # We only have data for the first group of one-hot features.
    
    # Create a vector of zeros for the remaining one-hot encoded features.
    remaining_one_hot = np.zeros(35)
    
    # Combine the one-hot encoded feedback with the remaining zeros.
    full_one_hot = np.concatenate((one_hot_feedback, remaining_one_hot))

    # Combine the numerical and one-hot encoded features.
    new_data = np.concatenate((feature_data_scaled.flatten(), full_one_hot))
    
    # The model's predict method expects a 2D array.
    new_data = new_data.reshape(1, -1)
    
  
    predicted_policy = model.predict(new_data)[0]  
    print(f"Predicted policy from model: {predicted_policy}")
    return predicted_policy

def run_simulation(routers, publishers, subscribers, policy, iterations, model=None):
    # Reset routers to ensure a clean state
    for router in routers:
        router.caching_policy = policy
        router.reset()

    contents = [f"cat_image{i}.jpg" for i in range(1, 51)] + [f"dog_image{i}.jpg" for i in range(1, 51)]
    simulation_data = []
    active_prob = 0.9 # Subscriber active probability

    for iteration in range(iterations):
        print(f"\n--- Iteration {iteration + 1}/{iterations} for {policy} policy ---")
        
        for subscriber in subscribers:
            subscriber.active = random.random() < active_prob

        active_subscribers = [s for s in subscribers if s.active]
        if active_subscribers: # Ensure there is at least one active subscriber
            subscriber = random.choice(active_subscribers)
            content_to_request = random.choice(contents)

            print(f"🔍 {subscriber.name} requesting {content_to_request}")
            
            interest_packet = InterestPacket(name=content_to_request)
            interest_packet.original_hop_count = estimate_max_possible_hops(routers, subscriber.connected_router)

            subscriber.send_interest(interest_packet, subscriber.connected_router)

            interest_packet.actual_hop_count = len(interest_packet.path)
            subscriber.last_interest_packet = interest_packet

        # Calculate metrics
        latency = random.uniform(0.01, 0.1)
        total_requests = sum(router.cache_hits + router.publisher_hits for router in routers)
        total_cache_hits = sum(router.cache_hits for router in routers)
        avg_cache_hit = (total_cache_hits / total_requests) * 100 if total_requests > 0 else 0
        avg_latency = latency / total_requests if total_requests > 0 else 0

        hop_reduction_ratios = []
        for subscriber in subscribers:
            if hasattr(subscriber, 'last_interest_packet'):
                pkt = subscriber.last_interest_packet
                if pkt.original_hop_count > 0:
                    reduction = (pkt.original_hop_count - pkt.actual_hop_count) / pkt.original_hop_count
                    hop_reduction_ratios.append(reduction)

        total_hop_reduction = sum(hop_reduction_ratios) / len(hop_reduction_ratios) if hop_reduction_ratios else 0

        # Collect simulation data (simplified format)
        simulation_data.append([datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                len(active_subscribers),
                                total_requests,
                                total_hop_reduction,
                                avg_cache_hit,
                                avg_latency])

        # If the policy is RandomForest, predict the next policy dynamically
        if model and policy == 'RandomForest':
            predicted_policy = predict_policy(model, simulation_data)  # Predict policy dynamically
            print(f"Predicted policy: {predicted_policy}")  # You can use this to log predicted policies

            # Set the predicted policy for the next iteration
            policy = predicted_policy


    # Save multipath performance data
    for router in routers:
        if hasattr(router, "save_multipath_performance"):
            router.save_multipath_performance(f"multipath_performance_{policy}.csv")

    return simulation_data

def save_simulation_data(simulation_data, policy):
    """Save the simulation data to a CSV file for each policy."""
    # Ensure the directory for saving the data exists
    os.makedirs(f'ML_Training_Data/{policy}', exist_ok=True)

    # Define columns for the dataset
    columns = ['Simulation Time', 'No of Clients', 'Total Requests',
               'Hop Reduction', 'Cache Hit Ratio', 'Latency', 'Feedback Scores']

    # Create a DataFrame from the collected data
    df = pd.DataFrame(simulation_data, columns=columns)

    # Save the data into CSV file for this policy
    df.to_csv(f'ML_Training_Data/{policy}/features.csv', mode='a', header=not os.path.exists(f'ML_Training_Data/{policy}/features.csv'), index=False)
    print(f"Data for {policy} policy saved successfully.")

def run_simulation_for_all_policies(routers, publishers, subscribers, iterations, random_forest_model=None):
    policies = ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR', 'RandomForest'] # Add RandomForest to the list of policies
    all_simulation_data = []

    # Run simulation for all caching policies
    for policy in policies:
        print(f"Running simulation for policy: {policy}")
        data_for_policy = run_simulation(routers, publishers, subscribers, policy, iterations, random_forest_model)

        # Collect the data for each policy
        all_simulation_data.append({
            'Policy': policy,
            'Data': data_for_policy
        })

    return all_simulation_data

def load_model(filename):
    try:
        with open(filename, 'rb') as file:
            model = pickle.load(file)
        if not isinstance(model, RandomForestClassifier):
            raise TypeError("Loaded model is not of type RandomForestClassifier")
        return model
    except Exception as e:
        print(f"Could not load model {filename}: {e}. Using simplified prediction.")
        return None

# Loading the Random Forest model with error handling
try:
    random_forest_model = load_model('models/random_forest_model.pkl')
except:
    random_forest_model = None
    print("Random Forest model not found. ")

# Preprocess the data for prediction
def preprocess_simulation_data(simulation_data):
    # Convert the real-time simulation data into a DataFrame for prediction
    df = pd.DataFrame([simulation_data])
    # Feature scaling (use the same scaler as during training)
    scaler = StandardScaler()
    scaled_data = scaler.fit_transform(df)
    return scaled_data

#Helper functions
def save_simulation_log(simulation_data):
    os.makedirs('Simulation_Log', exist_ok=True)
    with open('Simulation_Log/simulation_log.csv', mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Simulation Time", "No of Clients", "Total no of requests", "Average hop reduction", "Average Cache hit", "Average latency"])
        writer.writerows(simulation_data)
    print("Simulation log saved successfully.")

def save_policy_stats(policy, simulation_data):
    os.makedirs('Policy_Stats', exist_ok=True)
    filename = f'Policy_Stats/{policy}_stats.csv'
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Simulation Time", "No of Clients", "Total Requests", "Hop Reduction", "Cache Hit Ratio", "Latency"])
        writer.writerows(simulation_data)
    print(f"Stats saved for {policy} policy.")

def save_results(policy_stats):
    """Save the combined results of all policy simulations to a CSV file."""
    os.makedirs('Simulation_Results', exist_ok=True)
    filename = 'Simulation_Results/policy_comparison(chunked).csv'

    # Save all policy statistics into a CSV file
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        # Write header row
        writer.writerow(["Policy", "Iteration", "Cache Hit Ratio", "Latency", "Hop Reduction"])

        # Write each row of stats for every policy and iteration
        for stat in policy_stats:
            writer.writerow([
                stat["Policy"],
                stat["Iteration"],
                stat["Cache Hit Ratio"],
                stat["Latency"],
                stat["Hop Reduction"]
            ])

    print(f"Results saved to {filename}.")

def plot_policy_comparison(policy_stats):
    df = pd.DataFrame(policy_stats)
    # Calculate mean Cache Hit Ratio per policy
    cache_hit_avg = df.groupby('Policy')['Cache Hit Ratio'].mean()

    # Plot
    plt.figure(figsize=(8, 5))
    cache_hit_avg.plot(kind='bar', color='blue', edgecolor='black')
    plt.title('Average Cache Hit Ratio per Caching Policy (Chunked Transmission)', fontsize=14, fontweight='bold')
    plt.xlabel('Policy', fontsize=12)
    plt.ylabel('Cache Hit Ratio (%)', fontsize=12)
    plt.xticks(rotation=45, fontsize=10)
    plt.yticks(fontsize=10)
    plt.grid(axis='y', linestyle='--', linewidth=0.5)
    plt.tight_layout()
    plt.show()

def plot_network_graph(routers, publishers, subscribers):
    if not isinstance(routers, list):
        raise TypeError(f"Expected routers to be a list, but got {type(routers)}")

    G = nx.Graph()

    # Add routers
    for router in routers:
        G.add_node(router.name, label='Router', color='lightblue')

    # Add publishers
    for publisher in publishers:
        G.add_node(publisher.name, label='Publisher', color='lightgreen')

    # Add subscribers
    for subscriber in subscribers:
        G.add_node(subscriber.name, label='Subscriber', color='salmon')

    # Add edges (Router-Router, Router-Publisher, Subscriber-Router)
    for router in routers:
        for destination, next_hop in router.fib.items():
            if next_hop and next_hop.name in G:
                G.add_edge(router.name, next_hop.name)

    for subscriber in subscribers:
        if subscriber.connected_router:
            G.add_edge(subscriber.name, subscriber.connected_router.name)

    for router in routers:
        for destination, next_hop in router.fib.items():
            if isinstance(next_hop, Publisher) and next_hop.name in G:
                G.add_edge(router.name, next_hop.name)

    # Prepare for drawing
    colors = [G.nodes[node]['color'] for node in G.nodes]
    pos = nx.spring_layout(G, seed=42) # Fixed seed for reproducibility

    plt.figure(figsize=(12, 9))
    nx.draw_networkx_nodes(G, pos, node_color=colors, node_size=800, alpha=0.9)
    nx.draw_networkx_edges(G, pos, width=1.2, alpha=0.7)
    nx.draw_networkx_labels(G, pos, font_size=9, font_family="sans-serif", font_weight="bold")
    plt.title("Network Topology: Routers, Publishers, and Subscribers (Chunked Transmission)", fontsize=14, fontweight='bold')
    plt.axis('off')
    plt.tight_layout()
    plt.show()

def plot_simulation_log(simulation_data, policy):
    df = pd.DataFrame(simulation_data, columns=[
        "Simulation Time", "No of Clients", "Total Requests",
        "Hop Reduction", "Cache Hit Ratio", "Latency"
    ])
    df['Iteration'] = range(1, len(df) + 1)

    fig, axs = plt.subplots(2, 2, figsize=(14, 10))

    # Define plotting properties
    plot_settings = {
        "linewidth": 1.8,
        "marker": "o",
        "markersize": 4,
        "markevery": 10,
    }

    axs[0, 0].plot(df["Iteration"], df["No of Clients"], color='blue', **plot_settings)
    axs[0, 0].set_title('No of Clients over Iterations', fontsize=12, fontweight='bold')
    axs[0, 0].set_xlabel('Iteration', fontsize=10)
    axs[0, 0].set_ylabel('No of Clients', fontsize=10)
    axs[0, 0].grid(True, linestyle='--', linewidth=0.5)

    axs[0, 1].plot(df["Iteration"], df["Cache Hit Ratio"], color='darkgreen', **plot_settings)
    axs[0, 1].set_title('Cache Hit Ratio over Iterations', fontsize=12, fontweight='bold')
    axs[0, 1].set_xlabel('Iteration', fontsize=10)
    axs[0, 1].set_ylabel('Cache Hit Ratio (%)', fontsize=10)
    axs[0, 1].grid(True, linestyle='--', linewidth=0.5)

    axs[1, 0].plot(df["Iteration"], df["Latency"], color='red', **plot_settings)
    axs[1, 0].set_title('Latency over Iterations', fontsize=12, fontweight='bold')
    axs[1, 0].set_xlabel('Iteration', fontsize=10)
    axs[1, 0].set_ylabel('Latency', fontsize=10)
    axs[1, 0].grid(True, linestyle='--', linewidth=0.5)

    axs[1, 1].plot(df["Iteration"], df["Hop Reduction"], color='purple', **plot_settings)
    axs[1, 1].set_title('Hop Reduction over Iterations', fontsize=12, fontweight='bold')
    axs[1, 1].set_xlabel('Iteration', fontsize=10)
    axs[1, 1].set_ylabel('Hop Reduction', fontsize=10)
    axs[1, 1].grid(True, linestyle='--', linewidth=0.5)

    plt.suptitle(f"Chunked Transmission Results for {policy} Policy", fontsize=14, fontweight='bold')
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.show()

def plot_merged_graph(policy_stats):
    """Plot a merged graph comparing all traditional caching policies."""
    df = pd.DataFrame(policy_stats)
    fig, axs = plt.subplots(1, 3, figsize=(18, 6))

    # Define consistent colors for traditional policies
    traditional_colors = {
        'LRU': 'navy',
        'LFU': 'darkgreen',
        'FIFO': 'darkorange',
        'MRU': 'indigo',
        'FACR': 'saddlebrown'
    }

    # Common settings
    plot_settings = {
        "linewidth": 1.8,
        "marker": "o",
        "markersize": 4,
        "markevery": 10, # ✅ Markers every 10 points (as you want)
    }

    metrics = ["Cache Hit Ratio", "Latency", "Hop Reduction"]

    for i, metric in enumerate(metrics):
        ax = axs[i]
        for policy in df["Policy"].unique():
            policy_data = df[df["Policy"] == policy]
            ax.plot(
                policy_data["Iteration"], policy_data[metric],
                label=policy,
                color=traditional_colors.get(policy, 'gray'),
                linestyle='-',
                **plot_settings
            )

        ax.set_xlabel("Iteration", fontsize=10)
        ax.set_ylabel(metric, fontsize=10)
        ax.set_title(f"{metric} Comparison (Chunked)", fontsize=12, fontweight='bold')
        ax.grid(True, linestyle='--', linewidth=0.5)
        ax.legend(
            loc='best',
            fontsize='x-small',
            frameon=False,
            handlelength=2,
            labelspacing=0.3,
            borderpad=0.3,
            handletextpad=0.4
        )

    plt.suptitle("Chunked Transmission: Comparison of Caching Policies", fontsize=14, fontweight='bold')
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.show()

def main():
    print("=" * 80)
    print(" CHUNKED DATA TRANSMISSION SIMULATION")
    print("=" * 80)
    print(" Data will be divided into 4 chunks before transmission")
    print(" Clients will ONLY receive complete data when ALL chunks are received")
    print(" Chunks are cached and forwarded individually by routers")
    print("=" * 80)

    # Load existing network or create a new one
    routers, publishers, subscribers = setup_network()

    # Plot the network topology at the beginning
    plot_network_graph(routers, publishers, subscribers)

    # Get the number of iterations for the simulation
    iterations = int(input("Enter the number of content requests in the simulation: "))

    # Load the trained Random Forest model
    if random_forest_model:
        print("✓ Random Forest model loaded successfully")
    else:
        print("⚠️ Random Forest model not available - using simplified prediction")

    # Run the simulation for all policies and collect results
    policy_stats = []

    # Define the caching policies to be tested, including Random Forest
    policies = ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR', 'RandomForest']

    # Run the simulation for each policy and collect results
    for policy in policies:
        routers, publishers, subscribers = load_network() # Reload network for each policy

        print(f"\n🔧 Running chunked transmission simulation for {policy} policy...")

        # Modify `run_simulation` to handle the Random Forest policy dynamically
        if policy == 'RandomForest':
            stats = run_simulation(routers, publishers, subscribers, policy, iterations, random_forest_model)
        else:
            stats = run_simulation(routers, publishers, subscribers, policy, iterations)

        # Collect policy stats and add them to the list
        policy_stats.extend([
            {
                "Policy": policy,
                "Iteration": i + 1,
                "No of Clients": stat[1], # Number of clients
                "Cache Hit Ratio": stat[4], # Cache Hit Ratio
                "Latency": stat[5], # Latency
                "Hop Reduction": stat[3], # Hop Reduction
            }
            for i, stat in enumerate(stats)
        ])

    # Save the results for all policies to a CSV file
    save_results(policy_stats)

    # Plot the comparison of all policies in individual and merged graphs
    plot_policy_comparison(policy_stats)
    plot_merged_graph(policy_stats) # New merged graph plot
    
  
    print(" CHUNKED TRANSMISSION SIMULATION COMPLETED SUCCESSFULLY!")
    print("📊 Results saved to CSV files and plots generated")
   

if __name__ == "__main__":
    main()