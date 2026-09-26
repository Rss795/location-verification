"""Safe IPFS Cluster boundary: read-only inventory and desired-state plans only.

No implementation in this module writes pins, moves data, or issues HTTP requests
other than GET. The live client is restricted to a configured loopback endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
from types import MappingProxyType
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from ..placement.models import PlacementResult


class ClusterAdapterError(RuntimeError):
    """Unavailable or malformed local Cluster API response."""


class _NoRedirectHandler(HTTPRedirectHandler):
    """Do not let a loopback API response redirect requests off loopback."""

    def redirect_request(self, req, fp, code, msg, headers, new_url):
        return None


_NO_REDIRECT_OPENER = build_opener(ProxyHandler({}), _NoRedirectHandler)


def urlopen(request: Request, timeout: float):
    """Open a request without urllib's default automatic redirect handling."""

    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)


@dataclass(frozen=True, slots=True)
class ClusterPeer:
    peer_id: str

    def __post_init__(self) -> None:
        if not self.peer_id.strip():
            raise ValueError("peer_id must not be empty")


@dataclass(frozen=True, slots=True)
class PinAllocation:
    content_id: str
    peer_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.content_id.strip():
            raise ValueError("content_id must not be empty")


@dataclass(frozen=True, slots=True)
class DesiredPlacementAction:
    """A proposed diff for inspection; it is never submitted to Cluster."""

    content_id: str
    current_peer_ids: tuple[str, ...]
    desired_peer_ids: tuple[str, ...]
    add_peer_ids: tuple[str, ...]
    remove_peer_ids: tuple[str, ...]
    dry_run: bool = True
    operation: str = "REPRESENT_DESIRED_PLACEMENT_ONLY"


class ClusterAdapter(Protocol):
    """Read-only Cluster discovery and placement-diff representation interface."""

    def discover_peers(self) -> tuple[ClusterPeer, ...]: ...

    def get_pin_allocations(self, content_id: str) -> PinAllocation | None: ...

    def represent_desired_placement(
        self,
        content_id: str,
        placement: PlacementResult,
    ) -> DesiredPlacementAction: ...


class InMemoryIPFSClusterAdapter:
    """Deterministic mock adapter; reads fixture state and never mutates it."""

    def __init__(
        self,
        peers: tuple[ClusterPeer, ...] | list[ClusterPeer] = (),
        allocations: Mapping[str, PinAllocation] | None = None,
    ) -> None:
        peer_ids = [peer.peer_id for peer in peers]
        if len(peer_ids) != len(set(peer_ids)):
            raise ValueError("cluster peer IDs must be unique")
        self._peers = tuple(sorted(peers, key=lambda peer: peer.peer_id))
        self._allocations = MappingProxyType(dict(allocations or {}))
        unknown_allocation_peers = {
            peer_id
            for allocation in self._allocations.values()
            for peer_id in allocation.peer_ids
            if peer_id not in set(peer_ids)
        }
        if unknown_allocation_peers:
            raise ValueError("pin allocation refers to an unknown cluster peer")

    def discover_peers(self) -> tuple[ClusterPeer, ...]:
        return self._peers

    def get_pin_allocations(self, content_id: str) -> PinAllocation | None:
        if not content_id.strip():
            raise ValueError("content_id must not be empty")
        return self._allocations.get(content_id)

    def represent_desired_placement(
        self,
        content_id: str,
        placement: PlacementResult,
    ) -> DesiredPlacementAction:
        if not content_id.strip():
            raise ValueError("content_id must not be empty")
        discovered = {peer.peer_id for peer in self._peers}
        desired = tuple(item.peer_id for item in placement.selected_peers)
        unknown = set(desired) - discovered
        if unknown:
            raise ValueError(f"placement includes peers not discovered in cluster: {sorted(unknown)}")
        allocation = self.get_pin_allocations(content_id)
        current = allocation.peer_ids if allocation else ()
        return DesiredPlacementAction(
            content_id=content_id,
            current_peer_ids=current,
            desired_peer_ids=desired,
            add_peer_ids=tuple(sorted(set(desired) - set(current))),
            remove_peer_ids=tuple(sorted(set(current) - set(desired))),
            dry_run=True,
        )


class DryRunIPFSClusterAdapter(InMemoryIPFSClusterAdapter):
    """Named default adapter for local demos; all operations are fixture-only."""


class LocalIPFSClusterReadOnlyClient:
    """Optional loopback-only HTTP client that performs safe Cluster GET requests."""

    def __init__(self, base_url: str, request_timeout_seconds: float = 2.0) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be an HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("credentials must not be embedded in base_url")
        hostname = parsed.hostname.lower()
        loopback = hostname == "localhost"
        if not loopback:
            try:
                loopback = ipaddress.ip_address(hostname).is_loopback
            except ValueError:
                loopback = False
        if not loopback:
            raise ValueError("Cluster HTTP client only permits localhost/loopback URLs")
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        self.base_url = base_url.rstrip("/")
        self.request_timeout_seconds = request_timeout_seconds

    def _get_json(self, path: str) -> object:
        request = Request(f"{self.base_url}{path}", method="GET", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.request_timeout_seconds) as response:
                if response.status < 200 or response.status >= 300:
                    raise ClusterAdapterError(f"Cluster returned HTTP status {response.status}")
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ClusterAdapterError(f"local IPFS Cluster GET failed: {exc}") from exc

    @staticmethod
    def _peer_id(item: object) -> str:
        if not isinstance(item, dict):
            raise ClusterAdapterError("Cluster peer response entries must be objects")
        peer_id = item.get("id", item.get("peer_id"))
        if not isinstance(peer_id, str) or not peer_id.strip():
            raise ClusterAdapterError("Cluster peer response is missing a valid peer ID")
        return peer_id

    def discover_peers(self) -> tuple[ClusterPeer, ...]:
        payload = self._get_json("/peers")
        entries = payload.get("peers") if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            raise ClusterAdapterError("Cluster /peers response must be a list or contain a peers list")
        peers = tuple(sorted((ClusterPeer(self._peer_id(item)) for item in entries), key=lambda peer: peer.peer_id))
        if len({peer.peer_id for peer in peers}) != len(peers):
            raise ClusterAdapterError("Cluster /peers returned duplicate peer IDs")
        return peers

    def get_pin_allocations(self, content_id: str) -> PinAllocation | None:
        if not content_id.strip():
            raise ValueError("content_id must not be empty")
        payload = self._get_json(f"/pins/{quote(content_id, safe='')}")
        if not isinstance(payload, dict):
            raise ClusterAdapterError("Cluster pin response must be an object")
        allocations = payload.get("allocations", [])
        if not isinstance(allocations, list):
            raise ClusterAdapterError("Cluster pin allocations must be a list")
        peer_ids: list[str] = []
        for item in allocations:
            if isinstance(item, str) and item.strip():
                peer_ids.append(item)
            else:
                peer_ids.append(self._peer_id(item))
        return PinAllocation(content_id, tuple(sorted(set(peer_ids))))

    def represent_desired_placement(
        self,
        content_id: str,
        placement: PlacementResult,
    ) -> DesiredPlacementAction:
        discovered = {peer.peer_id for peer in self.discover_peers()}
        desired = tuple(item.peer_id for item in placement.selected_peers)
        unknown = set(desired) - discovered
        if unknown:
            raise ValueError(f"placement includes peers not discovered in cluster: {sorted(unknown)}")
        allocation = self.get_pin_allocations(content_id)
        current = allocation.peer_ids if allocation else ()
        return DesiredPlacementAction(
            content_id,
            current,
            desired,
            tuple(sorted(set(desired) - set(current))),
            tuple(sorted(set(current) - set(desired))),
            dry_run=True,
        )
