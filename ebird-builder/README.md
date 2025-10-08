# BirdNET-Pi eBird Region Pack Generator (POC)

A Rust CLI tool to generate H3 hexagonal grid-based region packs from eBird data for use with BirdNET-Pi.

## Overview

This tool processes eBird observation data and creates SQLite databases containing species occurrence information organized in H3 hexagonal grids (~5km resolution). Each hexagon has its own species frequency data, enabling neighborhood-level spatial precision for bird detection filtering.

## Features

- **H3 Hexagonal Grids**: Uses Uber's H3 geospatial indexing for uniform hexagonal cells
- **Neighborhood-Level Precision**: ~5km resolution provides Merlin Bird ID-like accuracy
- **SQLite Output**: Fast-loading databases with three-table schema
- **Flexible Filtering**: Geographic, temporal, and quality filters
- **Confidence Tiers**: Classifies species as common/uncommon/rare/vagrant
- **Monthly Patterns**: Tracks seasonal frequency variations

## Installation

```bash
cargo build --release
```

## Usage

### Basic Usage

```bash
cargo run --release -- \
  --input sample_data.tsv \
  --config examples/sf-bay-area.yaml \
  --output sf-bay-area-h3.db
```

### Configuration File

Create a YAML configuration file (see `examples/sf-bay-area.yaml`):

```yaml
region_id: us-ca-sf-bay-h3
region_name: San Francisco Bay Area (H3 Grid)
region_type: metro
h3_resolution: 7  # ~5km hexagons

bounding_box:
  min_latitude: 37.4
  max_latitude: 38.0
  min_longitude: -122.5
  max_longitude: -121.8

date_range:
  start: 2020-01-01
  end: 2025-12-31

filters:
  approved_only: true
  complete_checklists_only: true
  native_species_only: true
  min_observations: 5
  min_checklists: 3
  min_yearly_frequency: 0.01
  deduplication: group_identifier
```

### Input Data Format

Expects eBird Basic Dataset (EBD) format as tab-delimited CSV with these columns:

- SCIENTIFIC NAME
- COMMON NAME
- OBSERVATION COUNT
- LATITUDE
- LONGITUDE
- OBSERVATION DATE
- SAMPLING EVENT IDENTIFIER
- GROUP IDENTIFIER
- ALL SPECIES REPORTED
- APPROVED
- CATEGORY
- EXOTIC CODE

## Output Database Schema

The generated SQLite database has three tables:

### region_metadata

Key-value pairs with pack metadata (version, region info, filters, etc.)

### grid_metadata

Per-hexagon statistics:
- `h3_cell` (BIGINT): H3 cell index
- `resolution` (INTEGER): H3 resolution (7 = ~5km)
- `center_lat`, `center_lon` (REAL): Hexagon center
- `total_checklists`, `complete_checklists`, `total_observations`
- `date_range_start`, `date_range_end`
- `data_quality`: excellent/good/fair/sparse

### grid_species

Species occurrence per hexagon:
- `h3_cell` (BIGINT): Foreign key to grid_metadata
- `scientific_name`, `common_name`
- `yearly_frequency`: Proportion of complete checklists
- `total_observations`, `total_checklists`: For this hexagon
- `first_observation`, `last_observation`
- `confidence_tier`: common/uncommon/rare/vagrant
- `confidence_boost`: Multiplier (1.0-1.3)
- `monthly_frequency_json`: Array[12] of monthly frequencies
- `monthly_observations_json`: Array[12] of monthly counts

## Querying the Output

```bash
# Get total hexagons
sqlite3 output.db "SELECT COUNT(*) FROM grid_metadata;"

# Get species in specific hexagon for June
sqlite3 output.db "SELECT scientific_name, common_name,
  json_extract(monthly_frequency_json, '$[5]') AS june_freq
FROM grid_species
WHERE h3_cell = 617700169958293503
AND json_extract(monthly_frequency_json, '$[5]') > 0.1;"

# Get pack metadata
sqlite3 output.db "SELECT * FROM region_metadata;"
```

## H3 Resolution Levels

- Resolution 6: ~36 km² (~6.6km edge) - Sparse areas
- Resolution 7: ~5.16 km² (~2.5km edge) - Standard (recommended)
- Resolution 8: ~0.74 km² (~0.9km edge) - Dense urban areas
- Resolution 9: ~0.11 km² (~0.35km edge) - Very fine-grained

## Integration with BirdNET-Pi

Copy the generated database to BirdNET-Pi:

```bash
cp output.db ~/birdnet-pi/region_packs/
```

Configure BirdNET-Pi (in `birdnet.yaml`):

```yaml
enable_ebird_filtering: true
ebird_region_pack: region_packs/sf-bay-area-h3.db
ebird_h3_resolution: 7
ebird_neighbor_radius: 1  # k_ring=1 (center + 6 neighbors)
ebird_filter_mode: supplement
ebird_min_frequency: 0.01
```

## Architecture

- **src/config.rs**: Configuration structures (YAML deserialization)
- **src/ebird/record.rs**: eBird record parsing and filtering
- **src/h3/grid.rs**: H3 grid operations (lat/lon ↔ cell conversion)
- **src/h3/aggregator.rs**: Per-hexagon species aggregation
- **src/db/writer.rs**: SQLite database generation
- **src/main.rs**: CLI and main processing loop

## Dependencies

- `h3o`: Pure Rust H3 implementation (no C bindings)
- `rusqlite`: SQLite database library
- `serde`/`serde_yaml`: Configuration parsing
- `chrono`: Date handling
- `clap`: CLI argument parsing

## Limitations (POC)

- **Memory-based processing**: Loads all data into memory (not streaming)
- **Simple TSV input**: No tar.gz support yet
- **Basic fields**: Simplified eBird record structure
- **No progress bars**: Just log output
- **Single-threaded**: No parallel processing

## Future Enhancements

- Streaming tar.gz support for full EBD (~200GB)
- Parallel processing by hexagon
- Progress bars with indicatif
- Distance-weighted confidence adjustments using neighbor hexagons
- Multi-resolution packs (6+7+8) in single database
- Sampling dataset integration for true absence data

## Testing

```bash
# Run unit tests
cargo test

# Run with sample data
cargo run --release -- \
  --input examples/sample_data.tsv \
  --config examples/sf-bay-area.yaml \
  --output test_output.db
```

## License

TBD

## Acknowledgments

- **Cornell Lab of Ornithology** - eBird Basic Dataset
- **Patrick McGuire** - BirdNET-Pi creator
- **Stefan Kahl** - BirdNET model
- **Uber Technologies** - H3 Hexagonal Hierarchical Geospatial Indexing System
