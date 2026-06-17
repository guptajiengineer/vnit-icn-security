import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import make_interp_spline

# Load results from all three simulations
direct_df = pd.read_csv("Simulation_Results/policy_comparison(direct).csv")
chunked_df = pd.read_csv("Simulation_Results/policy_comparison(chunked).csv")
multipath_df = pd.read_csv("Simulation_Results/combined_results.csv")

# Get all unique policies
policies = direct_df["Policy"].unique()

# Define metrics to compare
metrics = ["Cache Hit Ratio", "Latency", "Hop Reduction"]

# Define colors for three transmission types
colors = {
    "Direct": "#1f77b4",      # Blue
    "Chunked": "#ff7f0e",     # Orange
    "Multipath": "#2ca02c"    # Green
}

# Plot for each policy
for policy in policies:
    direct_policy = direct_df[direct_df["Policy"] == policy].sort_values("Iteration").reset_index(drop=True)
    chunked_policy = chunked_df[chunked_df["Policy"] == policy].sort_values("Iteration").reset_index(drop=True)
    multipath_policy = multipath_df[multipath_df["Policy"] == policy].sort_values("Iteration").reset_index(drop=True)

    fig, axs = plt.subplots(1, 3, figsize=(20, 5))

    for i, metric in enumerate(metrics):
        ax = axs[i]

        if metric == "Latency":
            # Smooth Latency using spline interpolation for differentiable curve
            x_direct = direct_policy["Iteration"].values
            y_direct = direct_policy[metric].values

            x_chunked = chunked_policy["Iteration"].values
            y_chunked = chunked_policy[metric].values

            x_multipath = multipath_policy["Iteration"].values
            y_multipath = multipath_policy[metric].values

            # Create smoother x values
            x_smooth = np.linspace(
                min(x_direct.min(), x_chunked.min(), x_multipath.min()),
                max(x_direct.max(), x_chunked.max(), x_multipath.max()),
                300
            )

            # Fit splines for all three (ensure strictly increasing sequences)
            try:
                spline_direct = make_interp_spline(x_direct, y_direct, k=min(3, len(x_direct)-1))
                ax.plot(x_smooth, spline_direct(x_smooth),
                       label="Direct Transmission", color=colors["Direct"], linewidth=2.0)
            except:
                ax.plot(x_direct, y_direct,
                       label="Direct Transmission", color=colors["Direct"], linewidth=2.0)

            try:
                spline_chunked = make_interp_spline(x_chunked, y_chunked, k=min(3, len(x_chunked)-1))
                ax.plot(x_smooth, spline_chunked(x_smooth),
                       label="Chunked Transmission", color=colors["Chunked"], linewidth=2.0)
            except:
                ax.plot(x_chunked, y_chunked,
                       label="Chunked Transmission", color=colors["Chunked"], linewidth=2.0)

            try:
                spline_multipath = make_interp_spline(x_multipath, y_multipath, k=min(3, len(x_multipath)-1))
                ax.plot(x_smooth, spline_multipath(x_smooth),
                       label="Multipath Transmission", color=colors["Multipath"], linewidth=2.0)
            except:
                ax.plot(x_multipath, y_multipath,
                       label="Multipath Transmission", color=colors["Multipath"], linewidth=2.0)

            ax.set_yscale("log")  # Use log scale for Latency
        else:
            # For Cache Hit Ratio and Hop Reduction
            ax.plot(direct_policy["Iteration"], direct_policy[metric],
                   label="Direct Transmission", color=colors["Direct"], linewidth=2.0,  alpha=0.7)
            ax.plot(chunked_policy["Iteration"], chunked_policy[metric],
                   label="Chunked Transmission", color=colors["Chunked"], linewidth=2.0,  alpha=0.7)
            ax.plot(multipath_policy["Iteration"], multipath_policy[metric],
                   label="Multipath Transmission", color=colors["Multipath"], linewidth=2.0,  alpha=0.7)

        ax.set_xlabel("Iteration", fontsize=11, fontweight="bold")
        ax.set_ylabel(metric, fontsize=11, fontweight="bold")
        ax.set_title(f"{policy}: {metric}", fontsize=12, fontweight="bold")
        ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.7)
        ax.legend(fontsize="small", loc="best")

    plt.suptitle(f"{policy} Policy: Three Transmission Methods Comparison", 
                fontsize=14, fontweight="bold")
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(f"Simulation_Results/{policy}_three_way_comparison.png", dpi=300, bbox_inches="tight")
    plt.show()
    print(f"✓ Saved three-way comparison for {policy} policy")

print("\n" + "="*100)
print("SUMMARY STATISTICS: THREE-WAY COMPARISON")
print("="*100)


