# Synthetic evaluation results

These figures and explanations describe synthetic model results. They are not measurements from campus or geographically distributed peers, field accuracy, calibrated probabilities, or proof of physical location. The configured latency assumptions, generated witness layout, and noise determine the plotted rates. See [Evaluation Engine](evaluation_engine.md) for metric definitions and limitations.

## Plot 1 — Suspicious replicas selected

[Open Plot 1](figures/synthetic-distance-sweep/01_suspicious_selection.png)

![Synthetic suspicious replica selection comparison](figures/synthetic-distance-sweep/01_suspicious_selection.png)

**X-axis — Scenario**

Each label names a generated test situation:

- `all_honest`: generated peer claims match their generated truth.
- `distance_sweep`: a peer’s generated actual location is moved away from its claimed location by different distances.
- `domain_shortfall`: too few eligible domains are available to satisfy the requested replicas.
- `multiple_objects`: the same generated peer pool is used to place many objects.
- `multiple_suspicious`: several peers have generated mismatches.
- `one_suspicious`: one peer has a generated mismatch.
- `repeated_trials`: generated trials are repeated with different recorded seeds.
- `status_change`: a peer’s verification status changes after an initial placement.
- `uncertain_peers`: evidence is set up to produce uncertain verification results.

**Y-axis — Mean suspicious selected peers**

This is the average number of selected replicas that were classified as `SUSPICIOUS` by the verifier. It is a count per placement, not a percentage.

**Bars — Blue is Baseline; orange is FDAR**

For each scenario, compare the blue and orange bars. A taller bar means that method selected more peers classified as suspicious.

For example, in `one_suspicious`, the baseline bar is about 0.2 suspicious peers per placement, while the FDAR bar is at zero. That suggests the baseline selected the generated suspicious peer in some placements, while FDAR did not in the generated placements represented here. In `all_honest`, both are at zero, as expected if no peers were classified suspicious.

Important caveat: `distance_sweep` combines placements across many different distance offsets into one average. That bar can hide how behavior changes with distance; Plot 9 is the chart for that question. Also, a zero bar means no suspicious peer was selected in these generated records. It doesn’t prove that FDAR will always avoid suspicious peers in real networks.

## Plot 2 — Replica domain diversity

[Open Plot 2](figures/synthetic-distance-sweep/02_domain_diversity.png)

![Synthetic replica domain diversity](figures/synthetic-distance-sweep/02_domain_diversity.png)

**X-axis — Scenario**

These are the scenario categories, with `distance_sweep` left out. The labels have the same meanings as in Plot 1.

**Y-axis — Distinct domains / requested replicas**

This is a ratio:

\[
\frac{\text{number of distinct failure domains among selected replicas}}
{\text{number of requested replicas}}
\]

With a replication factor of 3:

- `1.0` means three replicas cover three distinct domains.
- About `0.67` means two distinct domains cover the requested three replicas.
- Lower values mean less domain diversity relative to the request.

**Lines and markers — Blue is Baseline; orange is FDAR**

Each marker is a result for a scenario. The chart connects the markers to make comparisons easier; the line does not represent a progression over time.

The lower FDAR value for `domain_shortfall` is meaningful: the generated setup has fewer eligible domains than the requested replication factor. FDAR reports the shortfall rather than putting multiple replicas in a domain just to reach three.

Plotting problem: `uncertain_peers` has results for multiple policies—strict, balanced, and permissive—but they are drawn at the same x-axis category and connected as if they were one line. This makes the orange drop at that category misleading. The chart needs to show those policies separately or aggregate them clearly before I’d use that part of it.

## Plot 3 — Placement success rate

[Open Plot 3](figures/synthetic-distance-sweep/03_placement_success.png)

![Synthetic placement success](figures/synthetic-distance-sweep/03_placement_success.png)

**X-axis — Scenario**

The generated scenarios, as above, excluding `distance_sweep`.

**Y-axis — Successful placement attempts / attempts**

This is the fraction of placement attempts that selected the full requested number of replicas:

- `1.0` means every counted attempt reached the replication factor.
- `0.0` means none did.
- `0.5` means half did.

**Lines and markers — Blue is Baseline; orange is FDAR**

The FDAR drop to zero at `domain_shortfall` is the expected outcome if there aren’t enough eligible domains for the requested three replicas. The system is prioritizing the configured domain constraint, so a shortfall is reported instead of filling the replica count by violating that constraint.

Plotting problem: As in Plot 2, the uncertain-peer results use multiple policies at the same x-axis category. The line connects these policy results without identifying them, so the apparent drop at `uncertain_peers` is not a clean single success-rate result. Don’t present it as one result until the policies are separated or explicitly combined.

## Plot 4 — Reconfiguration movement plan

[Open Plot 4](figures/synthetic-distance-sweep/04_reconfiguration_movement.png)

![Synthetic reconfiguration movement](figures/synthetic-distance-sweep/04_reconfiguration_movement.png)

**X-axis — FDAR**

The bar is labeled FDAR because this plot shows the generated FDAR repair plans included in the results.

**Y-axis — Mean replicas moved (plans only)**

This is the average number of replica assignments changed in the generated reconfiguration plans. The bar is at 1, meaning the plans changed one replica on average.

The chart is about planned assignment changes after a status change. It does not show bytes copied, transfer time, or actual movement of data. It would be clearer with the number of plans included, so the audience knows how many cases contribute to the average.

## Plot 5 — FDAR peer selection frequency

[Open Plot 5](figures/synthetic-distance-sweep/05_peer_selection_frequency.png)

![Synthetic peer selection frequency](figures/synthetic-distance-sweep/05_peer_selection_frequency.png)

**X-axis — Peer IDs**

Each label, such as `peer-001`, identifies one generated peer.

**Y-axis — Selected replica instances**

The bar height is how many times that peer appears in FDAR placements across the generated multi-object and repeated-trial scenarios. A taller bar means more selections in those records.

The bars are in a fairly similar range, though some peers are selected more often than others. This is a descriptive count, not a fairness measurement: the chart does not show how often each peer was eligible or available to be selected.

## Plot 6 — FDAR failure-domain selection frequency

[Open Plot 6](figures/synthetic-distance-sweep/06_domain_selection_frequency.png)

![Synthetic domain selection frequency](figures/synthetic-distance-sweep/06_domain_selection_frequency.png)

**X-axis — Failure-domain IDs**

Labels such as `A1`, `A2`, and `B1` identify generated failure domains. A failure domain is a group of peers treated as sharing a possible failure risk.

**Y-axis — Selected replica instances**

This counts how many selected replicas came from each domain across the generated multi-object and repeated-trial scenarios.

The bars look broadly similar, but some domains are selected more often. Like Plot 5, this is not enough by itself to claim the algorithm is fair: domains may differ in which peers they contain, and the chart doesn’t show each domain’s eligible opportunities.

## Plot 7 — Phase 3 verification statuses

[Open Plot 7](figures/synthetic-distance-sweep/07_verification_status_distribution.png)

![Synthetic verification status distribution](figures/synthetic-distance-sweep/07_verification_status_distribution.png)

**X-axis — Verification status**

- `PLAUSIBLE`: the available generated evidence meets the configured consistency and quality rules.
- `SUSPICIOUS`: the evidence conflicts with the claim strongly enough under the configured model.
- `UNCERTAIN`: the evidence is ambiguous or has a configured reason for caution.

**Y-axis — Generated peers**

This is the number of generated peer cases assigned each status across the counted synthetic trials and scenarios.

The chart shows that the evaluation exercised multiple verifier outcomes, with many more plausible peers than suspicious or uncertain ones. These counts depend on how the scenarios were generated; they are not estimates of how peers would be distributed in a real deployment. There is no `INSUFFICIENT_EVIDENCE` bar because that status did not occur in the records included in this plot.

## Plot 8 — Synthetic ground-truth detection

[Open Plot 8](figures/synthetic-distance-sweep/08_synthetic_ground_truth_detection.png)

![Synthetic ground-truth mismatch detection](figures/synthetic-distance-sweep/08_synthetic_ground_truth_detection.png)

**X-axis — Scenarios with generated mismatch labels**

The labels here are the scenarios for which the experiment has generated “ground truth” to compare against verification. That ground truth exists only inside the synthetic experiment.

**Y-axis — Rate (not real-world accuracy)**

The scale runs from 0.0 to 1.0:

- `1.0` means all relevant generated cases in that calculation were counted.
- `0.0` means none were.

**Bars — Synthetic detection rate**

This measures the share of generated mismatches classified as `SUSPICIOUS` by the verifier.

**Line — Synthetic false-alarm rate**

This measures the share of generated non-mismatches classified as `SUSPICIOUS`.

In this plot, the bars are at 1.0 and the false-alarm line is at or near zero for the shown scenarios. In this generated setup, the verifier flagged the mismatches and did not flag the generated non-mismatches counted by the metric.

That is a strong-looking result because the generated cases are controlled to make a contrast. It is not evidence of 100% real-world accuracy. Visually, the legend overlaps the upper part of the chart, and the zero false-alarm line is hard to see; both should be improved before a presentation.

## Plot 9 — Synthetic location distance sweep

[Open Plot 9](figures/synthetic-distance-sweep/09_synthetic_location_distance_sweep.png)

![Synthetic location mismatch sweep](figures/synthetic-distance-sweep/09_synthetic_location_distance_sweep.png)

**X-axis — Generated actual-to-claimed offset (km)**

This is how far apart the generated peer’s actual and claimed coordinates are, in kilometers. Each tested offset is a controlled scenario, not a measured peer location.

**Y-axis — Rate under configured model**

The rate runs from 0.0 to 1.0, meaning zero to all generated cases counted at that offset.

**Blue line — Synthetic mismatch detection**

At each offset, this is the share of generated location mismatches classified as suspicious. In this run, it is zero through 5,000 km, about 0.2 at 8,000 km, then 1.0 at 10,000 and 15,000 km.

**Orange line — Synthetic false alarm**

This is the share of generated non-mismatches classified as suspicious; it stays at zero in the displayed run.

The rising curve means the configured model detected larger generated offsets more often in these scenarios. It does not tell us the real distance at which location claims become detectable: actual routing, congestion, witness placement, and model calibration would all matter. The plotted rates are specific to these generated inputs.

## Reproduce

From the repository root, regenerate the full suite (Plots 1–8) and the independent 30-trial distance sweep (Plot 9):

```powershell
python experiments/run_evaluation.py --output-dir data/experiments
python experiments/run_evaluation.py --scenario distance_sweep --trials 30 --distance-sweep-km 500,1000,2000,5000,8000,10000,15000 --output-dir data/experiments/distance_sweep_extended
Copy-Item data/experiments/plots/0[1-8]_*.png docs/figures/synthetic-distance-sweep/
Copy-Item data/experiments/distance_sweep_extended/plots/09_synthetic_location_distance_sweep.png docs/figures/synthetic-distance-sweep/
```

The first command uses the scenarios, seeds, and parameters in `configs/evaluation.yaml`. The second specifies the offsets used for the 30-trial curve. Generated JSON/CSV records, manifests, and intermediate plots remain under `data/experiments/`; the selected synthetic PNG figures are committed here.
