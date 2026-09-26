# Phase 3: Location Consistency Inference

## 1. Purpose and boundary

The inference engine asks whether a peer's claimed coordinates are consistent with RTT observations independently collected by witnesses. It consumes `PeerClaim` and Phase 2 `WitnessEvidence` and returns the existing `VerificationResult` contract. It does not prove physical presence, identify malicious peers, or perform FDAR placement.

In the complete M1 pipeline, peer identities and declared `witnessing_zone`/rack hierarchy come from the M1 adapter. Claimed coordinates, target hosts, and witness coordinates/reliabilities remain explicit sidecar metadata because the M1 topology schema does not contain them. The adapter preserves M1 `unverifiable_short_range` independently; it never translates that label into Phase 3 `SUSPICIOUS`.

The research connection is conceptual: distributed observations, multiple witnesses, and evidence aggregation are inspired by Proof-of-Location research, including Brito et al. (ICSA-C 2026), and the broader decentralized physical-infrastructure trust context of Castillo et al. (ICBC 2025). The papers are not present in this workspace, so this document makes no claims about uninspected paper algorithms or results. This implementation adapts those broad ideas to IPFS physical failure-domain claims; it does not reproduce either paper.

References supplied for project context:

1. E. Brito, F. Castillo, A. Hadachi, U. Norbisrath, and J. Heiss, “Decentralized Proof-of-Location for Content Provenance: Towards Capture-Time Authenticity,” IEEE 23rd International Conference on Software Architecture Companion (ICSA-C), 2026, pp. 199–206, DOI: [10.1109/ICSA-C68850.2026.00049](https://doi.org/10.1109/ICSA-C68850.2026.00049), arXiv:2603.27883.
2. F. Castillo, O. Castillo, E. Brito, and S. Espinola, “Trustworthy Decentralized Autonomous Machines: A New Paradigm in Automation Economy,” IEEE International Conference on Blockchain and Cryptocurrency (ICBC), 2025, pp. 1–7, DOI: [10.1109/ICBC64466.2025.11185065](https://doi.org/10.1109/ICBC64466.2025.11185065).

## 2. Architecture

```text
PeerClaim + WitnessEvidence
  -> Haversine witness-to-claim distances
  -> expected RTT ranges
  -> residual / measurement-quality records
  -> sample and witness outlier flags (retained)
  -> reliability-weighted fusion
  -> status + VerificationResult evidence
```

Each module owns one step: `distance.py`, `latency_model.py`, `residuals.py`, `reliability.py`, `outliers.py`, `fusion.py`, and `verifier.py`. A saved Phase 2 processed JSON file does not assert witness coordinates; `load_saved_witness_evidence(path, witness)` requires the caller to provide witness metadata explicitly.

## 3. Haversine distance

For latitude/longitude pairs in radians, Haversine computes the central angle:

$$
a = \sin^2(\Delta\phi/2) + \cos(\phi_1)\cos(\phi_2)\sin^2(\Delta\lambda/2),\quad
c = 2\operatorname{atan2}(\sqrt{a}, \sqrt{1-a}),\quad
d = Rc.
$$

The implementation uses the IUGG mean Earth radius $R=6371.0088$ km. It is a spherical great-circle estimate between the witness's declared coordinates and the peer's claimed coordinates. It says nothing by itself about the truth of either coordinate.

## 4. Latency model and expected range

The transparent model is:

$$
\hat{t}(d)=\max(t_{min}, b + k d),\qquad
u(d)=u_0 + u_{100}(d/100),\qquad
range(d)=[\max(t_{min},\hat{t}-u),\hat{t}+u].
$$

Here $d$ is Haversine distance in km; $b$ is a baseline RTT in ms; $k$ is the assumed RTT increase in ms/km; $u$ is an assumed uncertainty half-width; and $t_{min}$ is a positive lower bound. The model's center is not a universal physical law. It is an interpretable engineering envelope intended for calibration with authorized measurements later.

Every default in `configs/default.yaml` is an **engineering assumption**, not a value claimed to be calibrated or taken from the cited papers:

| Parameter | Default | Meaning / reason |
| --- | ---: | --- |
| `baseline_rtt_ms` | 8.0 ms | Assumed non-distance baseline for access, route, and processing. |
| `propagation_factor_ms_per_km` | 0.01 ms/km | Idealized round-trip propagation scale for a signal in fiber near 200,000 km/s; real routes are not straight fiber paths. |
| `uncertainty_ms` | 15.0 ms | Broad assumed network/path variability half-width. |
| `uncertainty_per_100_km_ms` | 2.0 ms/100 km | Assumed range widening with distance. |
| `minimum_rtt_ms` | 0.1 ms | Positive output floor; not a geographic threshold. |

These values are starting assumptions only and require sensitivity analysis and empirical calibration before research conclusions.

## 5. Residual analysis

The primary observed value is Phase 2 median RTT $m$, not the mean. The signed residual is $r=m-\hat{t}$. The expected lower/upper range is recorded and `within_expected_range` is exposed for explanation. The continuous consistency score uses only excess outside that range:

$$
e=\max(L-m, m-U, 0),\quad
s=\sqrt{u^2+v^2},\quad
z=\operatorname{sign}(r)e/s,\quad
consistency=\exp(-z^2/2).
$$

$L,U$ are expected bounds; $v$ is an observed variability scale, the larger of MAD and jitter divided by $\sqrt{2}$. A value inside the broad expected interval has zero normalized excess and a score of 1. Outside it, support decreases smoothly with excess. This score is a heuristic evidence index, not a likelihood or probability. No successful median yields unavailable residual/consistency values rather than fabricated zero RTT.

## 6. Measurement quality and witness reliability

The current prototype calculates:

$$
completeness=\min(successful\_count/minimum\_samples,1),\quad
stability=1/(1+(MAD+jitter/2)/variability\_scale),\quad
loss\_quality=1-packet\_loss.
$$

Measurement quality is the configured weighted arithmetic mean of these three values. Weights default to 0.25, 0.35, and 0.40 respectively, and must sum to 1. Effective reliability equals measurement quality multiplied by the existing `Witness.reliability_score`. All of this is a proposed, interpretable evidence-weighting mechanism, not a universal or scientifically calibrated reliability law. Unstable/lossy data is down-weighted, not discarded.

## 7. Outlier handling

Individual successful RTT samples and witness-level normalized residuals are assessed separately using a median/MAD robust z-score. Group witness detection is disabled below the configured minimum of three usable witnesses. A robust score above the configured 3.5 threshold is flagged. The scale floor avoids division by zero when most values are identical. An outlier means unusual relative to this sample/group, not malicious. Outliers and raw samples remain inspectable; a flagged witness is only down-weighted during fusion.

## 8. Evidence fusion

Each usable witness's consistency score $q_i$ is weighted by effective reliability $w_i$; flagged witness weights are multiplied by the configured outlier multiplier (0.25 by default). Support is the weighted mean $S=\sum w_iq_i/\sum w_i$; contradiction is $C=1-S$. Agreement is $A=\max(0,1-\sqrt{\sum w_i(q_i-S)^2/\sum w_i})$. Evidence coverage is the mean effective fusion weight multiplied by a witness-count coverage factor capped at 1.

The evidence-strength score is $confidence=coverage\times agreement\times\max(S,C)$, bounded to [0,1], and `uncertainty = 1 - confidence`. This is **not a calibrated probability**. It summarizes the amount, reliability, agreement, and directional strength of evidence under the chosen assumptions. High confidence can accompany strong contradiction; inspect status and evidence fields together.

## 9. Statuses and short-distance ambiguity

- `PLAUSIBLE`: enough usable coverage and agreement, with support above the configured threshold.
- `SUSPICIOUS`: enough usable coverage and agreement, with contradiction above its configured threshold. This is inconsistency, not an accusation.
- `UNCERTAIN`: evidence is conflicting, coverage is weak, the score is not decisive, or all measured witnesses lie within the configured short-distance caution radius.
- `INSUFFICIENT_EVIDENCE`: fewer than the configured minimum of usable witnesses.

The default short-distance caution radius is 50 km, an explicit prototype guard rather than a known scientific boundary. If all witnesses are near the claim, the physical propagation component is small compared with baseline and network variation, so similar RTTs cannot discriminate location reliably. The verifier therefore returns `UNCERTAIN` even when the observations fit the range. This does not guarantee that distances beyond 50 km are distinguishable; it merely makes one known ambiguity visible. M1's separate `unverifiable_short_range` (the modeled ~500 km engineering limitation unless experimentally supported) is topology caution, not a Phase 3 status and not a finding of spoofing.

## 10. Configuration glossary

All values are read from the `inference` section. Units are included in field names where applicable. `minimum_samples` is a count; all score thresholds are dimensionless in [0,1]. `robust_z_threshold` is dimensionless; `scale_floor` is normalized-residual units. `minimum_witnesses` values are counts. `outlier_weight_multiplier` scales a flagged witness's weight. Decision thresholds govern prototype status routing and are tunable engineering choices, not empirical guarantees. The `decision.short_distance_km` caution is described above.

## 11. Limitations and assumptions

- Internet RTT is not geographic distance: routing, peering, congestion, queueing, endpoint processing, ICMP policy, tunnels, wireless links, and path asymmetry intervene.
- Witness coordinates and declared prior reliability are assumed inputs; this phase does not authenticate them.
- Witnesses may be correlated, compromised, geographically clustered, or selectively unavailable.
- The parametric expected-latency envelope and quality/fusion weights are not calibrated to a target population.
- A broad envelope improves tolerance to network variability but reduces discriminatory power.
- The robust outlier sample is small and flags unusual evidence only; it cannot infer cause.
- A confidence score is an uncalibrated evidence-strength index, not probability.
- Ordinary RTT and traceroute evidence cannot cryptographically prove physical presence or a building-level failure domain.

## 12. Research contribution and future improvements

The adaptation is the integration of multi-witness network observations, uncertainty-aware consistency scoring, robust retention/down-weighting, and a confidence-bearing result for physical failure-domain verification in an IPFS placement context. The synthetic distance sweep documented in [evaluation_engine.md](evaluation_engine.md) reports no detections at the tested offsets from 500 through 5,000 km under the default assumptions, then increasing detection at larger offsets. This is a software/model diagnostic only and does not validate a field threshold. Future work should collect authorized geographically distributed measurements, fit and validate latency envelopes by network context, test correlated/Byzantine witness models, calibrate score-to-frequency interpretations on held-out data, and quantify the distance-dependent false-acceptance/false-rejection boundary. No real-world accuracy is claimed here.
