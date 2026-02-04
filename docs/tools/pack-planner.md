# Pack Planner

Partition eBird region packs into GitHub-release-sized regions that fit within the 2GB limit.

## Overview

This tool reads density reports from `ebird-density-analyzer` and partitions individual packs into larger geographic regions optimized for distribution via GitHub releases. It uses a greedy merge algorithm to create the largest possible regions while respecting the 2GB size constraint.

## Features

- **Greedy partitioning**: Merges adjacent H3 cells to maximize region size
- **Monte Carlo optimization**: Optional randomized search for better partitions
- **Automatic naming**: Generates human-readable region IDs (e.g., "na-west-coast")
- **Registry generation**: Creates lookup index for client downloads
- **Size validation**: Ensures all regions fit within 2GB limit

## Installation

```bash
cd analysis/pack-planner
uv sync
```

## Usage

### Basic Usage

```bash
uv run pack-planner \
  --density-reports density_reports/ \
  --max-size-mb 1950 \
  --output-manifest pack_manifest.json \
  --output-registry pack_registry.json
```

### With Monte Carlo Optimization

```bash
uv run pack-planner \
  --density-reports density_reports/ \
  --method monte-carlo \
  --monte-carlo-iterations 100 \
  --output-manifest pack_manifest.json \
  --output-registry pack_registry.json
```

### Verbose Logging

```bash
uv run pack-planner \
  --density-reports density_reports/ \
  --output-manifest pack_manifest.json \
  --output-registry pack_registry.json \
  --verbose
```

## Output Files

### Pack Manifest (pack_manifest.json)

Contains full list of regions with all packs:

```json
{
  "regions": [
    {
      "region_id": "na-west-coast",
      "release_name": "na-west-coast-2025.08",
      "h3_cells": ["8001fffffffffff", "8003fffffffffff"],
      "packs": [
        {
          "pack_id": "h3-r4-599686042433355775-data-r7",
          "estimated_size_mb": 8.2
        }
      ],
      "size_mb": 1847.3,
      "pack_count": 245,
      "center": {"lat": 42.5, "lon": -122.0}
    }
  ]
}
```

### Pack Registry (pack_registry.json)

Minimal registry for client lookups (~100KB):

```json
{
  "version": "2025.08",
  "total_regions": 287,
  "total_packs": 8547,
  "total_size_gb": 67.3,
  "regions": [
    {
      "region_id": "na-west-coast",
      "h3_cells": ["8001fffffffffff", "8003fffffffffff"],
      "resolution": 2,
      "release_name": "na-west-coast-2025.08",
      "total_size_mb": 1847.3,
      "pack_count": 245,
      "center": {"lat": 42.5, "lon": -122.0},
      "bbox": {
        "min_lat": 32.5,
        "max_lat": 49.0,
        "min_lon": -125.0,
        "max_lon": -115.0
      }
    }
  ]
}
```

## Algorithms

### Greedy Merge

1. Group packs by H3 res 2 parent cells (~1,900 globally)
2. Sort regions by size (smallest first)
3. For each region, find adjacent regions that fit when merged
4. Merge and repeat until no more merges possible

**Characteristics:**
- Deterministic (same input → same output)
- Fast (~seconds for global dataset)
- Produces near-optimal results

### Monte Carlo

1. Run greedy merge with random pack order
2. Repeat N times with different random orders
3. Pick partition with fewest regions

**Characteristics:**
- Randomized (different runs → different results)
- Slower (~minutes for 100 iterations)
- Can find better partitions than pure greedy

## Region Naming

Regions are automatically named based on geographic location:

**North America:**
- `na-west-coast` - California, Oregon, Washington, BC
- `na-east-coast` - New York, Massachusetts, North Carolina
- `na-midwest` - Illinois, Ohio, Michigan, Indiana
- `na-southwest` - Arizona, New Mexico, West Texas

**Europe:**
- `europe-western` - UK, France, Spain, Portugal
- `europe-central` - Germany, Poland, Czech Republic, Austria
- `europe-northern` - Sweden, Norway, Finland

See `src/pack_planner/naming.py` for complete mappings.

## Dependencies

- `click`: CLI framework
- `h3`: H3 hexagonal indexing (Python bindings)
- `pyyaml`: YAML config parsing

## Testing

```bash
uv run pytest
```

## Performance

- **Input**: ~10,000 packs from density analysis
- **Greedy method**: ~5-10 seconds
- **Monte Carlo (100 iter)**: ~2-3 minutes
- **Memory usage**: <1 GB

## See Also

- [ebird-density-analyzer](../ebird-density-analyzer/) - Previous step: analyze density
- [ebird-region-pack-strategy.md](../../docs/ebird-region-pack-strategy.md) - Full design doc
