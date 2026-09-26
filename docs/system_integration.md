# Phase 6: Final System Integration

The actual teammate M1 producer was not present in the current workspace. `integrations/m1_builder.py` is a project-owned reference producer; `integrations/m1_adapter.py` is tested against the documented schema and fixtures, not against the teammate's production output. Before consuming that producer's artifact, verify its actual wrapper/enum serialization matches the adapter and adjust only this boundary if needed.

## Purpose

Phase 6 composes the completed Phase 1–5 modules. It does not replace Phase 3 verification, Phase 4 FDAR, or the Phase 5 evaluation framework. It provides a clear system call boundary, a deterministic synthetic dry-run, and an optional read-only boundary to a locally running IPFS Cluster API.

M1–M4 name the four team responsibilities (topology, placement, verification, verification-aware reconfiguration); Phase 1–6 name implementation stages. The complete integrated path is M1 topology -> M3 verification -> M2 FDAR -> M4 reconfiguration, with Phase 5 evaluating Phases 2–4 and Phase 6 orchestrating them.

## Complete architecture and flow

```text
Phase 1: PeerClaim / Witness / VerificationResult contracts
    -> Phase 2: repeated measurements and raw WitnessEvidence
    -> Phase 3: verify(PeerClaim, WitnessEvidence) -> VerificationResult
    -> Phase 4: topology + VerificationResult -> baseline / FDAR PlacementResult
    -> Phase 6: SystemOrchestrator -> SystemRunResult
         -> optional Phase 4 reconfiguration plan after a status change
         -> in-memory Cluster inventory / desired-state dry-run diff

Phase 5 evaluates the Phase 2-4 behavior across seeded synthetic scenarios.
```

`SystemOrchestrator.run()` checks that claims correspond to the supplied topology, invokes the existing Phase 3 `verify()` for each peer, attaches the returned results to placement peers, and invokes the existing baseline and FDAR functions. It optionally compares against baseline. `plan_verification_change()` updates one peer's verification status in a copied topology and calls the existing Phase 4 `plan_reconfiguration()`. It creates a plan only; it does not perform a move.

## M1 topology input

Run from flat peer claims with a separate metadata sidecar using the repository's reference producer:

```powershell
python experiments/run_full_system.py `
    --flat-claims examples/m1/flat_peer_claims.example.json `
    --built-topology-output data/m1_system/generated_topology.json `
    --metadata examples/m1/peer_witness_metadata.example.json `
    --synthetic --dry-run --failure-domain-level witnessing_zone `
    --simulate-status-change peer-003
```

This does not validate the external teammate M1 implementation. To consume an existing tree instead:

```powershell
python experiments/run_full_system.py `
    --topology <path-to-topology_map.json> `
    --metadata <path-to-peer-witness-metadata.json> `
    --evidence-dir <directory-containing-phase2-feature-json> `
    --dry-run --failure-domain-level witnessing_zone
```

The saved evidence loader indexes ordinary Phase 2 JSON files by embedded `target_peer_id` and `witness_id`. It does not rename or synthesize missing batches. Use `--synthetic` instead of `--evidence-dir` only for an adapter/pipeline smoke test; the signal is explicitly labeled `SYNTHETIC EVALUATION`. This CLI does not remotely collect from witness machines.

Collect one authorized vantage's real Phase 2 files with `experiments/collect_m1_measurements.py`. Loopback targets are refused unless `--allow-loopback` is set, and even then they are labeled as connectivity data, not geography.

## Result contract

`SystemRunResult` references existing `PeerClaim`, `VerificationResult`, `PlacementResult`, and `ReconfigurationPlan` objects rather than redefining those contracts. It carries object ID, claims, verification results, baseline and FDAR placements, optional reconfiguration, overall status/reasons, and metadata. `to_dict()` produces a JSON-compatible explanation including the research boundary that RTT plausibility is not cryptographic proof.

## IPFS Cluster mapping

| Project concept | Cluster-side input/output boundary | Important distinction |
| --- | --- | --- |
| `PeerClaim` | Cluster peer ID plus externally maintained coordinates and failure-domain labels. | IPFS Cluster does not natively authenticate physical location or domain membership. |
| `VerificationResult` | Project-owned evidence metadata associated with a peer ID. | It is not an IPFS Cluster proof or peer protocol field. |
| `PlacementResult` | Desired replica peer IDs/domains for an object/content ID. | The adapter represents the desired state; this phase does not submit a pin allocation. |
| `ReconfigurationPlan` | Proposed old-to-new replica difference. | It plans only; it does not copy, remove, or move data. |
| `PinAllocation` | Read-only current allocation returned by the optional local API or mock. | It is compared with the desired FDAR peer IDs to construct a dry-run diff. |

The responsibility split remains: location evidence comes from the verification subsystem; failure-domain placement comes from the FDAR subsystem; the adapter translates IDs and reads inventory only.

## Adapter behavior and safety

`ClusterAdapter` defines peer discovery, pin-allocation reading, and desired-placement representation. `DryRunIPFSClusterAdapter` / `InMemoryIPFSClusterAdapter` work with fixture values and do not mutate their inventory. `LocalIPFSClusterReadOnlyClient` is optional, restricted to HTTP(S) loopback URLs (`localhost`, `127.0.0.1`, `::1`), uses a request timeout, validates returned JSON, sends only GET requests to `/peers` and `/pins/{content_id}`, and refuses redirects so a loopback response cannot redirect a request to another host. It exposes no mutation method. No credentials are accepted or embedded in the URL.

Defaults in configuration are `enabled: false` and `dry_run: true`. The ordinary demo uses only generated in-memory state and makes no HTTP request. `--live` is required before the optional inventory client is constructed; it remains read-only. If the API is missing or malformed, the script reports `LIVE IPFS CLUSTER: NOT RUN` or a structured adapter error. API responsiveness is not location verification.

No pin update or data movement occurs in Phase 6. An eventual mutation-capable production adapter would require a separately reviewed authorization/safety design and is outside this project phase.

## Configuration

`configs/default.yaml` has the shared measurement, inference, placement, and `ipfs_cluster` sections. Cluster defaults:

- `enabled: false`: do not connect automatically.
- `base_url: http://127.0.0.1:9094`: loopback-only default; no public address or credentials.
- `dry_run: true`: expected mode for demonstrations.
- `request_timeout_seconds: 2.0`: bound local GET calls.

`configs/demo.yaml` is standalone and deterministic: generated peers/witnesses, no endpoints, no service dependency, and dry-run adapter settings. Its `demo.seed` controls synthetic evidence generation.

## Running the system

Install the project and dependencies, then from its root:

```powershell
python -m pip install -e ".[dev]"
python experiments/run_end_to_end_demo.py
python experiments/run_system.py --dry-run
```

Options include `--object-id`, `--replication-factor`, `--policy`, `--config`, `--output-dir`, and `--seed`. The demo reports evidence statuses, suspicious/uncertain peers, baseline and FDAR replicas/domains, diversity, excluded peers, reconfiguration movement, and the Cluster diff. JSON is saved under `data/system_demo/system_run_result.json` by default.

Optional local inventory commands:

```powershell
python experiments/run_ipfs_cluster_demo.py --dry-run
python experiments/run_ipfs_cluster_demo.py --live --config configs/default.yaml
```

To permit the read-only local API command, configure `ipfs_cluster.enabled: true` and keep `base_url` loopback-only. No actual IPFS pin/data operation is available.

## Phase 5 evaluation and tests

Phase 5 remains separate and consumes existing verifier/placement APIs:

```powershell
python experiments/run_evaluation.py
python experiments/plot_results.py
python -m pytest -q
```

The evaluation produces `data/experiments/` JSON/CSV and nine plots. Those values are `SYNTHETIC`; generated actual/claimed labels are ground truth only inside those controlled scenarios. The distance sweep is model sensitivity, not empirical calibration. The checked-in `127.0.0.1` measurement is loopback pipeline data, not location evidence, and is not used as evaluation ground truth.

## Research boundaries and limitations

- RTT estimates consistency only; it is not exact location or cryptographic proof.
- Witnesses, their coordinates, the latency envelope, thresholds, and reliability are not authenticated/calibrated by Phase 6.
- Failure-domain labels remain external metadata; IPFS Cluster does not provide physical truth.
- Synthetic evidence demonstrates reproducibility and component integration, not real-world accuracy.
- The placement code is CRUSH-inspired, not production CRUSH equivalence.
- The live adapter has not been tested against an available Cluster instance unless the operator explicitly runs it; it is read-only regardless.
- No automatic data movement, pin mutation, credential handling, or remote service is required.

## Reproducibility

The demo uses a fixed seed and ISO-independent generated timestamps in its evidence fixtures, so the serialized system result is deterministic for a given config/seed/object ID. The Phase 5 runner records seeds and full Phase 3/4 configuration snapshots. Output timestamps in Phase 5 naturally vary between invocations and are metadata, not measured system performance.
