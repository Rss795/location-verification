# Synthetic evaluation plots

These figures are deterministic **synthetic model results**. They are not measurements from campus or geographically distributed peers, field accuracy, calibrated probabilities, or proof of physical location. The configured latency assumptions, generated witness layout, and noise determine the plotted rates. See [Evaluation Engine](evaluation_engine.md) for the metric definitions and limits.

Plots 1–8 come from the full seeded synthetic evaluation suite. Plot 9 comes from a separate 30-trial location-mismatch sweep. Each chart is generated only when its source run contains the scenario data required for that chart; unsupported charts are omitted instead of being written as empty or zero-valued figures. The status distribution counts each generated trial and each distinct mismatch offset once, without counting the duplicated BASELINE/FDAR records twice.

The 30-trial sweep reports 0% generated mismatch detection at 500, 1,000, 2,000, and 5,000 km; 20% at 8,000 km; and 100% at 10,000 and 15,000 km. The generated false-alarm rate is 0% at each offset. These results describe this configured synthetic model only and do not establish a real-world distance threshold.

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

From the repository root, regenerate the full suite (plots 1–8) and the independent 30-trial distance sweep (plot 9):

```powershell
python experiments/run_evaluation.py --output-dir data/experiments
python experiments/run_evaluation.py --scenario distance_sweep --trials 30 --distance-sweep-km 500,1000,2000,5000,8000,10000,15000 --output-dir data/experiments/distance_sweep_extended
Copy-Item data/experiments/plots/0[1-8]_*.png docs/figures/synthetic-distance-sweep/
Copy-Item data/experiments/distance_sweep_extended/plots/09_synthetic_location_distance_sweep.png docs/figures/synthetic-distance-sweep/
```

The first command uses the scenarios, seeds, and parameters in `configs/evaluation.yaml`. The second command specifies the exact offsets used for the 30-trial curve. Generated JSON/CSV records, manifests, and intermediate plots remain under the ignored `data/experiments/` directory; the selected, explicitly synthetic PNG figures are committed here.
