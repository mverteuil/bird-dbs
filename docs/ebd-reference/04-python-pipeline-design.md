# Python Pipeline Design: ebd-pack-builder

## Overview

A Python CLI tool (`ebd`) that processes the eBird Basic Dataset (~200GB) into H3 hexagonal grid-based region packs for BirdNET-Pi. The pipeline converts, sorts, partitions, plans, builds, and packages SQLite databases containing species frequency data organized by H3 boundary cells.

**See**: [06-grid-based-architecture.md](06-grid-based-architecture.md) for the full H3 grid architecture.

## Project Structure

```
ebd-pack-builder/
├── pyproject.toml
├── README.md
├── src/ebd_pack_builder/
│   ├── __init__.py
│   ├── cli.py                    # Click CLI with subcommands
│   ├── pipeline.py               # State management and orchestration
│   │
│   ├── steps/                    # One module per pipeline step
│   │   ├── convert_to_parquet.py # Step 1: Tar → Parquet
│   │   ├── sort_by_location.py   # Step 2: Geographic sorting
│   │   ├── partition_by_h3.py    # Step 3: H3 boundary partitioning
│   │   ├── create_density_report.py  # Step 4: Density report
│   │   ├── plan_regions.py       # Step 5: Region planning
│   │   ├── build_region_packs.py # Step 6: SQLite pack building
│   │   ├── package_packs.py      # Step 7: Gzip compression
│   │   └── verify_integrity.py   # Validation step
│   │
│   ├── models/                   # Pydantic models
│   │   ├── config.py             # PipelineConfig
│   │   ├── state.py              # PipelineState, StepResult
│   │   └── pack.py               # PackManifest, RegionPack
│   │
│   └── utils/                    # Shared utilities
│       ├── formatting.py         # Size/duration formatting
│       └── parquet_utils.py      # Parquet file discovery
│
└── tests/
```

## Dependencies

```toml
[project]
dependencies = [
  "click>=8.2.1",      # CLI framework
  "duckdb>=1.0.0",     # SQL analytics engine
  "h3>=3.7.0",         # H3 hexagonal indexing
  "polars>=1.0.0",     # DataFrame operations
  "pydantic>=2.0.0",   # Data validation
]
```

**Key technology choices:**
- **DuckDB**: SQL-based analytics on Parquet files without loading into memory
- **Polars**: Fast DataFrame operations for streaming conversion
- **H3**: Uber's hexagonal hierarchical spatial index
- **Click**: Composable CLI with subcommands

## Pipeline Stages

### Stage 1: Convert (Tar → Parquet)

Streams eBird TSV directly from tarball to Parquet without extraction.

```python
# steps/convert_to_parquet.py
def convert_tarball_to_parquet(
    input_path: Path,
    output_dir: Path,
    chunk_size: int = 1_000_000,
) -> dict:
    """Stream tar → gzip → TSV → Parquet."""
    with tarfile.open(input_path, "r:") as tar:
        for member in tar:
            if member.name.endswith(".txt.gz"):
                with gzip.open(tar.extractfile(member), "rt") as f:
                    reader = csv.reader(f, delimiter="\t")
                    # Process in chunks using Polars
                    for chunk in chunked(reader, chunk_size):
                        df = pl.DataFrame(chunk, schema=EBD_SCHEMA)
                        df.write_parquet(output_dir / f"chunk_{i}.parquet")
```

**Input:** `ebd_relAug-2025.tar` (201GB)
**Output:** `ebird_parquet/` (~118GB, 399 files)
**Memory:** Constant ~2GB (streaming)

### Stage 2: Sort by Location

Sorts data geographically using latitude-band partitioning.

```python
# steps/sort_by_location.py
def sort_chunked(
    input_dir: Path,
    output_dir: Path,
    sort_order: str = "location",
    memory_limit: str = "24GB",
) -> dict:
    """Sort by latitude bands, then by location within each band."""
    # Define latitude bands (18 partitions)
    bands = [(-90, -60), (-60, -40), ..., (60, 90)]

    for band_min, band_max in bands:
        # Use DuckDB to filter and sort
        con = duckdb.connect()
        con.execute(f"""
            COPY (
                SELECT * FROM read_parquet('{input_dir}/*.parquet')
                WHERE latitude >= {band_min} AND latitude < {band_max}
                ORDER BY latitude, longitude
            ) TO '{output_dir}/band_{band_min}_{band_max}.parquet'
        """)
```

**Input:** `ebird_parquet/` (118GB)
**Output:** `ebird_by_location/` (~25GB, 18 partitions)
**Temp space:** Up to 200GB per partition

### Stage 3: Partition by H3 Boundary Cells

Partitions data into Hive-style directories by H3 cell.

```python
# steps/partition_by_h3.py
def partition_by_h3(
    input_dir: Path,
    output_dir: Path,
    boundary_resolution: int = 4,
) -> dict:
    """Partition by H3 boundary cell at resolution 4."""
    con = duckdb.connect()

    # Add H3 cell column and partition
    con.execute(f"""
        COPY (
            SELECT *,
                   h3_latlng_to_cell(latitude, longitude, {boundary_resolution})
                   AS boundary_cell
            FROM read_parquet('{input_dir}/*.parquet')
        ) TO '{output_dir}'
        (FORMAT PARQUET, PARTITION_BY (boundary_cell))
    """)
```

**Input:** `ebird_by_location/` (25GB)
**Output:** Hive-partitioned structure:
```
ebird_partitioned/
├── boundary_cell=842b9bdffffffff/
│   └── data_0.parquet
├── boundary_cell=842b9adffffffff/
│   └── data_0.parquet
└── ...
```

### Stage 4: Create Density Report

Generates statistics for each boundary cell.

```python
# steps/create_density_report.py
def create_density_report(
    boundary_cells_path: Path,
    output_path: Path,
) -> None:
    """Convert boundary cell stats to density report format."""
    with open(boundary_cells_path) as f:
        cells = json.load(f)

    report = {
        "resolution": 4,
        "cells": [
            {
                "cell_id": cell["cell_id"],
                "checklist_count": cell["checklist_count"],
                "observation_count": cell["observation_count"],
                "estimated_pack_size_mb": estimate_size(cell),
                "recommended_resolution": recommend_resolution(cell),
            }
            for cell in cells
        ]
    }

    with open(output_path, "w") as f:
        json.dump(report, f)
```

### Stage 5: Plan Regions

Groups boundary cells into downloadable regions.

```python
# steps/plan_regions.py
def plan_regions(
    density_report_path: Path,
    output_manifest_path: Path,
    output_registry_path: Path | None,
    max_region_size_mb: float = 80.0,  # Target 80MB → actual <150MB
    grouping_resolution: int = 2,
) -> dict:
    """Group boundary cells into regions under size limit."""
    with open(density_report_path) as f:
        density = json.load(f)

    # Group cells by H3 resolution 2 parent
    groups = defaultdict(list)
    for cell in density["cells"]:
        parent = h3.cell_to_parent(cell["cell_id"], grouping_resolution)
        groups[parent].append(cell)

    # Merge adjacent groups until size limit reached
    regions = []
    for parent, cells in groups.items():
        total_size = sum(c["estimated_pack_size_mb"] for c in cells)
        if total_size <= max_region_size_mb:
            regions.append(create_region(parent, cells))
        else:
            # Split by latitude bands
            regions.extend(split_region(parent, cells, max_region_size_mb))

    return {"regions": regions}
```

**Sizing strategy:**
- Hard maximum: 150 MB (uncompressed .db)
- Planning target: 80 MB (accounts for ~20% estimation error)
- Result: ~250 regions globally

### Stage 6: Build Region Packs

Builds SQLite databases for each region.

```python
# steps/build_region_packs.py
def build_region_packs(
    partitioned_dir: Path,
    manifest_path: Path,
    output_dir: Path,
    region: str | None = None,
    skip_existing: bool = False,
) -> dict:
    """Build SQLite region packs from partitioned data."""
    with open(manifest_path) as f:
        manifest = json.load(f)

    for region_def in manifest["regions"]:
        if region and region_def["region_id"] != region:
            continue

        db_path = output_dir / f"{region_def['region_id']}.db"
        if skip_existing and db_path.exists():
            continue

        # Create SQLite database
        con = sqlite3.connect(db_path)
        create_schema(con)

        # Load data for all boundary cells in this region
        for cell_id in region_def["boundary_cells"]:
            cell_dir = partitioned_dir / f"boundary_cell={cell_id}"
            if cell_dir.exists():
                load_cell_data(con, cell_dir, cell_id)

        # Write region metadata
        write_metadata(con, region_def)
        con.close()
```

**Output schema (3 tables):**
```sql
-- Region-level metadata
CREATE TABLE region_metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Per-cell statistics
CREATE TABLE grid_metadata (
    h3_cell TEXT PRIMARY KEY,
    resolution INTEGER,
    center_lat REAL,
    center_lon REAL,
    total_checklists INTEGER,
    data_quality TEXT
);

-- Species per cell
CREATE TABLE grid_species (
    h3_cell TEXT,
    scientific_name TEXT,
    common_name TEXT,
    yearly_frequency REAL,
    confidence_tier TEXT,
    monthly_frequency_json TEXT,
    PRIMARY KEY (h3_cell, scientific_name)
);
```

### Stage 7: Package for Release

Gzip compresses packs with release-compatible naming.

```python
# steps/package_packs.py
def package_packs(
    packs_dir: Path,
    registry_path: Path,
    compression_level: int = 6,
) -> dict:
    """Gzip all .db files with release naming."""
    with open(registry_path) as f:
        registry = json.load(f)

    for region in registry["regions"]:
        db_file = packs_dir / f"{region['region_id']}.db"
        gz_file = packs_dir / f"{region['release_name']}.db.gz"

        with open(db_file, "rb") as f_in:
            with gzip.open(gz_file, "wb", compresslevel=compression_level) as f_out:
                shutil.copyfileobj(f_in, f_out)
```

**Compression results (Aug 2025):**
- Uncompressed: ~16 GB
- Compressed: ~4 GB
- Ratio: ~25%

## CLI Interface

```bash
# Individual steps
ebd convert --input ebd.tar --output-dir ./parquet
ebd sort --input-dir ./parquet --output-dir ./sorted
ebd partition --input-dir ./sorted --output-dir ./partitioned
ebd density-report --boundary-cells ./partitioned/boundary_cells.json --output ./density.json
ebd plan --density-report ./density.json --output-manifest ./manifest.json --max-region-size-mb 80
ebd build --partitioned-dir ./partitioned --manifest ./manifest.json --output-dir ./packs
ebd package --packs-dir ./packs --registry ./pack_registry.json

# Full pipeline with state tracking
ebd run-all --input ebd.tar --output-dir ./pipeline --state-dir ./state

# Resume from failure
ebd run-all --input ebd.tar --output-dir ./pipeline --from-step partition

# Parallel building
ebd build ... --worker 0 --total-workers 4 &
ebd build ... --worker 1 --total-workers 4 &
ebd build ... --worker 2 --total-workers 4 &
ebd build ... --worker 3 --total-workers 4 &
wait
```

## State Management

JSON-based state tracking enables resumability:

```json
{
  "pipeline_id": "ebd-pipeline",
  "steps": {
    "convert": {
      "status": "completed",
      "output_path": "/path/to/parquet",
      "completed_at": "2025-08-01T12:00:00",
      "metrics": {"total_rows": 399000000}
    },
    "sort": {
      "status": "running",
      "started_at": "2025-08-01T14:00:00"
    },
    "partition": {
      "status": "pending"
    }
  }
}
```

## Performance Characteristics

| Stage | Duration | Memory | Disk I/O |
|-------|----------|--------|----------|
| convert | 12+ hours | 2 GB | Read 200GB, Write 118GB |
| sort | 6+ hours | 24 GB | Read 118GB, Write 25GB + 200GB temp |
| partition | 2.5 hours | 16 GB | Read 25GB, Write 50GB |
| density-report | seconds | 1 GB | Read JSON |
| plan | seconds | 1 GB | Read/Write JSON |
| build | 8-10 hours | 4 GB | Read 50GB, Write 16GB |
| package | 30 min | 1 GB | Read 16GB, Write 4GB |

**Total:** ~30 hours for full pipeline

## Key Design Decisions

### Why Python over Rust?

The original Rust POC was replaced with Python for:
- **DuckDB integration**: SQL-based analytics without loading data into memory
- **Polars performance**: Near-Rust speed for DataFrame operations
- **Ecosystem**: Better library support for H3, Parquet, SQLite
- **Maintainability**: Easier to modify and extend
- **Production proven**: Successfully processed 399M rows

### Why DuckDB?

- **Zero-copy Parquet reads**: Query directly without loading
- **SQL interface**: Familiar syntax for complex aggregations
- **Partitioned writes**: Native Hive-style partitioning
- **Memory efficient**: Streaming execution for large datasets

### Why Latitude-Band Sorting?

- **Locality preservation**: Nearby observations stay together
- **Partition independence**: Each band can be processed separately
- **Temp space control**: ~200GB per band vs ~2TB for global sort
- **Resume capability**: Skip completed bands on failure

### Why 80MB Planning Target?

Size estimation based on checklist counts is approximately 20% low:
- Planning at 80MB → Actual packs 100-140MB
- All packs stay under 150MB hard limit
- Compressed size ~25% (4GB total for 250 regions)

## Error Handling

```python
class PipelineManager:
    def start_step(self, step_name: str):
        self.state["steps"][step_name] = {
            "status": "running",
            "started_at": datetime.now().isoformat()
        }
        self.save_state()

    def complete_step(self, step_name: str, output_path: Path, metrics: dict):
        self.state["steps"][step_name] = {
            "status": "completed",
            "output_path": str(output_path),
            "completed_at": datetime.now().isoformat(),
            "metrics": metrics
        }
        self.save_state()

    def fail_step(self, step_name: str, error: str):
        self.state["steps"][step_name] = {
            "status": "failed",
            "error": error,
            "failed_at": datetime.now().isoformat()
        }
        self.save_state()
```

## Integration with Release Publisher

After packaging, the `release-publisher` tool uploads to GitHub:

```bash
cd release-publisher
uv run release-publisher \
    --registry ./pack_registry.json \
    --db-dir ./packs \
    --target-repo owner/birdnetpi-ebird-packs
```

The publisher:
- Bundles packs into ≤1950MB releases
- Adds eBird attribution
- Updates registry with download URLs
- Creates global registry release

## Production Results (August 2025)

- **Input**: 399 million eBird observations
- **Output**: 250 region packs
- **Largest pack**: 141 MB (uncompressed)
- **Total size**: 16 GB uncompressed, 4 GB compressed
- **Published to**: `mverteuil/birdnetpi-ebird-packs`
