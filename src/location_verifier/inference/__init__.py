"""Interpretable location-consistency inference over Phase 2 evidence."""

from .distance import haversine_distance_km
from .latency_model import ExpectedLatency, LatencyModel
from .residuals import WitnessResidual, analyze_residual
from .verifier import load_saved_witness_evidence, verify

__all__ = [
    "ExpectedLatency",
    "LatencyModel",
    "WitnessResidual",
    "analyze_residual",
    "haversine_distance_km",
    "load_saved_witness_evidence",
    "verify",
]
