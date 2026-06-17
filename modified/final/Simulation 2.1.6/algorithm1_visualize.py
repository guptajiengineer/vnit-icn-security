
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
import seaborn as sns

"""
Visualization Script for Algorithm1 Results
Generates performance comparison graphs using CSV data
"""

def load_results(results_dir='Algorithm1_Results'):
    """Load all CSV results"""
    results = {}
    policies = ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR']

    for policy in policies:
        filepath = os.path.join(results_dir, f'{policy}_results.csv')
        if os.path.exists(filepath):
            results[policy] = pd.read_csv(filepath)
        else:
            print(f"Warning: {filepath} not found")

    return results

def plot_cache_hit_ratio(results):
    """Plot cache hit ratio over iterations"""
    fig, ax = plt.subplots(figsize=(12, 6))

    for policy, df in results.items():
        ax.plot(df['iteration'], df['cache_hit_ratio'], 
               label=policy, marker='o', markersize=3, 
               markevery=max(1, len(df)//20), linewidth=1.5)

    ax.set_xlabel('Iteration', fontsize=12)
    ax.set_ylabel('Cache Hit Ratio (%)', fontsize=12)
    ax.set_title('Cache Hit Ratio over Iterations', fontsize=14, fontweight='bold')
    ax.legend(loc='best', frameon=True)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('Algorithm1_Results/cache_hit_ratio.png', dpi=300)
    print("Saved: cache_hit_ratio.png")
    plt.close()

def plot_latency(results):
    """Plot latency over iterations"""
    fig, ax = plt.subplots(figsize=(12, 6))

    for policy, df in results.items():
        ax.plot(df['iteration'], df['latency']*1000,  # Convert to ms
               label=policy, marker='s', markersize=3,
               markevery=max(1, len(df)//20), linewidth=1.5)

    ax.set_xlabel('Iteration', fontsize=12)
    ax.set_ylabel('Latency (ms)', fontsize=12)
    ax.set_title('Latency over Iterations', fontsize=14, fontweight='bold')
    ax.legend(loc='best', frameon=True)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('Algorithm1_Results/latency.png', dpi=300)
    print("Saved: latency.png")
    plt.close()

def plot_discovered_paths(results):
    """Plot discovered paths over iterations"""
    fig, ax = plt.subplots(figsize=(12, 6))

    for policy, df in results.items():
        ax.plot(df['iteration'], df['discovered_paths'],
               label=policy, marker='^', markersize=3,
               markevery=max(1, len(df)//20), linewidth=1.5)

    ax.set_xlabel('Iteration', fontsize=12)
    ax.set_ylabel('Number of Paths', fontsize=12)
    ax.set_title('Discovered Paths over Iterations', fontsize=14, fontweight='bold')
    ax.legend(loc='best', frameon=True)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('Algorithm1_Results/discovered_paths.png', dpi=300)
    print("Saved: discovered_paths.png")
    plt.close()

def plot_total_requests(results):
    """Plot total requests over iterations"""
    fig, ax = plt.subplots(figsize=(12, 6))

    for policy, df in results.items():
        ax.plot(df['iteration'], df['total_requests'],
               label=policy, marker='d', markersize=3,
               markevery=max(1, len(df)//20), linewidth=1.5)

    ax.set_xlabel('Iteration', fontsize=12)
    ax.set_ylabel('Total Requests', fontsize=12)
    ax.set_title('Total Requests over Iterations', fontsize=14, fontweight='bold')
    ax.legend(loc='best', frameon=True)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('Algorithm1_Results/total_requests.png', dpi=300)
    print("Saved: total_requests.png")
    plt.close()

def plot_2x2_comparison(results):
    """Plot 2x2 comparison grid"""
    fig, axs = plt.subplots(2, 2, figsize=(14, 10))

    # Cache Hit Ratio
    for policy, df in results.items():
        axs[0, 0].plot(df['iteration'], df['cache_hit_ratio'],
                      label=policy, linewidth=1.5, marker='o', markersize=2,
                      markevery=max(1, len(df)//20))
    axs[0, 0].set_title('Cache Hit Ratio', fontweight='bold')
    axs[0, 0].set_ylabel('Hit Ratio (%)')
    axs[0, 0].grid(True, alpha=0.3)
    axs[0, 0].legend()

    # Latency
    for policy, df in results.items():
        axs[0, 1].plot(df['iteration'], df['latency']*1000,
                      label=policy, linewidth=1.5, marker='s', markersize=2,
                      markevery=max(1, len(df)//20))
    axs[0, 1].set_title('Latency (ms)', fontweight='bold')
    axs[0, 1].set_ylabel('Latency (ms)')
    axs[0, 1].grid(True, alpha=0.3)
    axs[0, 1].legend()

    # Discovered Paths
    for policy, df in results.items():
        axs[1, 0].plot(df['iteration'], df['discovered_paths'],
                      label=policy, linewidth=1.5, marker='^', markersize=2,
                      markevery=max(1, len(df)//20))
    axs[1, 0].set_title('Discovered Paths', fontweight='bold')
    axs[1, 0].set_ylabel('Paths')
    axs[1, 0].set_xlabel('Iteration')
    axs[1, 0].grid(True, alpha=0.3)
    axs[1, 0].legend()

    # Total Requests
    for policy, df in results.items():
        axs[1, 1].plot(df['iteration'], df['total_requests'],
                      label=policy, linewidth=1.5, marker='d', markersize=2,
                      markevery=max(1, len(df)//20))
    axs[1, 1].set_title('Total Requests', fontweight='bold')
    axs[1, 1].set_ylabel('Requests')
    axs[1, 1].set_xlabel('Iteration')
    axs[1, 1].grid(True, alpha=0.3)
    axs[1, 1].legend()

    plt.suptitle('Algorithm1: Cache Performance Comparison', 
                fontsize=16, fontweight='bold', y=1.00)
    plt.tight_layout()
    plt.savefig('Algorithm1_Results/comparison_2x2.png', dpi=300)
    print("Saved: comparison_2x2.png")
    plt.close()

def plot_bar_comparison(results):
    """Plot bar chart comparing average metrics"""
    fig, axs = plt.subplots(1, 2, figsize=(14, 5))

    policies = list(results.keys())
    avg_cache_hits = [results[p]['cache_hit_ratio'].mean() for p in policies]
    avg_latencies = [results[p]['latency'].mean() * 1000 for p in policies]

    # Cache hit ratio comparison
    colors = plt.cm.Set3(np.linspace(0, 1, len(policies)))
    axs[0].bar(policies, avg_cache_hits, color=colors, edgecolor='black', linewidth=1.5)
    axs[0].set_ylabel('Average Cache Hit Ratio (%)', fontsize=12)
    axs[0].set_title('Average Cache Hit Ratio by Policy', fontweight='bold')
    axs[0].grid(axis='y', alpha=0.3)

    # Latency comparison
    axs[1].bar(policies, avg_latencies, color=colors, edgecolor='black', linewidth=1.5)
    axs[1].set_ylabel('Average Latency (ms)', fontsize=12)
    axs[1].set_title('Average Latency by Policy', fontweight='bold')
    axs[1].grid(axis='y', alpha=0.3)

    plt.suptitle('Algorithm1: Policy Comparison Summary', 
                fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('Algorithm1_Results/bar_comparison.png', dpi=300)
    print("Saved: bar_comparison.png")
    plt.close()

def create_summary_statistics(results):
    """Create and save summary statistics"""
    summary = {}

    for policy, df in results.items():
        summary[policy] = {
            'avg_cache_hit_ratio': df['cache_hit_ratio'].mean(),
            'std_cache_hit_ratio': df['cache_hit_ratio'].std(),
            'max_cache_hit_ratio': df['cache_hit_ratio'].max(),
            'min_cache_hit_ratio': df['cache_hit_ratio'].min(),
            'avg_latency': df['latency'].mean(),
            'std_latency': df['latency'].std(),
            'avg_paths': df['discovered_paths'].mean(),
            'total_requests': df['total_requests'].iloc[-1]
        }

    summary_df = pd.DataFrame(summary).T
    summary_df.to_csv('Algorithm1_Results/summary_statistics.csv')

    print("\nSummary Statistics:")
    print(summary_df.to_string())

    return summary_df

def main():
    """Main visualization function"""
    print("Algorithm1 Visualization Script")
    print("=" * 60)

    # Load results
    results = load_results()

    if not results:
        print("No results found. Please run algorithm1_main.py first.")
        return

    print(f"Loaded results for {len(results)} policies")

    # Create visualizations
    print("\nGenerating visualizations...")
    plot_cache_hit_ratio(results)
    plot_latency(results)
    plot_discovered_paths(results)
    plot_total_requests(results)
    plot_2x2_comparison(results)
    plot_bar_comparison(results)

    # Create summary statistics
    summary_stats = create_summary_statistics(results)

    print("\n" + "=" * 60)
    print("Visualization complete!")
    print(f"All results saved to 'Algorithm1_Results' directory")

if __name__ == "__main__":
    main()
