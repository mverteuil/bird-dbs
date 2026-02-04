# Region Pack Specification (H3 Hexagonal Grid)

## Overview

A **region pack** is a SQLite database containing eBird-derived species occurrence data organized in an **H3 hexagonal grid**. Each hexagon cell (~5km) has its own species frequency data, enabling neighborhood-level precision and distance-weighted confidence adjustments in BirdNET-Pi.

**See**:
- [05-format-decision.md](05-format-decision.md) - Why SQLite vs JSON
- [06-grid-based-architecture.md](06-grid-based-architecture.md) - Why H3 hexagons vs squares/geohash

## File Format

### Container
- **Format**: SQLite 3 database
- **Extension**: `.db`
- **Encoding**: UTF-8 (for text fields)
- **Max size**: ~1.5MB (typical for 450 species)

### Database Schema

The region pack consists of three tables: `region_metadata` (pack-level config), `grid_metadata` (per-hexagon stats), and `grid_species` (species per hexagon).

```sql
-- Region-level metadata (key-value pairs)
CREATE TABLE region_metadata (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);

CREATE INDEX idx_region_metadata_key ON region_metadata(key);

-- Per-hexagon metadata (cell-level statistics)
CREATE TABLE grid_metadata (
    h3_cell BIGINT PRIMARY KEY NOT NULL,  -- H3 index as 64-bit integer
    resolution INTEGER NOT NULL,          -- H3 resolution level (6, 7, 8, 9)
    center_lat REAL NOT NULL,
    center_lon REAL NOT NULL,
    total_checklists INTEGER NOT NULL,
    complete_checklists INTEGER NOT NULL,  -- From sampling dataset
    total_observations INTEGER NOT NULL,
    date_range_start DATE NOT NULL,
    date_range_end DATE NOT NULL,
    data_quality TEXT DEFAULT 'good'  -- 'excellent', 'good', 'fair', 'sparse'
);

CREATE INDEX idx_grid_resolution ON grid_metadata(resolution);
CREATE INDEX idx_grid_quality ON grid_metadata(data_quality);
CREATE INDEX idx_grid_latlon ON grid_metadata(center_lat, center_lon);

-- Species occurrence per hexagon
CREATE TABLE grid_species (
    h3_cell BIGINT NOT NULL,
    scientific_name TEXT NOT NULL,
    common_name TEXT NOT NULL,

    -- Occurrence statistics (for THIS hexagon only)
    yearly_frequency REAL NOT NULL CHECK(yearly_frequency >= 0.0 AND yearly_frequency <= 1.0),
    total_observations INTEGER NOT NULL CHECK(total_observations > 0),
    total_checklists INTEGER NOT NULL CHECK(total_checklists > 0),
    first_observation DATE NOT NULL,
    last_observation DATE NOT NULL,

    -- Filtering parameters
    confidence_tier TEXT NOT NULL CHECK(confidence_tier IN ('common', 'uncommon', 'rare', 'vagrant')),
    confidence_boost REAL NOT NULL DEFAULT 1.0 CHECK(confidence_boost >= 1.0 AND confidence_boost <= 2.0),

    -- Temporal data (stored as JSON arrays)
    monthly_frequency_json TEXT NOT NULL,     -- Array[12] of floats (0.0-1.0)
    monthly_observations_json TEXT NOT NULL,  -- Array[12] of integers

    -- Optional metadata
    peak_months_json TEXT,           -- Array of month indices [1-12]
    breeding_season_json TEXT,       -- Array of month indices [1-12]
    taxon_concept_id TEXT,           -- Avibase ID
    category TEXT DEFAULT 'species', -- species, issf, hybrid, etc.
    exotic_status TEXT,              -- null, N, P, X

    PRIMARY KEY (h3_cell, scientific_name),
    FOREIGN KEY (h3_cell) REFERENCES grid_metadata(h3_cell)
);

-- Performance indexes
CREATE INDEX idx_grid_species_freq ON grid_species(h3_cell, yearly_frequency DESC);
CREATE INDEX idx_grid_species_tier ON grid_species(h3_cell, confidence_tier);
CREATE INDEX idx_grid_species_name ON grid_species(scientific_name);  -- For reverse lookup
```

### Example Data

**Region metadata table**:
```sql
INSERT INTO region_metadata (key, value) VALUES
    ('version', '2.0'),  -- Version 2.0 = H3 hexagonal grid
    ('region_id', 'us-ca-sf-bay-h3'),
    ('region_name', 'San Francisco Bay Area (H3 Grid)'),
    ('region_type', 'metro'),
    ('h3_resolution', '7'),  -- Resolution 7 = ~5km hexagons
    ('generated_at', '2025-10-08T10:30:00Z'),
    ('generator', 'ebird-region-pack v2.0.0'),
    ('ebird_version', 'EBD_relAug-2025'),
    ('date_range_start', '2020-01-01'),
    ('date_range_end', '2025-08-01'),
    ('total_checklists', '125430'),
    ('total_observations', '2845672'),
    ('total_h3_cells', '240'),  -- Number of hexagons in region
    ('min_latitude', '37.4'),
    ('max_latitude', '38.0'),
    ('min_longitude', '-122.5'),
    ('max_longitude', '-121.8'),
    ('filter_approved_only', 'true'),
    ('filter_complete_checklists_only', 'true'),
    ('filter_native_species_only', 'true'),
    ('filter_min_observations', '10'),
    ('filter_min_checklists', '5'),
    ('filter_deduplication', 'group_identifier');
```

**Grid metadata table** (example hexagon):
```sql
-- H3 cell covering San Francisco Mission District
INSERT INTO grid_metadata VALUES (
    617700169958293503,  -- h3_cell (0x8928308280fffff) - Mission District SF
    7,                   -- resolution (7 = ~5km hexagons)
    37.7599,             -- center_lat
    -122.4194,           -- center_lon
    523,                 -- total_checklists
    487,                 -- complete_checklists (from sampling dataset)
    12845,               -- total_observations
    '2020-01-01',        -- date_range_start
    '2025-08-01',        -- date_range_end
    'excellent'          -- data_quality (>100 complete checklists)
);

-- Neighboring hexagon (Oakland)
INSERT INTO grid_metadata VALUES (
    617700169958359039,  -- h3_cell (0x8928308281fffff) - Oakland
    7,                   -- resolution
    37.8044,             -- center_lat
    -122.2712,           -- center_lon
    612,                 -- total_checklists
    558,                 -- complete_checklists
    15203,               -- total_observations
    '2020-01-01',
    '2025-08-01',
    'excellent'
);
```

**Grid species table** (example species in one hexagon):
```sql
-- Western Gull in Mission District hexagon
INSERT INTO grid_species VALUES (
    617700169958293503,  -- h3_cell (Mission District)
    'Larus occidentalis',                                    -- scientific_name
    'Western Gull',                                          -- common_name
    0.682,                                                   -- yearly_frequency
    3321,                                                    -- total_observations (in this hex)
    332,                                                     -- total_checklists (in this hex)
    '2020-01-03',                                           -- first_observation
    '2025-07-28',                                           -- last_observation
    'common',                                                -- confidence_tier
    1.20,                                                    -- confidence_boost
    '[0.72,0.71,0.69,0.66,0.63,0.65,0.67,0.68,0.70,0.71,0.71,0.72]',  -- monthly_frequency_json
    '[289,285,276,264,252,260,268,272,280,284,284,287]',    -- monthly_observations_json
    '[1,2,12]',                                             -- peak_months_json
    '[4,5,6,7,8]',                                          -- breeding_season_json
    'avibase-12345678',                                     -- taxon_concept_id
    'species',                                              -- category
    NULL                                                     -- exotic_status
);

-- Same species in Oakland hexagon (different frequency!)
INSERT INTO grid_species VALUES (
    617700169958359039,  -- h3_cell (Oakland)
    'Larus occidentalis',
    'Western Gull',
    0.521,               -- Lower frequency in Oakland than SF
    2914,
    292,
    '2020-01-05',
    '2025-07-30',
    'common',
    1.16,
    '[0.58,0.56,0.54,0.51,0.48,0.50,0.52,0.53,0.55,0.56,0.57,0.58]',
    '[167,162,156,148,139,145,151,154,159,162,165,166]',
    '[1,11,12]',
    '[4,5,6,7]',
    'avibase-12345678',
    'species',
    NULL
);
```

### Field Definitions

#### Region Metadata Table Keys

All pack-level configuration stored as key-value pairs in `region_metadata` table.

**Required keys**:

| Key | Type | Description |
|-----|------|-------------|
| `version` | string | Pack format version (e.g., "2.0" for H3 grid) |
| `region_id` | string | Unique region identifier |
| `region_name` | string | Human-readable region name |
| `region_type` | string | `metro`, `state`, `county`, `bcr`, `iba`, `custom` |
| `h3_resolution` | int | H3 resolution level (6, 7, 8, 9) |
| `generated_at` | ISO8601 | Generation timestamp |
| `generator` | string | Tool name and version |
| `ebird_version` | string | eBird release identifier |
| `date_range_start` | date | Start date of data (YYYY-MM-DD) |
| `date_range_end` | date | End date of data (YYYY-MM-DD) |
| `total_checklists` | int | Total checklists across all hexagons |
| `total_observations` | int | Total bird observations across all hexagons |
| `total_h3_cells` | int | Number of hexagons in pack |
| `min_latitude` | float | Bounding box minimum latitude |
| `max_latitude` | float | Bounding box maximum latitude |
| `min_longitude` | float | Bounding box minimum longitude |
| `max_longitude` | float | Bounding box maximum longitude |

**Filter documentation keys**:

| Key | Type | Description |
|-----|------|-------------|
| `filter_approved_only` | bool | Only eBird-approved records |
| `filter_complete_checklists_only` | bool | ALL_SPECIES_REPORTED=1 only |
| `filter_native_species_only` | bool | EXOTIC_CODE=null only |
| `filter_min_observations` | int | Minimum observations per species |
| `filter_min_checklists` | int | Minimum checklists per species |
| `filter_deduplication` | string | `group_identifier`, `sampling_event`, `none` |

#### Grid Metadata Table Fields

Per-hexagon statistics and metadata. Each row represents one H3 hexagon cell.

**H3 identification**:

| Field | Type | Description |
|-------|------|-------------|
| `h3_cell` | BIGINT PRIMARY KEY | H3 index as 64-bit integer (e.g., 617700169958293503) |
| `resolution` | INTEGER | H3 resolution level: 6 (~36km²), 7 (~5km²), 8 (~0.7km²), 9 (~0.1km²) |
| `center_lat` | REAL | Hexagon center latitude (-90 to 90) |
| `center_lon` | REAL | Hexagon center longitude (-180 to 180) |

**Observation statistics** (for this hexagon only):

| Field | Type | Description |
|-------|------|-------------|
| `total_checklists` | INTEGER | Total checklists submitted in this hexagon |
| `complete_checklists` | INTEGER | Checklists with ALL_SPECIES_REPORTED=1 (from sampling dataset) |
| `total_observations` | INTEGER | Total bird observations in this hexagon |
| `date_range_start` | DATE | First observation date in hexagon (YYYY-MM-DD) |
| `date_range_end` | DATE | Last observation date in hexagon (YYYY-MM-DD) |

**Data quality indicator**:

| Field | Type | Description |
|-------|------|-------------|
| `data_quality` | TEXT | `excellent` (>100 complete checklists), `good` (50-100), `fair` (20-50), `sparse` (<20) |

#### Grid Species Table Fields

Species occurrence data per hexagon. Same species can appear in multiple hexagons with different frequencies.

**Grid and species identification**:

| Field | Type | Description |
|-------|------|-------------|
| `h3_cell` | BIGINT | Foreign key to `grid_metadata.h3_cell` |
| `scientific_name` | TEXT | eBird scientific name (stable identifier) |
| `common_name` | TEXT | eBird English common name |

**Occurrence statistics** (for this hexagon only):

| Field | Type | Description |
|-------|------|-------------|
| `yearly_frequency` | REAL | Proportion of complete checklists in THIS hexagon (0.0-1.0) |
| `total_observations` | INTEGER | Number of times observed in THIS hexagon |
| `total_checklists` | INTEGER | Number of unique checklists in THIS hexagon |
| `first_observation` | DATE | First observation date in THIS hexagon (YYYY-MM-DD) |
| `last_observation` | DATE | Last observation date in THIS hexagon (YYYY-MM-DD) |

**Confidence parameters** (computed from hexagon data):

| Field | Type | Description |
|-------|------|-------------|
| `confidence_tier` | TEXT | `common` (≥20%), `uncommon` (5-20%), `rare` (1-5%), `vagrant` (<1%) |
| `confidence_boost` | REAL | BirdNET confidence multiplier (1.0-2.0) based on hexagon frequency |

**Temporal data** (JSON arrays for this hexagon):

| Field | Type | Description |
|-------|------|-------------|
| `monthly_frequency_json` | TEXT | Array[12] of frequencies in THIS hexagon (0.0-1.0) |
| `monthly_observations_json` | TEXT | Array[12] of observation counts in THIS hexagon |
| `peak_months_json` | TEXT | Array of month indices [1-12] when species peaks in THIS hexagon |
| `breeding_season_json` | TEXT | Array of month indices [1-12] for breeding in THIS hexagon |

**Optional metadata**:

| Field | Type | Description |
|-------|------|-------------|
| `taxon_concept_id` | TEXT | Avibase ID for taxonomy tracking |
| `category` | TEXT | `species`, `issf`, `hybrid`, etc. |
| `exotic_status` | TEXT | `null`, `N` (naturalized), `P` (provisional), `X` (exotic) |

**Key insight**: The same species (e.g., Western Gull) will have **different** `yearly_frequency` values in different hexagons. A species common in San Francisco may be uncommon in Oakland, and this is reflected in separate rows with different `h3_cell` values.

## Region Identifier Conventions

### Format: `{country}-{state/province}-{area}-{custom}`

**Examples**:
- `us-ca` - California, USA
- `us-ca-sf-bay` - San Francisco Bay Area
- `us-ny-nyc` - New York City metropolitan area
- `ca-on` - Ontario, Canada
- `mx-ver` - Veracruz, Mexico
- `bcr-32` - Bird Conservation Region 32 (Coastal California)
- `iba-us-ca-001` - IBA code mapping

**Guidelines**:
- Use ISO 3166-2 for country/state codes
- Lowercase, hyphen-separated
- Max 64 characters
- ASCII only (no special characters)

## Hierarchical Pack Strategy

**Directory structure**:

```
region_packs/
├── global.db                   # Fallback (all 6000 species)
├── continents/
│   ├── north-america.db
│   ├── europe.db
│   └── asia.db
├── countries/
│   ├── us.db
│   ├── ca.db
│   └── mx.db
├── states/
│   ├── us-ca.db
│   ├── us-ny.db
│   └── ca-on.db
└── custom/
    ├── us-ca-sf-bay.db
    ├── us-ca-yosemite.db
    └── us-ny-central-park.db
```

**Fallback hierarchy** (from most specific to least):
1. Custom region (e.g., `us-ca-sf-bay`)
2. State/province (e.g., `us-ca`)
3. Country (e.g., `us`)
4. Continent (e.g., `north-america`)
5. Global (all species)

## Frequency Thresholds

### Recommended Thresholds by Region Size

| Region Type | Area (km²) | Min Observations | Min Checklists | Min Yearly Freq |
|-------------|-----------|------------------|----------------|-----------------|
| Custom (small) | < 1,000 | 10 | 5 | 0.01 (1%) |
| County | 1,000-10,000 | 20 | 10 | 0.005 (0.5%) |
| State | 10,000-500,000 | 50 | 20 | 0.002 (0.2%) |
| Country | > 500,000 | 100 | 50 | 0.001 (0.1%) |

**Rationale**:
- **Too high**: Misses valid rare species (false negatives)
- **Too low**: Includes vagrants, doesn't improve filtering
- **Sweet spot**: 0.5-1% for local regions

### Confidence Boost Calculation

```rust
fn calculate_confidence_boost(yearly_frequency: f64, config: &Config) -> f64 {
    let base_boost = 1.0;
    let max_boost = config.max_confidence_boost; // e.g., 1.3

    // Linear scaling based on frequency
    let boost = base_boost + (yearly_frequency * (max_boost - base_boost));

    // Clamp to reasonable range
    boost.max(1.0).min(max_boost)
}

// Examples:
// 70% frequency → 1.0 + (0.7 * 0.3) = 1.21
// 30% frequency → 1.0 + (0.3 * 0.3) = 1.09
// 5% frequency  → 1.0 + (0.05 * 0.3) = 1.015
```

## Species Priority Classification

```rust
enum SpeciesPriority {
    Common,   // yearly_frequency >= 0.20 (20%)
    Uncommon, // 0.05 - 0.20
    Rare,     // 0.01 - 0.05
    Vagrant,  // < 0.01
}
```

**Usage**:
- **Common**: Always include, high confidence boost
- **Uncommon**: Include, moderate boost
- **Rare**: Include with warning, minimal/no boost
- **Vagrant**: Optionally exclude in strict mode

## Temporal Filtering

### Monthly Frequency Array (Index 0-11 = Jan-Dec)

```json
"monthly_frequency": [
  0.72,  // January
  0.71,  // February
  0.69,  // March
  0.66,  // April
  0.63,  // May
  0.65,  // June
  0.67,  // July
  0.68,  // August
  0.70,  // September
  0.71,  // October
  0.71,  // November
  0.72   // December
]
```

### Mapping BirdNET Week (1-48) to Month

```rust
fn week_to_month(week: u8) -> u8 {
    // BirdNET uses weeks 1-48 (approximates year as 48 weeks)
    // Each "week" is ~7.6 days
    match week {
        1..=4   => 1,  // January
        5..=8   => 2,  // February
        9..=13  => 3,  // March
        14..=17 => 4,  // April
        18..=21 => 5,  // May
        22..=26 => 6,  // June
        27..=30 => 7,  // July
        31..=35 => 8,  // August
        36..=39 => 9,  // September
        40..=43 => 10, // October
        44..=48 => 11, // November
        _       => 12, // December
    }
}
```

**Seasonal boost**:

```rust
fn get_seasonal_boost(species: &Species, month: u8) -> f64 {
    let monthly_freq = species.temporal.monthly_frequency[month as usize - 1];
    let yearly_freq = species.occurrence.yearly_frequency;

    // Boost if current month frequency is higher than yearly average
    if monthly_freq > yearly_freq {
        1.0 + ((monthly_freq - yearly_freq) * 0.5)
    } else {
        1.0
    }
}
```

## Validation Rules

### Required Fields
All species objects must have:
- `scientific_name` (non-empty string)
- `occurrence.yearly_frequency` (0.0-1.0)
- `temporal.monthly_frequency` (array of 12 floats, 0.0-1.0)

### Data Integrity Checks
1. `species_count` must equal `species.length`
2. All `yearly_frequency` values between 0.0 and 1.0
3. All `monthly_frequency` values between 0.0 and 1.0
4. `total_checklists` ≤ `source_data.total_checklists`
5. `first_observation` ≤ `last_observation`
6. `bounding_box` coordinates valid (-90 to 90, -180 to 180)

### Pack Size Limits
- **Max species**: 10,000 per pack
- **Max file size**: 20MB uncompressed
- **Max JSON depth**: 5 levels

## Example: Minimal H3 Grid Pack

Complete SQLite database for Yosemite National Park with 2 hexagons and 2 species:

```sql
-- Create H3 grid schema (version 2.0)
CREATE TABLE region_metadata (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);

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

CREATE TABLE grid_species (
    h3_cell BIGINT NOT NULL,
    scientific_name TEXT NOT NULL,
    common_name TEXT NOT NULL,
    yearly_frequency REAL NOT NULL,
    total_observations INTEGER NOT NULL,
    total_checklists INTEGER NOT NULL,
    first_observation DATE NOT NULL,
    last_observation DATE NOT NULL,
    confidence_tier TEXT NOT NULL,
    confidence_boost REAL NOT NULL DEFAULT 1.0,
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

CREATE INDEX idx_grid_resolution ON grid_metadata(resolution);
CREATE INDEX idx_grid_species_freq ON grid_species(h3_cell, yearly_frequency DESC);
CREATE INDEX idx_grid_species_name ON grid_species(scientific_name);

-- Insert region metadata
INSERT INTO region_metadata (key, value) VALUES
    ('version', '2.0'),
    ('region_id', 'us-ca-yosemite-h3'),
    ('region_name', 'Yosemite National Park (H3 Grid)'),
    ('region_type', 'custom'),
    ('h3_resolution', '7'),
    ('generated_at', '2025-10-08T10:30:00Z'),
    ('generator', 'ebird-region-pack v2.0.0'),
    ('ebird_version', 'EBD_relAug-2025'),
    ('date_range_start', '2020-01-01'),
    ('date_range_end', '2025-08-01'),
    ('total_checklists', '8420'),
    ('total_observations', '12345'),
    ('total_h3_cells', '2'),
    ('min_latitude', '37.5'),
    ('max_latitude', '38.2'),
    ('min_longitude', '-119.9'),
    ('max_longitude', '-119.2'),
    ('filter_approved_only', 'true'),
    ('filter_complete_checklists_only', 'true'),
    ('filter_native_species_only', 'true'),
    ('filter_min_observations', '10'),
    ('filter_min_checklists', '5'),
    ('filter_deduplication', 'group_identifier');

-- Insert grid metadata (2 hexagons in Yosemite)
INSERT INTO grid_metadata VALUES
    (617700440036646911, 7, 37.7485, -119.5873, 4210, 3950, 6850, '2020-01-01', '2025-08-01', 'excellent'),
    (617700440036712447, 7, 37.8653, -119.5384, 4210, 3970, 5495, '2020-01-01', '2025-08-01', 'excellent');

-- Insert species (Steller's Jay in both hexagons, Dark-eyed Junco in both hexagons)
-- Steller's Jay in hexagon 1 (Yosemite Valley)
INSERT INTO grid_species VALUES (
    617700440036646911, 'Cyanocitta stelleri', 'Steller''s Jay',
    0.52, 2050, 2060, '2020-01-05', '2025-07-30', 'common', 1.16,
    '[0.55,0.54,0.53,0.51,0.48,0.46,0.45,0.47,0.50,0.52,0.54,0.56]',
    '[229,225,221,213,200,192,188,196,209,217,225,234]',
    '[1,11,12]', NULL, NULL, 'species', NULL
);

-- Steller's Jay in hexagon 2 (Tuolumne Meadows - higher elevation, different frequency)
INSERT INTO grid_species VALUES (
    617700440036712447, 'Cyanocitta stelleri', 'Steller''s Jay',
    0.38, 2770, 1729, '2020-01-08', '2025-07-28', 'uncommon', 1.11,
    '[0.22,0.24,0.28,0.35,0.42,0.48,0.52,0.51,0.45,0.38,0.30,0.25]',
    '[176,192,224,280,336,384,416,408,360,304,240,200]',
    '[6,7,8]', NULL, NULL, 'species', NULL
);

-- Dark-eyed Junco in hexagon 1 (year-round resident in valley)
INSERT INTO grid_species VALUES (
    617700440036646911, 'Junco hyemalis', 'Dark-eyed Junco',
    0.45, 1980, 1778, '2020-01-01', '2025-08-01', 'common', 1.14,
    '[0.58,0.56,0.52,0.45,0.38,0.32,0.28,0.30,0.36,0.44,0.52,0.56]',
    '[232,224,208,180,152,128,112,120,144,176,208,224]',
    '[1,2,12]', '[5,6,7]', NULL, 'species', NULL
);

-- Dark-eyed Junco in hexagon 2 (strongly seasonal at high elevation)
INSERT INTO grid_species VALUES (
    617700440036712447, 'Junco hyemalis', 'Dark-eyed Junco',
    0.31, 1970, 1423, '2020-03-15', '2025-07-25', 'uncommon', 1.09,
    '[0.08,0.10,0.18,0.28,0.38,0.48,0.52,0.50,0.42,0.32,0.20,0.12]',
    '[210,225,257,297,297,286,217,165,132,99,66,44]',
    '[6,7,8]', '[5,6,7,8]', NULL, 'species', NULL
);

-- Optimize
VACUUM;
PRAGMA page_size = 4096;
PRAGMA optimize;
```

**Query examples**:

```sql
-- Get total hexagon count
SELECT COUNT(*) FROM grid_metadata;
-- Returns: 2

-- Get species count across all hexagons
SELECT COUNT(DISTINCT scientific_name) FROM grid_species;
-- Returns: 2

-- Get species in a specific hexagon for June (month 6, index 5)
SELECT scientific_name, common_name, confidence_tier,
       json_extract(monthly_frequency_json, '$[5]') AS june_freq
FROM grid_species
WHERE h3_cell = 617700440036646911
  AND json_extract(monthly_frequency_json, '$[5]') > 0.1;
-- Returns: Cyanocitta stelleri (0.46), Junco hyemalis (0.32)

-- Compare same species across hexagons (shows spatial variation)
SELECT h3_cell, yearly_frequency, confidence_tier
FROM grid_species
WHERE scientific_name = 'Cyanocitta stelleri'
ORDER BY yearly_frequency DESC;
-- Returns:
--   617700440036646911 | 0.52 | common
--   617700440036712447 | 0.38 | uncommon

-- Get region info
SELECT value FROM region_metadata WHERE key = 'region_name';
-- Returns: Yosemite National Park (H3 Grid)
```

**Key insight**: Notice how Steller's Jay is "common" (52%) in Yosemite Valley (hexagon 1) but "uncommon" (38%) in Tuolumne Meadows (hexagon 2) at higher elevation. This neighborhood-level precision is the core benefit of the H3 grid approach.

## Future Extensions

### Version 1.1 (Planned)
- GeoJSON polygon boundaries (precise vs bounding box)
- Subspecies-level data
- Breeding status indicators (confirmed/probable/possible)
- Rarity alerts (unusual detections)

### Version 2.0 (Future)
- Multi-year comparison (trend data)
- Hour-of-day patterns (diurnal/nocturnal)
- Habitat associations
- Abundance estimates (not just frequency)
- Integration with eBird Status & Trends models
