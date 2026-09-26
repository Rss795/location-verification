# Measurement and Evidence Collection

## M1 Peer Targets

The M1 integration obtains peer IDs and failure-domain hierarchy from `topology_map.json`, but the M1 bucket schema does not promise network target hosts or coordinates. The integrated path therefore requires an external metadata sidecar mapping every M1 peer ID to an authorized `target_host` and coordinates, and each witness ID to its own authorized measurement endpoint and coordinates. The M1 adapter rejects incomplete or extra peer mappings rather than making up locations. For distributed witnesses, supply Phase 2 processed batches collected by those witnesses; running this collector centrally does not by itself create independent remote vantage points.

Collect one vantage's real batches for every M1 peer:

```powershell
python experiments/collect_m1_measurements.py `
	--topology <path-to-topology_map.json> `
	--metadata <path-to-peer-witness-metadata.json> `
	--witness-id witness-1
```

The command labels output `REAL MEASUREMENTS` and refuses `127.0.0.1`/`localhost` unless `--allow-loopback` is set. Loopback remains connectivity data only; it is not geographic evidence. Independent campus/building/distant witnesses must each run this collector. Use `--synthetic` on `run_full_system.py` only for adapter tests; that branch is `SYNTHETIC EVALUATION`.

## Purpose

Phase 2 answers: **what network evidence did each witness observe about a target peer?** It preserves raw observations and calculates descriptive features. It does not interpret the evidence as proof of a physical location, assign confidence, or make a placement decision.

The use of multiple observations and independent witnesses is conceptually inspired by distributed Proof-of-Location research, including the 2026 ICSA-C paper named in the project brief. Proof-of-Location research is not the same as this implementation: this prototype adapts multi-observer evidence collection to physical failure-domain verification in an IPFS replication context.

## Measurement process

1. A witness identifies itself and supplies the target host/peer ID.
2. `RealPingSource` builds an OS-specific argument list and invokes the system ping utility with `shell=False`.
3. `collect_measurements` performs exactly the configured number of probes and waits only between probes.
4. Each attempt becomes a timezone-aware `MeasurementObservation`, including timeout or other failure reason when there is no RTT.
5. `extract_features` calculates descriptive statistics without discarding the raw observations.
6. `save_measurement_batch` writes raw CSV and a JSON batch/feature summary.

The `PingSource` protocol is the collection boundary. A later deterministic simulated source can implement `ping_once` and return `PingResult` values without changing collector or statistics code. Distributed orchestration across machines is not included yet; each witness can run the collector independently and provide its evidence record to a later aggregation layer.

## Platform and errors

Windows uses `ping -n 1 -w <milliseconds>`. Linux uses `ping -n -c 1 -W <seconds>`. macOS uses `ping -n -c 1 -W <milliseconds>`. All are argument arrays, not shell command strings. The subprocess also has a timeout as a final guard; OS option granularity and scheduling can make actual elapsed time differ slightly from the requested timeout.

The low-level result distinguishes success, timeout, target unreachable, missing ping executable, invalid target, malformed output, and other command errors. Invalid targets and unavailable ping executables stop the collector with a `MeasurementCollectionError`; probe-level failures remain represented in observations and batch status. All-unreachable batches are distinguished from batches that simply have no successful RTTs. Traceroute is a separate optional operation; its absence or failure does not affect RTT collection.

## Feature definitions

| Feature | Definition |
| --- | --- |
| `sample_count` | Number of probes attempted. |
| `successful_count` | Observations with a parsed RTT. |
| `timeout_count` | Probes explicitly classified as timeouts. |
| `failure_count` | Probes without an RTT, including unreachable or malformed results. |
| `packet_loss_rate` | `timeout_count / sample_count`; for an empty batch it is 1.0. An explicit unreachable response is retained as a failure but is not counted as a timeout. |
| minimum/maximum/mean | Minimum, maximum, and arithmetic mean of successful RTTs. |
| median and MAD | Median RTT and median absolute deviation `median(abs(x - median(x)))`; MAD is unscaled. |
| standard deviation | Population standard deviation of successful RTTs. |
| p50/p75/p90/p95 | Linear interpolation using rank `(n - 1) * q`, matching the common linear percentile convention. |
| jitter | Mean absolute difference between consecutive successful RTTs in observation order. Failed attempts are skipped, so consecutive successful values may have failures between them. A single success yields 0.0; no successes yields `None`. |

If there are no successful RTTs, every RTT-derived feature is `None`; no zero-valued RTT is fabricated. The parser retains the numeric value printed for coarse values such as Windows `time<1ms` as 1 ms, which is a displayed bound rather than a precise sub-millisecond measurement.

## Why repeated, multi-witness observations?

A single RTT is too fragile to support a physical claim: routing and path asymmetry, congestion, processing delay, network technology, packet loss, and temporary conditions all affect latency. Close locations can be indistinguishable, while distant peers can have unexpectedly efficient routes. Multiple witnesses provide observations from different network vantage points, but witnesses themselves may be unreliable, compromised, correlated, or poorly placed. These measurements describe evidence; later phases must model uncertainty rather than treat RTT as geographic distance.

## Raw data and reproducibility

Raw observations are retained in CSV and in the JSON batch export alongside timestamps, failure reasons, batch metadata, and extracted features. This supports re-analysis when later statistical methods change. Files are written to `data/raw/` and `data/processed/`; no database or real sample data is bundled. The measurement host is included in these local exports, so handle the files according to the network/privacy policies of the environment.

## Running real measurements

From the project root, install the package and its test dependencies, then run:

```powershell
python -m pip install -e ".[dev]"
python experiments/collect_measurements.py `
  --target-host <authorized-host> `
  --target-peer-id peer_07 `
  --witness-id witness_1
```

The script uses `measurement` settings from `configs/default.yaml`, validates the configured witness ID when a witness list is present, prints a measurement summary, and saves raw CSV/feature JSON. Use only targets you are authorized to probe. It does not print or produce a location verdict.

## Viva summary

- **What?** Platform-aware repeated RTT observations and descriptive summaries.
- **Why?** Preserve richer evidence than one ping while recording losses and variability.
- **How?** Shell-free system ping commands, timezone-aware raw samples, explicit failure reasons, and fixed statistical definitions.
- **Limitation?** These observations cannot cryptographically prove physical presence and do not remove routing, congestion, witness, or reachability uncertainty.
