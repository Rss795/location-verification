"""Verification-aware failure-domain placement prototype."""

from .fdar import place_baseline, place_fdar
from .models import (
    EligibilityState,
    PlacementMode,
    PlacementPeer,
    PlacementResult,
    PlacementStatus,
    VerificationPolicyMode,
)
from .topology import FailureDomainTopology
from .reconfiguration import ReconfigurationPlan, plan_reconfiguration

__all__ = [
    "EligibilityState",
    "FailureDomainTopology",
    "PlacementMode",
    "PlacementPeer",
    "PlacementResult",
    "PlacementStatus",
    "ReconfigurationPlan",
    "VerificationPolicyMode",
    "place_fdar",
    "place_baseline",
    "plan_reconfiguration",
]
