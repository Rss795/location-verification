"""Apply configured verification-status policy to placement candidates."""

from __future__ import annotations

from ..config import VerificationPolicyConfig
from ..models import VerificationStatus
from .models import EligibilityState, PeerDecision, PlacementPeer


def decide_eligibility(
    peer: PlacementPeer,
    policy: VerificationPolicyConfig,
) -> PeerDecision:
    """Return a reasoned policy decision; status is never collapsed to a boolean."""

    result = peer.verification
    confidence = result.confidence if result is not None else None
    uncertainty = result.uncertainty if result is not None else None
    status = peer.verification_status
    m1_state = peer.topology_verification_state
    if not peer.available:
        state, reason, multiplier = EligibilityState.INELIGIBLE, "peer is unavailable", 0.0
    elif m1_state == "untrusted":
        state, reason, multiplier = (
            EligibilityState.QUARANTINED,
            "M1 topology marks this peer untrusted; preserved separately from Phase 3 status",
            0.0,
        )
    elif status is VerificationStatus.SUSPICIOUS:
        state, reason, multiplier = (
            EligibilityState.QUARANTINED,
            "evidence is inconsistent with the claim; quarantined by placement policy, not labeled malicious",
            0.0,
        )
    elif status is VerificationStatus.INSUFFICIENT_EVIDENCE:
        state, reason, multiplier = (
            EligibilityState.INELIGIBLE,
            "Phase 3 has insufficient evidence; M1 topology state cannot substitute for measurements",
            0.0,
        )
    elif m1_state == "unverifiable_short_range" and policy.short_range_mode == "strict":
        state, reason, multiplier = (
            EligibilityState.INELIGIBLE,
            "M1 marks physical separation unverifiable at short range; strict topology policy excludes it",
            0.0,
        )
    elif m1_state == "unverifiable_short_range" and policy.short_range_mode == "balanced":
        state, reason, multiplier = (
            EligibilityState.CONDITIONAL,
            "M1 marks physical separation unverifiable at short range; retained cautiously by balanced policy",
            policy.short_range_preference_multiplier,
        )
    elif m1_state == "unverifiable_short_range" and policy.short_range_mode == "permissive":
        state, reason, multiplier = (
            EligibilityState.ELIGIBLE,
            "M1 marks physical separation unverifiable at short range; permissive policy allows it with reduced preference",
            policy.short_range_preference_multiplier,
        )
    elif status is VerificationStatus.PLAUSIBLE:
        state, reason, multiplier = EligibilityState.ELIGIBLE, "verification evidence is plausible", 1.0
    elif status is VerificationStatus.UNCERTAIN and policy.mode == "balanced":
        state = EligibilityState.CONDITIONAL
        reason = "verification is uncertain; allowed with reduced placement preference by balanced policy"
        multiplier = policy.balanced_uncertain_multiplier
    elif status is VerificationStatus.UNCERTAIN and policy.mode == "permissive":
        state = EligibilityState.ELIGIBLE
        reason = "verification is uncertain; allowed with reduced preference by permissive policy"
        multiplier = policy.permissive_uncertain_multiplier
    elif status is VerificationStatus.UNCERTAIN:
        state, reason, multiplier = EligibilityState.INELIGIBLE, "uncertain peers are excluded by strict policy", 0.0
    else:
        state, reason, multiplier = (
            EligibilityState.INELIGIBLE,
            "insufficient verification evidence for configured placement policy",
            0.0,
        )
    return PeerDecision(
        peer_id=peer.peer_id,
        state=state,
        reason=reason,
        preference_multiplier=multiplier,
        verification_status=status,
        confidence=confidence,
        uncertainty=uncertainty,
        topology_verification_state=m1_state,
        witnessing_zone_verification_state=peer.witnessing_zone_verification_state,
    )