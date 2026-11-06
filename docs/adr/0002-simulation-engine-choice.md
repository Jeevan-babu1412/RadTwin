# ADR-0002: Omniverse over Unreal Engine and Unity for the simulation core

**Status:** Accepted

## Context
The core must render physically plausible images, simulate equipment and patient physics, generate labelled
synthetic data at scale, and run headless on cloud GPUs. Visual review by people matters, but the main
consumer is AI training and validation.

## Options scored
Scores 1 (weak) to 5 (strong) are the team's judgement for **this** use case; weights reflect the platform's priorities.

| Criterion | Weight | NVIDIA Omniverse | Unreal Engine 5 | Unity |
|---|---|---|---|---|
| Physically based rendering / sensor realism | 3 | 5 | 4 | 3 |
| Synthetic data + automatic labels | 3 | 5 (Replicator) | 3 (plugins / custom) | 4 (Perception package) |
| Open scene format, multi-team pipelines | 2 | 5 (native OpenUSD) | 3 (USD import) | 2 |
| Physics for equipment and bodies | 2 | 4 (PhysX) | 4 (Chaos) | 4 (PhysX) |
| Headless scaling on cloud GPUs | 2 | 4 | 3 | 4 |
| Python automation | 2 | 5 | 3 | 2 |
| Real-time interactive UX / XR | 1 | 3 | 5 | 5 |
| Team skills available | 1 | 3 | 4 | 4 |
| **Weighted total (max 80)** | | **72** | **56** | **54** |

## Decision
Use **NVIDIA Omniverse** (Kit apps, OpenUSD, PhysX, Replicator) for the simulation and data core.
Keep **Unreal** or **Unity** as options for operator-facing interactive or XR front ends that consume the same USD assets.

## Consequences
- Positive: one stack for rendering, physics and labelled data; Python-first automation; links to NVIDIA's
  AI ecosystem (Cosmos world models, Isaac, MONAI / Holoscan).
- Negative: GPU-heavy (RTX required); Kit extension versions must be pinned (the prototype hit a PhysX bundle
  version conflict when enabling a newer registry version); smaller talent pool than Unreal / Unity.
- Review again if the platform's main consumer shifts from AI teams to human training.
