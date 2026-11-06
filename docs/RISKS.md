# RadTwin risk register

Likelihood and impact: L = low, M = medium, H = high.

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | **Sim-to-real gap**: models trained on synthetic images underperform on real ones | H | H | Domain randomisation (lighting, materials, poses); validate on a small real dataset; Cosmos-style augmentation; track the gap as a metric |
| 2 | **Unrepresentative patient population** (body types, ages, conditions missing) | M | H | Population matrix agreed with clinical experts; per-group benchmark metrics (already in `benchmark.py`); re-balance the generator |
| 3 | **Anatomical inaccuracy** of virtual patients | H (prototype) | H | Replace stand-ins with validated anatomical models; clinical review gate for new assets |
| 4 | **Unsafe positioning logic** reaches a real system | L | H | Clearance rules and BLOCKED state; scenario runs as regression tests; ISO 14971 risk file; human approval before hardware |
| 5 | **PHI leakage** if real data is introduced | L | H | Synthetic-only by default; de-identification (DICOM PS3.15) at the boundary; access logging; no real data in dev environments |
| 6 | **GPU cost overrun** at scale | M | M | Queue-based autoscaling, spot GPU nodes for batch, render resolution per use, cost dashboards |
| 7 | **Extension / version drift** in Omniverse Kit | M | M | Pin Kit and extension versions in the app `.kit` file; upgrade in a branch with scenario regression tests |
| 8 | **Regulatory evidence gaps** (IEC 62304, ISO 13485) | M | H | Versioned code and datasets, manifests and run logs as evidence, requirement-to-test traceability |
| 9 | **Key-person dependency** on Omniverse / USD skills | M | M | Architecture docs, ADRs, pairing, internal training |
