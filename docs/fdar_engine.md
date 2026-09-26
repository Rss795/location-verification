# Phase 4: Verification-Aware FDAR Placement

## 1. Purpose and boundary

This phase connects Phase 3's `VerificationResult` to replica placement: the result changes candidate eligibility and preference instead of remaining a detached report. Phase 4 is a research prototype, not production CRUSH and not a live IPFS Cluster integration. It plans peer selection only; it moves no IPFS data.

## 2. Why failure domains matter

Distinct peer IDs or hash buckets do not guarantee independent physical risk. Multiple replicas in one building can share power, access network, or building-wide hazards. The placement model therefore groups peers by explicit infrastructure labels such as region, site, building, and floor. These labels are supplied topology metadata; geographic distance alone does not define shared failure domains.

## 3. Literature concepts and our implementation

**Literature/system concepts:** hierarchical CRUSH-style placement maps objects deterministically through a hierarchy; distributed Proof-of-Location work motivates multiple-observer evidence; decentralized physical infrastructure motivates trust-aware operation. The cited papers are not present in this workspace. We do not attribute FDAR or this specific placement algorithm to them and make no claims about uninspected paper results.

**Our implementation:** Phase 3 status, confidence, agreement, and measurement quality feed configurable eligibility and preference. A small SHA-256-ranked selector then chooses distinct physical domains. This adapts hierarchical deterministic placement to the project's physical failure-domain context; it is not a complete production CRUSH implementation.

## 4. Phase 3 integration and verification eligibility

`PlacementPeer` composes the existing `PeerClaim`, declared hierarchy IDs, availability, and optional Phase 3 `VerificationResult`. The configured `verification_policy.mode` governs the status mapping:

| Mode | PLAUSIBLE | UNCERTAIN | SUSPICIOUS | INSUFFICIENT_EVIDENCE |
| --- | --- | --- | --- | --- |
| strict | Eligible | Ineligible | Quarantined | Ineligible |
| balanced | Eligible | Conditional, reduced preference | Quarantined | Ineligible |
| permissive | Eligible | Eligible, reduced preference | Quarantined | Ineligible |

An unavailable peer is ineligible in all modes. Suspicious means current evidence is inconsistent with the claim, not that the peer is malicious. Excluded and quarantined peers retain their status, confidence, uncertainty, and reason in the placement result.

When the topology comes from M1, its `region`, `asn`, `witnessing_zone`, and `rack` values are the authoritative declared failure-domain keys. The adapter does not rename `witnessing_zone` to `datacenter`. M1's separate `unverifiable_short_range` state is preserved; the placement config applies `short_range_mode` (`strict`, `balanced`, or `permissive`) without changing the Phase 3 verification status. A Phase 3 suspicious or insufficient result takes precedence over short-range caution. M1 `PeerNode.weight` is passed through and multiplies the deterministic preference score equally in baseline and FDAR; a default weight of 1 preserves existing rankings.

## 5. Physical topology hierarchy

`FailureDomainTopology` accepts an ordered level list; the default is `region -> site -> building -> floor`, with `peer` available as a leaf selection level. Each peer must supply one non-empty identifier at every configured level. The hierarchy can be changed for an installation, but this prototype does not derive or authenticate its labels. Adding two peers to one building does not create two building failure domains.

## 6. Deterministic CRUSH-style selection and diversity

For an object/domain/peer tuple, the selector hashes `object_id NUL failure_domain NUL peer_id` with SHA-256. FDAR combines the normalized hash fraction with configured Phase 3 confidence, witness agreement, and mean per-witness measurement quality; the policy multiplier reduces conditional uncertain peers. Candidates are ranked deterministically. The selector then accepts at most one peer per configured failure domain until the replication factor is met.

The score weights default to confidence 0.30, agreement 0.25, measurement quality 0.20, and deterministic hash 0.25. They sum to 1, are engineering assumptions, and express placement preference only, not probability or scientific optimality. Baseline uses the same topology, candidate pool, domain rule, object ID, and hash selector but ranks using the hash only and ignores verification. This is the control representing trust in peer claims.

When peers originate from M1, its positive `PeerNode.weight` is retained as a capacity/preference multiplier on the final deterministic rank in both baseline and FDAR. The default weight 1 leaves existing Phase 4 results unchanged; non-default M1 weights are external placement inputs, not verification probabilities.

When eligible distinct domains are fewer than the requested replica count, placement returns `INSUFFICIENT_DOMAINS`; it never silently places duplicate-domain replicas. Empty eligible pools return `NO_ELIGIBLE_PEERS`.

## 7. Placement result and explanation

`PlacementResult` includes object ID, requested factor, selected peers/domains, level, excluded decisions, status, reason, mode, eligible count, distinct domain capacity, verification-status summary, and hash metadata. Each selected record states its verification status, confidence/uncertainty, eligibility reason, selection reason, and score. Results serialize with `to_dict()` and `to_json()`.

Metrics are descriptive: replica count, distinct domains, domain collisions, eligible/excluded/uncertain/suspicious counts, success, and reconfiguration moves. No accuracy is reported because the synthetic topology has no empirical ground truth.

## 8. Dynamic reconfiguration

`plan_reconfiguration` re-evaluates the previous FDAR peers against the current topology and verification policy. It preserves every still-eligible replica that does not collide at the selected domain level, and deterministically fills only missing slots. `required_moves` counts invalidated/removed peers from the old placement; an impossible repair explicitly returns an incomplete placement and failure reason. The function plans only; no copy, deletion, or IPFS operation occurs.

## 9. Synthetic simulation and comparison

`experiments/run_placement_simulation.py` builds a fixed synthetic topology with multiple peers in one building and candidates across five buildings/two regions, including uncertain and suspicious statuses. It prints baseline, FDAR, metrics, and a status-change reconfiguration plan. `experiments/compare_placement.py` reports the same-pool comparison. These are deterministic demonstrations, not network experiments or real-world validation.

## 10. Configuration and assumptions

The `placement` section in `configs/default.yaml` documents each value inline. Replication factor 3 and building-level diversity are prototype defaults. Balanced policy admits uncertain peers at a 0.5 preference multiplier. The score weights listed above, policy mode, uncertain multipliers, and reconfiguration flags are operating assumptions only. No values are presented as empirically optimal.

## 11. IPFS Cluster adapter boundary

The package accepts a peer candidate list/topology and an object ID plus placement config, and returns a serializable plan. A future adapter can map IPFS peer records and replication requests into these values and submit a result to a separate actuator. No live Cluster API, pin state, replication, or data movement is included in this phase.

## 12. Limitations

- RTT is not geographic proof; topology labels may still be wrong when evidence is uncertain.
- Witnesses can be compromised, correlated, sparse, or poorly placed; routing can distort latency.
- Short physical distances can be indistinguishable using RTT.
- Verification status reflects current evidence, not intent or maliciousness.
- The latency model, Phase 3 confidence, placement weights, and policy are not calibrated against operational ground truth here.
- Domain correctness depends on externally supplied topology metadata.
- The simplified selector is not production CRUSH and has no production reweighting or failure-recovery guarantees.
- No actual IPFS data movement occurs.

## 13. Reproduction

From the project directory:

```powershell
python -m pytest -q
python experiments/run_placement_simulation.py
python experiments/compare_placement.py
```

Phase 5 adds repeated seeded evaluation, ground-truth-labeled synthetic scenarios, aggregate metrics, and plots without replacing these Phase 4 placement APIs. See [evaluation_engine.md](evaluation_engine.md).
