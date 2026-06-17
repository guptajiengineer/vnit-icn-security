# Experiment Execution Flow

This README explains what happens when the experiment orchestration in `run_experiments.py` is invoked, and how the main classes move through the system.

## Important entrypoint note

- `python experiments.py` only loads the module and exits.
- The practical entrypoint is `run_experiments.py`.
- `run_experiments.py` imports `run_full_experiment()` from `simulator.py`, which re-exports it from `experiments.py`.

So the real runtime path is:

```text
run_experiments.py
  -> simulator.py
    -> experiments.py
      -> network.py / content.py / network_scenario.py / metrics.py / resources.py / learning.py / state.py / paths.py
```

## High-level call flow

When experiments are launched from `run_experiments.py`, the flow is:

```text
main()
  -> build_default_content_specs()
  -> run_full_experiment()
      -> build_base_topology()
      -> evaluate_topology_scenarios()
          -> get_user_nodes()
          -> assign_content_publishers()
          -> build_exploration_snapshot()
              -> NetworkScenario(...)
              -> bootstrap_exploration()
          -> simulate_lmm1()
              -> run_dynamic_scenario()
                  -> NetworkScenario(...)
                  -> run_round() x total_rounds
          -> simulate_lmm2()
              -> run_dynamic_scenario()
                  -> NetworkScenario(...)
                  -> run_round() x total_rounds
      -> summarize_records()
      -> write_csv()
```

## What each module contributes

- `config.py`
  Holds global knobs such as learning constants, warmup/measurement rounds, and chunking mode helpers.

- `models.py`
  Defines the shared data classes used everywhere else.

- `network.py`
  Builds the base topology and chooses cache nodes.

- `content.py`
  Creates `ContentSpec` objects and assigns which publishers serve which content.

- `network_scenario.py`
  Runs the actual request/exploration simulation for LMM-1 and LMM-2.

- `learning.py`
  Updates path weights using prior observations.

- `resources.py`
  Simulates resource consumption and caching side effects.

- `metrics.py`
  Aggregates per-user and per-round results into final averages.

- `state.py`
  Clones topology and snapshot state so each simulation starts from a clean copy.

- `paths.py`
  Builds and scores paths between edge nodes and publishers.

## Class lifecycle: who creates what, and when

| Class | Created in | Used by | Purpose in the run |
| --- | --- | --- | --- |
| `ContentSpec` | `content.build_default_content_specs()` | `experiments.py`, `network_scenario.py`, `resources.py`, `network.py` | Describes each content item: ID, lifetime, cache cost, popularity. |
| `ResourceBudget` | `network.make_router_resources()` | `SimNode`, `resources.py`, `state.py` | Tracks CPU/cache/bandwidth/energy capacity and remaining budget. |
| `SimNode` | `network.sample_router()` and `network.build_base_topology()` | `BaseTopology`, `paths.py`, `network_scenario.py`, `resources.py` | Represents each node in the topology, including resource and cache state. |
| `BaseTopology` | `network.build_base_topology()` | `experiments.py`, `network_scenario.py`, `paths.py`, `resources.py`, `state.py` | Container for nodes, adjacency list, publisher candidates, and edge nodes. |
| `PathRecord` | `paths.path_records_from_raw_paths()` | `network_scenario.py`, `learning.py`, `network.py`, `state.py` | Stores a scored path from an edge node to a provider or cache. |
| `ExplorationSnapshot` | `network_scenario.build_exploration_snapshot()` | `experiments.py`, `network_scenario.py` | Saves discovered paths and path tables so LMM-1 and LMM-2 reuse the same exploration results. |
| `InterestMessage` | `NetworkScenario.start_exploration()` and `NetworkScenario.on_user_request()` | `RuntimeNode.on_interest()` | Forward message used both for path exploration and for real content fetches. |
| `DataMessage` | `NetworkScenario.on_node_interest()` | `RuntimeNode.on_data()` | Reverse-path response carrying exploration results or fetched content. |
| `RequestState` | `NetworkScenario.on_user_request()` | `NetworkScenario.on_node_data()`, `on_user_timer()`, `on_path_timer()` | Tracks one user request across chunks, paths, timings, and completion state. |
| `CachedContentState` | `resources.store_in_cache()` | `resources.py`, `content.py`, `network_scenario.py`, `state.py` | Records cached content lifetime and cache cost at a node. |
| `EventLoop` | `NetworkScenario.bootstrap_exploration()`, `run_isolated_request()`, `run_round()` | `NetworkScenario` | Minimal scheduler for timed message passing. |
| `RuntimeNode` | `NetworkScenario.__init__()` | `NetworkScenario` | Wrapper that forwards node events back into the scenario logic. |
| `EdgeRuntimeNode` | `NetworkScenario.__init__()` | `NetworkScenario` | Specialized runtime node for user-facing edge nodes. |
| `NetworkScenario` | `build_exploration_snapshot()` and `run_dynamic_scenario()` | `simulate_lmm1()`, `simulate_lmm2()` | The main simulation engine. |

## Detailed sequence when `run_full_experiment()` is called

### 1. Content setup

`run_experiments.py:main()` first creates content with:

```python
content_specs = build_default_content_specs(args.content_count)
```

This creates one `ContentSpec` per content item.

### 2. Topology creation

`experiments.run_full_experiment()` loops over experiment iterations and calls:

```python
base = build_base_topology(topology_seed, edge_node_count=edge_node_count)
```

Inside `build_base_topology()`:

- edge nodes and routers are created as `SimNode`
- each router gets `ResourceBudget` objects
- all nodes are wrapped into one `BaseTopology`
- publisher candidates are precomputed

### 3. Scenario preparation per `(Np, Nu)`

`evaluate_topology_scenarios()` then:

1. slices `base.publisher_candidates` to get the active publishers
2. calls `get_user_nodes()` to choose edge nodes for users
3. calls `assign_content_publishers()` to map content IDs to publishers
4. calls `build_exploration_snapshot()`

`build_exploration_snapshot()` creates a temporary `NetworkScenario` whose job is only to discover valid paths before the real LMM runs begin.

### 4. Exploration bootstrap

Inside `NetworkScenario.__init__()`:

- `BaseTopology` is cloned using `state.clone_base_topology()`
- `RuntimeNode` objects are created for all nodes
- `EdgeRuntimeNode` objects are created for access nodes
- if no snapshot is supplied, `bootstrap_exploration()` runs

During exploration:

- `EdgeRuntimeNode.start_exploration()` sends `InterestMessage`
- intermediate nodes forward them using `on_node_interest()`
- providers answer with `DataMessage`
- returning data causes `register_discovered_path()`
- `refresh_path_table()` converts raw paths into `PathRecord`
- `apply_learning_scores()` adjusts the path weights
- `select_multipaths()` keeps the usable path set

The snapshot returned from this stage is an `ExplorationSnapshot`.

### 5. LMM-1 and LMM-2 simulation

For each user count and chunking mode, `evaluate_topology_scenarios()` calls both:

- `simulate_lmm1(...)`
- `simulate_lmm2(...)`

Each one forwards to `run_dynamic_scenario()`, which creates a fresh `NetworkScenario` using the saved `ExplorationSnapshot`.

That means:

- both LMMs start from the same discovered paths
- the runtime state is clean for each run
- only the LMM behavior differs

### 6. Round execution

`run_dynamic_scenario()` runs:

```python
for round_index in range(WARMUP_ROUNDS + MEASUREMENT_ROUNDS):
    round_summary = scenario.run_round(round_index, num_users)
```

Inside `run_round()`:

- users are attached to edge nodes
- an `EventLoop` is created
- each user schedules a request at some arrival offset
- each request enters `on_user_request()`

### 7. Request execution

When a user request starts:

1. `RequestState` is created.
2. The selected `PathRecord` objects determine which paths will be used.
3. One or more `InterestMessage` objects are sent.
4. Nodes process the messages through `on_node_interest()`.
5. A provider or cache node responds with `DataMessage`.
6. `on_node_data()` walks the response back to the edge node.

When the data arrives back:

- learning scores are updated
- path tables are refreshed
- `touch_path_resources()` consumes CPU/cache/bandwidth/energy
- `store_in_cache()` may create `CachedContentState` in LMM-2
- request completion is written into user metrics

### 8. Metrics and result aggregation

Per-request metrics become per-user records through:

- `metrics.make_user_record()`
- `metrics.summarize_user_metrics()`

Per-round summaries are then combined by:

- `metrics.summarize_rounds()`

Finally, `experiments.py` appends one output record for LMM-1 and one for LMM-2, then later groups everything with:

- `summarize_records()`
- `write_csv()`

## Short version: class call map

If you only want the class flow, it is:

```text
ContentSpec
  -> used to assign content publishers
  -> used by NetworkScenario to decide requests, caching, and lifetimes

ResourceBudget + SimNode
  -> created while building the topology
  -> packed into BaseTopology

BaseTopology
  -> passed into experiments
  -> cloned into each NetworkScenario

ExplorationSnapshot
  -> built once from exploration
  -> reused by LMM-1 and LMM-2

PathRecord
  -> derived from discovered raw paths
  -> scored, learned, filtered, then used for fetch requests

InterestMessage / DataMessage
  -> drive message passing in the event loop

RequestState
  -> tracks each active user request

CachedContentState
  -> appears only when content is stored in cache

NetworkScenario
  -> central runtime controller that ties all of the above together
```

## One subtle but important detail

If you are documenting this for a report or viva, the most accurate wording is:

> "`experiments.py` is the experiment orchestration module, but `run_experiments.py` is the executable entrypoint in the current codebase."

That distinction matters because `experiments.py` defines the workflow but does not directly start it by itself.
