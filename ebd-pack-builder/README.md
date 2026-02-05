# EBD Pack Builder

eBird Basic Dataset pack builder for BirdNET-Pi region packs.

Consolidates the eBird processing pipeline into a unified CLI with JSON-based state tracking for resumability.

## Installation

```bash
cd bird-dbs/ebd-pack-builder
uv sync
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `ebd convert` | Convert eBird tarball to Parquet format |
| `ebd sort` | Sort data geographically by latitude bands |
| `ebd partition` | Partition data by H3 boundary cells |
| `ebd density-report` | Create density report for pack-planner |
| `ebd size-manifest` | Create size manifest from built packs |
| `ebd build` | Build SQLite region packs |
| `ebd verify` | Verify Parquet dataset integrity |
| `ebd status` | Show pipeline status |
| `ebd run-all` | Run complete pipeline |

## Usage Examples

### Complete Pipeline

```bash
ebd run-all \
    --input /Volumes/backup/ebird/ebd_relAug-2025.tar \
    --output-dir /Volumes/Lightroom/ebd_pipeline \
    --pack-manifest ./pack_manifest.json \
    --state-dir ./ebd_state
```

### Step-by-Step Execution

```bash
# Step 1: Convert tarball to Parquet
ebd convert \
    --input /Volumes/backup/ebird/ebd_relAug-2025.tar \
    --output-dir ./ebird_parquet

# Step 2: Sort by geographic location
ebd sort \
    --input-dir ./ebird_parquet \
    --output-dir ./ebird_by_location \
    --sort-order location

# Step 3: Partition by H3 boundary cells
ebd partition \
    --input-dir ./ebird_by_location \
    --output-dir ./ebird_partitioned \
    --boundary-resolution 4

# Step 4: Create density report
ebd density-report \
    --boundary-cells ./ebird_partitioned/boundary_cells.json \
    --output ./density_report.json

# (Run pack-planner separately to create pack_manifest.json)

# Step 5: Build region packs
ebd build \
    --partitioned-dir ./ebird_partitioned \
    --manifest ./pack_manifest.json \
    --output-dir ./region_packs
```

### Resume After Failure

```bash
# Check status
ebd status --state-dir ./ebd_state

# Resume from a specific step
ebd run-all \
    --input /path/to/ebd.tar \
    --output-dir ./output \
    --pack-manifest ./manifest.json \
    --from-step partition
```

### Parallel Build

```bash
# Run 4 workers in parallel
ebd build --partitioned-dir ./partitioned --manifest ./manifest.json --output-dir ./packs --worker 0 --total-workers 4 &
ebd build --partitioned-dir ./partitioned --manifest ./manifest.json --output-dir ./packs --worker 1 --total-workers 4 &
ebd build --partitioned-dir ./partitioned --manifest ./manifest.json --output-dir ./packs --worker 2 --total-workers 4 &
ebd build --partitioned-dir ./partitioned --manifest ./manifest.json --output-dir ./packs --worker 3 --total-workers 4 &
wait
```

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      EBD Pack Builder Pipeline                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐             │
│  │  convert   │───▶│    sort    │───▶│ partition  │             │
│  │ tar→parquet│    │ by location│    │   by H3    │             │
│  └────────────┘    └────────────┘    └────────────┘             │
│                                              │                   │
│                                              ▼                   │
│                                    ┌────────────────┐           │
│                                    │ density-report │           │
│                                    └────────────────┘           │
│                                              │                   │
│                                              ▼                   │
│                                    ┌────────────────┐           │
│                                    │  pack-planner  │           │
│                                    │   (external)   │           │
│                                    └────────────────┘           │
│                                              │                   │
│                                              ▼                   │
│                                    ┌────────────────┐           │
│                                    │     build      │           │
│                                    │ region packs   │           │
│                                    └────────────────┘           │
│                                              │                   │
│                                              ▼                   │
│                                    ┌────────────────┐           │
│                                    │    verify      │           │
│                                    └────────────────┘           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## State Management

Pipeline state is stored in JSON format for resumability:

```json
{
  "pipeline_id": "ebd-pipeline",
  "steps": {
    "convert": {
      "status": "completed",
      "output_path": "/path/to/parquet",
      "metrics": {"total_rows": 399000000}
    },
    "sort": {
      "status": "running",
      "started_at": "2025-08-01T10:00:00"
    }
  }
}
```

## Development

```bash
# Install with dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Run linting
uv run ruff check src/
```

## License

MIT
