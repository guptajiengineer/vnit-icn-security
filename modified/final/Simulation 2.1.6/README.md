# Simulation 2.1.6 Workflow

This project compares three transmission approaches across the same caching policies:

- `main.py`: direct transmission simulation
- `main2.py`: chunked transmission simulation
- `main3.py`: multipath transmission simulation

Each script saves its results to CSV, and `comparison_three_way.py` reads those CSV files to generate graphs that compare all three approaches.

## Main Workflow

Run the scripts in this order:

1. `python main.py`
2. `python main2.py`
3. `python main3.py`
4. `python comparison_three_way.py`

## What Each Script Does

### 1. `main.py`

Runs the direct transmission simulation for these policies:

- `LRU`
- `LFU`
- `FIFO`
- `MRU`
- `FACR`
- `RandomForest`

It prompts for the number of content requests, runs the simulation, and saves:

- `Simulation_Results/policy_comparison(direct).csv`
- `Policy_Stats/<POLICY>_stats.csv`
- `Simulation_Log/simulation_log.csv`

The main comparison CSV written by this file contains:

- `Policy`
- `Iteration`
- `Cache Hit Ratio`
- `Latency`
- `Hop Reduction`

### 2. `main2.py`

Runs the chunked transmission version of the same simulation and saves:

- `Simulation_Results/policy_comparison(chunked).csv`
- `Policy_Stats/<POLICY>_stats.csv`
- `Simulation_Log/simulation_log.csv`

Like `main.py`, it also prompts for the number of content requests.

### 3. `main3.py`

Runs the multipath simulation and saves:

- `Algorithm1_Results/combined_results.csv`
- `Simulation_Results/combined_results.csv`
- `Algorithm1_Results/LRU_results.csv`
- `Algorithm1_Results/LFU_results.csv`
- `Algorithm1_Results/FIFO_results.csv`
- `Algorithm1_Results/MRU_results.csv`
- `Algorithm1_Results/FACR_results.csv`
- `Algorithm1_Results/RandomForest_results.csv`
- `Algorithm1_Results/comparison_report.txt`

The multipath combined CSV contains:

- `Policy`
- `Iteration`
- `Total Requests`
- `Cache Hit Ratio`
- `Latency`
- `Hop Reduction`

`main3.py` currently runs with fixed values inside the script:

- `num_routers=8`
- `cache_size=15`
- `num_requests=100`

## Three-Way Comparison Graphs

After all three simulations finish, run:

```bash
python comparison_three_way.py
```

This script reads:

- `Simulation_Results/policy_comparison(direct).csv`
- `Simulation_Results/policy_comparison(chunked).csv`
- `Simulation_Results/combined_results.csv`

It then creates one graph image per caching policy:

- `Simulation_Results/LRU_three_way_comparison.png`
- `Simulation_Results/LFU_three_way_comparison.png`
- `Simulation_Results/FIFO_three_way_comparison.png`
- `Simulation_Results/MRU_three_way_comparison.png`
- `Simulation_Results/FACR_three_way_comparison.png`
- `Simulation_Results/RandomForest_three_way_comparison.png`

Each image compares the three transmission approaches using:

- `Cache Hit Ratio`
- `Latency`
- `Hop Reduction`

## Optional Multipath-Only Visualizations

If you want extra graphs only for the `main3.py` results, run:

```bash
python algorithm1_visualize.py
```

This generates additional files in `Algorithm1_Results/`, including:

- `cache_hit_ratio.png`
- `latency.png`
- `total_requests.png`
- `comparison_2x2.png`
- `bar_comparison.png`
- `summary_statistics.csv`

## Requirements

Install the Python libraries used by the scripts before running them:

```bash
pip install pandas matplotlib networkx numpy scipy seaborn scikit-learn
```

## Notes

- The Random Forest policy uses `models/random_forest_model.pkl` when available.
- Run the files in the workflow order so the comparison script can find all required CSV outputs.
- `comparison_three_way.py` depends on the CSV files produced by the first three scripts and will fail if any of them are missing.
