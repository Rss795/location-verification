"""Great-circle distance using the Haversine formula."""

from __future__ import annotations

import math

from ..models import GeoLocation

EARTH_MEAN_RADIUS_KM = 6371.0088
"""IUGG mean Earth radius used for deterministic spherical distance estimates."""


def haversine_distance_km(origin: GeoLocation, destination: GeoLocation) -> float:
    """Return great-circle surface distance; this is geometry, not claim validation."""

    lat1 = math.radians(origin.latitude)
    lat2 = math.radians(destination.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(destination.longitude - origin.longitude)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    central_angle = 2 * math.atan2(math.sqrt(haversine), math.sqrt(max(0.0, 1 - haversine)))
    return EARTH_MEAN_RADIUS_KM * central_angle
