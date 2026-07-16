# Performance Evaluation

This suite evaluates the **networking behaviour of the ICN routing simulator**.
It answers questions about *how the network performs* — not about security.

> These experiments evaluate the **network**. For the security architecture
> (cryptography, blockchain, authentication), see
> [`../security_evaluation/`](../security_evaluation/).

---

## Purpose

Drive the ICN simulator (`app/run_experiments.py`) across a matrix of
configurations and measure how routing and delivery behave as load grows.
Concretely, this suite characterises:

- **latency** — average simulated delay vs. publisher/user counts
- **routing efficiency** — path length (hops) for LMM-1 vs. LMM-2
- **multipath performance** — effect of chunk multipath distribution
- **throughput** — effective request throughput
- **reliability / scalability** — success and failure rates as the topology scales
- **auth wall-clock overhead** — real time cost of enabling Fabric authentication

The simulator itself is **not modified**; this suite only runs it and analyses
its outputs.

---

## Directory layout

```
performance_evaluation/
├── README.md
├── scripts/
│   ├── run_benchmarks.py    ← Step 1: run experiments, record timing
│   ├── analyze_results.py   ← Step 2: merge + derive processed datasets
│   ├── generate_graphs.py   ← Step 3: produce publication-quality figures
│   └── utils.py             ← shared paths, plot style, helpers
├── data/
│   ├── raw/                 ← produced by run_benchmarks.py
│   └── processed/           ← produced by analyze_results.py
├── graphs/
│   ├── png/                 ← 300 dpi PNG
│   ├── pdf/                 ← vector PDF
│   └── svg/                 ← vector SVG
└── reports/                 ← reserved for generated reports
```

---

## How to run

From the **repository root**, run the three-step pipeline in order:

```bash
# 1. Ensure Fabric is up (only needed for the with_auth modes)
docker compose up -d

# 2. Run the pipeline
python benchmark/performance_evaluation/scripts/run_benchmarks.py --iterations 5
python benchmark/performance_evaluation/scripts/analyze_results.py
python benchmark/performance_evaluation/scripts/generate_graphs.py
```

To run without Fabric (skips the `with_auth` modes):

```bash
python benchmark/performance_evaluation/scripts/run_benchmarks.py --skip-auth
```

`run_benchmarks.py` CLI options: `--iterations`, `--publisher-start/-end`,
`--user-start/-end`, `--skip-auth`.

---

## Expected outputs

**Raw data** (`data/raw/`) — one subdirectory per mode combination
(`{with,without}_chunking__{with,without}_auth`), plus `benchmark_config.json`
and `benchmark_timing.csv`.

**Processed data** (`data/processed/`) — merged and derived datasets:
`all_raw.csv`, `summary_by_publishers.csv`, `summary_by_users.csv`,
`lmm_comparison_publishers.csv`, `lmm_comparison_users.csv`,
`chunking_impact.csv`, `failure_rates.csv`, `effective_throughput.csv`.

**Graphs** (`graphs/png|pdf|svg/`) — 10 figures × 3 formats:

| Figure | Shows |
|---|---|
| fig01 | LMM-1 vs LMM-2: avg delay vs publishers |
| fig02 | LMM-1 vs LMM-2: avg delay vs users |
| fig03 | LMM-1 vs LMM-2: avg hops vs publishers |
| fig04 | LMM-1 vs LMM-2: success rate vs publishers |
| fig05 | LMM-1 vs LMM-2: success rate vs users |
| fig06 | chunking impact: delay + success rate |
| fig07 | auth wall-clock overhead per mode |
| fig08 | failure rate vs publishers (all modes) |
| fig09 | effective throughput vs publishers |
| fig10 | metric convergence across iterations |

- Generated graphs are stored in `graphs/{png,pdf,svg}/`.
- Raw and processed data are stored in `data/{raw,processed}/`.

---

## Relation to the ICN routing simulator

This suite is a thin **driver + analysis layer** around
`app/run_experiments.py`. It launches the simulator as a subprocess for each
configuration, times the runs with `time.perf_counter()`, and derives figures
from the CSVs the simulator emits. All routing, chunking, and authentication
logic lives in `app/`; this suite measures that logic without changing it.

> **Note on metrics.** Delay is *simulated* (hop-count based, in simulation time
> units), not wall-clock latency. `effective_throughput` is a derived metric.
> CPU/memory utilisation, per-operation timing breakdowns, per-transaction
> blockchain latency, and cache hit/miss rates are **not** available here because
> the simulator does not instrument them — those per-operation security costs are
> measured separately in the [security evaluation](../security_evaluation/).
