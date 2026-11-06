# RadTwin roadmap

| Phase | Goal | Key deliverables | Exit criteria |
|---|---|---|---|
| **0. Prototype** (done) | Prove the loop end to end | Exam room twin, patient variants, autonomous positioning, scenario runner, dataset generator, HL7 to DICOM, benchmark | All scripts run on one workstation; dataset + benchmark produced |
| **1. Platform foundation** | Make it a product, not scripts | Shared logic as a Kit extension; containerised headless Kit worker; `exam-service` and `scenario-service` (FastAPI); CI with scenario regression tests; pinned versions | A scenario job submitted over the API produces the same result as the prototype |
| **2. Fidelity** | Close the realism gap | Anatomical patient models with clinical review; manufacturer-accurate equipment from CAD; Replicator segmentation masks; material and lighting randomisation; simulated radiograph output | Clinical sign-off on assets; sim-to-real gap measured on a small real set |
| **3. Scale on Azure** | Thousands of scenarios per day | AKS GPU node pool; Service Bus; ADLS dataset lake; Azure ML registration; Kit App Streaming review UI; cost dashboards | Throughput and cost targets met; datasets traceable end to end |
| **4. AI enablement** | Feed and gate the AI teams | Benchmark gates per patient group; Cosmos-based augmentation evaluated; MONAI / PyTorch training pipelines on the dataset contract | No model release without passing per-population benchmark gates |
| **5. Clinical integration** | Connect to real systems safely | HL7 / FHIR and DICOM integration with RIS / PACS; full PS3.15 de-identification; IEC 62304 / ISO 14971 documentation | Regulatory review readiness |
