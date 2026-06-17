
import os
import csv
import random
import datetime
import time
import collections
import networkx as nx
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

"""
Algorithm1: One Producer, One Consumer, Multiple Paths
Cache Replacement Policies: LRU, LFU, FIFO, MRU, FACR
"""

class DataPacket:
    """Represents a data packet in the network"""
    def __init__(self, name, content_id, size=1024):
        self.name = name
        self.content_id = content_id
        self.size = size
        self.timestamp = time.time()

class InterestPacket:
    """Represents an interest packet requesting content"""
    def __init__(self, name, content_id):
        self.name = name
        self.content_id = content_id
        self.nonce = random.randint(1000, 9999)
        self.path = []
        self.hop_count = 0

class CacheReplacement:
    """Base class for cache replacement policies"""
    def __init__(self, cache_size=100):
        self.cache = {}
        self.cache_size = cache_size
        self.policy_name = "Base"

    def get(self, key):
        """Retrieve item from cache"""
        if key in self.cache:
            return self.cache[key]
        return None

    def put(self, key, value):
        """Insert item into cache, evicting if necessary"""
        pass

    def evict(self):
        """Evict an item from cache according to policy"""
        pass

class LRU(CacheReplacement):
    """Least Recently Used Cache"""
    def __init__(self, cache_size=100):
        super().__init__(cache_size)
        self.policy_name = "LRU"
        self.access_time = {}

    def get(self, key):
        if key in self.cache:
            self.access_time[key] = time.time()
            return self.cache[key]
        return None

    def put(self, key, value):
        if len(self.cache) >= self.cache_size:
            self.evict()
        self.cache[key] = value
        self.access_time[key] = time.time()

    def evict(self):
        lru_key = min(self.access_time, key=self.access_time.get)
        del self.cache[lru_key]
        del self.access_time[lru_key]

class LFU(CacheReplacement):
    """Least Frequently Used Cache"""
    def __init__(self, cache_size=100):
        super().__init__(cache_size)
        self.policy_name = "LFU"
        self.frequency = {}

    def get(self, key):
        if key in self.cache:
            self.frequency[key] = self.frequency.get(key, 0) + 1
            return self.cache[key]
        return None

    def put(self, key, value):
        if len(self.cache) >= self.cache_size:
            self.evict()
        self.cache[key] = value
        self.frequency[key] = self.frequency.get(key, 0) + 1

    def evict(self):
        lfu_key = min(self.frequency, key=self.frequency.get)
        del self.cache[lfu_key]
        del self.frequency[lfu_key]

class FIFO(CacheReplacement):
    """First In First Out Cache"""
    def __init__(self, cache_size=100):
        super().__init__(cache_size)
        self.policy_name = "FIFO"
        self.order = []

    def get(self, key):
        if key in self.cache:
            return self.cache[key]
        return None

    def put(self, key, value):
        if len(self.cache) >= self.cache_size:
            self.evict()
        self.cache[key] = value
        self.order.append(key)

    def evict(self):
        oldest_key = self.order.pop(0)
        del self.cache[oldest_key]

class MRU(CacheReplacement):
    """Most Recently Used Cache"""
    def __init__(self, cache_size=100):
        super().__init__(cache_size)
        self.policy_name = "MRU"
        self.access_time = {}

    def get(self, key):
        if key in self.cache:
            self.access_time[key] = time.time()
            return self.cache[key]
        return None

    def put(self, key, value):
        if len(self.cache) >= self.cache_size:
            self.evict()
        self.cache[key] = value
        self.access_time[key] = time.time()

    def evict(self):
        mru_key = max(self.access_time, key=self.access_time.get)
        del self.cache[mru_key]
        del self.access_time[mru_key]

class FACR(CacheReplacement):
    """Frequency and Recency aware Cache (Hybrid approach)"""
    def __init__(self, cache_size=100):
        super().__init__(cache_size)
        self.policy_name = "FACR"
        self.frequency = {}
        self.access_time = {}

    def get(self, key):
        if key in self.cache:
            self.frequency[key] = self.frequency.get(key, 0) + 1
            self.access_time[key] = time.time()
            return self.cache[key]
        return None

    def put(self, key, value):
        if len(self.cache) >= self.cache_size:
            self.evict()
        self.cache[key] = value
        self.frequency[key] = self.frequency.get(key, 0) + 1
        self.access_time[key] = time.time()

    def evict(self):
        # Combine frequency and recency scores
        scores = {}
        for key in self.cache:
            freq_score = self.frequency.get(key, 0)
            time_score = time.time() - self.access_time.get(key, time.time())
            # Lower score = evict first (higher frequency and more recent = higher score)
            scores[key] = freq_score / (1 + time_score)

        evict_key = min(scores, key=scores.get)
        del self.cache[evict_key]
        del self.frequency[evict_key]
        del self.access_time[evict_key]

class Router:
    """Router node in the network with caching"""
    def __init__(self, name, cache_policy='LRU', cache_size=100):
        self.name = name
        self.cache_policy = cache_policy

        # Initialize cache based on policy
        if cache_policy == 'LRU':
            self.cache = LRU(cache_size)
        elif cache_policy == 'LFU':
            self.cache = LFU(cache_size)
        elif cache_policy == 'FIFO':
            self.cache = FIFO(cache_size)
        elif cache_policy == 'MRU':
            self.cache = MRU(cache_size)
        elif cache_policy == 'FACR':
            self.cache = FACR(cache_size)
        else:
            self.cache = LRU(cache_size)

        self.cache_hits = 0
        self.cache_misses = 0
        self.latency_times = []
        self.total_requests = 0

    def receive_interest(self, interest):
        """Process interest packet"""
        self.total_requests += 1
        start_time = time.time()

        # Try to find content in cache
        cached_data = self.cache.get(interest.name)

        if cached_data is not None:
            self.cache_hits += 1
            latency = time.time() - start_time
            self.latency_times.append(latency)
            return cached_data, True  # Found in cache
        else:
            self.cache_misses += 1
            latency = time.time() - start_time
            self.latency_times.append(latency)
            return None, False  # Not in cache

    def cache_content(self, name, data):
        """Cache content in router"""
        self.cache.put(name, data)

    def get_cache_hit_ratio(self):
        """Calculate cache hit ratio"""
        if self.total_requests == 0:
            return 0
        return (self.cache_hits / self.total_requests) * 100

    def get_avg_latency(self):
        """Calculate average latency"""
        if len(self.latency_times) == 0:
            return 0
        return np.mean(self.latency_times)

class Producer:
    """Content producer"""
    def __init__(self, name, num_contents=1000):
        self.name = name
        self.contents = {}
        for i in range(num_contents):
            self.contents[f'content_{i}'] = DataPacket(f'content_{i}', i, 1024)

    def get_content(self, content_name):
        """Retrieve content from producer"""
        return self.contents.get(content_name)

class Consumer:
    """Content consumer"""
    def __init__(self, name):
        self.name = name
        self.requests = 0
        self.discovered_paths = 0

    def request_content(self, content_name):
        """Make content request"""
        self.requests += 1
        return InterestPacket(content_name, hash(content_name) % 1000)

class Network:
    """Simulates network with producer, consumer, and multiple paths"""
    def __init__(self, num_routers=5, cache_policy='LRU', cache_size=100):
        self.routers = [Router(f'Router_{i}', cache_policy, cache_size) for i in range(num_routers)]
        self.producer = Producer('Producer', 1000)
        self.consumer = Consumer('Consumer')
        self.num_paths = len(self.routers)

    def request_content_via_paths(self, content_name):
        """Request content through multiple router paths"""
        discovered_paths = 0
        content_found = False
        path_results = []

        for router in self.routers:
            interest = self.consumer.request_content(content_name)
            found_in_router, is_cache_hit = router.receive_interest(interest)

            if found_in_router:
                content_found = True
                path_results.append({'router': router.name, 'cache_hit': True})
            else:
                # Check producer
                content = self.producer.get_content(content_name)
                if content:
                    router.cache_content(content_name, content)
                    path_results.append({'router': router.name, 'cache_hit': False})
                    content_found = True
                    discovered_paths += 1

        self.consumer.discovered_paths = discovered_paths
        return content_found, path_results

    def simulate(self, num_requests=1000, content_distribution='zipf'):
        """Simulate network requests"""
        results = {
            'iteration': [],
            'cache_hit_ratio': [],
            'latency': [],
            'discovered_paths': [],
            'total_requests': []
        }

        for iteration in range(num_requests):
            # Generate request based on distribution
            if content_distribution == 'zipf':
                # Zipf distribution for realistic content popularity
                content_id = np.random.zipf(1.5) % 1000
            else:
                # Uniform distribution
                content_id = random.randint(0, 999)

            content_name = f'content_{content_id}'

            # Request through network
            found, paths = self.request_content_via_paths(content_name)

            # Collect metrics
            avg_cache_hit = np.mean([r.get_cache_hit_ratio() for r in self.routers])
            avg_latency = np.mean([r.get_avg_latency() for r in self.routers])
            total_requests = sum(r.total_requests for r in self.routers)

            results['iteration'].append(iteration + 1)
            results['cache_hit_ratio'].append(avg_cache_hit)
            results['latency'].append(avg_latency)
            results['discovered_paths'].append(self.consumer.discovered_paths)
            results['total_requests'].append(total_requests)

        return pd.DataFrame(results)

def run_algorithm1_simulation(num_routers=5, cache_size=100, num_requests=1000):
    """Run Algorithm1 simulation for all cache policies"""
    policies = ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR']
    all_results = {}

    for policy in policies:
        print(f"Simulating {policy} policy...")
        network = Network(num_routers, policy, cache_size)
        results = network.simulate(num_requests, 'zipf')
        all_results[policy] = results

    return all_results

def save_results_to_csv(all_results):
    """Save simulation results to CSV"""
    os.makedirs('Algorithm1_Results', exist_ok=True)

    for policy, df in all_results.items():
        df.to_csv(f'Algorithm1_Results/{policy}_results.csv', index=False)
        print(f"Saved {policy} results to CSV")

    # Create combined results
    combined = pd.DataFrame()
    for policy, df in all_results.items():
        df['policy'] = policy
        combined = pd.concat([combined, df], ignore_index=True)

    combined.to_csv('Algorithm1_Results/combined_results.csv', index=False)
    print("Saved combined results to CSV")

if __name__ == "__main__":
    print("Running Algorithm1: One Producer, One Consumer, Multiple Paths")
    print("=" * 60)

    # Run simulation
    all_results = run_algorithm1_simulation(num_routers=5, cache_size=100, num_requests=1000)

    # Save results
    save_results_to_csv(all_results)

    print("\nSimulation completed successfully!")
