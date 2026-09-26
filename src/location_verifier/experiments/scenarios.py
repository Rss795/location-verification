"""Controlled evaluation scenario names and concise experimental definitions."""

from enum import StrEnum


class ScenarioName(StrEnum):
    ALL_HONEST = "all_honest"
    ONE_SUSPICIOUS = "one_suspicious"
    MULTIPLE_SUSPICIOUS = "multiple_suspicious"
    UNCERTAIN_PEERS = "uncertain_peers"
    DOMAIN_SHORTFALL = "domain_shortfall"
    STATUS_CHANGE = "status_change"
    MULTIPLE_OBJECTS = "multiple_objects"
    REPEATED_TRIALS = "repeated_trials"
    DISTANCE_SWEEP = "distance_sweep"


SCENARIOS = {
    ScenarioName.ALL_HONEST: "All claims match generated actual domains and locations.",
    ScenarioName.ONE_SUSPICIOUS: "One peer claims a remote failure domain/location; Phase 3 judges its generated witness batches.",
    ScenarioName.MULTIPLE_SUSPICIOUS: "Several generated peers have remote actual locations but local claims, reducing eligible domains.",
    ScenarioName.UNCERTAIN_PEERS: "Witnesses are generated within the Phase 3 short-distance caution radius.",
    ScenarioName.DOMAIN_SHORTFALL: "Only two eligible claimed buildings remain for replication factor three.",
    ScenarioName.STATUS_CHANGE: "A selected plausible peer changes to suspicious, then the Phase 4 reconfiguration planner repairs placement.",
    ScenarioName.MULTIPLE_OBJECTS: "One generated peer pool is placed for many deterministic object identifiers.",
    ScenarioName.REPEATED_TRIALS: "Multiple seeded trials generate distinct peer pools and repeated object placements.",
    ScenarioName.DISTANCE_SWEEP: "Synthetic actual locations are offset from a fixed claimed location while evidence is generated at the actual location; failure-domain labels remain fixed.",
}
