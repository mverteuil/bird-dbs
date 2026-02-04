# Pack Planner

Partition eBird region packs into optimally-sized regions for distribution.

## Overview

This tool reads density reports and size manifests to partition packs into geographic
regions optimized for distribution. It supports two workflows:

### Linear Workflow (Recommended)

Uses estimated sizes from density reports - no initial build required:

1. **Create bootstrap size manifest**: From density report estimates
2. **Run pack-planner**: Create regions based on estimated sizes
3. **Build packs**: Single build pass
4. **(Optional) Refine**: If estimates were off, re-plan with actual sizes

### Legacy Workflow (Two-Pass)

Requires building packs twice to get actual sizes:

1. Initial build → get actual sizes
2. Re-plan with actual sizes
3. Final build

## Prerequisites

- Density reports from `convert_discovery_to_density_report.py`
- Partitioned eBird data from `partition_by_boundary.py`
- Size manifest (bootstrap from estimates, or measured from actual builds)

## Installation

```bash
cd analysis/pack-planner
uv sync
```

## Linear Workflow (Recommended)

### Step 1: Create Bootstrap Size Manifest

Create size manifest from density report estimates (no builds needed):

```bash
cd ../scripts
uv run create_bootstrap_size_manifest.py \
  --density-report /Volumes/Lightroom/ebird_partitioned/density_report_res4.json \
  --output /Volumes/Lightroom/ebird_partitioned/size_manifest.json
```

### Step 2: Run Pack Planner

Create regions using estimated sizes:

```bash
cd ../analysis/pack-planner
uv run pack-planner \
  --density-reports /path/to/density_reports/ \
  --size-manifest /Volumes/Lightroom/ebird_partitioned/size_manifest.json \
  --max-region-size-mb 250 \
  --output-manifest /Volumes/Lightroom/ebird_partitioned/pack_manifest.json \
  --output-registry /Volumes/Lightroom/ebird_partitioned/pack_registry.json
```

### Step 3: Build Packs

Build the final packs:

```bash
cd ../scripts
uv run build_packs_from_partitions.py \
  --partitioned-dir /Volumes/Lightroom/ebird_partitioned \
  --manifest /Volumes/Lightroom/ebird_partitioned/pack_manifest.json \
  --output-dir /Volumes/Lightroom/region_packs
```

### Optional: Refinement Pass

If estimated sizes differ significantly from actual builds:

```bash
# 1. Create accurate size manifest from actual builds
uv run create_size_manifest.py \
  --packs-dir /Volumes/Lightroom/region_packs \
  --pack-manifest /Volumes/Lightroom/ebird_partitioned/pack_manifest.json \
  --output /Volumes/Lightroom/ebird_partitioned/size_manifest_v2.json

# 2. Re-plan with actual sizes
cd ../analysis/pack-planner
uv run pack-planner \
  --density-reports /path/to/density_reports/ \
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

## CLI Options

```bash
uv run pack-planner --help
```

| Option | Default | Description |
|--------|---------|-------------|
| `--density-reports` | (required) | Directory with density report JSONs |
| `--size-manifest` | (required) | JSON mapping cells to actual sizes |
| `--max-region-size-mb` | 250 | Maximum size per region in MB |
| `--max-pack-size-mb` | 500 | Maximum size per individual pack |
| `--output-manifest` | (required) | Output path for pack manifest |
| `--output-registry` | (required) | Output path for region registry |
| `--method` | continental | Partitioning method |
| `--verbose` | false | Enable debug logging |

## Output Files

### Pack Manifest (pack_manifest.json)

Full region definitions with all packs:

```json
{
  "regions": [
    {
      "region_id": "western-europe-1",
      "h3_cells": ["8001fffffffffff", ...],
      "packs": [...],
      "size_mb": 245.3,
      "pack_count": 312,
      "center": {"lat": 48.5, "lon": 2.3},
      "m49_region": "western-europe-1"
    }
  ]
}
```

### Size Manifest (size_manifest.json)

Per-cell size mapping. Can be either:
- **Bootstrap manifest**: From density report estimates (has `"bootstrap": true`)
- **Measured manifest**: From actual build sizes (has `"source_region": "region-name"`)

Bootstrap manifest (from `create_bootstrap_size_manifest.py`):

```json
{
  "version": "1.0",
  "description": "Bootstrap size manifest from density estimates (not actual builds)",
  "bootstrap": true,
  "stats": {
    "total_cells": 28967,
    "total_size_mb": 19800.5,
    "average_size_mb_per_cell": 0.68
  },
  "cells": [
    {
      "boundary_cell": "842b9bdffffffff",
      "size_mb": 0.72,
      "source_region": "bootstrap"
    }
  ]
}
```

Measured manifest (from `create_size_manifest.py`):

```json
{
  "version": "1.0",
  "stats": {
    "total_cells": 28967,
    "total_size_mb": 19800.5,
    "average_size_mb_per_cell": 0.68
  },
  "cells": [
    {
      "boundary_cell": "842b9bdffffffff",
      "size_mb": 0.72,
      "source_region": "north-america-great-lakes"
    }
  ]
}
```

## Partitioning Algorithm

The `continental` method (default):

1. **Geographic grouping**: Assign packs to predefined continental boundaries
2. **Size-aware splitting**: Split regions exceeding `max-region-size-mb`
   - Sort packs by latitude for geographic locality
   - Create sub-regions targeting equal size distribution
3. **Gap filling**: Add interior cells for continuous coverage
4. **Border overlap**: Add 1-cell overlap at region boundaries
5. **Global coverage**: Assign remaining cells to nearest region

## Size Estimation

The size manifest provides actual MB-per-cell values from real builds. This is critical because:

- Multi-resolution data (res 5/4/2) makes packs ~3-5x larger than single-resolution
- Cell density varies significantly by region (0.45 - 1.56 MB/cell observed)
- Accurate sizing enables optimal region boundaries

## Example: Target 250 MB Regions

With our actual data:
- Total: 19.3 GB across 28,967 cells
- Average: 0.68 MB per cell
- For 250 MB target: ~370 cells per region
- Expected: ~80-90 regions globally

## Dependencies

- `click`: CLI framework
- `h3`: H3 hexagonal indexing
- `pyyaml`: YAML config parsing

## Testing

```bash
uv run pytest
```
