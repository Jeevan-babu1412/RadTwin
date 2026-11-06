# ADR-0003: Microservices around an event bus

**Status:** Accepted

## Context
Demand is bursty (a dataset request can mean thousands of scenarios) while GPU capacity is expensive and
limited. Different parts change at different speeds: HL7 / DICOM integration, scenario logic, rendering,
dataset tooling. Several teams own them.

## Decision
Split the platform into services with clear APIs (`exam-service`, `scenario-service`, `dataset-service`,
`dicom-service`) and run simulation as **stateless GPU workers** that consume jobs from an **event bus**
(Azure Service Bus). Each job carries everything needed to reproduce it: asset versions, variant selections,
protocol, random seed.

## Consequences
- Positive: workers scale on queue depth; failures retry or dead-letter without blocking others; teams
  release independently; any run is reproducible from its job message.
- Negative: more moving parts (monitoring, tracing, contract versioning); eventual consistency between services.
- Mitigations: OpenTelemetry tracing, schema-versioned job messages, contract tests in CI.
- The prototype runs these steps as scripts in one process; the boundaries in this ADR are where it will be split.
