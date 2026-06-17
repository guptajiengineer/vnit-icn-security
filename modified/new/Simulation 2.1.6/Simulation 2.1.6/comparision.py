import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import make_interp_spline

# Load results from both simulations
direct_df = pd.read_csv("Simulation_Results/policy_comparison(direct).csv")
chunked_df = pd.read_csv("Simulation_Results/policy_comparison(chunked).csv")

# Get all unique policies
policies = direct_df["Policy"].unique()

# Define metrics to compare
metrics = ["Cache Hit Ratio", "Latency", "Hop Reduction"]
colors = {"Direct": "blue", "Chunked": "red"}

# Plot for each policy
for policy in policies:
    direct_policy = direct_df[direct_df["Policy"] == policy]
    chunked_policy = chunked_df[chunked_df["Policy"] == policy]

    fig, axs = plt.subplots(1, 3, figsize=(18, 5))
    for i, metric in enumerate(metrics):
        ax = axs[i]
        if metric == "Latency":
            # Smooth Latency using spline interpolation for differentiable curve
            x = direct_policy["Iteration"].values
            y_direct = direct_policy[metric].values
            y_chunked = chunked_policy[metric].values

            # Create smoother x values
            x_smooth = np.linspace(x.min(), x.max(), 300)

            # Fit splines
            spline_direct = make_interp_spline(x, y_direct, k=3)
            spline_chunked = make_interp_spline(x, y_chunked, k=3)

            ax.plot(x_smooth, spline_direct(x_smooth),
                    label="Direct Transmission", color=colors["Direct"], linewidth=1.8)
            ax.plot(x_smooth, spline_chunked(x_smooth),
                    label="Chunked Transmission", color=colors["Chunked"], linewidth=1.8)
            ax.set_yscale("log")  # Use log scale for Latency
        else:
            ax.plot(direct_policy["Iteration"], direct_policy[metric],
                    label="Direct Transmission", color=colors["Direct"], linewidth=1.8)
            ax.plot(chunked_policy["Iteration"], chunked_policy[metric],
                    label="Chunked Transmission", color=colors["Chunked"], linewidth=1.8)

        ax.set_xlabel("Iteration", fontsize=10)
        ax.set_ylabel(metric, fontsize=10)
        ax.set_title(f"{policy}: {metric}", fontsize=12, fontweight="bold")
        ax.grid(True, linestyle="--", linewidth=0.5)
        ax.legend(fontsize="small")

    plt.suptitle(f"{policy} Policy: Direct vs Chunked Transmission", fontsize=14, fontweight="bold")
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.show()