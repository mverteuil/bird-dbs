# EBD Pack Builder

Unified Python CLI for building eBird region packs for BirdNET-Pi.

## Overview

The `ebd-pack-builder` package consolidates the complete eBird processing pipeline into a single CLI tool with subcommands for each step. It replaces the previous collection of standalone scripts and the Rust POC.

## Features

- **Single CLI**: All pipeline steps via `ebd <command>`
- **State tracking**: JSON-based resumability across failures
- **Parallel builds**: Worker-based parallelization for pack building
- **Integrated planning**: Built-in region planning (no external pack-planner needed)
- **Release packaging**: Gzip compression with release-compatible naming

## Installation

```bash
cd bird-dbs/ebd-pack-builder
uv sync
```

## Commands

| Command | Description |
|---------|-------------|
| `ebd convert` | Convert eBird tarball to Parquet format |
| `ebd sort` | Sort data geographically by latitude bands |
| `ebd partition` | Partition data by H3 boundary cells |
| `ebd density-report` | Create density report for planning |
| `ebd plan` | Plan region packs from density report |
| `ebd size-manifest` | Create size manifest from built packs |
| `ebd build` | Build SQLite region packs |
| `ebd package` | Package packs for release (gzip compression) |
| `ebd verify` | Verify Parquet dataset integrity |
| `ebd status` | Show pipeline status |
| `ebd run-all` | Run complete pipeline |

## Quick Start

```bash
# Full pipeline
ebd convert --input /path/to/ebd.tar --output-dir ./parquet
ebd sort --input-dir ./parquet --output-dir ./sorted
ebd partition --input-dir ./sorted --output-dir ./partitioned
ebd density-report --boundary-cells ./partitioned/boundary_cells.json --output ./density.json
ebd plan --density-report ./density.json --output-manifest ./manifest.json --max-region-size-mb 80
ebd build --partitioned-dir ./partitioned --manifest ./manifest.json --output-dir ./packs
ebd package --packs-dir ./packs --registry ./pack_registry.json
```

## Region Sizing

The `plan` command groups H3 boundary cells into downloadable regions:

| Parameter | Value | Notes |
|-----------|-------|-------|
| **Hard maximum** | 150 MB | Uncompressed .db file |
| **Planning target** | 80 MB | Accounts for ~20% size underestimation |
| **Compressed size** | ~25% | Typical gzip compression ratio |

Use `--max-region-size-mb 80` to stay under the 150 MB limit.

## Production Results (Aug 2025)

- 250 regions globally
- Largest pack: 141 MB
- Total uncompressed: ~16 GB
- Total compressed: ~4 GB

## Architecture

```
src/ebd_pack_builder/
├── cli.py                    # Click CLI with subcommands
├── pipeline.py               # State management
├── steps/                    # Pipeline step modules
│   ├── convert_to_parquet.py
│   ├── sort_by_location.py
│   ├── partition_by_h3.py
│   ├── create_density_report.py
│   ├── plan_regions.py
│   ├── create_size_manifest.py
│   ├── build_region_packs.py
│   ├── package_packs.py
│   └── verify_integrity.py
├── models/                   # Pydantic models
└── utils/                    # Shared utilities
```

## Publishing

After packaging, use the `release-publisher` tool to upload to GitHub:

```bash
cd bird-dbs/release-publisher
uv run release-publisher \
    --registry ./pack_registry.json \
    --db-dir ./packs \
    --target-repo owner/birdnetpi-ebird-packs
```

See [release-publisher](./release-publisher.md) for details.

## See Also

- [Complete Pipeline Guide](../../README.md) - Full pipeline documentation
- [release-publisher](./release-publisher.md) - GitHub release automation
- [pack-manifest-visualizer](./pack-manifest-visualizer.md) - Coverage visualization
