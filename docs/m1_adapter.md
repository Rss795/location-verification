# M1 Topology Adapter

## Status and ownership

M1 is the physical topology/failure-domain module. The workspace did **not** contain the teammate's source tree or actual `topology_map.json` output. The repository now includes `m1_builder.py`, a typed, deterministic reference producer that converts flat claims into the documented hierarchy, alongside the adapter for existing tree input. This producer is not represented as the teammate implementation and does not validate compatibility with it. `examples/m1/topology_map.example.json` remains a schema example, not actual teammate output.

The reference builder requires explicit region, ASN, witnessing-zone, rack, weight, and topology-state inputs; it never derives geography from hostnames or bucket names. `m1_adapter.py` validates tree input and translates it to existing Phase 4 types. M4 may emit a derived tree with M3 results annotated per peer, while keeping shared M1 bucket states unchanged.

## Expected M1 input

The adapter accepts a root bucket directly, or a JSON wrapper with `root` or `topology`, using:

```text
root -> region -> asn -> witnessing_zone -> rack -> peer node
```

The bucket types and M1 states are validated. `witnessing_zone` remains the literal level name throughout; it is never renamed to `datacenter`. Peer IDs must be unique, and the parent/child type sequence is checked. Placement domain keys are compact JSON arrays of the full bucket ancestor path (for example, a witnessing-zone key contains its region, ASN, and zone IDs). This prevents repeated local bucket labels under different parents from collapsing into one domain; the original M1 labels remain available on `M1PeerRecord`.

## M1 states

The adapter retains both the exact `witnessing_zone_verification_state` and all `path_verification_states` on `M1PeerRecord`, plus a conservative effective topology state on the existing `PlacementPeer`:

| M1 state | Adapter/placement treatment |
| --- | --- |
| `verified` | Retained as topology metadata. Phase 3 evidence is still required to produce `PLAUSIBLE`. |
| `pending_check` | Retained; it does not become verified. Without Phase 3 measurements, the peer remains `INSUFFICIENT_EVIDENCE` and ineligible. |
| `unverifiable_short_range` | Retained distinctly from suspicious. Strict short-range policy excludes it; balanced keeps it conditional with reduced preference; permissive keeps it eligible with reduced preference. It does not assert physical separation. |
| `untrusted` | Quarantined regardless of Phase 3 plausibility. This follows M1's topology trust state and is not a finding of malicious intent. |

When several path buckets have states, the adapter uses the most cautious state in this precedence: `untrusted`, `unverifiable_short_range`, `pending_check`, `verified`. The individual path and exact zone state remain inspectable. Phase 3 `SUSPICIOUS` and `INSUFFICIENT_EVIDENCE` take precedence over a short-range allowance; M1 caution cannot override missing or contradictory M3 evidence.

The short-range threshold in Phase 3 configuration is an engineering/model limitation, not a validated universal 500 km boundary. M1's `unverifiable_short_range` flag is consumed as supplied and remains an independent source of topology caution.

## External metadata is mandatory

The M1 tree schema does not include coordinates or network endpoints. The adapter intentionally does not invent them. A separate metadata JSON must provide one record per exact M1 peer ID:

```json
{
  "peers": {
    "peer-001": {
      "latitude": 17.385,
      "longitude": 78.4867,
      "target_host": "authorized-peer.example.internal",
      "reliability_score": 0.8
    }
  },
  "witnesses": [
    {
      "witness_id": "witness-1",
      "host": "authorized-target.example.internal",
      "latitude": 28.6139,
      "longitude": 77.209,
      "reliability_score": 0.8
    }
  ],
  "current_pin_allocations": {}
}
```

Use actual authorized metadata in a real run. The checked-in sidecar example uses reserved `.internal` placeholders and example coordinates; it is not operational metadata.

## Phase 2 evidence input

For real multi-witness integration, provide Phase 2 processed JSON already collected at each witness. `--evidence-dir` indexes standard Phase 2 feature files by their embedded `target_peer_id` and `witness_id`, so the original timestamped Phase 2 filenames can be used unchanged. The loader checks peer and witness IDs, M1 target host, batch structure, timestamps, observations, and features. Missing or duplicate peer/witness batches are errors; the system does not silently pretend that one local ping represents multiple distributed witnesses. Saved evidence remains accompanied by explicit witness coordinates/reliability from metadata.

If `--synthetic` is selected instead, deterministic model-consistent RTT samples are generated using the supplied claimed coordinates and the configured Phase 3 latency model. They are labeled synthetic and are not evidence about actual peer locations.

## M1 -> M3 -> M2 -> M4

1. Read and validate the M1 topology map.
2. Require external coordinate/endpoint/witness metadata for the exact M1 peer set.
3. Load saved Phase 2 batches or explicitly request synthetic batches.
4. Build existing `PeerClaim`/`WitnessEvidence` inputs; call Phase 3 `verify()` for each M1 peer.
5. Convert the M1 hierarchy to Phase 4 domain keys: `region`, `asn`, `witnessing_zone`, and `rack`; the values are path-qualified to distinguish repeated bucket IDs under different parents.
6. Call existing baseline and FDAR placement. Default integration level is `witnessing_zone`; choose another level explicitly if justified.
7. Optionally simulate a status change and use existing Phase 4 reconfiguration.
8. Produce a dry-run Cluster desired-state difference only.

The peer ID and M1 failure-domain labels are the topology authority. Haversine distance does not create or redefine failure domains.

## Topology cases

Honest declared hierarchy:

```text
Root
 `-- Region
   `-- ASN
     `-- witnessing_zone
       `-- Rack
         `-- PeerNode
```

See [architecture.md](architecture.md) for the complete M1→M3→M2→M4 mermaid data-flow and the honest / spoofed / short-range diagrams.

Spoof/inconsistency flow:

```text
peer claim -> M1 declared zone -> M3 witness RTT evidence
                -> inconsistent -> SUSPICIOUS
                -> M2 quarantine/exclusion
                -> M4 desired replacement plan
```

Short-range ambiguity:

```text
nearby peers -> M1 unverifiable_short_range
       -> physical independence is not asserted
       -> configured strict/balanced/permissive caution
       -> seek another declared zone or report domain shortfall
```

Distinct zone IDs are declared topology domains, but `unverifiable_short_range` warns that RTT does not establish their physical separation. Balanced mode admits such a peer conditionally; strict mode may fail placement rather than treat peer IDs as physical proof.

## Reproduction and limitations

The repository did not include the actual other-team M1 source or output during implementation, so the example schema fixture is used for adapter tests. Before using the integrated path with team output, run the adapter against the actual `topology_map.json`; adjust only the compatibility parser if the serialized shape differs while preserving M1's meaning. No actual M1 map, authorized real witness batches, or live Cluster was available in this workspace.

The checked-in `.example.json` files are schema and CLI fixtures only. They are not actual M1 output or real location measurements.

RTT is not proof of exact location. Witness trust/correlation, routing, congestion, technology, short-range ambiguity, and the Phase 3 uncalibrated evidence-strength score remain limitations. Failure-domain labels are externally supplied; the adapter does not authenticate them.
