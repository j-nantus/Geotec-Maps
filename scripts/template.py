"""National bore / lithology CSV template field order."""

from __future__ import annotations

BORE_FIELDS = [
    "key",
    "region_id",
    "jurisdiction",
    "bore_id",
    "dataset",
    "lat",
    "lon",
    "depth_m",
    "drilled",
    "use",
    "position_accuracy",
    "driller",
    "source_url",
    "parish",
    "has_log",
]

LITHOLOGY_FIELDS = [
    "key",
    "log_source",
    "depth_from_m",
    "depth_to_m",
    "description",
]
