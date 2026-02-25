"""Build region packs from pre-partitioned eBird data.

Each region produces ONE SQLite pack containing data for all boundary cells
in that region, with multi-resolution fallback.
"""

import datetime
import json
import os
import sqlite3
import time
from pathlib import Path

import duckdb
import h3

from ebd_pack_builder.models.config import (
    DATA_RESOLUTIONS,
    RESOLUTION_PENALTIES,
    TIER_BOOSTS,
    TIER_THRESHOLDS,
)
from ebd_pack_builder.utils.formatting import format_duration, format_size


def create_schema(conn: sqlite3.Connection) -> None:
    """Create pack schema with multi-resolution support."""
    conn.executescript(
        """
        -- Main species presence table with resolution for fallback queries
        CREATE TABLE grid_species (
            h3_cell INTEGER NOT NULL,
            resolution INTEGER NOT NULL,
            avibase_id TEXT NOT NULL,
            confidence_tier TEXT NOT NULL,
            confidence_boost REAL NOT NULL,
            yearly_frequency REAL NOT NULL,
            quality_score REAL NOT NULL DEFAULT 0.5,
            PRIMARY KEY (h3_cell, resolution, avibase_id)
        );

        -- Monthly frequency data with resolution
        CREATE TABLE grid_species_monthly (
            h3_cell INTEGER NOT NULL,
            resolution INTEGER NOT NULL,
            avibase_id TEXT NOT NULL,
            month INTEGER NOT NULL,
            frequency REAL NOT NULL,
            checklist_count INTEGER NOT NULL,
            PRIMARY KEY (h3_cell, resolution, avibase_id, month)
        );

        -- Species lookup (resolution-independent)
        CREATE TABLE species_lookup (
            avibase_id TEXT PRIMARY KEY,
            scientific_name TEXT NOT NULL,
            common_name TEXT
        );

        -- Pack metadata
        CREATE TABLE pack_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """
    )
    conn.commit()


def compute_frequency_at_resolution(
    ddb: duckdb.DuckDBPyConnection,
    file_list: str,
    resolution: int,
) -> list:
    """Compute species frequency data at a specific H3 resolution."""
    query = f"""
        WITH cell_data AS (
            SELECT
                h3_latlng_to_cell(
                    CAST("LATITUDE" AS DOUBLE),
                    CAST("LONGITUDE" AS DOUBLE),
                    {resolution}
                ) as h3_cell,
                "TAXON CONCEPT ID" as avibase_id,
                "SCIENTIFIC NAME" as scientific_name,
                CAST(SUBSTR("OBSERVATION DATE", 6, 2) AS INTEGER) as month,
                "SAMPLING EVENT IDENTIFIER" as checklist_id
            FROM read_parquet({file_list})
            WHERE "TAXON CONCEPT ID" IS NOT NULL
                AND "OBSERVATION DATE" IS NOT NULL
        ),
        cell_month_totals AS (
            SELECT h3_cell, month, COUNT(DISTINCT checklist_id) as total_checklists
            FROM cell_data
            GROUP BY h3_cell, month
        ),
        species_counts AS (
            SELECT h3_cell, avibase_id, scientific_name, month,
                   COUNT(DISTINCT checklist_id) as species_checklists
            FROM cell_data
            GROUP BY h3_cell, avibase_id, scientific_name, month
        )
        SELECT
            sc.h3_cell, sc.avibase_id, sc.scientific_name, sc.month,
            sc.species_checklists, cmt.total_checklists,
            sc.species_checklists::DOUBLE / cmt.total_checklists::DOUBLE as frequency
        FROM species_counts sc
        JOIN cell_month_totals cmt ON sc.h3_cell = cmt.h3_cell AND sc.month = cmt.month
    """
    return ddb.execute(query).fetchall()


def build_single_region_pack(
    region: dict,
    partitioned_dir: Path,
    output_dir: Path,
) -> dict | None:
    """Build a single region pack containing all cells in the region.

    Args:
        region: Region definition dict with region_id, center, packs
        partitioned_dir: Directory with partitioned data
        output_dir: Output directory for pack database

    Returns:
        Build result dict or None if no data
    """
    region_id = region["region_id"]
    center = region.get("center", {"lat": 0, "lon": 0})
    packs = region.get("packs", [])

    if not packs:
        return None

    # Get all boundary cells in this region
    boundary_cells = [p["boundary_cell"] for p in packs if p.get("boundary_cell")]

    # Collect all parquet files from all partition directories
    all_parquet_files: list[Path] = []
    missing_partitions = []

    for cell in boundary_cells:
        partition_dir = partitioned_dir / f"boundary_cell={cell}"
        if partition_dir.exists():
            files = [f for f in partition_dir.glob("*.parquet") if not f.name.startswith("._")]
            all_parquet_files.extend(files)
        else:
            missing_partitions.append(cell)

    if not all_parquet_files:
        print(f"  Warning: No parquet files found for region {region_id}")
        return None

    if missing_partitions:
        print(f"  Warning: {len(missing_partitions)} partitions missing for region {region_id}")

    file_list = "[" + ", ".join(f"'{f}'" for f in all_parquet_files) + "]"

    # Initialize DuckDB
    ddb = duckdb.connect()
    ddb.execute("INSTALL h3 FROM community; LOAD h3")

    # Collect data at all resolutions
    all_monthly: list[tuple] = []
    all_grid_species: list[tuple] = []
    species_names: dict[str, str] = {}
    cells_by_resolution: dict[int, set] = {res: set() for res in DATA_RESOLUTIONS}

    for resolution in DATA_RESOLUTIONS:
        print(f"    Processing resolution {resolution}...")
        result = compute_frequency_at_resolution(ddb, file_list, resolution)

        if not result:
            continue

        # Process data for this resolution
        cell_species_data: dict[tuple, dict] = {}

        for (
            h3_cell,
            avibase_id,
            scientific_name,
            month,
            species_count,
            _total_count,
            frequency,
        ) in result:
            key = (h3_cell, avibase_id)
            cells_by_resolution[resolution].add(h3_cell)

            if key not in cell_species_data:
                cell_species_data[key] = {"months": {}, "name": scientific_name}

            cell_species_data[key]["months"][month] = {
                "freq": frequency,
                "count": species_count,
            }

            if avibase_id not in species_names:
                species_names[avibase_id] = scientific_name

        # Build tables for this resolution
        resolution_penalty = RESOLUTION_PENALTIES.get(resolution, 1.0)

        for (h3_cell, avibase_id), data in cell_species_data.items():
            freqs = []
            total_count = 0

            for month, md in data["months"].items():
                all_monthly.append(
                    (h3_cell, resolution, avibase_id, month, md["freq"], md["count"])
                )
                freqs.append(md["freq"])
                total_count += md["count"]

            avg_freq = sum(freqs) / len(freqs)

            # Determine tier from frequency
            if avg_freq >= TIER_THRESHOLDS["common"]:
                tier = "common"
            elif avg_freq >= TIER_THRESHOLDS["uncommon"]:
                tier = "uncommon"
            elif avg_freq >= TIER_THRESHOLDS["rare"]:
                tier = "rare"
            else:
                tier = "vagrant"

            # Apply resolution penalty to boost
            base_boost = TIER_BOOSTS[tier]
            penalized_boost = base_boost * resolution_penalty

            quality = min(1.0, total_count / 100)
            all_grid_species.append(
                (h3_cell, resolution, avibase_id, tier, penalized_boost, avg_freq, quality)
            )

    ddb.close()

    if not all_grid_species:
        return None

    species = [(aid, name, None) for aid, name in species_names.items()]

    # Create database
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{region_id}.db"

    if output_path.exists():
        output_path.unlink()

    conn = sqlite3.connect(output_path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")

    create_schema(conn)

    # Batch insert for performance
    print(f"    Inserting {len(all_grid_species):,} grid_species rows...")
    conn.executemany("INSERT INTO grid_species VALUES (?,?,?,?,?,?,?)", all_grid_species)

    print(f"    Inserting {len(all_monthly):,} monthly rows...")
    conn.executemany("INSERT INTO grid_species_monthly VALUES (?,?,?,?,?,?)", all_monthly)

    conn.executemany("INSERT INTO species_lookup VALUES (?,?,?)", species)

    # Metadata
    metadata = [
        ("region_id", region_id),
        ("boundary_cells", ",".join(boundary_cells)),
        ("boundary_cell_count", str(len(boundary_cells))),
        ("data_resolutions", ",".join(str(r) for r in DATA_RESOLUTIONS)),
        ("center_lat", str(center.get("lat", 0))),
        ("center_lon", str(center.get("lon", 0))),
        ("species_count", str(len(species))),
        ("data_cell_count_res5", str(len(cells_by_resolution.get(5, set())))),
        ("data_cell_count_res4", str(len(cells_by_resolution.get(4, set())))),
        ("data_cell_count_res2", str(len(cells_by_resolution.get(2, set())))),
        ("build_date", datetime.datetime.now().isoformat()),
    ]
    conn.executemany("INSERT INTO pack_metadata VALUES (?,?)", metadata)

    # Create indexes
    print("    Creating indexes...")
    conn.executescript(
        """
        CREATE INDEX idx_grid_species_cell_res ON grid_species(h3_cell, resolution);
        CREATE INDEX idx_grid_species_avibase ON grid_species(avibase_id);
        CREATE INDEX idx_species_monthly_cell_res ON grid_species_monthly(h3_cell, resolution);
        CREATE INDEX idx_species_lookup_name ON species_lookup(scientific_name);
    """
    )

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("VACUUM")
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()

    file_size = os.path.getsize(output_path)

    # Build result entry
    result = {
        "region_id": region_id,
        "boundary_cells": boundary_cells,
        "boundary_cell_count": len(boundary_cells),
        "data_resolutions": DATA_RESOLUTIONS,
        "center_lat": center.get("lat", 0),
        "center_lon": center.get("lon", 0),
        "size_mb": file_size / (1024 * 1024),
        "num_cells_res5": len(cells_by_resolution.get(5, set())),
        "num_cells_res4": len(cells_by_resolution.get(4, set())),
        "num_cells_res2": len(cells_by_resolution.get(2, set())),
        "total_species": len(species),
        "grid_species_rows": len(all_grid_species),
        "monthly_rows": len(all_monthly),
    }

    # Write manifest
    manifest_path = output_dir / f"{region_id}.manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(result, f, indent=2)

    return result


def generate_pack_registry(output_dir: Path, results: list[dict]) -> dict:
    """Generate pack_registry.json for release-publisher.

    Args:
        output_dir: Directory containing built .db files
        results: List of build result dicts

    Returns:
        Registry dict in release-publisher format
    """
    version = datetime.datetime.now().strftime("%Y.%m")
    regions = []

    for r in results:
        region_id = r["region_id"]
        boundary_cells = r.get("boundary_cells", [])

        # Calculate bounding box from boundary cells
        lats = []
        lons = []
        for cell_hex in boundary_cells:
            try:
                lat, lon = h3.cell_to_latlng(cell_hex)
                lats.append(lat)
                lons.append(lon)
            except Exception:
                continue

        if lats and lons:
            bbox = {
                "min_lat": min(lats),
                "max_lat": max(lats),
                "min_lon": min(lons),
                "max_lon": max(lons),
            }
        else:
            bbox = {"min_lat": 0, "max_lat": 0, "min_lon": 0, "max_lon": 0}

        regions.append(
            {
                "region_id": region_id,
                "release_name": f"{region_id}-{version}",
                "h3_cells": boundary_cells,
                "pack_count": r.get("boundary_cell_count", len(boundary_cells)),
                "total_size_mb": r.get("size_mb", 0),
                "resolution": 4,  # Boundary resolution
                "center": {
                    "lat": r.get("center_lat", 0),
                    "lon": r.get("center_lon", 0),
                },
                "bbox": bbox,
            }
        )

    return {
        "version": version,
        "generated_at": datetime.datetime.now().isoformat(),
        "total_regions": len(regions),
        "total_packs": sum(r["pack_count"] for r in regions),
        "regions": regions,
    }


def build_region_packs(
    partitioned_dir: Path,
    manifest_path: Path,
    output_dir: Path,
    region_filter: str | None = None,
    worker_id: int = 0,
    total_workers: int = 1,
    skip_existing: bool = False,
) -> dict:
    """Build region packs from pre-partitioned eBird data.

    Args:
        partitioned_dir: Directory with partitioned data
        manifest_path: Pack manifest JSON from pack-planner
        output_dir: Output directory for region pack databases
        region_filter: Build only this specific region
        worker_id: Worker ID for parallel execution (0-indexed)
        total_workers: Total number of parallel workers
        skip_existing: Skip regions that already exist

    Returns:
        Dict with build statistics
    """
    # Load manifest
    with open(manifest_path) as f:
        manifest = json.load(f)

    regions = manifest.get("regions", [])

    if not regions:
        raise ValueError("No regions found in manifest")

    # Filter to specific region if requested
    if region_filter:
        regions = [r for r in regions if r.get("region_id") == region_filter]
        if not regions:
            raise ValueError(f"Region not found: {region_filter}")

    # Filter for this worker
    if total_workers > 1:
        regions = [r for i, r in enumerate(regions) if i % total_workers == worker_id]

    print("=" * 60)
    print("Building Region Packs from Partitioned Data")
    print("=" * 60)
    print(f"Regions to process: {len(regions)}")
    print(f"Data resolutions: {DATA_RESOLUTIONS} (with fallback)")
    print(f"Resolution penalties: {RESOLUTION_PENALTIES}")
    if total_workers > 1:
        print(f"Worker: {worker_id + 1}/{total_workers}")
    print()

    output_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()
    completed = 0
    skipped = 0
    failed = 0
    all_results: list[dict] = []

    for i, region in enumerate(regions, 1):
        region_id = region.get("region_id", "unknown")
        output_path = output_dir / f"{region_id}.db"

        if skip_existing and output_path.exists():
            skipped += 1
            print(f"[{i}/{len(regions)}] {region_id}: SKIPPED (exists)")
            # Load existing manifest to include in registry
            manifest_path_existing = output_dir / f"{region_id}.manifest.json"
            if manifest_path_existing.exists():
                with open(manifest_path_existing) as f:
                    all_results.append(json.load(f))
            continue

        region_start = time.time()
        print(f"[{i}/{len(regions)}] {region_id}: Building...")

        try:
            result = build_single_region_pack(region, partitioned_dir, output_dir)

            if result:
                completed += 1
                all_results.append(result)
                elapsed = time.time() - region_start

                # Progress
                total_elapsed = time.time() - start_time
                rate = completed / total_elapsed if total_elapsed > 0 else 0
                remaining = len(regions) - i
                eta = remaining / rate if rate > 0 else 0

                print(
                    f"  -> {result['total_species']} species, "
                    f"res5={result['num_cells_res5']}/res4={result['num_cells_res4']}/res2={result['num_cells_res2']} cells, "
                    f"{format_size(int(result['size_mb'] * 1024 * 1024))}, "
                    f"{elapsed:.1f}s (ETA: {format_duration(eta)})"
                )
            else:
                failed += 1
                print("  -> No data")

        except Exception as e:
            failed += 1
            print(f"  -> ERROR: {e}")
            import traceback

            traceback.print_exc()

    # Write combined manifest
    combined_manifest = {
        "regions": all_results,
        "total_regions": len(all_results),
        "data_resolutions": DATA_RESOLUTIONS,
        "resolution_penalties": RESOLUTION_PENALTIES,
    }

    manifest_out_path = output_dir / f"regions_manifest_worker{worker_id}.json"
    with open(manifest_out_path, "w") as f:
        json.dump(combined_manifest, f, indent=2)

    # Generate pack_registry.json for release-publisher (only for single worker or worker 0)
    if total_workers == 1 or worker_id == 0:
        registry = generate_pack_registry(output_dir, all_results)
        registry_path = output_dir / "pack_registry.json"
        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2)
        print(f"  Registry: {registry_path}")

    elapsed = time.time() - start_time

    print()
    print("=" * 60)
    print("BUILD COMPLETE")
    print("=" * 60)
    print(f"  Completed: {completed}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed: {failed}")
    print(f"  Time: {format_duration(elapsed)}")
    if elapsed > 0 and completed > 0:
        print(f"  Rate: {completed / elapsed * 60:.1f} regions/minute")
    print(f"  Manifest: {manifest_out_path}")

    return {
        "completed": completed,
        "skipped": skipped,
        "failed": failed,
        "duration_seconds": elapsed,
    }
