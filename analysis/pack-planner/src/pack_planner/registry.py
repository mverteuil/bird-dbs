"""Registry builder for pack distribution metadata."""

import logging
from datetime import datetime

import h3

logger = logging.getLogger(__name__)


class RegistryBuilder:
    """Build pack registry for client lookups."""

    def build_registry(self, regions: list[dict]) -> dict:
        """
        Build pack registry from regions.

        Args:
            regions: List of region dictionaries

        Returns:
            Registry dictionary with version, regions, and metadata
        """
        logger.info("Building pack registry for %d regions", len(regions))

        total_packs = sum(r["pack_count"] for r in regions)

        registry_regions = []

        for region in regions:
            # Calculate bounding box
            bbox = self._calculate_bbox(region["packs"])

            registry_region = {
                "region_id": region["region_id"],
                "h3_cells": region["h3_cells"],
                "resolution": h3.get_resolution(region["h3_cells"][0]),
                "release_name": region["release_name"],
                "total_size_mb": -1,  # Placeholder - actual size set by ebird-builder
                "pack_count": region["pack_count"],
                "center": region["center"],
                "bbox": bbox,
            }

            registry_regions.append(registry_region)

        registry = {
            "version": "2025.08",  # CalVer placeholder
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_regions": len(regions),
            "total_packs": total_packs,
            "regions": registry_regions,
        }

        return registry

    def _calculate_bbox(self, packs: list[dict]) -> dict:
        """Calculate bounding box from pack locations."""
        lats = [p["center_lat"] for p in packs]
        lons = [p["center_lon"] for p in packs]

        return {
            "min_lat": min(lats),
            "max_lat": max(lats),
            "min_lon": min(lons),
            "max_lon": max(lons),
        }
