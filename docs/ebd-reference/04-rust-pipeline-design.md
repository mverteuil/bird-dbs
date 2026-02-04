# Rust Pipeline Design: ebird-region-pack

## Overview

A Rust CLI tool to generate H3 hexagonal grid-based region packs from eBird Basic Dataset tarballs by streaming, filtering, aggregating by H3 cells, and serializing to SQLite databases.

**See**: [06-grid-based-architecture.md](06-grid-based-architecture.md) for the full H3 grid architecture.

## Project Structure

```
ebird-region-pack/
├── Cargo.toml
├── README.md
├── src/
│   ├── main.rs              # CLI entry point
│   ├── lib.rs               # Library exports
│   ├── config.rs            # Configuration models
│   ├── ebird/
│   │   ├── mod.rs
│   │   ├── record.rs        # eBird record parsing
│   │   ├── reader.rs        # Tar.gz streaming
│   │   └── filter.rs        # Geographic/temporal filtering
│   ├── h3/
│   │   ├── mod.rs
│   │   ├── grid.rs          # H3 cell operations
│   │   └── aggregator.rs    # H3-based species aggregation
│   ├── aggregation/
│   │   ├── mod.rs
│   │   ├── species.rs       # Species-level aggregation per H3 cell
│   │   └── temporal.rs      # Monthly frequency calculation
│   ├── region/
│   │   ├── mod.rs
│   │   ├── pack.rs          # Region pack model (H3 grid)
│   │   └── writer.rs        # SQLite database creation (3-table schema)
│   └── utils/
│       ├── mod.rs
│       ├── geography.rs     # Bounding box, distance calc
│       └── validation.rs    # Data validation
├── tests/
│   ├── integration_tests.rs
│   └── fixtures/
│       └── sample_ebd.tar.gz
└── examples/
    ├── simple_region.rs
    └── batch_generation.rs
```

## Dependencies (Cargo.toml)

```toml
[package]
name = "ebird-region-pack"
version = "0.1.0"
edition = "2021"

[dependencies]
# Database
rusqlite = { version = "0.32", features = ["bundled"] }
serde_json = "1.0"  # For JSON array serialization in SQLite

# H3 hexagonal grid
h3o = "0.6"  # Pure Rust H3 implementation (no C bindings)

# Serialization (for config parsing)
serde = { version = "1.0", features = ["derive"] }

# Tar & Compression
tar = "0.4"
flate2 = "1.0"

# CLI
clap = { version = "4.5", features = ["derive"] }

# Date/Time
chrono = { version = "0.4", features = ["serde"] }

# Parallel processing
rayon = "1.10"

# Error handling
anyhow = "1.0"
thiserror = "1.0"

# Logging
env_logger = "0.11"
log = "0.4"

# Geography (optional)
geo = { version = "0.28", optional = true }

# Progress bars
indicatif = "0.17"

[dev-dependencies]
tempfile = "3.10"
```

## Core Data Structures

### eBird Record

```rust
// src/ebird/record.rs
use chrono::NaiveDate;
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize)]
pub struct EBirdRecord {
    #[serde(rename = "SCIENTIFIC NAME")]
    pub scientific_name: String,

    #[serde(rename = "COMMON NAME")]
    pub common_name: String,

    #[serde(rename = "OBSERVATION COUNT")]
    pub observation_count: ObservationCount,

    #[serde(rename = "LATITUDE")]
    pub latitude: f64,

    #[serde(rename = "LONGITUDE")]
    pub longitude: f64,

    #[serde(rename = "OBSERVATION DATE")]
    pub observation_date: NaiveDate,

    #[serde(rename = "SAMPLING EVENT IDENTIFIER")]
    pub sampling_event_id: String,

    #[serde(rename = "GROUP IDENTIFIER")]
    pub group_identifier: Option<String>,

    #[serde(rename = "ALL SPECIES REPORTED")]
    pub all_species_reported: bool,

    #[serde(rename = "APPROVED")]
    pub approved: bool,

    #[serde(rename = "CATEGORY")]
    pub category: String,

    #[serde(rename = "EXOTIC CODE")]
    pub exotic_code: Option<String>,
}

#[derive(Debug, Clone)]
pub enum ObservationCount {
    Count(u32),
    Present, // 'X' in data
}

impl<'de> Deserialize<'de> for ObservationCount {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where D: serde::Deserializer<'de> {
        let s = String::deserialize(deserializer)?;
        match s.as_str() {
            "X" => Ok(ObservationCount::Present),
            _ => s.parse::<u32>()
                .map(ObservationCount::Count)
                .map_err(serde::de::Error::custom),
        }
    }
}
```

### Configuration

```rust
// src/config.rs
use chrono::NaiveDate;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RegionConfig {
    pub region_id: String,
    pub region_name: String,
    pub region_type: RegionType,
    pub h3_resolution: u8,         // H3 resolution (6, 7, 8, 9)
    pub bounding_box: BoundingBox,
    pub date_range: DateRange,
    pub filters: FilterConfig,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub enum RegionType {
    Custom,
    State,
    County,
    BCR,
    IBA,
    Country,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct BoundingBox {
    pub min_latitude: f64,
    pub max_latitude: f64,
    pub min_longitude: f64,
    pub max_longitude: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct DateRange {
    pub start: NaiveDate,
    pub end: NaiveDate,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct FilterConfig {
    pub approved_only: bool,
    pub complete_checklists_only: bool,
    pub native_species_only: bool,
    pub min_observations: u32,
    pub min_checklists: u32,
    pub min_yearly_frequency: f64,
    pub deduplication: DeduplicationMode,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub enum DeduplicationMode {
    GroupIdentifier,
    SamplingEvent,
    None,
}
```

### H3 Grid Data Structures

```rust
// src/h3/grid.rs
use h3o::{CellIndex, LatLng, Resolution};
use anyhow::Result;

pub struct H3Grid {
    resolution: Resolution,
}

impl H3Grid {
    pub fn new(resolution: u8) -> Result<Self> {
        Ok(Self {
            resolution: Resolution::try_from(resolution)?,
        })
    }

    pub fn lat_lon_to_cell(&self, lat: f64, lon: f64) -> Result<CellIndex> {
        let coord = LatLng::new(lat, lon)?;
        Ok(coord.to_cell(self.resolution))
    }

    pub fn cell_to_lat_lon(&self, cell: CellIndex) -> (f64, f64) {
        let coord: LatLng = cell.into();
        (coord.lat(), coord.lng())
    }

    pub fn cell_to_i64(&self, cell: CellIndex) -> i64 {
        // Convert H3 CellIndex to 64-bit integer for SQLite storage
        u64::from(cell) as i64
    }

    pub fn i64_to_cell(&self, value: i64) -> Result<CellIndex> {
        CellIndex::try_from(value as u64)
    }
}

// src/h3/aggregator.rs
use std::collections::HashMap;
use h3o::CellIndex;
use crate::ebird::record::EBirdRecord;
use crate::aggregation::species::SpeciesAccumulator;

pub struct H3Aggregator {
    pub h3_cells: HashMap<CellIndex, H3CellData>,
    pub resolution: u8,
}

pub struct H3CellData {
    pub h3_cell: CellIndex,
    pub center_lat: f64,
    pub center_lon: f64,
    pub species: HashMap<String, SpeciesAccumulator>,
    pub total_checklists: HashSet<String>,
    pub complete_checklists: HashSet<String>,
    pub date_range_start: Option<NaiveDate>,
    pub date_range_end: Option<NaiveDate>,
}

impl H3Aggregator {
    pub fn new(resolution: u8) -> Self {
        Self {
            h3_cells: HashMap::new(),
            resolution,
        }
    }

    pub fn add_record(&mut self, record: EBirdRecord) -> Result<()> {
        let grid = H3Grid::new(self.resolution)?;
        let h3_cell = grid.lat_lon_to_cell(record.latitude, record.longitude)?;

        let cell_data = self.h3_cells.entry(h3_cell).or_insert_with(|| {
            let (lat, lon) = grid.cell_to_lat_lon(h3_cell);
            H3CellData::new(h3_cell, lat, lon)
        });

        cell_data.add_observation(record);
        Ok(())
    }

    pub fn finalize(self, config: &FilterConfig) -> Vec<GridCellPack> {
        self.h3_cells
            .into_iter()
            .map(|(cell, data)| data.finalize(cell, config))
            .collect()
    }
}

impl H3CellData {
    pub fn new(h3_cell: CellIndex, center_lat: f64, center_lon: f64) -> Self {
        Self {
            h3_cell,
            center_lat,
            center_lon,
            species: HashMap::new(),
            total_checklists: HashSet::new(),
            complete_checklists: HashSet::new(),
            date_range_start: None,
            date_range_end: None,
        }
    }

    pub fn add_observation(&mut self, record: EBirdRecord) {
        // Track checklist IDs
        let checklist_id = record.group_identifier
            .clone()
            .unwrap_or(record.sampling_event_id.clone());

        self.total_checklists.insert(checklist_id.clone());

        if record.all_species_reported {
            self.complete_checklists.insert(checklist_id.clone());
        }

        // Update date range
        self.date_range_start = Some(
            self.date_range_start
                .map(|d| d.min(record.observation_date))
                .unwrap_or(record.observation_date)
        );
        self.date_range_end = Some(
            self.date_range_end
                .map(|d| d.max(record.observation_date))
                .unwrap_or(record.observation_date)
        );

        // Add to species accumulator
        let species = self.species
            .entry(record.scientific_name.clone())
            .or_insert_with(|| SpeciesAccumulator::new(
                record.scientific_name.clone(),
                record.common_name.clone()
            ));

        species.add_record(record);
    }
}
```

### Region Pack Output

```rust
// src/region/pack.rs
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegionPack {
    pub version: String,
    pub region_id: String,
    pub generated_at: DateTime<Utc>,
    pub generator: String,
    pub source_data: SourceMetadata,
    pub region: RegionInfo,
    pub filters_applied: FiltersSummary,
    pub species_count: usize,
    pub species: Vec<SpeciesData>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpeciesData {
    pub scientific_name: String,
    pub common_name: String,
    pub occurrence: OccurrenceData,
    pub temporal: TemporalData,
    pub filtering: FilteringData,
    pub metadata: Option<SpeciesMetadata>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OccurrenceData {
    pub yearly_frequency: f64,
    pub total_observations: u32,
    pub total_checklists: u32,
    pub first_observation: NaiveDate,
    pub last_observation: NaiveDate,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TemporalData {
    pub monthly_frequency: [f64; 12],
    pub monthly_observations: [u32; 12],
    pub peak_months: Vec<u8>,
    pub breeding_season: Vec<u8>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FilteringData {
    pub confidence_boost: f64,
    pub priority: SpeciesPriority,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum SpeciesPriority {
    Common,
    Uncommon,
    Rare,
    Vagrant,
}
```

## Processing Pipeline

### 1. Tar.gz Streaming

```rust
// src/ebird/reader.rs
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;
use tar::Archive;
use flate2::read::GzDecoder;
use anyhow::Result;

pub struct EBirdReader {
    archive: Archive<File>,
}

impl EBirdReader {
    pub fn new(tarball_path: &Path) -> Result<Self> {
        let file = File::open(tarball_path)?;
        let archive = Archive::new(file);
        Ok(Self { archive })
    }

    pub fn stream_records<F>(&mut self, mut callback: F) -> Result<()>
    where
        F: FnMut(EBirdRecord) -> Result<()>,
    {
        for entry in self.archive.entries()? {
            let entry = entry?;
            let path = entry.path()?;

            // Find the main data file (ends with .txt.gz)
            if path.to_str().unwrap().ends_with(".txt.gz") {
                let gz = GzDecoder::new(entry);
                let reader = BufReader::new(gz);

                self.parse_tsv(reader, callback)?;
                break;
            }
        }
        Ok(())
    }

    fn parse_tsv<R, F>(&self, reader: R, mut callback: F) -> Result<()>
    where
        R: BufRead,
        F: FnMut(EBirdRecord) -> Result<()>,
    {
        let mut rdr = csv::ReaderBuilder::new()
            .delimiter(b'\t')
            .from_reader(reader);

        for result in rdr.deserialize() {
            let record: EBirdRecord = result?;
            callback(record)?;
        }

        Ok(())
    }
}
```

### 2. Geographic Filtering

```rust
// src/ebird/filter.rs
use crate::config::{BoundingBox, DateRange};
use crate::ebird::record::EBirdRecord;

pub struct RecordFilter {
    bbox: BoundingBox,
    date_range: DateRange,
    approved_only: bool,
    complete_only: bool,
    native_only: bool,
}

impl RecordFilter {
    pub fn new(
        bbox: BoundingBox,
        date_range: DateRange,
        approved_only: bool,
        complete_only: bool,
        native_only: bool,
    ) -> Self {
        Self {
            bbox,
            date_range,
            approved_only,
            complete_only,
            native_only,
        }
    }

    pub fn matches(&self, record: &EBirdRecord) -> bool {
        // Geographic filter
        if !self.in_bounding_box(record) {
            return false;
        }

        // Temporal filter
        if !self.in_date_range(record) {
            return false;
        }

        // Quality filters
        if self.approved_only && !record.approved {
            return false;
        }

        if self.complete_only && !record.all_species_reported {
            return false;
        }

        if self.native_only && record.exotic_code.is_some() {
            return false;
        }

        // Category filter (species only)
        if record.category != "species" {
            return false;
        }

        true
    }

    fn in_bounding_box(&self, record: &EBirdRecord) -> bool {
        record.latitude >= self.bbox.min_latitude
            && record.latitude <= self.bbox.max_latitude
            && record.longitude >= self.bbox.min_longitude
            && record.longitude <= self.bbox.max_longitude
    }

    fn in_date_range(&self, record: &EBirdRecord) -> bool {
        record.observation_date >= self.date_range.start
            && record.observation_date <= self.date_range.end
    }
}
```

### 3. Species Aggregation

```rust
// src/aggregation/species.rs
use std::collections::{HashMap, HashSet};
use chrono::NaiveDate;
use crate::ebird::record::EBirdRecord;

pub struct SpeciesAggregator {
    species_data: HashMap<String, SpeciesAccumulator>,
    total_checklists: HashSet<String>,
}

struct SpeciesAccumulator {
    scientific_name: String,
    common_name: String,
    observations: Vec<ObservationEvent>,
    checklists: HashSet<String>,
}

struct ObservationEvent {
    date: NaiveDate,
    checklist_id: String,
    count: u32,
}

impl SpeciesAggregator {
    pub fn new() -> Self {
        Self {
            species_data: HashMap::new(),
            total_checklists: HashSet::new(),
        }
    }

    pub fn add_record(&mut self, record: EBirdRecord) {
        // Track unique checklists
        let checklist_id = record.group_identifier
            .clone()
            .unwrap_or(record.sampling_event_id.clone());

        self.total_checklists.insert(checklist_id.clone());

        // Aggregate by species
        let entry = self.species_data
            .entry(record.scientific_name.clone())
            .or_insert_with(|| SpeciesAccumulator {
                scientific_name: record.scientific_name.clone(),
                common_name: record.common_name.clone(),
                observations: Vec::new(),
                checklists: HashSet::new(),
            });

        let count = match record.observation_count {
            ObservationCount::Count(n) => n,
            ObservationCount::Present => 1,
        };

        entry.observations.push(ObservationEvent {
            date: record.observation_date,
            checklist_id: checklist_id.clone(),
            count,
        });

        entry.checklists.insert(checklist_id);
    }

    pub fn finalize(self, config: &FilterConfig) -> Vec<SpeciesData> {
        let total_checklists = self.total_checklists.len() as f64;

        self.species_data
            .into_iter()
            .filter_map(|(_, acc)| {
                self.compute_species_data(acc, total_checklists, config)
            })
            .collect()
    }

    fn compute_species_data(
        &self,
        acc: SpeciesAccumulator,
        total_checklists: f64,
        config: &FilterConfig,
    ) -> Option<SpeciesData> {
        let total_obs = acc.observations.len() as u32;
        let total_lists = acc.checklists.len() as u32;

        // Apply minimum thresholds
        if total_obs < config.min_observations || total_lists < config.min_checklists {
            return None;
        }

        let yearly_frequency = total_lists as f64 / total_checklists;

        if yearly_frequency < config.min_yearly_frequency {
            return None;
        }

        // Compute temporal patterns
        let temporal = self.compute_temporal_data(&acc.observations, total_checklists);

        // Compute filtering parameters
        let filtering = FilteringData {
            confidence_boost: calculate_confidence_boost(yearly_frequency),
            priority: classify_priority(yearly_frequency),
        };

        Some(SpeciesData {
            scientific_name: acc.scientific_name,
            common_name: acc.common_name,
            occurrence: OccurrenceData {
                yearly_frequency,
                total_observations: total_obs,
                total_checklists: total_lists,
                first_observation: acc.observations.iter().map(|o| o.date).min().unwrap(),
                last_observation: acc.observations.iter().map(|o| o.date).max().unwrap(),
            },
            temporal,
            filtering,
            metadata: None,
        })
    }
}

fn calculate_confidence_boost(yearly_frequency: f64) -> f64 {
    const MAX_BOOST: f64 = 1.3;
    1.0 + (yearly_frequency * (MAX_BOOST - 1.0))
}

fn classify_priority(yearly_frequency: f64) -> SpeciesPriority {
    if yearly_frequency >= 0.20 {
        SpeciesPriority::Common
    } else if yearly_frequency >= 0.05 {
        SpeciesPriority::Uncommon
    } else if yearly_frequency >= 0.01 {
        SpeciesPriority::Rare
    } else {
        SpeciesPriority::Vagrant
    }
}
```

### 4. Temporal Aggregation

```rust
// src/aggregation/temporal.rs
use crate::aggregation::species::ObservationEvent;
use crate::region::pack::TemporalData;

pub fn compute_temporal_data(
    observations: &[ObservationEvent],
    total_checklists: f64,
) -> TemporalData {
    // Group by month
    let mut monthly_obs: [u32; 12] = [0; 12];
    let mut monthly_checklists: [HashSet<String>; 12] = Default::default();

    for obs in observations {
        let month = obs.date.month0() as usize; // 0-11
        monthly_obs[month] += 1;
        monthly_checklists[month].insert(obs.checklist_id.clone());
    }

    // Calculate monthly frequencies
    let monthly_frequency = monthly_checklists.map(|set| {
        set.len() as f64 / total_checklists
    });

    // Find peak months (top 3)
    let mut month_freq_pairs: Vec<_> = monthly_frequency
        .iter()
        .enumerate()
        .map(|(i, &freq)| (i as u8 + 1, freq))
        .collect();
    month_freq_pairs.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
    let peak_months = month_freq_pairs
        .iter()
        .take(3)
        .map(|(month, _)| *month)
        .collect();

    TemporalData {
        monthly_frequency,
        monthly_observations: monthly_obs,
        peak_months,
        breeding_season: vec![], // TODO: Extract from breeding codes
    }
}
```

### 5. Main Pipeline

```rust
// src/main.rs
use clap::Parser;
use anyhow::Result;
use log::info;
use indicatif::ProgressBar;

#[derive(Parser)]
#[command(name = "ebird-region-pack")]
#[command(about = "Generate region packs from eBird data")]
struct Cli {
    /// Input tarball path
    #[arg(short, long)]
    input: PathBuf,

    /// Output SQLite database path (.db)
    #[arg(short, long)]
    output: PathBuf,

    /// Region configuration (YAML/JSON)
    #[arg(short, long)]
    config: PathBuf,

    /// Optimize database after creation
    #[arg(long, default_value = "true")]
    optimize: bool,
}

fn main() -> Result<()> {
    env_logger::init();
    let cli = Cli::parse();

    // Load configuration
    info!("Loading configuration from {:?}", cli.config);
    let config: RegionConfig = load_config(&cli.config)?;

    // Create filter and H3 aggregator
    let filter = RecordFilter::new(
        config.bounding_box.clone(),
        config.date_range.clone(),
        config.filters.approved_only,
        config.filters.complete_checklists_only,
        config.filters.native_species_only,
    );

    let mut aggregator = H3Aggregator::new(config.h3_resolution);

    // Stream and process
    info!("Streaming records from {:?} (H3 resolution {})", cli.input, config.h3_resolution);
    let progress = ProgressBar::new_spinner();
    let mut record_count = 0;

    let mut reader = EBirdReader::new(&cli.input)?;
    reader.stream_records(|record| {
        record_count += 1;
        if record_count % 100_000 == 0 {
            progress.set_message(format!("Processed {} records", record_count));
        }

        if filter.matches(&record) {
            aggregator.add_record(record)?;
        }

        Ok(())
    })?;

    progress.finish_with_message(format!("Processed {} total records", record_count));

    // Finalize and generate pack
    info!("Finalizing grid cell data");
    let grid_cells = aggregator.finalize(&config.filters);

    let total_species: usize = grid_cells.iter().map(|c| c.species.len()).sum();

    let pack = RegionPack {
        version: "2.0".to_string(),  // Version 2.0 = H3 grid
        region_id: config.region_id,
        h3_resolution: config.h3_resolution,
        generated_at: Utc::now(),
        generator: format!("ebird-region-pack v{}", env!("CARGO_PKG_VERSION")),
        grid_cells,
        // ... other metadata
    };

    // Write output
    info!("Writing H3 grid region pack to {:?}", cli.output);
    write_region_pack(&pack, &cli.output, cli.optimize)?;

    info!("Done! Generated pack with {} hexagons and {} total species records",
          pack.grid_cells.len(), total_species);

    Ok(())
}
```

## Performance Optimizations

### 1. Streaming (Not Loading All into Memory)
- Process records line-by-line
- Discard filtered-out records immediately
- Only accumulate aggregation state

### 2. Parallel Processing (Optional)
```rust
use rayon::prelude::*;

// Partition by species for parallel aggregation
let species_groups: HashMap<String, Vec<EBirdRecord>> = ...;
let results: Vec<SpeciesData> = species_groups
    .par_iter()
    .map(|(_, records)| compute_species_data(records))
    .collect();
```

### 3. Memory-Mapped I/O (If Needed)
```rust
use memmap2::Mmap;

let file = File::open(path)?;
let mmap = unsafe { Mmap::map(&file)? };
// Process mmap as byte slice
```

## Testing Strategy

```rust
// tests/integration_tests.rs
#[test]
fn test_small_region() {
    let config = RegionConfig {
        region_id: "test-region".to_string(),
        bounding_box: BoundingBox {
            min_latitude: 37.0,
            max_latitude: 38.0,
            min_longitude: -122.0,
            max_longitude: -121.0,
        },
        // ... rest of config
    };

    let pack = generate_region_pack("tests/fixtures/sample.tar.gz", &config).unwrap();

    assert!(pack.species_count > 0);
    assert!(pack.species.iter().all(|s| s.occurrence.yearly_frequency <= 1.0));
}
```

## CLI Usage Examples

```bash
# Simple H3 grid region pack (resolution 7 = ~5km hexagons)
ebird-region-pack \
  --input ebd_relAug-2025.tar \
  --config regions/us-ca-sf-bay.yaml \
  --output region_packs/us-ca-sf-bay-h3.db

# Example config file (us-ca-sf-bay.yaml):
#   region_id: us-ca-sf-bay-h3
#   region_name: San Francisco Bay Area (H3 Grid)
#   region_type: metro
#   h3_resolution: 7  # Resolution 7 = ~5km hexagons
#   bounding_box:
#     min_latitude: 37.4
#     max_latitude: 38.0
#     min_longitude: -122.5
#     max_longitude: -121.8
#   ...

# Batch processing
for config in configs/*.yaml; do
  ebird-region-pack \
    --input ebd_relAug-2025.tar \
    --config "$config" \
    --output "packs/$(basename "$config" .yaml).db"
done

# Different resolutions for different use cases:
# Resolution 6 (~36km) - Sparse areas, broad regional coverage
# Resolution 7 (~5km)  - Standard resolution for most regions
# Resolution 8 (~0.7km) - Dense urban areas, fine-grained precision
# Resolution 9 (~0.1km) - Ultra-precise for small parks/reserves
```

## SQLite Writer Implementation

```rust
// src/region/writer.rs
use rusqlite::{Connection, params};
use anyhow::Result;
use std::path::Path;
use crate::region::pack::RegionPack;

pub fn write_region_pack(
    pack: &RegionPack,
    output_path: &Path,
    optimize: bool,
) -> Result<()> {
    let mut conn = Connection::open(output_path)?;

    // Create schema
    create_schema(&mut conn)?;

    // Insert metadata
    insert_metadata(&mut conn, pack)?;

    // Insert species (bulk transaction)
    insert_species(&mut conn, &pack.species)?;

    // Optimize database
    if optimize {
        optimize_database(&mut conn)?;
    }

    Ok(())
}

fn create_schema(conn: &mut Connection) -> Result<()> {
    conn.execute_batch(
        "CREATE TABLE region_metadata (
            key TEXT PRIMARY KEY NOT NULL,
            value TEXT NOT NULL
        );

        CREATE INDEX idx_region_metadata_key ON region_metadata(key);

        CREATE TABLE grid_metadata (
            h3_cell BIGINT PRIMARY KEY NOT NULL,
            resolution INTEGER NOT NULL,
            center_lat REAL NOT NULL,
            center_lon REAL NOT NULL,
            total_checklists INTEGER NOT NULL,
            complete_checklists INTEGER NOT NULL,
            total_observations INTEGER NOT NULL,
            date_range_start DATE NOT NULL,
            date_range_end DATE NOT NULL,
            data_quality TEXT DEFAULT 'good'
        );

        CREATE INDEX idx_grid_resolution ON grid_metadata(resolution);
        CREATE INDEX idx_grid_quality ON grid_metadata(data_quality);
        CREATE INDEX idx_grid_latlon ON grid_metadata(center_lat, center_lon);

        CREATE TABLE grid_species (
            h3_cell BIGINT NOT NULL,
            scientific_name TEXT NOT NULL,
            common_name TEXT NOT NULL,
            yearly_frequency REAL NOT NULL CHECK(yearly_frequency >= 0.0 AND yearly_frequency <= 1.0),
            total_observations INTEGER NOT NULL CHECK(total_observations > 0),
            total_checklists INTEGER NOT NULL CHECK(total_checklists > 0),
            first_observation DATE NOT NULL,
            last_observation DATE NOT NULL,
            confidence_tier TEXT NOT NULL CHECK(confidence_tier IN ('common', 'uncommon', 'rare', 'vagrant')),
            confidence_boost REAL NOT NULL DEFAULT 1.0 CHECK(confidence_boost >= 1.0 AND confidence_boost <= 2.0),
            monthly_frequency_json TEXT NOT NULL,
            monthly_observations_json TEXT NOT NULL,
            peak_months_json TEXT,
            breeding_season_json TEXT,
            taxon_concept_id TEXT,
            category TEXT DEFAULT 'species',
            exotic_status TEXT,
            PRIMARY KEY (h3_cell, scientific_name),
            FOREIGN KEY (h3_cell) REFERENCES grid_metadata(h3_cell)
        );

        CREATE INDEX idx_grid_species_freq ON grid_species(h3_cell, yearly_frequency DESC);
        CREATE INDEX idx_grid_species_tier ON grid_species(h3_cell, confidence_tier);
        CREATE INDEX idx_grid_species_name ON grid_species(scientific_name);"
    )?;
    Ok(())
}

fn insert_metadata(conn: &mut Connection, pack: &RegionPack) -> Result<()> {
    let tx = conn.transaction()?;

    {
        let mut stmt = tx.prepare("INSERT INTO region_metadata (key, value) VALUES (?, ?)")?;

        stmt.execute(params!["version", "2.0"])?;  // Version 2.0 = H3 grid
        stmt.execute(params!["region_id", &pack.region_id])?;
        stmt.execute(params!["region_name", &pack.region.name])?;
        stmt.execute(params!["region_type", &pack.region.region_type])?;
        stmt.execute(params!["h3_resolution", &pack.h3_resolution.to_string()])?;
        stmt.execute(params!["generated_at", &pack.generated_at.to_rfc3339()])?;
        stmt.execute(params!["generator", &pack.generator])?;
        stmt.execute(params!["ebird_version", &pack.source_data.ebird_version])?;
        stmt.execute(params!["date_range_start", &pack.source_data.date_range.start.to_string()])?;
        stmt.execute(params!["date_range_end", &pack.source_data.date_range.end.to_string()])?;
        stmt.execute(params!["total_checklists", &pack.source_data.total_checklists.to_string()])?;
        stmt.execute(params!["total_observations", &pack.source_data.total_observations.to_string()])?;
        stmt.execute(params!["total_h3_cells", &pack.grid_cells.len().to_string()])?;
        stmt.execute(params!["min_latitude", &pack.region.bounding_box.min_latitude.to_string()])?;
        stmt.execute(params!["max_latitude", &pack.region.bounding_box.max_latitude.to_string()])?;
        stmt.execute(params!["min_longitude", &pack.region.bounding_box.min_longitude.to_string()])?;
        stmt.execute(params!["max_longitude", &pack.region.bounding_box.max_longitude.to_string()])?;
        stmt.execute(params!["filter_approved_only", if pack.filters_applied.approved_only { "true" } else { "false" }])?;
        stmt.execute(params!["filter_complete_checklists_only", if pack.filters_applied.complete_checklists_only { "true" } else { "false" }])?;
        stmt.execute(params!["filter_native_species_only", if pack.filters_applied.native_species_only { "true" } else { "false" }])?;
        stmt.execute(params!["filter_min_observations", &pack.filters_applied.min_observations.to_string()])?;
        stmt.execute(params!["filter_min_checklists", &pack.filters_applied.min_checklists.to_string()])?;
        stmt.execute(params!["filter_deduplication", &pack.filters_applied.deduplication])?;
    }

    tx.commit()?;
    Ok(())
}

fn insert_grid_data(conn: &mut Connection, grid_cells: &[GridCellPack]) -> Result<()> {
    let tx = conn.transaction()?;

    // First, insert grid_metadata
    {
        let mut stmt = tx.prepare(
            "INSERT INTO grid_metadata (h3_cell, resolution, center_lat, center_lon, \
             total_checklists, complete_checklists, total_observations, \
             date_range_start, date_range_end, data_quality) \
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )?;

        for cell in grid_cells {
            let grid = H3Grid::new(cell.resolution)?;
            let h3_i64 = grid.cell_to_i64(cell.h3_cell);

            // Determine data quality based on complete checklists
            let data_quality = match cell.complete_checklists {
                n if n >= 100 => "excellent",
                n if n >= 50 => "good",
                n if n >= 20 => "fair",
                _ => "sparse",
            };

            stmt.execute(params![
                h3_i64,
                cell.resolution,
                cell.center_lat,
                cell.center_lon,
                cell.total_checklists,
                cell.complete_checklists,
                cell.total_observations,
                cell.date_range_start.to_string(),
                cell.date_range_end.to_string(),
                data_quality,
            ])?;
        }
    }

    // Second, insert grid_species
    {
        let mut stmt = tx.prepare(
            "INSERT INTO grid_species (h3_cell, scientific_name, common_name, \
             yearly_frequency, total_observations, total_checklists, \
             first_observation, last_observation, confidence_tier, confidence_boost, \
             monthly_frequency_json, monthly_observations_json, peak_months_json, \
             breeding_season_json, taxon_concept_id, category, exotic_status) \
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )?;

        for cell in grid_cells {
            let grid = H3Grid::new(cell.resolution)?;
            let h3_i64 = grid.cell_to_i64(cell.h3_cell);

            for sp in &cell.species {
                stmt.execute(params![
                    h3_i64,
                    sp.scientific_name,
                    sp.common_name,
                    sp.occurrence.yearly_frequency,
                    sp.occurrence.total_observations,
                    sp.occurrence.total_checklists,
                    sp.occurrence.first_observation.to_string(),
                    sp.occurrence.last_observation.to_string(),
                    sp.filtering.confidence_tier.as_str(),
                    sp.filtering.confidence_boost,
                    serde_json::to_string(&sp.temporal.monthly_frequency)?,
                    serde_json::to_string(&sp.temporal.monthly_observations)?,
                    sp.temporal.peak_months.as_ref().map(|v| serde_json::to_string(v)).transpose()?,
                    sp.temporal.breeding_season.as_ref().map(|v| serde_json::to_string(v)).transpose()?,
                    sp.metadata.as_ref().and_then(|m| m.taxon_concept_id.as_ref()),
                    sp.metadata.as_ref().map(|m| m.category.as_str()),
                    sp.metadata.as_ref().and_then(|m| m.exotic_status.as_ref()),
                ])?;
            }
        }
    }

    tx.commit()?;
    Ok(())
}

fn optimize_database(conn: &mut Connection) -> Result<()> {
    conn.execute_batch(
        "PRAGMA page_size = 4096;
         PRAGMA journal_mode = DELETE;
         PRAGMA synchronous = OFF;
         VACUUM;
         PRAGMA optimize;"
    )?;
    Ok(())
}
```

## Next Steps

1. **Implement H3 grid module** (h3/grid.rs, h3/aggregator.rs)
   - Lat/lon to H3 cell conversion
   - Cell-based species aggregation
   - Per-hexagon statistics tracking

2. **Update aggregation logic** for H3 cells
   - Species accumulation per hexagon
   - Monthly frequency calculation per hexagon
   - Confidence tier assignment based on cell frequency

3. **Implement three-table SQLite writer**
   - region_metadata table
   - grid_metadata table
   - grid_species table with composite key (h3_cell, scientific_name)

4. **Add tests** with small sample data
   - Test H3 cell assignment
   - Test species aggregation per cell
   - Test data quality classification

5. **Optimize** memory usage and performance
   - H3 cell lookup efficiency
   - Bulk SQLite inserts
   - Parallel processing by hexagon

6. **Add validation** for output database
   - Check H3 cell validity
   - Verify foreign key constraints
   - Validate frequency ranges per cell

7. **Create example configs** for common regions
   - Different H3 resolutions (6, 7, 8, 9)
   - Urban vs rural configurations
   - Multi-resolution packs

8. **Build batch processing** for multiple regions
   - Process multiple bounding boxes
   - Generate hierarchical packs (resolution 6 + 7 + 8)

9. **Add progress reporting** and logging
   - Hexagon count tracking
   - Species per hexagon metrics
   - Data quality distribution

10. **Package and distribute** as binary
    - Static linking with bundled SQLite
    - Include h3o crate (pure Rust, no C dependencies)
