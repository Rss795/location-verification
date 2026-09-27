# Synthetic evaluation plots

These figures are committed so they can be viewed directly on GitHub. They come from a generated distance-sweep evaluation and are **synthetic model results**, not measurements from campus or geographically distributed peers. The rates shown describe only generated scenarios under the configured latency assumptions, witness layout, and noise. They are not field accuracy, calibrated probabilities, or evidence of physical location.

The reported 30-trial run flagged 0% of generated mismatches at 500, 1,000, 2,000, and 5,000 km; 20% at 8,000 km; and all generated mismatches at 10,000 and 15,000 km. This run does not support a 500 km verification boundary. See [Evaluation Engine](evaluation_engine.md) for interpretation and limitations.

## Plots

### Suspicious peers selected

![Synthetic suspicious replica selection comparison](figures/synthetic-distance-sweep/01_suspicious_selection.png)

### Replica domain diversity

![Synthetic replica domain diversity](figures/synthetic-distance-sweep/02_domain_diversity.png)

### Placement success

![Synthetic placement success](figures/synthetic-distance-sweep/03_placement_success.png)

### Reconfiguration movement

![Synthetic reconfiguration movement](figures/synthetic-distance-sweep/04_reconfiguration_movement.png)

### Peer selection frequency

![Synthetic peer selection frequency](figures/synthetic-distance-sweep/05_peer_selection_frequency.png)

### Failure-domain selection frequency

![Synthetic domain selection frequency](figures/synthetic-distance-sweep/06_domain_selection_frequency.png)

### Verification status distribution

![Synthetic verification status distribution](figures/synthetic-distance-sweep/07_verification_status_distribution.png)

### Generated-label detection and false alarms

![Synthetic ground-truth mismatch detection](figures/synthetic-distance-sweep/08_synthetic_ground_truth_detection.png)

### Detection by generated location offset

![Synthetic location mismatch sweep](figures/synthetic-distance-sweep/09_synthetic_location_distance_sweep.png)

## Reproduce

From the repository root:

```powershell
python experiments/run_evaluation.py --scenario distance_sweep --trials 30 --distance-sweep-km 0,50,250,500,1000,2000,5000,8000,10000,15000 --output-dir data/experiments/distance_sweep_extended
python experiments/plot_results.py --input data/experiments/distance_sweep_extended/raw/evaluation_records.json --aggregated data/experiments/distance_sweep_extended/aggregated/evaluation_summary.json --output-dir data/experiments/distance_sweep_extended/plots
```

The generated JSON/CSV records and other run outputs stay under the ignored `data/experiments/` directory; only these selected, explicitly synthetic PNG figures are included in the repository.
