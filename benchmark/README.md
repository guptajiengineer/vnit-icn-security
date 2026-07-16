# ICN Benchmarking

This directory contains **two independent evaluation suites** for the
Information-Centric Networking (ICN) project. They measure fundamentally
different things and are intentionally kept separate.

```
benchmark/
├── README.md                     ← you are here
├── performance_evaluation/       ← evaluates the NETWORK (routing simulator)
└── security_evaluation/          ← evaluates the SECURITY architecture
```

---

## Why two suites?

The repository grew two distinct benchmarking efforts that previously shared
directories:

1. an original **performance** benchmark that drives the ICN routing simulator
   and measures its networking behaviour, and
2. a newer **security** evaluation that instruments the real cryptographic and
   blockchain code paths to produce the seven graphs required by the research
   guide.

Mixing them in one tree made it unclear which scripts, datasets, and figures
belonged to which study. Separating them solves that: each suite owns its own
`scripts`/`instrumentation`, `data`, `graphs`, and report, so a reader can open
one folder and understand a complete, self-contained study without wading
through the other. This improves **maintainability** (changes stay local),
**reproducibility** (each suite documents its own workflow and outputs), and
**research clarity** (the two research questions never get conflated).

---

## Performance Evaluation vs. Security Evaluation

| | **Performance Evaluation** | **Security Evaluation** |
|---|---|---|
| **What it evaluates** | The network / routing simulator itself | The proposed security architecture |
| **Question answered** | How well does the ICN network route and deliver content? | What does the security mechanism cost, and does it work? |
| **Method** | Drives `app/run_experiments.py` across configurations | Instruments the real `app/` crypto & blockchain code paths |
| **Examples** | latency, routing efficiency, multipath performance, throughput, cache behaviour, network scalability | cryptographic processing, authentication, blockchain registration, blockchain storage, security overhead, key management, security effectiveness |
| **Location** | `performance_evaluation/` | `security_evaluation/` |

### Performance Evaluation

Measures the **networking behaviour** of the ICN simulator — for example
latency, routing efficiency, multipath (LMM) performance, throughput, cache
behaviour, and scalability with publisher/user counts. These experiments
evaluate **the network**.

### Security Evaluation

Measures the **cost and effectiveness of the proposed security architecture** —
for example cryptographic processing time, authentication performance,
blockchain registration and storage overhead, total security overhead, key
management overhead, and tamper-detection effectiveness. These experiments
evaluate **the security mechanisms**.

---

## Independence

The two suites are fully independent:

- They share no scripts, data files, or figures.
- Each has its own `README.md` describing how to run it and what it produces.
- Each writes only into its own `data/` and `graphs/` directories.

Both suites treat `app/` as read-only: **neither modifies the simulator or the
security implementation.** They only *observe* and *drive* the existing code.

See the per-suite READMEs for details:

- [`performance_evaluation/README.md`](performance_evaluation/README.md)
- [`security_evaluation/README.md`](security_evaluation/README.md)

# Research Evaluation Branch

⚠️ This branch contains benchmarking, instrumentation,
evaluation scripts, raw experimental data, and generated
figures used for research evaluation.

It is intentionally separated from the production simulator.

Do NOT merge this branch into `main`.

If improvements to the simulator are required, implement
them independently in `main` and update the instrumentation
accordingly.