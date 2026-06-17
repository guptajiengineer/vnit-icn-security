import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import make_interp_spline
import os

# Create Simulation_Results folder if it doesn't exist
if not os.path.exists("Simulation_Results"):
    os.makedirs("Simulation_Results")

# Load results from both simulations
direct_df = pd.read_csv("Simulation_Results/policy_comparison(direct).csv")
chunked_df = pd.read_csv("Simulation_Results/policy_comparison(chunked).csv")

# Add source column to identify which method each row came from
direct_df["Source"] = "Direct"
chunked_df["Source"] = "Chunked"

# Create combined results
combined_df = pd.concat([direct_df, chunked_df], ignore_index=True)

# Save combined results
combined_df.to_csv("Simulation_Results/combined_results.csv", index=False)
print("✓ combined_results.csv created successfully!")
print(f"  Total rows: {len(combined_df)}")
print(f"  Columns: {combined_df.columns.tolist()}")

# Get all unique policies
policies = direct_df["Policy"].unique()

# Define metrics to compare
metrics = ["Cache Hit Ratio", "Latency", "Hop Reduction"]
colors = {"Direct": "#1f77b4", "Chunked": "#ff7f0e"}

# Create comparison plots for each policy
for policy in policies:
    direct_policy = direct_df[direct_df["Policy"] == policy]
    chunked_policy = chunked_df[chunked_df["Policy"] == policy]

    fig, axs = plt.subplots(1, 3, figsize=(18, 5))

    for i, metric in enumerate(metrics):
        ax = axs[i]

        if metric == "Latency":
            # Smooth Latency using spline interpolation
            x = direct_policy["Iteration"].values
            y_direct = direct_policy[metric].values
            y_chunked = chunked_policy[metric].values

            x_smooth = np.linspace(x.min(), x.max(), 300)
            spline_direct = make_interp_spline(x, y_direct, k=3)
            spline_chunked = make_interp_spline(x, y_chunked, k=3)

            ax.plot(x_smooth, spline_direct(x_smooth), label="Direct Transmission", 
                   color=colors["Direct"], linewidth=2)
            ax.plot(x_smooth, spline_chunked(x_smooth), label="Chunked Transmission", 
                   color=colors["Chunked"], linewidth=2)
            ax.set_yscale("log")
        else:
            ax.plot(direct_policy["Iteration"], direct_policy[metric], 
                   label="Direct Transmission", color=colors["Direct"], linewidth=2)
            ax.plot(chunked_policy["Iteration"], chunked_policy[metric], 
                   label="Chunked Transmission", color=colors["Chunked"], linewidth=2)

        ax.set_xlabel("Iteration", fontsize=10)
        ax.set_ylabel(metric, fontsize=10)
        ax.set_title(f"{policy}: {metric}", fontsize=12, fontweight="bold")
        ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.7)
        ax.legend(fontsize="small", loc="best")

    plt.suptitle(f"{policy} Policy: Direct vs Chunked Transmission", 
                fontsize=14, fontweight="bold")
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(f"Simulation_Results/{policy}_comparison.png", dpi=300, bbox_inches="tight")
    plt.show()
    print(f"✓ Saved visualization for {policy} policy")

# Create summary statistics comparison
print("\n" + "="*80)
print("SUMMARY STATISTICS COMPARISON")
print("="*80)

for policy in policies:
    direct_policy = direct_df[direct_df["Policy"] == policy]
    chunked_policy = chunked_df[chunked_df["Policy"] == policy]

    print(f"\n>>> {policy} Policy <<<")
    print("\nDirect Transmission:")
    print(direct_policy[metrics].describe().round(4))
    print("\nChunked Transmission:")
    print(chunked_policy[metrics].describe().round(4))

    print("\nDifference (Chunked - Direct):")
    for metric in metrics:
        diff_mean = chunked_policy[metric].mean() - direct_policy[metric].mean()
        diff_pct = (diff_mean / direct_policy[metric].mean()) * 100
        print(f"  {metric}: {diff_mean:.4f} ({diff_pct:+.2f}%)")
