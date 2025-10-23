"""Region partitioning algorithms for pack distribution."""

import logging
import random

import h3

logger = logging.getLogger(__name__)


class RegionPartitioner:
    """Partition packs into regions that fit within size constraints."""

    def __init__(self, max_size_mb: float = 1950.0):
        """
        Initialize partitioner.

        Args:
            max_size_mb: Maximum size per region in MB (default: 1950 = 2GB - 50MB buffer)
        """
        self.max_size_mb = max_size_mb

    def partition_greedy(self, packs: list[dict]) -> list[dict]:
        """
        Partition packs using greedy merge algorithm.

        Start with H3 res 2 grouping, then greedily merge adjacent regions.

        Args:
            packs: List of pack dictionaries with size and location info

        Returns:
            List of region dictionaries
        """
        logger.info("Starting greedy partition...")

        # Step 1: Group by H3 res 2 parent cells
        regions = self._group_by_parent(packs, resolution=2)

        logger.info("Initial grouping: %d regions", len(regions))

        # Step 2: Greedy merge
        changed = True
        merge_count = 0

        while changed:
            changed = False
            # Sort by size (merge smallest first)
            regions.sort(key=lambda r: r["size_mb"])

            for i, region_a in enumerate(regions):
                # Find adjacent regions that fit when merged
                for j in range(i + 1, len(regions)):
                    region_b = regions[j]

                    if self._are_adjacent(region_a, region_b) and (
                        region_a["size_mb"] + region_b["size_mb"] <= self.max_size_mb
                    ):
                        # Merge them
                        merged = self._merge_regions(region_a, region_b)

                        # Remove old regions, add merged
                        regions = [r for r in regions if r not in [region_a, region_b]]
                        regions.append(merged)

                        changed = True
                        merge_count += 1
                        break

                if changed:
                    break

        logger.info("Completed %d merges, final regions: %d", merge_count, len(regions))

        return regions

    def partition_monte_carlo(self, packs: list[dict], iterations: int = 100) -> list[dict]:
        """
        Partition packs using Monte Carlo optimization.

        Try multiple random merge orders and pick the one with fewest regions.

        Args:
            packs: List of pack dictionaries
            iterations: Number of random iterations

        Returns:
            Best partition found
        """
        logger.info("Starting Monte Carlo partition with %d iterations...", iterations)

        best_partition = None
        best_score = float("inf")

        for i in range(iterations):
            # Randomize merge order by shuffling packs
            shuffled = packs.copy()
            random.shuffle(shuffled)

            # Run greedy on shuffled input
            partition = self.partition_greedy(shuffled)

            # Score: fewer regions = better
            score = len(partition)

            if score < best_score:
                best_score = score
                best_partition = partition
                logger.debug("Iteration %d: New best score %d regions", i, score)

        logger.info("Best partition: %d regions", len(best_partition))

        return best_partition

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
                    "size_mb": 0.0,
                    "pack_count": 0,
                    "center": {"lat": lat, "lon": lng},
                }

            regions[parent]["packs"].append(pack)
            regions[parent]["size_mb"] += pack["estimated_size_mb"]
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
        # Calculate new center (weighted by pack count)
        total_packs = region_a["pack_count"] + region_b["pack_count"]

        new_center_lat = (
            region_a["center"]["lat"] * region_a["pack_count"]
            + region_b["center"]["lat"] * region_b["pack_count"]
        ) / total_packs

        new_center_lon = (
            region_a["center"]["lon"] * region_a["pack_count"]
            + region_b["center"]["lon"] * region_b["pack_count"]
        ) / total_packs

        return {
            "h3_cells": region_a["h3_cells"] + region_b["h3_cells"],
            "packs": region_a["packs"] + region_b["packs"],
            "size_mb": region_a["size_mb"] + region_b["size_mb"],
            "pack_count": region_a["pack_count"] + region_b["pack_count"],
            "center": {"lat": new_center_lat, "lon": new_center_lon},
        }
