# Phase 5: Systematic Evaluation Engine

## Purpose and separation of concerns

Phase 5 evaluates the existing Phase 1–4 system; it does not replace or tune the verifier or placement algorithms. Each synthetic peer's generated actual and claimed location/domain are retained separately. The runner creates Phase 2 `MeasurementBatch`/`WitnessEvidence`, invokes the existing Phase 3 `verify()`, stores its `VerificationResult` on Phase 4 `PlacementPeer`, then calls the existing `place_baseline()`, `place_fdar()`, and `plan_reconfiguration()` functions.

The measurements are generated deterministically in memory. The runner does not ping hosts and does not read or score the saved localhost loopback artifact.

## Scenario definitions

Phase 5's existing synthetic generator remains separate from M1 ingestion. The M1 integrated CLI can use saved Phase 2 batches for M1 peer IDs or explicitly requested synthetic batches; its synthetic branch is an adapter/pipeline smoke test, not an evaluation of M1's actual topology generator.

| Scenario | Controlled setup | Evaluation distinction |
| --- | --- | --- |
| `all_honest` | Generated actual/claimed coordinates and domains match; RTT batches follow the same transparent latency model used for the synthetic signal. | Normal-case placement success, diversity, and suspicious count. |
| `one_suspicious` | One peer has a remote synthetic actual location/domain but claims a local location/domain; its witness batches are generated at the actual location and passed through Phase 3. | Baseline may select the claim; FDAR eligibility follows the verifier's produced status. The runner records many object IDs to avoid a single hash outcome. |
| `multiple_suspicious` | Several peers have generated actual/claimed mismatches and corresponding synthetic witness batches. | Whether the verifier and policy exclude them and how many domains remain. |
| `uncertain_peers` | Witnesses are placed within the verifier's configured short-distance caution radius. | Existing Phase 3 verifier returns `UNCERTAIN`; Phase 4 is run under strict, balanced, and permissive modes. Baseline is repeated as the same verification-blind control under each mode label. |
| `domain_shortfall` | Only two honest eligible claimed buildings remain; other candidate domains carry generated inconsistent claims. | Baseline can use unverified claims; FDAR must return `INSUFFICIENT_DOMAINS` for replication factor three. |
| `status_change` | Start with the existing generated Phase 3 results and a successful FDAR placement; change one selected result from `PLAUSIBLE` to `SUSPICIOUS`. | Existing Phase 4 planner's preserved/replaced replica and movement counts. This is a planned change only, not data transfer. |
| `multiple_objects` | Apply a fixed generated peer pool to many deterministic object IDs. | Placement success, domains, collisions, and peer/domain selection frequencies. |
| `repeated_trials` | Repeat generated peer/witness pools across effective seeds and many object IDs. | Trial/scenario/mode aggregate means and rates. |
| `distance_sweep` | Displace one peer's actual location from its fixed claimed location by configurable great-circle offsets; generate RTT evidence at the actual location. Keep its failure-domain label constant. | Location mismatch detection and false-alarm frequencies by offset under the chosen synthetic latency model and witness layout. This is model behavior, not field calibration. |

The false-location cases are purposely large geographic mismatches so this prototype's assumed RTT envelope can expose a controlled contrast. They do not characterize a real-world verification boundary.

## Baseline and FDAR

Baseline calls the existing Phase 4 baseline function on the same topology, candidate set, object IDs, replication factor, and failure-domain level. It uses peer availability and deterministic hash ranking, but ignores verification. FDAR calls the existing verification-aware function and consumes the `VerificationResult` status, evidence-strength confidence, uncertainty through confidence-bearing results, witness agreement, per-witness measurement quality, policy, and configured scoring weights. Neither placement implementation is redefined by Phase 5.

## Metrics

Per placement, the runner records success/count, replica count, distinct domains, collisions, distinct-domain/requested-replica ratio, eligible/excluded counts, suspicious and uncertain selected/excluded counts, suspicious selection/exclusion rates, and selected peers/domains. It reports separate generated-label measures for failure-domain mismatches and coordinate mismatches. Distance-sweep summaries retain the offset and do not average across distances.

For generated ground truth only, failure-domain mismatch means `actual_failure_domain != claimed_failure_domain`; coordinate mismatch means non-zero generated actual-to-claimed great-circle distance. Each label is compared separately with Phase 3 `SUSPICIOUS`. These are **synthetic scenario frequencies**, not network accuracy or probabilities. No such metric is applied to the stored `127.0.0.1` measurement.

The default distance sweep spans 0–15,000 km, including 500 km. In one 30-trial run at tested offsets 500, 1,000, 2,000, 5,000, 8,000, 10,000, and 15,000 km, the checked-in model flagged 0% at the first four offsets, 20% at 8,000 km, and all cases at 10,000 and 15,000 km. This result is specific to generated witness layout, model parameters, and noise; it does not establish a real threshold and does not support the proposed ~500 km boundary. The plotted rates are synthetic scenario frequencies only.

For status-change records it reports events, replicas preserved, removed/replaced, movement count, movement ratio, repair success, and whether distinct-domain placement remains satisfied. It does not model bytes copied, transfer time, or IPFS operations.

## Seeds and reproducibility

`configs/evaluation.yaml` defines seeds, trial count, peer/witness/object counts, measurement samples, replication factor, hierarchy level, scenarios, policies, and output path. Each trial records its effective seed. A fixed seed controls Python's local random generator for coordinate offsets and RTT noise; fixed model parameters and fixed object IDs then yield stable statuses/placement for that seed. Timestamps in result records naturally change between runs; compare experiment values, not the run timestamp.

Every per-object record also carries its scenario/seed/trial/object identifiers, peer/witness/object counts, replication factor, failure-domain level, mode/policy, and the complete Phase 3 and Phase 4 configuration snapshots used for that run.

Outputs are written below `data/experiments/`:

- `evaluation_manifest.json`: run settings, phase configs, effective seeds, and labels.
- `raw/evaluation_records.json` and `.csv`: per-object baseline/FDAR rows and generated truth/status summaries.
- `aggregated/evaluation_summary.json`: grouped trial/object summaries.
- `plots/`: nine generated PNG plots, including synthetic location-distance sensitivity.

## Plots

1. Baseline vs FDAR suspicious selected count.
2. Domain diversity ratio.
3. Placement success rate.
4. Reconfiguration movement count.
5. FDAR peer-selection frequency over many objects.
6. FDAR failure-domain selection frequency.
7. Phase 3 verification status distribution.
8. Synthetic-ground-truth detection and false-alarm rates, only when mismatch labels exist.
9. Synthetic location-mismatch detection and false-alarm frequency by generated offset.

Every plot labels its data synthetic. Plots do not call scores “probabilities,” imply real accuracy, or show unsupported error bars.

## Reading results honestly

Acceptable interpretation: “In this generated scenario, baseline selected a peer whose generated actual domain differed from its claim, while Phase 3 classified it suspicious and FDAR excluded it under the configured policy.” The result is a controlled pipeline demonstration. It does not establish that FDAR is universally better, the thresholds are optimal, or real networks can be classified at the same rates.

The Phase 3 confidence remains an uncalibrated evidence-strength score, not a probability. Synthetic actual/claimed labels are ground truth only inside the generator. The local loopback artifact is not geographic evidence and is not included in these experiments.

## Limitations

- Synthetic RTTs use an engineering latency model; they are not observations from independent real witnesses.
- Deliberate large location differences make scenario distinctions clearer than difficult close-distance cases.
- Phase 3's assumptions and Phase 4 policy/scoring weights remain uncalibrated.
- Synthetic witnesses, domains, peers, and claims omit correlated failures, strategic behavior, and real ISP routing complexity.
- Results provide no real-world geographic accuracy estimate, cryptographic proof, production CRUSH equivalence, or live IPFS Cluster behavior.
- Phase 5 outputs remain `SYNTHETIC EVALUATION`. They are not the same as `REAL MEASUREMENTS` collected through `collect_m1_measurements.py`.

## Reproduction

From the project root:

```powershell
python -m pytest -q
python experiments/run_evaluation.py
python experiments/plot_results.py
```

Small deterministic run:

```powershell
python experiments/run_evaluation.py --seed 42 --scenario one_suspicious --trials 2 --objects 20 --output-dir data/experiments/demo
python experiments/plot_results.py --input data/experiments/demo/raw/evaluation_records.json --aggregated data/experiments/demo/aggregated/evaluation_summary.json --output-dir data/experiments/demo/plots
python experiments/run_evaluation.py --scenario distance_sweep --trials 30 --distance-sweep-km 0,50,250,500,1000,2000,5000,8000,10000,15000 --output-dir data/experiments/distance_sweep
```
