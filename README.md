# BirdNET-Pi Database Builders

Reference database builders for BirdNET-Pi species filtering.

## Complete Pipeline: From Raw eBird Data to Published Region Packs

This guide documents the full pipeline to build and publish region packs from scratch.

### Prerequisites

**Required Software:**
- Python 3.11+ with [uv](https://github.com/astral-sh/uv) package manager
- Node.js 18+ (for visualization tools)
- [GitHub CLI](https://cli.github.com/) (`gh`) - authenticated
- ~2TB free disk space (SSD recommended for temp files)
- 32GB+ RAM recommended

**Input Data:**
- `ebd_relAug-2025.tar` (~201GB) - eBird Basic Dataset
- `ebd_sampling_relAug-2025.tar` (~7GB) - Sampling event metadata

Download from [eBird Basic Dataset](https://ebird.org/data/download) (requires account).

---

## Pipeline Overview

```
                                    STEP 1 (12+ hours)
ebd_relAug-2025.tar ──────────────────────────────────────► ebird_parquet/
     (201GB)                convert_ebird_to_parquet.py         (118GB)
                                                                   │
                                                                   │ STEP 2 (6+ hours)
                                                                   │ sort_parquet_chunked.py
                                                                   ▼
                                                          ebird_by_location/
                                                               (25GB)
                                                                   │
                           ┌───────────────────────────────────────┤
                           │                                       │
            STEP 3a (2.5 hours)                        STEP 3b (2.5 hours)
     partition_by_boundary.py                     partition_by_boundary.py
     (--discover-only)                                             │
                           │                                       ▼
                           ▼                              ebird_partitioned/
                  boundary_cells.json                       (Hive-style)
                           │
              STEP 4 (seconds)
        convert_discovery_to_density_report.py
                           │
                           ▼
                  density_report.json
                           │
              STEP 4b (seconds)
        create_bootstrap_size_manifest.py
                           │
                           ▼
                  size_manifest.json (bootstrap/estimated)
                           │
              STEP 5 (seconds)
         pack-planner (with --size-manifest)
                           │
                           ├──► pack_manifest.json
                           └──► pack_registry.json
                                       │
                                       │         ebird_partitioned/
                                       │                │
                                       ▼                ▼
                          STEP 6 (8-10 hours)
                       build_packs_from_partitions.py
                                       │
                                       ▼
                           region_packs/*.db (~98 regions, ~19GB)
                                       │
                           STEP 7 (optional)
                        pack-manifest-visualizer
                                       │
                                       ▼
                              visualization/index.html
                                       │
                           STEP 8 (hours)
                          release-publisher
                                       │
                                       ▼
                          GitHub Releases

(OPTIONAL REFINEMENT - if estimated sizes differ significantly from actual)
                                       │
              create_size_manifest.py ◄┘ (from actual builds)
                           │
                           ▼
              size_manifest_v2.json (measured)
                           │
              pack-planner (refined)
                           │
              pack_manifest_v2.json
                           │
              rebuild packs
```

---

## Step 1: Convert eBird Tarball to Parquet

Streams raw eBird TSV from tarball directly to Parquet without extracting to disk.

```bash
cd bird-dbs/scripts

uv run convert_ebird_to_parquet.py \
    --input /Volumes/backup/ebird/ebd_relAug-2025.tar \
    --output-dir /Volumes/Lightroom/ebird_parquet \
    --chunk-size 1000000
```

**Time estimate:** 12-24 hours (depends on disk speed)
**Output:** ~118GB in 399 Parquet files (~1M rows each)
**Disk usage:** Only output directory (no extraction needed)

**What it does:**
- Streams `tar` -> `gzip` -> `TSV` -> `Parquet` (no intermediate files)
- Uses Polars for efficient conversion
- ZSTD compression (level 3)

---

## Step 2: Sort Parquet by Location

Sort data by geographic coordinates for efficient spatial queries.

```bash
uv run sort_parquet_chunked.py \
    --input-dir /Volumes/Lightroom/ebird_parquet \
    --output-dir /Volumes/Lightroom/ebird_by_location \
    --sort-order location \
    --memory-limit 24GB \
    --max-temp-size 200GiB
```

**Time estimate:** 6-8 hours
**Output:** ~25GB in 18 latitude-band partitions
**Temp space needed:** Up to 200GB per partition (cleaned automatically)

**Sort orders available:**
- `location` - Sorted by lat/lon (required for pack building)
- `date` - Sorted by observation date
- `taxon` - Sorted by species

---

## Step 3a: Discover Boundary Cells

Scan all data to find which H3 boundary cells have observations.

```bash
uv run partition_by_boundary.py \
    --input /Volumes/Lightroom/ebird_by_location \
    --output /Volumes/Lightroom/ebird_partitioned \
    --boundary-resolution 4 \
    --discover-only
```

**Time estimate:** 30-60 minutes
**Output:** `boundary_cells.json` with statistics for each cell

---

## Step 3b: Partition Data by Boundary Cells

Partition all observations into Hive-style directories by H3 boundary cell.

```bash
uv run partition_by_boundary.py \
    --input /Volumes/Lightroom/ebird_by_location \
    --output /Volumes/Lightroom/ebird_partitioned \
    --boundary-resolution 4 \
    --memory-limit 16GB
```

**Time estimate:** 2-3 hours
**Output:** Hive-partitioned directory structure:
```
ebird_partitioned/
├── boundary_cell=842b9bdffffffff/
│   └── data_0.parquet
├── boundary_cell=842b9adffffffff/
│   └── data_0.parquet
└── ...
```

---

## Step 4: Convert Discovery to Density Report

Bridge the partition discovery output to pack-planner format.

```bash
uv run convert_discovery_to_density_report.py \
    --input /Volumes/Lightroom/ebird_partitioned/boundary_cells.json \
    --output /Volumes/Lightroom/density_report_res4.json
```

**Time estimate:** Seconds
**Output:** `density_report_res4.json` with:
- Estimated pack sizes
- Recommended data resolutions
- Coverage statistics

---

## Step 4b: Create Bootstrap Size Manifest

Create a size manifest from density report estimates (no builds needed).

```bash
cd bird-dbs/scripts

uv run create_bootstrap_size_manifest.py \
    --density-report /Volumes/Lightroom/ebird_partitioned/density_report_res4.json \
    --output /Volumes/Lightroom/ebird_partitioned/size_manifest.json
```

**Time estimate:** Seconds
**Output:** `size_manifest.json` with estimated per-cell sizes from density report

This bootstrap manifest uses the `estimated_pack_size_mb` values calculated during density
report generation. These estimates are based on checklist counts and are accurate enough
for initial region planning.

---

## Step 5: Pack Planning

Run pack-planner with the bootstrap size manifest to create regions.

```bash
cd bird-dbs/analysis/pack-planner
uv sync

uv run pack-planner \
    --density-reports /Volumes/Lightroom/density_reports/ \
    --size-manifest /Volumes/Lightroom/ebird_partitioned/size_manifest.json \
    --max-region-size-mb 250 \
    --output-manifest /Volumes/Lightroom/ebird_partitioned/pack_manifest.json \
    --output-registry /Volumes/Lightroom/ebird_partitioned/pack_registry.json
```

**Time estimate:** Seconds
**Output:**
- `pack_manifest.json` - Regions sized to ~250 MB each
- `pack_registry.json` - Minimal registry for client lookups

The planner splits oversized regions using latitude-band sorting for geographic locality.
With ~20GB total data and 250 MB target: expect ~80-100 regions globally.

**Expected results (Aug 2025 data):**
- ~98 regions
- Max size: ~324 MB (high-density regions like north-america-great-lakes)
- Most regions: 150-250 MB
- Total: ~19.3 GB

---

## Step 6: Build Region Packs

Build the SQLite region packs.

```bash
cd bird-dbs/scripts

uv run build_packs_from_partitions.py \
    --partitioned-dir /Volumes/Lightroom/ebird_partitioned \
    --manifest /Volumes/Lightroom/ebird_partitioned/pack_manifest.json \
    --output-dir /Volumes/Lightroom/region_packs
```

**Time estimate:** 8-10 hours
**Output:** `region_packs/*.db` - ~98 region packs, ~19 GB total

**Resume after interruption:**
```bash
uv run build_packs_from_partitions.py \
    --partitioned-dir /Volumes/Lightroom/ebird_partitioned \
    --manifest /Volumes/Lightroom/ebird_partitioned/pack_manifest.json \
    --output-dir /Volumes/Lightroom/region_packs \
    --skip-existing
```

### Optional: Refinement Pass

If pack sizes differ significantly from estimates (>20% variance), you can refine:

```bash
# 1. Create accurate size manifest from actual builds
uv run create_size_manifest.py \
    --packs-dir /Volumes/Lightroom/region_packs \
    --pack-manifest /Volumes/Lightroom/ebird_partitioned/pack_manifest.json \
    --output /Volumes/Lightroom/ebird_partitioned/size_manifest_v2.json

# 2. Re-plan with actual sizes
cd ../analysis/pack-planner
uv run pack-planner \
    --density-reports /Volumes/Lightroom/density_reports/ \
    --size-manifest /Volumes/Lightroom/ebird_partitioned/size_manifest_v2.json \
    --max-region-size-mb 250 \
    --output-manifest /Volumes/Lightroom/ebird_partitioned/pack_manifest_v2.json \
    --output-registry /Volumes/Lightroom/ebird_partitioned/pack_registry_v2.json

# 3. Rebuild with optimized regions
cd ../scripts
rm -rf /Volumes/Lightroom/region_packs
uv run build_packs_from_partitions.py \
    --partitioned-dir /Volumes/Lightroom/ebird_partitioned \
    --manifest /Volumes/Lightroom/ebird_partitioned/pack_manifest_v2.json \
    --output-dir /Volumes/Lightroom/region_packs
```

For most use cases, the bootstrap estimates are accurate enough and refinement is not needed.

---

## Step 7: Visualize Coverage (Optional)

Generate an interactive map showing pack coverage.

```bash
cd bird-dbs/pack-manifest-visualizer
npm install
npm run build

node dist/index.js /Volumes/Lightroom/pack_manifest.json ./visualization
```

**Output:** `visualization/index.html` - standalone HTML map

Open in browser to explore regions and H3 cell coverage.

---

## Step 8: Publish to GitHub Releases

Upload packs to GitHub releases for distribution.

```bash
cd bird-dbs/release-publisher
uv sync

# Dry run first
uv run release-publisher \
    --registry /Volumes/Lightroom/pack_registry.json \
    --db-dir /Volumes/Lightroom/packs \
    --target-repo owner/birdnetpi-ebird-packs \
    --dry-run

# Actual upload
uv run release-publisher \
    --registry /Volumes/Lightroom/pack_registry.json \
    --db-dir /Volumes/Lightroom/packs \
    --target-repo owner/birdnetpi-ebird-packs \
    --workers 16
```

**Time estimate:** Several hours (depends on connection speed)
**Features:**
- Bundles packs into ~1950MB releases (bin-packing)
- Includes eBird attribution
- Idempotent (safe to re-run)
- Uploads global registry for programmatic discovery

---

## Directory Structure

```
bird-dbs/
├── scripts/                          # Data processing scripts
│   ├── convert_ebird_to_parquet.py   # Step 1: Raw TSV -> Parquet
│   ├── sort_parquet_chunked.py       # Step 2: Sort by location
│   ├── partition_by_boundary.py      # Step 3: H3 partitioning
│   ├── convert_discovery_to_density_report.py  # Step 4: Format conversion
│   ├── create_bootstrap_size_manifest.py # Step 4b: Bootstrap sizes from estimates
│   ├── create_size_manifest.py       # (Optional) Extract sizes from actual builds
│   ├── build_packs_from_partitions.py # Step 6: Build SQLite packs
│   ├── convert_sampling_to_parquet.py # (Optional) Sampling events
│   └── verify_parquet_integrity.py    # (Optional) Validation
│
├── analysis/
│   └── pack-planner/                 # Step 5: Region planning
│
├── pack-manifest-visualizer/         # Step 7: Map visualization
│
├── release-publisher/                # Step 8: GitHub releases
│
├── ioc-builder/                      # IOC taxonomy database
├── wikidata-builder/                 # Wikidata translations
├── avilistr-builder/                 # Avibase taxonomy extraction
│
├── shared/avilistr/                  # Shared taxonomy mapping
├── ground_sample/                    # Test data
└── docs/                             # Documentation
```

---

## Time Estimates Summary

| Step | Task | Time | Notes |
|------|------|------|-------|
| 1 | Tarball to Parquet | 12-24 hours | I/O bound |
| 2 | Sort by location | 6-8 hours | CPU + I/O |
| 3a | Discover boundaries | 30-60 min | Read-only scan |
| 3b | Partition data | 2-3 hours | Write-heavy |
| 4 | Density report | Seconds | Conversion only |
| 4b | Bootstrap size manifest | Seconds | From density estimates |
| 5 | Pack planning | Seconds | Create regions |
| 6 | Build packs | 8-10 hours | ~98 regions |
| 7 | Visualization | Minutes | Optional |
| 8 | GitHub upload | Hours | Network bound |
| **Total** | | **~30-45 hours** | Single build pass |

**Note:** Optional refinement pass adds ~8-10 hours but is usually not needed.

---

## Disk Space Requirements

| Directory | Size | Notes |
|-----------|------|-------|
| Input tarball | 201GB | Read-only |
| `ebird_parquet/` | 118GB | Intermediate |
| `ebird_by_location/` | 25GB | Sorted |
| `ebird_partitioned/` | ~50GB | Hive-style |
| `region_packs/` | ~19GB | Final output (~98 regions) |
| Temp space | 200GB | During sorting |
| **Total working** | ~610GB | Peak usage |

After completion, intermediate files can be deleted:
- `ebird_parquet/` - Safe to delete after partitioning
- `ebird_partitioned/` - Keep if you may need to rebuild

---

## Annual Update Process

eBird releases new data each August. To update:

1. Download new `ebd_relXXX-YYYY.tar` from eBird
2. Run Steps 1-4 (data conversion and partitioning)
3. Run Step 4b (create bootstrap size manifest)
4. Run Step 5 (pack planning)
5. Run Step 6 (build packs)
6. Verify pack integrity
7. Publish new release (Step 8)

**Note:** The bootstrap size manifest uses estimated sizes which are typically accurate
within 10-20%. If you need more precise region boundaries, run the optional refinement
pass after the initial build.

The entire pipeline is idempotent and can be re-run safely.

---

## Repository Structure

```
bird-dbs/
├── [BUILDERS] ────────────────────────────────────────────────────────
│   ├── ioc-builder/                   # IOC World Bird List -> SQLite
│   └── wikidata-builder/              # Wikidata SPARQL -> SQLite
│
├── [ANALYSIS TOOLS] ──────────────────────────────────────────────────
│   └── analysis/pack-planner/         # Python: Region partitioning
│
├── [SUPPORT TOOLS] ───────────────────────────────────────────────────
│   ├── avilistr-builder/              # R: Avibase taxonomy extraction
│   ├── pack-manifest-visualizer/      # TypeScript: H3 visualization
│   └── release-publisher/             # Python: GitHub release automation
│
├── [DATA SCRIPTS] ────────────────────────────────────────────────────
│   └── scripts/                       # Python/Polars/DuckDB data pipeline
│
├── [SHARED DATA] ─────────────────────────────────────────────────────
│   ├── shared/avilistr/               # Avibase taxonomy mapping (CSV)
│   └── ground_sample/                 # Test data with expected results
│
└── [DOCUMENTATION] ───────────────────────────────────────────────────
    └── docs/
```

---

## Troubleshooting

### Out of disk space during sorting
- Increase `--max-temp-size` if you have more space
- Use a faster SSD for temp directory
- Reduce `--memory-limit` (trades speed for less temp usage)

### Pack building is slow
- Use `--skip-existing` to resume after interruption
- Ensure partitioned data is on SSD
- Building ~98 regions takes 8-10 hours single-threaded

### Regions still too large after size-aware planning
- Reduce `--max-region-size-mb` (default: 250)
- Check that size_manifest.json has complete data
- Some high-density regions (e.g., Great Lakes) may exceed target slightly

### GitHub upload fails
- Check `gh auth status`
- Use `--dry-run` first
- Reduce `--workers` if rate limited

### Memory errors
- Reduce `--chunk-size` in Step 1
- Reduce `--memory-limit` in Step 2

### Size manifest missing cells
- Ensure all regions built successfully in Step 5b
- Check for disk I/O errors in build logs
- Re-run initial build for failed regions

---

## License

This tool builds databases from eBird data, which is subject to the [eBird Terms of Use](https://www.birds.cornell.edu/home/ebird-data-access-terms-of-use/).

The region packs include proper eBird attribution as required by the license.
