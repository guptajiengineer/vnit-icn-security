"""
benchmark/instrumentation — measurement code for the seven guide-required
evaluation graphs (docs/graphs_notes.md).

Rules
-----
- Instrumentation only OBSERVES: it calls the real, unmodified functions from
  app/ (crypto_auth.py, content.py, fabric/chain.py, ...) and times / counts /
  sizes their actual execution.
- No simulator source file is changed by this package unless a measurement
  hook is strictly unavoidable (documented per milestone).
- Every CSV row is produced by an actual execution — never hand-written,
  estimated, or interpolated.
"""
