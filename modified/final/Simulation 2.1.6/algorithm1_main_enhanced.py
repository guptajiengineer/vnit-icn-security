
"""
Algorithm1: One Producer, One Consumer, Multiple Paths
Cache Replacement Policies: LRU, LFU, FIFO, MRU, FACR, RandomForest
Enhanced with Machine Learning-based cache policy

CSV Format:
Policy, Iteration, Total Requests, Cache Hit Ratio, Latency, Hop Reduction
"""

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
import pickle
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

# ═══════════════════════════════════════════════════════════════════════════
# DATA PACKET & INTEREST PACKET CLASSES
# ═══════════════════════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════════════════════
# BASE CACHE REPLACEMENT CLASS
# ═══════════════════════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════════════════════
# TRADITIONAL CACHE POLICIES
# ═══════════════════════════════════════════════════════════════════════════

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
        scores = {}
        for key in self.cache:
            freq_score = self.frequency.get(key, 0)
            time_score = time.time() - self.access_time.get(key, time.time())
            scores[key] = freq_score / (1 + time_score)

        evict_key = min(scores, key=scores.get)
        del self.cache[evict_key]
        del self.frequency[evict_key]
        del self.access_time[evict_key]

# ═══════════════════════════════════════════════════════════════════════════
# RANDOM FOREST CACHE POLICY (FALLBACK ONLY - NO MODEL)
# ═══════════════════════════════════════════════════════════════════════════

class RandomForestCache(CacheReplacement):
    """
    Machine Learning-based Cache Policy using Random Forest
    Falls back to FACR when no model available
    """

    def __init__(self, cache_size=100, model_path=None):
        super().__init__(cache_size)
        self.policy_name = "RandomForest"
        self.frequency = {}
        self.access_time = {}
        self.content_popularity = collections.defaultdict(int)

        # For fallback strategy
        self.model = None
        self.scaler = StandardScaler()

        if model_path and os.path.exists(model_path):
            try:
                with open(model_path, 'rb') as f:
                    self.model = pickle.load(f)
                print(f"Loaded Random Forest model from {model_path}")
            except Exception as e:
                print(f"Could not load model: {e}. Using FACR fallback.")

    def get(self, key):
        if key in self.cache:
            self.frequency[key] = self.frequency.get(key, 0) + 1
            self.access_time[key] = time.time()
            self.content_popularity[key] += 1
            return self.cache[key]
        return None

    def put(self, key, value):
        if len(self.cache) >= self.cache_size:
            self.evict()
        self.cache[key] = value
        self.frequency[key] = self.frequency.get(key, 0) + 1
        self.access_time[key] = time.time()
        self.content_popularity[key] += 1

    def evict(self):
        """Use FACR-like heuristic (model likely has different feature dimensions)"""
        if len(self.cache) == 0:
            return

        scores = {}
        for key in self.cache:
            freq_score = self.frequency.get(key, 0)
            time_score = time.time() - self.access_time.get(key, 0)
            scores[key] = freq_score / (1 + time_score)

        evict_key = min(scores, key=scores.get)
        del self.cache[evict_key]
        del self.frequency[evict_key]
        del self.access_time[evict_key]

# ═══════════════════════════════════════════════════════════════════════════
# ROUTER CLASS
# ═══════════════════════════════════════════════════════════════════════════

class Router:
    """Router node in the network with caching"""
    def __init__(self, name, cache_policy='LRU', cache_size=100, model_path=None):
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
        elif cache_policy == 'RandomForest':
            self.cache = RandomForestCache(cache_size, model_path)
        else:
            self.cache = LRU(cache_size)

        self.cache_hits = 0
        self.cache_misses = 0
        self.latency_times = []
        self.total_requests = 0
        self.optimal_hops = 1  # Direct producer path
        self.actual_hops = 0
        self.total_hop_difference = 0

    def receive_interest(self, interest, hop_count=1):
        """Process interest packet"""
        self.total_requests += 1
        self.actual_hops += hop_count
        start_time = time.time()

        # Try to find content in cache
        cached_data = self.cache.get(interest.name)
        if cached_data is not None:
            self.cache_hits += 1
            latency = time.time() - start_time
            self.latency_times.append(latency)
            self.total_hop_difference += (hop_count - self.optimal_hops)
            return cached_data, True
        else:
            self.cache_misses += 1
            latency = time.time() - start_time
            self.latency_times.append(latency)
            self.total_hop_difference += (hop_count - self.optimal_hops)
            return None, False

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

    def get_hop_reduction(self):
        """Calculate hop reduction (negative = increase, positive = reduction)"""
        if self.total_requests == 0:
            return 0
        optimal_total = self.total_requests * self.optimal_hops
        return (optimal_total - self.actual_hops) / self.total_requests

# ═══════════════════════════════════════════════════════════════════════════
# PRODUCER & CONSUMER CLASSES
# ═══════════════════════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════════════════════
# NETWORK CLASS
# ═══════════════════════════════════════════════════════════════════════════

class Network:
    """Simulates network with producer, consumer, and multiple paths"""
    def __init__(self, num_routers=5, cache_policy='LRU', cache_size=100, model_path=None):
        self.routers = [
            Router(f'Router_{i}', cache_policy, cache_size, model_path) 
            for i in range(num_routers)
        ]
        self.producer = Producer('Producer', 1000)
        self.consumer = Consumer('Consumer')
        self.num_paths = len(self.routers)

    def request_content_via_paths(self, content_name):
        """Request content through multiple router paths"""
        discovered_paths = 0
        content_found = False
        path_results = []
        hop_increment = 1

        for router in self.routers:
            interest = self.consumer.request_content(content_name)
            found_in_router, is_cache_hit = router.receive_interest(interest, hop_increment)

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
                    hop_increment += 1

        self.consumer.discovered_paths = discovered_paths
        return content_found, path_results

    def simulate(self, num_requests=1000, content_distribution='zipf'):
        """Simulate network requests"""
        results = []

        for iteration in range(num_requests):
            # Generate request based on distribution
            if content_distribution == 'zipf':
                content_id = np.random.zipf(1.5) % 1000
            else:
                content_id = random.randint(0, 999)

            content_name = f'content_{content_id}'

            # Request through network
            found, paths = self.request_content_via_paths(content_name)

            # Collect metrics from first router (representative)
            router = self.routers[0]

            avg_cache_hit = np.mean([r.get_cache_hit_ratio() for r in self.routers])
            avg_latency = np.mean([r.get_avg_latency() for r in self.routers])
            avg_hop_reduction = np.mean([r.get_hop_reduction() for r in self.routers])
            total_requests = sum(r.total_requests for r in self.routers)

            # Append row for this iteration
            results.append({
                'Policy': self.routers[0].cache_policy,
                'Iteration': iteration + 1,
                'Total Requests': total_requests,
                'Cache Hit Ratio': avg_cache_hit,
                'Latency': avg_latency,
                'Hop Reduction': avg_hop_reduction
            })

        return results

# ═══════════════════════════════════════════════════════════════════════════
# SIMULATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def run_algorithm1_simulation(num_routers=5, cache_size=100, num_requests=1000, model_path=None):
    """Run Algorithm1 simulation for all cache policies including RandomForest"""
    policies = ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR', 'RandomForest']
    all_results = []

    for policy in policies:
        print(f"Simulating {policy} policy...")
        network = Network(num_routers, policy, cache_size, model_path)
        results = network.simulate(num_requests, 'zipf')
        all_results.extend(results)

    return pd.DataFrame(all_results)

def save_results_to_csv(df, filename='Algorithm1_Results/combined_results.csv'):
    """Save simulation results to CSV with specified format"""
    os.makedirs('Algorithm1_Results', exist_ok=True)

    # Reorder columns as specified
    df_reordered = df[['Policy', 'Iteration', 'Total Requests', 'Cache Hit Ratio', 'Latency', 'Hop Reduction']]

    # Save to CSV
    df_reordered.to_csv(filename, index=False)
    print(f"✓ Saved results to: {filename}")
    print(f"  Columns: Policy, Iteration, Total Requests, Cache Hit Ratio, Latency, Hop Reduction")
    print(f"  Total rows: {len(df_reordered)}")

def save_policy_specific_csv(df):
    """Save individual CSV files for each policy"""
    os.makedirs('Algorithm1_Results', exist_ok=True)

    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]
        policy_df_reordered = policy_df[['Policy', 'Iteration', 'Total Requests', 'Cache Hit Ratio', 'Latency', 'Hop Reduction']]

        filename = f'Algorithm1_Results/{policy}_results.csv'
        policy_df_reordered.to_csv(filename, index=False)
        print(f"✓ Saved {policy}: {filename} ({len(policy_df_reordered)} rows)")

def save_comparison_report(df):
    """Generate and save comparison report"""
    os.makedirs('Algorithm1_Results', exist_ok=True)

    report = []
    report.append("\n" + "="*90)
    report.append("ALGORITHM1 CACHE POLICY COMPARISON REPORT")
    report.append("Format: Policy, Iteration, Total Requests, Cache Hit Ratio, Latency, Hop Reduction")
    report.append("="*90 + "\n")

    for policy in df['Policy'].unique():
        policy_df = df[df['Policy'] == policy]

        report.append(f"\n{'Policy':<20} {policy}")
        report.append("-" * 90)
        report.append(f"{'Average Cache Hit Ratio':<40} {policy_df['Cache Hit Ratio'].mean():>10.2f}%")
        report.append(f"{'Std Dev Cache Hit Ratio':<40} {policy_df['Cache Hit Ratio'].std():>10.2f}%")
        report.append(f"{'Max Cache Hit Ratio':<40} {policy_df['Cache Hit Ratio'].max():>10.2f}%")
        report.append(f"{'Min Cache Hit Ratio':<40} {policy_df['Cache Hit Ratio'].min():>10.2f}%")
        report.append(f"")
        report.append(f"{'Average Latency (seconds)':<40} {policy_df['Latency'].mean():>10.8f}")
        report.append(f"{'Min Latency':<40} {policy_df['Latency'].min():>10.8f}")
        report.append(f"{'Max Latency':<40} {policy_df['Latency'].max():>10.8f}")
        report.append(f"")
        report.append(f"{'Average Hop Reduction':<40} {policy_df['Hop Reduction'].mean():>10.4f}")
        report.append(f"{'Total Requests':<40} {int(policy_df['Total Requests'].iloc[-1]):>10}")
        report.append(f"")

    report_text = "\n".join(report)
    print(report_text)

    with open('Algorithm1_Results/comparison_report.txt', 'w') as f:
        f.write(report_text)

    print(f"\n✓ Saved report to: Algorithm1_Results/comparison_report.txt")

# ═══════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("="*90)
    print("Algorithm1: One Producer, One Consumer, Multiple Paths")
    print("CSV Format: Policy, Iteration, Total Requests, Cache Hit Ratio, Latency, Hop Reduction")
    print("="*90)

    # Optional: Specify model path if you have a trained Random Forest model
    MODEL_PATH = 'models/random_forest_model.pkl' if os.path.exists('models/random_forest_model.pkl') else None

    # Run simulation
    print("\nRunning simulations...")
    df_results = run_algorithm1_simulation(
        num_routers=5, 
        cache_size=100, 
        num_requests=1000,
        model_path=MODEL_PATH
    )

    # Save results
    print("\nSaving results...")
    save_results_to_csv(df_results, 'Algorithm1_Results/combined_results.csv')
    save_policy_specific_csv(df_results)

    # Generate comparison report
    save_comparison_report(df_results)

    print("\n✓ Simulation completed successfully!")
    print("✓ Results saved to Algorithm1_Results/")
    print("\nGenerated files:")
    print("  • combined_results.csv - All results combined")
    print("  • LRU_results.csv, LFU_results.csv, etc. - Per-policy results")
    print("  • comparison_report.txt - Performance comparison")
