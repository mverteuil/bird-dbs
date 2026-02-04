# eBird Density Analyzer

Analyze eBird observation data to determine geographic density patterns for optimal region pack generation.

## Overview

This tool processes the eBird Basic Dataset (EBD) and generates density reports showing checklist counts per H3 hexagonal cell at multiple resolutions. These reports inform the pack planning process for distributing region packs via GitHub releases.

## Features

- **Multi-resolution analysis**: Analyze at resolutions 2-5 simultaneously
- **Two-pass mode**: Memory-efficient processing for billion-record datasets (constant ~50MB RAM)
- **Terminal UI**: Real-time progress visualization with scrollable logs
- **Streaming processing**: Handles 200GB+ tar.gz eBird archives efficiently
- **Quality filtering**: Applies standard eBird quality filters (approved, complete, native, species-only)
- **Size estimation**: Predicts pack database sizes based on density
- **Sampling support**: Optional sampling for faster exploratory analysis

## Installation

```bash
cd analysis/ebird-density-analyzer
cargo build --release
```

## Usage

### Basic Usage

```bash
./target/release/ebird-density-analyzer \
  --input /Volumes/backup/ebird/ebd_relAug-2025.tar.gz \
  --resolutions 2,3,4,5 \
  --output density_reports/
```

### With Sampling (for testing)

```bash
./target/release/ebird-density-analyzer \
  --input /Volumes/backup/ebird/ebd_relAug-2025.tar.gz \
  --resolutions 2,3,4 \
  --sample-rate 0.1 \
  --output density_reports/
```

### Plain TSV Input

```bash
./target/release/ebird-density-analyzer \
  --input sample_data.tsv \
  --resolutions 2,3,4,5 \
  --output density_reports/
```

### Two-Pass Mode (For Large Datasets)

For memory-constrained environments or billion-record datasets, use two-pass mode:

```bash
./target/release/ebird-density-analyzer \
  --input /Volumes/backup/ebird/ebd_relAug-2025.tar \
  --resolutions 2,3,4,5 \
  --output density_reports/ \
  --two-pass \
  --temp-dir /Volumes/backup/ebird/temp/
```

**With Terminal UI** (recommended for interactive sessions):

```bash
./target/release/ebird-density-analyzer \
  --input /Volumes/backup/ebird/ebd_relAug-2025.tar \
  --resolutions 2,3,4,5 \
  --output density_reports/ \
  --two-pass \
  --temp-dir /Volumes/backup/ebird/temp/ \
  --tui
```

The TUI displays:
- Real-time progress bar with phase info (Pass 1, Sorting, Pass 2)
- Scrollable log window with color-coded messages
- Live metrics (records read, pairs written, filtered counts)
- Elapsed time

Press **'q'** to quit the TUI display.

See [PROGRESS.md](PROGRESS.md) for detailed progress feedback documentation.

## Output Format

Generates JSON files for each resolution:

**density_reports/global_density_res4.json:**
```json
{
  "resolution": 4,
  "cells": [
    {
      "h3_cell": "599686042433355775",
      "center_lat": 37.7749,
      "center_lon": -122.4194,
      "unique_checklists": 45678,
      "complete_checklists": 32145,
      "total_observations": 1234567,
      "date_range_start": "2010-01-01",
      "date_range_end": "2025-08-31",
      "estimated_pack_size_mb": 8.2,
      "recommended_data_resolution": 7
    }
  ]
}
```

## Quality Filters

The analyzer applies standard eBird filters:
- ✅ Approved observations only
- ✅ Complete checklists only (all species reported)
- ✅ Native species only (excludes exotics)
- ✅ Species-level only (excludes hybrids, subspecies, etc.)

## Performance

### Single-Pass Mode (Default)
- **Full EBD (~200GB)**: ~2-4 hours on modern hardware
- **Memory usage**: ~4-8 GB RAM (holds all data in memory)
- **Sample rate 0.1**: ~20-30 minutes (10% of data)

### Two-Pass Mode (--two-pass)
- **Full EBD (~1 billion records)**: ~5-6 hours
  - Pass 1: 2-3 hours (extract pairs)
  - Sort: 1-2 hours (external sort)
  - Pass 2: 1 hour (aggregate)
- **Memory usage**: Constant ~10-50 MB (regardless of dataset size)
- **Disk usage**: ~450 GB peak during sort (225 GB pairs + 225 GB sorted)
- **Ideal for**: Memory-constrained environments, very large datasets

## Algorithm

1. Stream through eBird tar.gz archive
2. Parse TSV records (tab-delimited eBird format)
3. Apply quality filters
4. Convert lat/lon to H3 cells at specified resolutions
5. Aggregate checklists per cell
6. Estimate pack sizes based on density
7. Output JSON reports

## Dependencies

- `h3o`: H3 hexagonal indexing
- `csv`: TSV parsing
- `tar` + `flate2`: Archive decompression
- `ratatui` + `crossterm`: Terminal UI (TUI)
- `serde_json`: JSON output

## Testing

```bash
cargo test
```

## See Also

- [pack-planner](../pack-planner/) - Next step: partition cells into regions
- [ebird-region-pack-strategy.md](../../docs/ebird-region-pack-strategy.md) - Full design doc
