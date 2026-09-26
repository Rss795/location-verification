"""Optional, read-only integration boundaries for external cluster systems."""

from .ipfs_cluster import (
    ClusterAdapter,
    ClusterAdapterError,
    ClusterPeer,
    DesiredPlacementAction,
    DryRunIPFSClusterAdapter,
    InMemoryIPFSClusterAdapter,
    LocalIPFSClusterReadOnlyClient,
    PinAllocation,
)
from .m1_adapter import (
    M1AdapterError,
    M1ExternalMetadata,
    M1PeerRecord,
    M1TopologySnapshot,
    M1VerificationState,
    load_external_metadata,
    load_topology_map,
    parse_topology_map,
    is_loopback_host,
)
from .m1_builder import FlatClaimsDocument, FlatPeerClaim, build_from_document, build_m1_topology
from .m1_pipeline import (
    M1SystemExecution,
    collect_real_m1_measurements,
    generate_synthetic_m1_evidence,
    load_m1_witness_evidence,
    run_m1_pipeline,
)

__all__ = [
    "ClusterAdapter",
    "ClusterAdapterError",
    "ClusterPeer",
    "DesiredPlacementAction",
    "DryRunIPFSClusterAdapter",
    "InMemoryIPFSClusterAdapter",
    "LocalIPFSClusterReadOnlyClient",
    "M1AdapterError",
    "M1ExternalMetadata",
    "M1PeerRecord",
    "M1SystemExecution",
    "M1TopologySnapshot",
    "M1VerificationState",
    "FlatClaimsDocument",
    "FlatPeerClaim",
    "build_from_document",
    "build_m1_topology",
    "PinAllocation",
    "collect_real_m1_measurements",
    "generate_synthetic_m1_evidence",
    "is_loopback_host",
    "load_external_metadata",
    "load_m1_witness_evidence",
    "load_topology_map",
    "parse_topology_map",
    "run_m1_pipeline",
]
