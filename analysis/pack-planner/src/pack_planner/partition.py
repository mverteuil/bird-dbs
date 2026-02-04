"""Region partitioning algorithms for pack distribution."""

import logging
import random

import h3

logger = logging.getLogger(__name__)


# Custom regional boundaries (based on M49 Level 2 with modifications)
# https://unstats.un.org/unsd/methodology/m49/
# Updated 2025-10-23: Split 7 oversized regions per REGIONAL_SPLIT_VALIDATION.md
# Final count: 7 original oversized regions → 17 sub-regions
# All sub-regions target < 6.5M checklists (2x Caribbean baseline)
CONTINENTAL_BOUNDARIES = {
    # North America - Split into sub-regions with minimal overlap
    # Boundaries tightened iteratively to stay under 2x Caribbean (6.5M checklists)

    # New England (2.04x Caribbean - split into 2)
    "north-america-northern-new-england": {
        "lon": (-71, -66),  # ME, VT, NH (tight)
        "lat": (43.5, 47.5),
    },
    "north-america-southern-new-england": {
        "lon": (-73.5, -69.5),  # MA, RI, CT (tight, small overlap with NY)
        "lat": (41, 42.5),
    },

    # Mid-Atlantic (4.89x Caribbean - split into 3)
    "north-america-pennsylvania-west-virginia": {
        "lon": (-81, -76),  # PA, WV tighter core
        "lat": (39, 42),
    },
    "north-america-new-york": {
        "lon": (-79, -73.5),  # NY tighter core
        "lat": (41, 45),
    },
    "north-america-new-jersey-delaware-maryland": {
        "lon": (-76.5, -74),  # NJ, DE, MD tighter (reduce 0.5° west)
        "lat": (38, 41.5),  # Tighter south boundary
    },

    # Midwest (4.82x Caribbean - split into 3)
    "north-america-great-lakes": {
        "lon": (-92, -82),  # MI, WI core (unchanged, already under limit)
        "lat": (42, 48),
    },
    "north-america-ohio-valley": {
        "lon": (-88, -81.5),  # OH, IN core (tightened to reduce to ~5.5M)
        "lat": (38.5, 42),
    },
    "north-america-northern-plains": {
        "lon": (-102, -90),  # IA, MO, KS, NE (unchanged, already under limit)
        "lat": (38.5, 44),
    },

    # Southwest (3.52x Caribbean - split into 2)
    "north-america-southwest-interior": {
        "lon": (-112.5, -108.5),  # AZ, NV core (extremely tight)
        "lat": (32.5, 36.5),  # Extremely tight boundaries
    },
    "north-america-southern-plains": {
        "lon": (-106, -94),  # TX, OK (unchanged, already under limit)
        "lat": (26, 37),
    },

    # Southeast (2.87x Caribbean - split into 2)
    "north-america-atlantic-southeast": {
        "lon": (-84, -75),  # NC, SC, GA, FL Atlantic (unchanged, already under limit)
        "lat": (25, 36.5),
    },
    "north-america-gulf-coast": {
        "lon": (-92, -81),  # AL, MS, LA, FL Gulf (unchanged, already under limit)
        "lat": (26, 33),
    },

    # Northwest (2.54x Caribbean - split into 3)
    "north-america-pacific-coast": {
        "lon": (-124, -122.5),  # WA, OR very narrow coastal strip
        "lat": (42.5, 48.5),  # Tighter lat range
    },
    "north-america-inland-northwest": {
        "lon": (-122, -111),  # ID, MT, eastern WA/OR (interior)
        "lat": (42, 49),
    },
    "north-america-northern-canada": {
        "lon": (-141, -105),  # YT, NT, northern BC, AB, SK (reduced overlap)
        "lat": (53, 75),
    },

    # Central America (3.64x Caribbean - split into 2)
    "central-america-northern": {
        "lon": (-92, -86),  # Guatemala, Belize, Honduras, El Salvador (tighter)
        "lat": (13, 18),
    },
    "central-america-southern": {
        "lon": (-90, -77),  # Nicaragua, Costa Rica, Panama (reduced overlap)
        "lat": (7, 15),
    },

    # Other Americas (unchanged)
    "caribbean": {
        "lon": (-90, -60),
        "lat": (10, 28),
    },
    "south-america-north": {"lon": (-82, -34), "lat": (-5, 13)},
    "south-america-south": {"lon": (-82, -34), "lat": (-60, -5)},  # Exclude Antarctica
    # Europe (keep as-is)
    "northern-europe": {"lon": (-25, 32), "lat": (50, 82)},
    "western-europe": {"lon": (-10, 17), "lat": (42, 60)},
    "eastern-europe": {"lon": (17, 70), "lat": (44, 70)},
    "southern-europe": {"lon": (-10, 30), "lat": (35, 48)},
    # Africa (keep as-is)
    "northern-africa": {"lon": (-18, 52), "lat": (15, 38)},
    "western-africa": {"lon": (-18, 16), "lat": (4, 28)},
    "middle-africa": {"lon": (8, 32), "lat": (-13, 10)},
    "eastern-africa": {"lon": (22, 52), "lat": (-26, 18)},
    "southern-africa": {"lon": (10, 41), "lat": (-35, -15)},
    # Asia (add middle-east, fix northeast asia)
    "middle-east": {"lon": (34, 64), "lat": (12, 43)},  # Arabian Peninsula + Levant
    "western-asia": {"lon": (26, 46), "lat": (35, 43)},  # Turkey, Caucasus
    "central-asia": {"lon": (46, 88), "lat": (35, 56)},
    "southern-asia": {"lon": (60, 98), "lat": (5, 38)},
    "southeastern-asia": {"lon": (92, 141), "lat": (-11, 29)},
    "eastern-asia": {"lon": (73, 146), "lat": (18, 60)},  # Extended north to capture NE Asia
    "northeastern-asia": {"lon": (130, 180), "lat": (45, 75)},  # Far East Russia, NE China
    # Oceania
    "australia-new-zealand": {"lon": (110, 180), "lat": (-48, -10)},
    "melanesia": {"lon": (140, 180), "lat": (-22, 2)},
    "micronesia": {"lon": (130, 172), "lat": (-2, 21)},
    "polynesia": {"lon": (-180, -130), "lat": (-28, 25)},  # Includes Hawaii
    # Antarctica
    "antarctica": {"lon": (-180, 180), "lat": (-90, -60)},
}


class RegionPartitioner:
    """Partition packs into regions that fit within size constraints."""

    def __init__(
        self,
        max_size_mb: float = 250.0,
        min_checklists: int = 6000000,
        size_manifest: dict = None,
    ):
        """
        Initialize partitioner.

        Args:
            max_size_mb: Maximum size per region in MB (default: 250 for practical downloads)
            min_checklists: Minimum checklists per region (default: 6M for ~60 regions globally)
            size_manifest: Dict mapping boundary_cell -> size_mb from actual builds (required)
        """
        if size_manifest is None:
            raise ValueError(
                "size_manifest is required. Run build_packs_from_partitions.py first "
                "to generate actual size data, then create size manifest with "
                "scripts/create_size_manifest.py"
            )
        self.max_size_mb = max_size_mb
        self.min_checklists = min_checklists
        self.size_manifest = size_manifest

    def _get_pack_size(self, pack: dict) -> float:
        """Get size for a pack from the size manifest."""
        cell = pack.get("boundary_cell")
        if cell and cell in self.size_manifest:
            return self.size_manifest[cell]
        # Fallback for cells not in manifest (shouldn't happen with proper workflow)
        logger.warning("Cell %s not in size manifest, using default 0.5 MB", cell)
        return 0.5

    def _get_region_size(self, region: dict) -> float:
        """Calculate total size of a region from its packs."""
        return sum(self._get_pack_size(p) for p in region.get("packs", []))

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
            # Sort by pack count (merge smallest first)
            regions.sort(key=lambda r: r["pack_count"])

            for i, region_a in enumerate(regions):
                # Find adjacent regions to merge
                for j in range(i + 1, len(regions)):
                    region_b = regions[j]

                    if self._are_adjacent(region_a, region_b):
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

    def partition_continental(self, packs: list[dict]) -> list[dict]:
        """
        Partition packs using custom regional boundaries - one region pack per boundary.

        Strategy:
        1. Pre-group packs by custom regional boundaries (28 regions)
        2. Each boundary becomes ONE region pack (no density-based merging)
        3. Fill interior gaps (cells surrounded by region cells)
        4. Add border overlap (1-cell buffer with adjacent regions)
        5. Assign remaining cells to nearest region (global coverage)

        Args:
            packs: List of pack dictionaries with size and location info

        Returns:
            List of region dictionaries with continuous coverage and overlap
        """
        logger.info("Starting regional partition with custom boundaries...")

        # Step 1: Pre-group by custom regional boundaries
        regional_groups = self._group_by_continent(packs)

        logger.info(
            "Regional grouping: %s",
            {region: len(packs) for region, packs in regional_groups.items()},
        )

        # Step 2: Create one region pack per boundary (no merging)
        all_regions = []
        for region_name, region_packs in regional_groups.items():
            if not region_packs:
                continue

            logger.info(
                "Creating region pack: %s with %d populated cells", region_name, len(region_packs)
            )

            # Calculate center from all packs
            center_lat = sum(p["center_lat"] for p in region_packs) / len(region_packs)
            center_lon = sum(p["center_lon"] for p in region_packs) / len(region_packs)

            # Get all H3 cells from packs
            h3_cells = [p["boundary_cell"] for p in region_packs]

            region = {
                "h3_cells": h3_cells,
                "packs": region_packs,
                "size_mb": self._get_region_size({"packs": region_packs}),
                "pack_count": len(region_packs),
                "center": {"lat": center_lat, "lon": center_lon},
                "m49_region": region_name,
            }

            all_regions.append(region)

        logger.info("Created %d region packs from custom boundaries", len(all_regions))

        # Step 3: Split oversized regions based on actual size data
        all_regions = self._split_oversized_regions(all_regions)

        # Step 4: Fill interior gaps
        all_regions = self._fill_interior_gaps(all_regions)

        # Step 5: Add border overlap
        all_regions = self._add_border_overlap(all_regions)

        # Step 6: Global coverage (assign remaining cells)
        all_regions = self._ensure_global_coverage(all_regions)

        logger.info("Final: %d region packs with continuous coverage and overlap", len(all_regions))

        return all_regions

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
                    "size_mb": -1,  # Placeholder - actual size set by ebird-builder
                    "pack_count": 0,
                    "center": {"lat": lat, "lon": lng},
                }

            regions[parent]["packs"].append(pack)
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
            "size_mb": -1,  # Placeholder - actual size set by ebird-builder
            "pack_count": region_a["pack_count"] + region_b["pack_count"],
            "center": {"lat": new_center_lat, "lon": new_center_lon},
        }

    def _group_by_continent(self, packs: list[dict]) -> dict[str, list[dict]]:
        """Group packs by continent based on geographic location."""
        continental_groups = {continent: [] for continent in CONTINENTAL_BOUNDARIES}

        for pack in packs:
            lat = pack["center_lat"]
            lon = pack["center_lon"]

            # Find all regions this pack could belong to
            matching_regions = []
            for continent, bounds in CONTINENTAL_BOUNDARIES.items():
                lon_min, lon_max = bounds["lon"]
                lat_min, lat_max = bounds["lat"]

                if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
                    matching_regions.append(continent)

            if matching_regions:
                # Assign to ALL matching regions (cells can belong to multiple regions)
                for region in matching_regions:
                    continental_groups[region].append(pack)
            else:
                # Assign to nearest region by geographic distance
                nearest_region = min(
                    CONTINENTAL_BOUNDARIES.keys(),
                    key=lambda region: (
                        (
                            (
                                CONTINENTAL_BOUNDARIES[region]["lat"][0]
                                + CONTINENTAL_BOUNDARIES[region]["lat"][1]
                            )
                            / 2
                            - lat
                        )
                        ** 2
                        + (
                            (
                                CONTINENTAL_BOUNDARIES[region]["lon"][0]
                                + CONTINENTAL_BOUNDARIES[region]["lon"][1]
                            )
                            / 2
                            - lon
                        )
                        ** 2
                    )
                    ** 0.5,
                )
                continental_groups[nearest_region].append(pack)
                logger.debug(
                    "Assigned orphaned cell at (%.2f, %.2f) to nearest region: %s",
                    lat,
                    lon,
                    nearest_region,
                )

        # Remove empty continents
        return {cont: packs for cont, packs in continental_groups.items() if packs}

    def _merge_by_density(self, regions: list[dict], min_checklists: int) -> list[dict]:
        """Merge adjacent regions until each has minimum checklists."""
        changed = True
        merge_count = 0

        while changed:
            changed = False

            # Find regions below threshold
            small_regions = [
                r
                for r in regions
                if sum(p.get("total_checklists", 0) for p in r["packs"]) < min_checklists
            ]

            if not small_regions:
                break

            # Sort by size (merge smallest first)
            small_regions.sort(key=lambda r: sum(p.get("total_checklists", 0) for p in r["packs"]))

            for region_a in small_regions:
                # Find nearest adjacent region
                best_neighbor = None
                best_checklists = 0

                for region_b in regions:
                    if region_b is region_a:
                        continue

                    if self._are_adjacent(region_a, region_b):
                        checklists = sum(p.get("total_checklists", 0) for p in region_b["packs"])
                        if checklists > best_checklists:
                            best_neighbor = region_b
                            best_checklists = checklists

                if best_neighbor:
                    # Merge with best neighbor
                    merged = self._merge_regions(region_a, best_neighbor)

                    # Remove old regions, add merged
                    regions = [r for r in regions if r not in [region_a, best_neighbor]]
                    regions.append(merged)

                    changed = True
                    merge_count += 1
                    break

        logger.info("Density-based merges: %d", merge_count)
        return regions

    def _split_oversized_regions(self, regions: list[dict]) -> list[dict]:
        """
        Split regions that exceed max_size_mb into smaller sub-regions.

        Uses geographic clustering (latitude bands) to split large regions
        while maintaining spatial locality.
        """
        logger.info(
            "Splitting oversized regions (max %.0f MB)...", self.max_size_mb
        )

        result = []
        split_count = 0

        for region in regions:
            region_size = self._get_region_size(region)
            region_name = region.get("m49_region", "unknown")

            if region_size <= self.max_size_mb:
                # Region fits, keep as-is
                region["size_mb"] = region_size
                result.append(region)
                continue

            # Need to split this region
            num_splits = max(2, int(region_size / self.max_size_mb) + 1)
            logger.info(
                "Splitting %s (%.0f MB) into %d sub-regions",
                region_name, region_size, num_splits
            )

            # Sort packs by latitude for geographic clustering
            packs = sorted(region["packs"], key=lambda p: p["center_lat"])

            # Split into roughly equal-sized chunks by accumulated size
            target_size = region_size / num_splits
            sub_regions = []
            current_packs = []
            current_size = 0
            sub_index = 1

            for pack in packs:
                pack_size = self._get_pack_size(pack)
                current_packs.append(pack)
                current_size += pack_size

                # Start new sub-region when we exceed target (except for last)
                if current_size >= target_size and len(sub_regions) < num_splits - 1:
                    sub_region = self._create_sub_region(
                        current_packs, region_name, sub_index
                    )
                    sub_regions.append(sub_region)
                    sub_index += 1
                    current_packs = []
                    current_size = 0

            # Add remaining packs to final sub-region
            if current_packs:
                sub_region = self._create_sub_region(
                    current_packs, region_name, sub_index
                )
                sub_regions.append(sub_region)

            result.extend(sub_regions)
            split_count += len(sub_regions) - 1

        logger.info(
            "Split %d regions, total now: %d", split_count, len(result)
        )
        return result

    def _create_sub_region(
        self, packs: list[dict], parent_name: str, index: int
    ) -> dict:
        """Create a sub-region from a list of packs."""
        center_lat = sum(p["center_lat"] for p in packs) / len(packs)
        center_lon = sum(p["center_lon"] for p in packs) / len(packs)
        h3_cells = [p["boundary_cell"] for p in packs]
        size_mb = sum(self._get_pack_size(p) for p in packs)

        return {
            "h3_cells": h3_cells,
            "packs": packs,
            "size_mb": size_mb,
            "pack_count": len(packs),
            "center": {"lat": center_lat, "lon": center_lon},
            "m49_region": f"{parent_name}-{index}",
        }

    def _fill_interior_gaps(self, regions: list[dict]) -> list[dict]:
        """
        Fill interior gaps - add cells that are completely surrounded by region cells.

        This ensures continuous coverage within region boundaries.
        """
        logger.info("Filling interior gaps...")

        for region in regions:
            # Get all cells in this region
            region_cells = set(region["h3_cells"])

            # Find cells surrounded by region cells
            cells_to_add = set()

            for cell in region_cells:
                # Get all neighbors
                neighbors = set(h3.grid_disk(cell, 1))  # Returns cell + immediate neighbors

                # Check each neighbor
                for neighbor in neighbors:
                    if neighbor in region_cells:
                        continue  # Already in region

                    # Check if this neighbor is surrounded by region cells
                    neighbor_neighbors = set(h3.grid_disk(neighbor, 1))

                    # If all neighbors of the neighbor are in the region, it's surrounded
                    if neighbor_neighbors.issubset(region_cells | {neighbor}):
                        cells_to_add.add(neighbor)

            if cells_to_add:
                logger.debug("Adding %d interior gap cells to region", len(cells_to_add))
                region["h3_cells"].extend(list(cells_to_add))

        return regions

    def _add_border_overlap(self, regions: list[dict]) -> list[dict]:
        """
        Add 1-cell overlap at borders between adjacent regions.

        This ensures users at borders have seamless coverage.
        """
        logger.info("Adding border overlap...")

        # Build adjacency map
        for i, region_a in enumerate(regions):
            region_a_cells = set(region_a["h3_cells"])
            overlap_cells = set()

            # Check all other regions for adjacency
            for j, region_b in enumerate(regions):
                if i == j:
                    continue

                region_b_cells = set(region_b["h3_cells"])

                # Find cells in region_b that are adjacent to region_a
                for cell_b in region_b_cells:
                    neighbors = set(h3.grid_disk(cell_b, 1))

                    # If any neighbor is in region_a, this cell is on the border
                    if neighbors & region_a_cells:
                        overlap_cells.add(cell_b)

            if overlap_cells:
                logger.debug("Adding %d overlap cells to region", len(overlap_cells))
                region_a["h3_cells"].extend(list(overlap_cells))

        return regions

    def _ensure_global_coverage(self, regions: list[dict]) -> list[dict]:
        """
        Assign all remaining res-2 cells to nearest region.

        This ensures every location on Earth has a region match.
        """
        logger.info("Ensuring global coverage...")

        # Get all res-2 cells claimed by regions
        claimed_cells = set()
        for region in regions:
            claimed_cells.update(region["h3_cells"])

        # Get all possible res-2 cells globally
        all_res2_cells = set()
        res0_cells = h3.get_res0_cells()
        for res0_cell in res0_cells:
            children = h3.cell_to_children(res0_cell, 2)
            all_res2_cells.update(children)

        # Find unclaimed cells
        unclaimed = all_res2_cells - claimed_cells

        if not unclaimed:
            logger.info("Complete res-2 coverage already achieved")
            return regions

        logger.info(
            "Found %d unclaimed res-2 cells, assigning to nearest regions...", len(unclaimed)
        )

        # Assign each unclaimed cell to nearest region by geographic distance
        for cell in unclaimed:
            cell_lat, cell_lng = h3.cell_to_latlng(cell)

            # Find nearest region by center distance
            nearest_region = min(
                regions,
                key=lambda r: (
                    (r["center"]["lat"] - cell_lat) ** 2 + (r["center"]["lon"] - cell_lng) ** 2
                )
                ** 0.5,
            )

            nearest_region["h3_cells"].append(cell)

        # Log coverage statistics
        total_cells_per_region = [len(r["h3_cells"]) for r in regions]
        logger.info(
            "Coverage complete: %d regions covering all %d res-2 cells (avg %.1f cells/region)",
            len(regions),
            len(all_res2_cells),
            sum(total_cells_per_region) / len(regions),
        )

        return regions
