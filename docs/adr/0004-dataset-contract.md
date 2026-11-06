# ADR-0004: Dataset contract: images + per-frame JSON + versioned manifest

**Status:** Accepted

## Context
AI teams need synthetic data they can trust, trace and compare across versions. Regulators expect evidence
of how training and validation data was produced.

## Decision
Every dataset is a folder with:
- `rgb/` images
- `labels/<frame>.json`: annotations (amodal boxes, keypoints), regression targets (beam offset), patient,
  exam, equipment and camera metadata, `synthetic: true`, `contains_phi: false`
- `manifest.json`: dataset name and semantic version, generator script and seed, source stage, class list,
  deterministic train / val / test split (hash of frame id), distribution by patient and exam, SHA-256 per file
- `LABELLING.md`: classes and labelling rules for that version

## Consequences
- Positive: any dataset can be regenerated from seed + stage; splits never leak between versions; hashes
  detect tampering or partial copies; the distribution table exposes population gaps before training.
- Negative: JSON per frame is less efficient than a columnar format at very large scale.
- Follow-up: add segmentation masks via Replicator; export to COCO for detection tools; register datasets in Azure ML.
