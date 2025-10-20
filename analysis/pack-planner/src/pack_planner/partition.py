"""Region partitioning algorithms for pack distribution."""

import json
import logging
from pathlib import Path

import h3

logger = logging.getLogger(__name__)


class RegionPartitioner:
    """Partition packs into regions based on observation density."""

    def __init__(self, min_checklists_per_region: int = 6000000):
        """
        Initialize partitioner.

        Args:
            min_checklists_per_region: Minimum checklists per region (default: 6,000,000)
        """
        self.min_checklists_per_region = min_checklists_per_region

    def partition(self, packs: list[dict]) -> list[dict]:
        """
        Partition packs using observation density-based grouping.

        Strategy:
        1. Group by H3 res 2 parent cells
        2. Aggressively merge regions below minimum threshold
        3. Force small regions to merge with neighbors

        Args:
            packs: List of pack dictionaries with checklist counts

        Returns:
            List of region dictionaries
        """
        logger.info("Starting density-based partition...")

        # Step 1: Group by H3 res 2 parent cells
        regions = self._group_by_parent(packs, resolution=2)

        logger.info("Initial grouping: %d regions", len(regions))

        # Step 2: Force merging of regions below minimum threshold
        changed = True
        merge_count = 0

        while changed:
            changed = False

            # Find regions below minimum threshold
            small_regions = [
                r for r in regions if r["total_checklists"] < self.min_checklists_per_region
            ]

            if not small_regions:
                break  # All regions meet minimum

            # Sort small regions by size (smallest first for aggressive merging)
            small_regions.sort(key=lambda r: r["total_checklists"])

            for region_a in small_regions:
                # Find smallest adjacent neighbor
                best_neighbor = None
                best_size = float("inf")

                for region_b in regions:
                    if region_b is region_a:
                        continue

                    if self._are_adjacent(region_a, region_b):
                        if region_b["total_checklists"] < best_size:
                            best_neighbor = region_b
                            best_size = region_b["total_checklists"]

                if best_neighbor:
                    # Merge with smallest neighbor
                    merged = self._merge_regions(region_a, best_neighbor)

                    # Remove old regions, add merged
                    regions = [r for r in regions if r not in [region_a, best_neighbor]]
                    regions.append(merged)

                    changed = True
                    merge_count += 1
                    break  # Restart to re-evaluate

        logger.info("Completed %d merges, final regions: %d", merge_count, len(regions))

        return regions

    def _group_by_parent(self, packs: list[dict], resolution: int) -> list[dict]:
        """Group packs by H3 parent cell at given resolution."""
        regions = {}

        for pack in packs:
            # Get parent cell
            cell = pack["boundary_cell"]
            parent = h3.cell_to_parent(cell, resolution)

            if parent not in regions:
                lat, lng = h3.cell_to_latlng(parent)
                regions[parent] = {
                    "h3_cells": [parent],
                    "packs": [],
                    "total_checklists": 0,
                    "pack_count": 0,
                    "center": {"lat": lat, "lon": lng},
                }

            regions[parent]["packs"].append(pack)
            regions[parent]["total_checklists"] += pack.get("total_checklists", 0)
            regions[parent]["pack_count"] += 1

        return list(regions.values())

    def _are_adjacent(self, region_a: dict, region_b: dict) -> bool:
        """Check if two regions are adjacent (share H3 cell neighbors)."""
        for cell_a in region_a["h3_cells"]:
            for cell_b in region_b["h3_cells"]:
                if h3.are_neighbor_cells(cell_a, cell_b):
                    return True

        return False

    def _merge_regions(self, region_a: dict, region_b: dict) -> dict:
        """Merge two regions into one."""
        # Calculate new center (weighted by checklist count)
        total_checklists = region_a["total_checklists"] + region_b["total_checklists"]

        if total_checklists > 0:
            new_center_lat = (
                region_a["center"]["lat"] * region_a["total_checklists"]
                + region_b["center"]["lat"] * region_b["total_checklists"]
            ) / total_checklists

            new_center_lon = (
                region_a["center"]["lon"] * region_a["total_checklists"]
                + region_b["center"]["lon"] * region_b["total_checklists"]
            ) / total_checklists
        else:
            # Fallback to simple average if no checklists
            new_center_lat = (region_a["center"]["lat"] + region_b["center"]["lat"]) / 2
            new_center_lon = (region_a["center"]["lon"] + region_b["center"]["lon"]) / 2

        return {
            "h3_cells": region_a["h3_cells"] + region_b["h3_cells"],
            "packs": region_a["packs"] + region_b["packs"],
            "total_checklists": total_checklists,
            "pack_count": region_a["pack_count"] + region_b["pack_count"],
            "center": {"lat": new_center_lat, "lon": new_center_lon},
        }
