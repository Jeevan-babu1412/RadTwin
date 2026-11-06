# ADR-0001: OpenUSD as the scene and asset format

**Status:** Accepted

## Context
The platform combines assets from many sources: CAD of imaging equipment, artist-made rooms, generated
patient populations. Several teams (equipment, clinical, AI) edit them in parallel, and the same assets
must feed simulation, rendering and data generation for years.

## Decision
Use **OpenUSD** for every scene and asset. Structure:
- **Layers** per concern (room, equipment, patients, scenario overrides) so teams edit without conflicts.
- **References / payloads** so a scene loads only what it needs.
- **Variant sets** for populations and configurations (e.g. `bodyType` on the patient).
- **Custom attributes** (`radtwin:*`) for twin state such as table height, SID, exam state.
- **UsdPhysics** schemas for colliders, rigid bodies and mass.

## Consequences
- Positive: open standard (Pixar, AOUSD), supported by Omniverse, Blender, Maya, Houdini and Unreal import;
  non-destructive layering; variants avoid duplicating assets.
- Negative: learning curve for composition rules (strength ordering surprised us: a local opinion overrides a
  variant opinion, so variant-driven values must live on prims with no local opinion).
- Follow-up: define a naming and layer convention document; validate assets in CI.
