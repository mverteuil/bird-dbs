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

## Quick Start

```bash
cd bird-dbs/ebd-pack-builder
uv sync

# Run the full pipeline
uv run ebd convert --input /path/to/ebd.tar --output-dir ./ebird_parquet
uv run ebd sort --input-dir ./ebird_parquet --output-dir ./ebird_by_location
uv run ebd partition --input-dir ./ebird_by_location --output-dir ./ebird_partitioned
uv run ebd density-report --boundary-cells ./ebird_partitioned/boundary_cells.json --output ./density.json
uv run ebd plan --density-report ./density.json --output-manifest ./pack_manifest.json --max-region-size-mb 80
uv run ebd build --partitioned-dir ./ebird_partitioned --manifest ./pack_manifest.json --output-dir ./packs
uv run ebd package --packs-dir ./packs --registry ./pack_registry.json
uv run ebd verify ./packs

# Check pipeline status
uv run ebd status --state-dir ./ebd_state
```

**Features:**
- JSON-based state tracking for resumability
- Consistent CLI interface across all steps
- `--force` flag to re-run completed steps
- `--skip-existing` for build resumability

---

## Pipeline Overview

```
                                    STEP 1 (12+ hours)
ebd_relAug-2025.tar ──────────────────────────────────────► ebird_parquet/
     (201GB)                      ebd convert                    (118GB)
                                                                   │
                                                                   │ STEP 2 (6+ hours)
                                                                   │ ebd sort
                                                                   ▼
                                                          ebird_by_location/
                                                               (25GB)
                                                                   │
                           ┌───────────────────────────────────────┤
                           │                                       │
            STEP 3a (2.5 hours)                        STEP 3b (2.5 hours)
            ebd partition                                  ebd partition
            (--discover-only)                                      │
                           │                                       ▼
                           ▼                              ebird_partitioned/
                  boundary_cells.json                       (Hive-style)
                           │
              STEP 4 (seconds)
              ebd density-report
                           │
                           ▼
                  density_report.json
                           │
              STEP 5 (seconds)
                  ebd plan
                           │
                           ├──► pack_manifest.json
                           └──► pack_registry.json
                                       │
                                       │         ebird_partitioned/
                                       │                │
                                       ▼                ▼
                          STEP 6 (8-10 hours)
                              ebd build
                                       │
                                       ▼
                           region_packs/*.db (~250 regions, ~16GB)
                                       │
                           STEP 7 (30 min)
                              ebd package
                                       │
                                       ▼
                           region_packs/*.db.gz (~4GB compressed)
                                       │
                           STEP 8 (optional)
                        pack-manifest-visualizer
                                       │
                                       ▼
                              visualization/index.html
                                       │
                           STEP 9 (hours)
                          release-publisher
                                       │
                                       ▼
                          GitHub Releases
```

---

## Step 1: Convert eBird Tarball to Parquet

Streams raw eBird TSV from tarball directly to Parquet without extracting to disk.

```bash
cd bird-dbs/ebd-pack-builder

uv run ebd convert \
    --input /Volumes/backup/ebird/ebd_relAug-2025.tar \
    --output-dir /Volumes/Lightroom/ebird_parquet \
    --chunk-size 1000000
```

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
uv run ebd sort \
    --input-dir /Volumes/Lightroom/ebird_parquet \
    --output-dir /Volumes/Lightroom/ebird_by_location \
    --memory-limit 24GB
```

**Output:** ~25GB in 18 latitude-band partitions
**Temp space needed:** Up to 200GB per partition (cleaned automatically)

---

## Step 3a: Discover Boundary Cells

Scan all data to find which H3 boundary cells have observations.

```bash
uv run ebd partition \
    --input-dir /Volumes/Lightroom/ebird_by_location \
    --output-dir /Volumes/Lightroom/ebird_partitioned \
    --boundary-resolution 4 \
    --discover-only
```

**Output:** `boundary_cells.json` with statistics for each cell

---

## Step 3b: Partition Data by Boundary Cells

Partition all observations into Hive-style directories by H3 boundary cell.

```bash
uv run ebd partition \
    --input-dir /Volumes/Lightroom/ebird_by_location \
    --output-dir /Volumes/Lightroom/ebird_partitioned \
    --boundary-resolution 4
```

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

## Step 4: Create Density Report

Convert boundary cell statistics to planning format.

```bash
uv run ebd density-report \
    --boundary-cells /Volumes/Lightroom/ebird_partitioned/boundary_cells.json \
    --output /Volumes/Lightroom/density_report.json
```

**Output:** `density_report.json` with:
- Estimated pack sizes
- Recommended data resolutions
- Coverage statistics

---

## Step 5: Plan Region Packs

Group boundary cells into downloadable regions optimized for distribution.

```bash
uv run ebd plan \
    --density-report /Volumes/Lightroom/density_report.json \
    --output-manifest /Volumes/Lightroom/pack_manifest.json \
    --output-registry /Volumes/Lightroom/pack_registry.json \
    --max-region-size-mb 80
```

**Output:**
- `pack_manifest.json` - Full region definitions for building
- `pack_registry.json` - Minimal registry for client lookups

**Sizing notes:**
- Use `--max-region-size-mb 80` to account for ~20% size underestimation
- This keeps actual pack sizes under the 150 MB hard limit
- Expected results (Aug 2025 data): ~250 regions, largest ~141 MB

---

## Step 6: Build Region Packs

Build the SQLite region packs.

```bash
uv run ebd build \
    --partitioned-dir /Volumes/Lightroom/ebird_partitioned \
    --manifest /Volumes/Lightroom/pack_manifest.json \
    --output-dir /Volumes/Lightroom/region_packs
```

**Output:** `region_packs/*.db` - ~250 region packs, ~16 GB total

**Resume after interruption:**
```bash
uv run ebd build \
    --partitioned-dir /Volumes/Lightroom/ebird_partitioned \
    --manifest /Volumes/Lightroom/pack_manifest.json \
    --output-dir /Volumes/Lightroom/region_packs \
    --skip-existing
```

**Build specific region:**
```bash
uv run ebd build \
    --partitioned-dir /Volumes/Lightroom/ebird_partitioned \
    --manifest /Volumes/Lightroom/pack_manifest.json \
    --output-dir /Volumes/Lightroom/region_packs \
    --region na-east-001
```

---

## Step 7: Package for Release

Gzip compress all packs with release-compatible naming.

```bash
uv run ebd package \
    --packs-dir /Volumes/Lightroom/region_packs \
    --registry /Volumes/Lightroom/pack_registry.json \
    --compression-level 6
```

**Output:** `region_packs/*.db.gz` - compressed packs (~25% of original size)

**Results (Aug 2025 data):**
- 250 regions packaged
- Uncompressed: ~16 GB
- Compressed: ~4 GB
- Compression ratio: ~25%

---

## Step 8: Visualize Coverage (Optional)

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

## Step 9: Publish to GitHub Releases

Upload packs to GitHub releases for distribution.

```bash
cd bird-dbs/release-publisher
uv sync

# Dry run first
uv run release-publisher \
    --registry /Volumes/Lightroom/pack_registry.json \
    --db-dir /Volumes/Lightroom/region_packs \
    --target-repo owner/birdnetpi-ebird-packs \
    --dry-run

# Actual upload
uv run release-publisher \
    --registry /Volumes/Lightroom/pack_registry.json \
    --db-dir /Volumes/Lightroom/region_packs \
    --target-repo owner/birdnetpi-ebird-packs \
    --workers 16
```

**Features:**
- Bundles packs into ~1950MB releases (bin-packing)
- Includes eBird attribution
- Idempotent (safe to re-run)
- Uploads global registry for programmatic discovery

---

## Directory Structure

```
bird-dbs/
├── ebd-pack-builder/                 # eBird pipeline CLI
│   └── src/ebd_pack_builder/         # Python package
│       ├── cli.py                    # Click CLI with subcommands
│       ├── pipeline.py               # State management
│       ├── steps/                    # Pipeline step modules
│       ├── models/                   # Pydantic models
│       └── utils/                    # Shared utilities
│
├── pack-manifest-visualizer/         # Map visualization
│
├── release-publisher/                # GitHub release automation
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

| Step | Task | Command | Notes |
|------|------|---------|-------|
| 1 | Tarball to Parquet | `ebd convert` | I/O bound |
| 2 | Sort by location | `ebd sort` | CPU + I/O |
| 3a | Discover boundaries | `ebd partition --discover-only` | Read-only scan |
| 3b | Partition data | `ebd partition` | Write-heavy |
| 4 | Density report | `ebd density-report` | Seconds |
| 5 | Pack planning | `ebd plan` | Seconds |
| 6 | Build packs | `ebd build` | ~250 regions |
| 7 | Package packs | `ebd package` | 30 min |
| 8 | Visualization | `pack-manifest-visualizer` | Optional |
| 9 | GitHub upload | `release-publisher` | Network bound |

---

## Disk Space Requirements

| Directory | Size | Notes |
|-----------|------|-------|
| Input tarball | 201GB | Read-only |
| `ebird_parquet/` | 118GB | Intermediate |
| `ebird_by_location/` | 25GB | Sorted |
| `ebird_partitioned/` | ~50GB | Hive-style |
| `region_packs/` (uncompressed) | ~16GB | ~250 regions |
| `region_packs/` (compressed) | ~4GB | Final output |
| Temp space | 200GB | During sorting |
| **Total working** | ~610GB | Peak usage |

After completion, intermediate files can be deleted:
- `ebird_parquet/` - Safe to delete after partitioning
- `ebird_partitioned/` - Keep if you may need to rebuild

---

## Region Sizing Strategy

The `ebd plan` command uses estimated sizes to group boundary cells into regions:

| Parameter | Value | Notes |
|-----------|-------|-------|
| **Hard maximum** | 150 MB | Uncompressed .db file |
| **Planning target** | 80 MB | Use `--max-region-size-mb 80` |
| **Estimation accuracy** | ~80% | Actual sizes ~20% higher than estimates |
| **Compressed size** | ~25% | Typical gzip compression ratio |

**Why 80 MB target for 150 MB limit?**

The size estimation uses checklist counts and is approximately 20% low. Planning at 80 MB results in actual packs of ~100-140 MB, safely under the 150 MB limit.

**Results (Aug 2025 data):**
- 250 regions globally
- Largest uncompressed: 141 MB
- Total uncompressed: ~16 GB
- Total compressed: ~4 GB

---

## Annual Update Process

eBird releases new data each August. To update:

1. Download new `ebd_relXXX-YYYY.tar` from eBird
2. Run `ebd convert` (Step 1)
3. Run `ebd sort` (Step 2)
4. Run `ebd partition` (Steps 3a, 3b)
5. Run `ebd density-report` (Step 4)
6. Run `ebd plan` (Step 5)
7. Run `ebd build` (Step 6)
8. Run `ebd package` (Step 7)
9. Run `ebd verify` to check integrity
10. Publish new release with `release-publisher` (Step 9)

The entire pipeline is idempotent and can be re-run safely.

---

## Repository Structure

```
bird-dbs/
├── [EBD PIPELINE] ────────────────────────────────────────────────────
│   └── ebd-pack-builder/              # Unified CLI for eBird processing
│
├── [BUILDERS] ────────────────────────────────────────────────────────
│   ├── ioc-builder/                   # IOC World Bird List -> SQLite
│   └── wikidata-builder/              # Wikidata SPARQL -> SQLite
│
├── [SUPPORT TOOLS] ───────────────────────────────────────────────────
│   ├── avilistr-builder/              # R: Avibase taxonomy extraction
│   ├── pack-manifest-visualizer/      # TypeScript: H3 visualization
│   └── release-publisher/             # Python: GitHub release automation
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
- Use a faster SSD for temp directory
- Reduce `--memory-limit` (trades speed for less temp usage)

### Pack building is slow
- Use `--skip-existing` to resume after interruption
- Ensure partitioned data is on SSD
- Use `--region` to build specific regions

### Regions exceed 150 MB limit
- Reduce `--max-region-size-mb` in plan step (use 80 or lower)
- The estimation is ~20% low, so plan conservatively

### GitHub upload fails
- Check `gh auth status`
- Use `--dry-run` first
- Reduce `--workers` if rate limited

### Memory errors
- Reduce `--chunk-size` in convert step
- Reduce `--memory-limit` in sort step

---

## License

This tool builds databases from eBird data, which is subject to the [eBird Terms of Use](https://www.birds.cornell.edu/home/ebird-data-access-terms-of-use/).

The region packs include proper eBird attribution as required by the license.
