# Clean LMM Reproduction

This folder contains a clean, isolated reproduction path for the LMM-1 vs LMM-2 experiments without depending on the legacy event-loop simulator.

It is designed for:

- `Np = 4..10`
- `Nu = 2..8`
- `200` iterations by default
- a paper-style real-world geometric IoT network (`150m x 150m`, `120` nodes, `20m` communication range)

The published paper reports `50` iterations in `ns-3`. This runner uses `200` by default because the goal here is smoother reproduction plots, but you can switch back to `50` with `--iterations 50`.

## What This Fixes

The legacy code in the workspace mixes several concerns in one codepath. The biggest sources of instability were:

- success rate was multiplied across users inside one iteration instead of averaged per user
- the recorded delay ignored actual completion timing and overwrote it with a static value
- experiment state was reused in ways that could leak across runs
- publisher activation and path selection were noisy enough to make the `Np` sweep fluctuate

This clean implementation keeps every iteration independent and uses the same random scenario for both `LMM-1` and `LMM-2` so the comparison is fair.

## Model Used

The simulator follows the paper-oriented logic already reflected in the current repository:

- path weight is computed from average path duration, pending requests, packet loss, and response time
- node metrics are stateful, so congestion, packet loss, response time, and active duration move together as resources are consumed and recovered
- paths are reweighted over repeated rounds using a reward/penalty learning signal instead of being rescored from unrelated random values each time
- `LMM-1` serves each user independently over selected provider paths
- `LMM-2` adds a caching node and request aggregation behavior
- hop count is measured in graph hops
- delay is measured in simulation time units from both hop distance and current node response conditions
- per-user success rate is derived from per-node loss along the serving segment, and the scenario success rate is the product across users to match the paper equations

The implementation is still intentionally high-level. It does not replay the old packet-level flooding logic or full `ns-3` radio behavior, but it does preserve interdependent resource dynamics across repeated requests.

## Running

Use module execution from the workspace root:

```bash
python -m paper_repro_clean.run_experiments
```

Useful options:

```bash
python -m paper_repro_clean.run_experiments --iterations 200 --seed-base 1000
python -m paper_repro_clean.run_experiments --no-plots
python -m paper_repro_clean.run_experiments --output-dir paper_repro_clean/results_custom
```

On a typical local Python install, the full `Np=4..10`, `Nu=2..8`, `200`-iteration sweep is materially heavier than the earlier static model because each scenario now runs repeated stateful rounds.

## Outputs

The script writes:

- `raw_results.csv`
- `summary_by_publishers_and_users.csv`
- `summary_by_publishers.csv`
- `summary_by_users.csv`
- `iteration_profile_by_publishers.csv`
- `iteration_profile_by_users.csv`
- `manifest.json`

If `matplotlib` is installed, it also writes:

- `summary_curves.png`
- `iteration_profiles.png`

## Notes

- The topology generator creates one subscriber and ranks ten candidate publishers from farthest to closest so the `Np` sweep is much more stable.
- The same base topology seed is reused across `LMM-1` and `LMM-2` for each iteration.
- The same user ordering is reused across `LMM-1` and `LMM-2` inside each `(iteration, Np, Nu)` scenario.
- Users in the `Nu` sweep are measured from a common round snapshot, while aggregate request pressure is folded back into the persistent topology after each round. This keeps the paper-style distance trend without discarding resource exhaustion.
- The paper formulas are written for multiple users `Ui` attached to edge nodes `ENi`. This clean runner is still a high-level approximation rather than a full `ns-3` reproduction of spatially distinct users and edge nodes.
