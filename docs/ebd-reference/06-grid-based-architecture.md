# Grid-Based Region Pack Architecture (Version 2.0)

## Overview

This document describes an enhanced architecture for region packs that provides **neighborhood-level spatial precision** rather than broad regional aggregation. Inspired by Merlin Bird ID's approach, this design enables BirdNET-Pi to distinguish between species present in nearby locations (e.g., "Tufted Titmouse in Oakland" vs "not in San Francisco proper").

**Key improvement**: Instead of creating one aggregated database per region, we create a **grid-based database** where each small geographic cell (~5km × 5km) has its own species frequency data.

## Motivation

### Problem with Region Aggregation (v1.0)

Current approach: Create `us-ca-sf-bay.db` with species frequencies averaged across entire SF Bay Area (~100km × 60km).

**Issue**: If Tufted Titmouse appears in 15% of checklists in Oakland but 0% in San Francisco (only 10km away), the aggregated pack shows ~8% frequency for the entire region. This loses critical spatial precision.

**Real-world example** (from user):
> "There's no Tufted Titmice in my neighbourhood and Merlin Bird ID would generally factor that in. If enough detections or a truly unmistakeable detection happens, it may show up with an icon to say it's unlikely."

### Solution: Grid-Based Approach

Divide regions into small grid cells (~5km resolution). Each cell has its own species list with frequencies. At query time, BirdNET-Pi loads species data for the user's specific grid cell, providing neighborhood-level precision.

## Architecture

### Grid Cell System: H3 Hexagonal Grid

**Why hexagons over squares?**
- ✅ **All 6 neighbors equidistant** from center (vs squares: corners 1.41x farther)
- ✅ **Perfect for distance-weighted confidence adjustments** (user's primary requirement!)
- ✅ **Smoother transitions** at cell boundaries
- ✅ **Industry-proven** at scale (Uber, Foursquare)
- ✅ **Hierarchical** parent-child relationships

**H3 Resolution levels** (for our use case):
- **Resolution 6**: ~36 km² per hexagon (~6.5km edge) - Regional fallback
- **Resolution 7**: ~5.16 km² per hexagon (~2.5km edge) - **Primary target** 🎯
- **Resolution 8**: ~0.74 km² per hexagon (~900m edge) - Fine-grained urban areas
- **Resolution 9**: ~0.10 km² per hexagon (~350m edge) - Ultra-precise hotspots

**H3 Cell ID encoding**:
```
H3 Index (64-bit integer): 0x872830828ffffff
As hex string: "872830828ffffff" (15 characters)
Encodes: latitude, longitude, resolution level
```

**Calculation**:
```rust
use h3o::{LatLng, Resolution};

fn lat_lon_to_h3_cell(lat: f64, lon: f64, resolution: u8) -> u64 {
    let coord = LatLng::new(lat, lon).expect("valid coordinates");
    let cell = coord.to_cell(Resolution::try_from(resolution).unwrap());
    cell.into()  // Returns u64
}

// Example: User at (37.773, -122.431) at resolution 7
// → H3 cell: 0x872830828ffffff
```

**Python equivalent**:
```python
import h3

cell = h3.geo_to_h3(37.773, -122.431, 7)
# Result: 617700169958293503 (as integer)
# Or: "872830828ffffff" (as hex string)
```

### Database Schema

```sql
-- Region-level metadata
CREATE TABLE region_metadata (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);

-- Per-hexagon-cell metadata
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

-- Species occurrence per hexagon cell
CREATE TABLE grid_species (
    h3_cell BIGINT NOT NULL,
    scientific_name TEXT NOT NULL,
    common_name TEXT NOT NULL,

    -- Occurrence statistics (for THIS hexagon only)
    yearly_frequency REAL NOT NULL CHECK(yearly_frequency >= 0.0 AND yearly_frequency <= 1.0),
    total_observations INTEGER NOT NULL,
    total_checklists INTEGER NOT NULL,
    first_observation DATE NOT NULL,
    last_observation DATE NOT NULL,

    -- Confidence parameters
    confidence_tier TEXT NOT NULL CHECK(confidence_tier IN ('common', 'uncommon', 'rare', 'vagrant')),
    confidence_boost REAL NOT NULL DEFAULT 1.0,

    -- Temporal data
    monthly_frequency_json TEXT NOT NULL,
    monthly_observations_json TEXT NOT NULL,

    -- Optional metadata
    peak_months_json TEXT,
    breeding_season_json TEXT,

    PRIMARY KEY (h3_cell, scientific_name),
    FOREIGN KEY (h3_cell) REFERENCES grid_metadata(h3_cell)
);

CREATE INDEX idx_grid_species_freq ON grid_species(h3_cell, yearly_frequency DESC);
CREATE INDEX idx_grid_species_tier ON grid_species(h3_cell, confidence_tier);
CREATE INDEX idx_grid_species_name ON grid_species(scientific_name);  -- For reverse lookup
```

### Confidence Tier System

Four-tier classification matching Merlin Bird ID behavior:

| Tier | Frequency | Behavior | UI Treatment | Confidence Boost |
|------|-----------|----------|--------------|------------------|
| **common** | ≥ 20% | Always show | Normal | 1.2-1.3× |
| **uncommon** | 5-20% | Always show | Normal | 1.05-1.15× |
| **rare** | 1-5% | Show with warning | ⚠️ "Unlikely here" | 1.0× (no boost) |
| **vagrant** | < 1% or zero | Hide unless high confidence | ⚠️⚠️ "Extremely rare" | 0.9× (penalty) |

**Example**: Tufted Titmouse in user's SF neighborhood
- Grid cell: 37.75_-122.40 (San Francisco proper)
- Frequency: 0% (zero observations in this cell)
- Tier: `vagrant`
- **Result**: Hidden by default. Only shown if BirdNET confidence > 0.95, then displayed with "extremely rare here" warning.

**Example**: Anna's Hummingbird in same location
- Frequency: 68%
- Tier: `common`
- **Result**: Always shown, confidence boosted by 1.25×

## Data Processing

### Using Both Datasets

**Full EBD (ebd_relAug-2025.tar, 201GB)**:
- All observations (presence data)
- Used to count species occurrences per grid cell

**Sampling Dataset (ebd_sampling_relAug-2025.tar, 7.2GB)**:
- Complete checklists only (ALL_SPECIES_REPORTED=1)
- Used to compute total birding effort per grid cell
- Enables **true absence** calculation: Species expected but not detected

**Frequency calculation**:
```
yearly_frequency = species_checklists / complete_checklists_in_grid
```

Not `species_checklists / all_checklists` (which inflates frequencies).

### Rust Pipeline Modifications

#### Step 1: H3 Cell Discretization

```rust
// src/aggregation/grid.rs
use std::collections::HashMap;
use h3o::{LatLng, CellIndex, Resolution};

pub struct H3Aggregator {
    h3_cells: HashMap<CellIndex, H3CellData>,
    resolution: Resolution,  // H3 resolution (e.g., Resolution::Seven)
}

struct H3CellData {
    h3_cell: CellIndex,
    center_lat: f64,
    center_lon: f64,
    species_data: HashMap<String, SpeciesAccumulator>,
    complete_checklists: HashSet<String>,  // From sampling dataset
    total_checklists: HashSet<String>,
    total_observations: u32,
    date_range: (NaiveDate, NaiveDate),
}

impl H3Aggregator {
    pub fn new(resolution: Resolution) -> Self {
        Self {
            h3_cells: HashMap::new(),
            resolution,
        }
    }

    pub fn add_record(&mut self, record: EBirdRecord) -> Result<()> {
        let h3_cell = self.lat_lon_to_h3_cell(record.latitude, record.longitude)?;

        let cell = self.h3_cells.entry(h3_cell).or_insert_with(|| {
            H3CellData::new(h3_cell, record.latitude, record.longitude)
        });

        cell.add_observation(record);
        Ok(())
    }

    fn lat_lon_to_h3_cell(&self, lat: f64, lon: f64) -> Result<CellIndex> {
        let coord = LatLng::new(lat, lon)?;
        Ok(coord.to_cell(self.resolution))
    }
}
```

#### Step 2: Complete Checklist Integration

```rust
pub fn process_sampling_dataset(&mut self, sampling_path: &Path) -> Result<()> {
    let mut reader = EBirdSamplingReader::new(sampling_path)?;

    reader.stream_records(|checklist| {
        if checklist.all_species_reported == 1 {
            let h3_cell = self.lat_lon_to_h3_cell(
                checklist.latitude,
                checklist.longitude
            )?;

            if let Some(cell) = self.h3_cells.get_mut(&h3_cell) {
                cell.complete_checklists.insert(checklist.sampling_event_id.clone());
            }
        }
        Ok(())
    })?;

    Ok(())
}
```

#### Step 3: Tier Classification

```rust
fn classify_confidence_tier(
    yearly_frequency: f64,
    complete_checklists_in_grid: usize,
) -> ConfidenceTier {
    // Require minimum data for reliable classification
    if complete_checklists_in_grid < 20 {
        return ConfidenceTier::Vagrant;  // Conservative default
    }

    match yearly_frequency {
        f if f >= 0.20 => ConfidenceTier::Common,
        f if f >= 0.05 => ConfidenceTier::Uncommon,
        f if f >= 0.01 => ConfidenceTier::Rare,
        _ => ConfidenceTier::Vagrant,
    }
}
```

#### Step 4: Adaptive Resolution

```rust
pub fn finalize_with_adaptive_resolution(&mut self) -> Vec<GridCell> {
    let mut final_cells = Vec::new();

    for (grid_id, mut cell) in self.grid_cells.drain() {
        let quality = match cell.complete_checklists.len() {
            n if n >= 100 => DataQuality::Excellent,
            n if n >= 50 => DataQuality::Good,
            n if n >= 20 => DataQuality::Fair,
            _ => DataQuality::Sparse,
        };

        // For sparse cells, aggregate with neighbors
        if quality == DataQuality::Sparse {
            cell = self.aggregate_with_neighbors(grid_id, cell);
            cell.resolution = 0.10;  // Increased to 10km
        }

        cell.data_quality = quality;
        final_cells.push(cell);
    }

    final_cells
}
```

## BirdNET-Pi Integration

### Configuration Extension

```python
# config/models.py
class BirdNETConfig(BaseModel):
    # ... existing fields ...

    # eBird H3 Grid Pack Settings
    enable_ebird_grid_filtering: bool = False
    ebird_grid_pack: str = ""  # Path to H3-based pack
    ebird_h3_resolution: int = 7  # H3 resolution (7 = ~5km hexagons)
    ebird_distance_weighting: bool = True  # Enable distance-weighted confidence
    ebird_neighbor_radius: int = 1  # K-ring radius for neighbor cells
    ebird_show_rare_species: bool = True  # Show tier='rare' with warning
    ebird_show_vagrant_species: bool = False  # Hide tier='vagrant' by default
    ebird_vagrant_confidence_threshold: float = 0.95  # Show vagrants if conf > this
```

### Query Implementation with H3

```python
# detections/birdnet.py
import h3
import sqlite3
import json
from math import radians, cos, sin, asin, sqrt

class BirdDetectionService:
    def __init__(self, config: BirdNETConfig):
        # ... existing code ...

        if config.enable_ebird_grid_filtering:
            self._load_ebird_grid_pack(config.ebird_grid_pack)

    def _load_ebird_grid_pack(self, pack_path: str):
        """Load H3 grid pack metadata."""
        self.grid_conn = sqlite3.connect(pack_path)
        self.grid_conn.row_factory = sqlite3.Row

        # Pre-load grid metadata for fast lookups
        self.grid_metadata = {}
        for row in self.grid_conn.execute("SELECT * FROM grid_metadata").fetchall():
            self.grid_metadata[row['h3_cell']] = dict(row)

        logger.info(f"Loaded {len(self.grid_metadata)} H3 cells from {pack_path}")

    def get_filtered_species_list(self, lat, lon, week):
        """Returns species list filtered by H3-based eBird data."""
        if not self.grid_conn:
            return self._predict_filter_raw(lat, lon, week)  # Fallback

        # Convert lat/lon to H3 cell
        h3_cell = h3.geo_to_h3(lat, lon, self.config.ebird_h3_resolution)

        # Check if cell has sufficient data
        cell_meta = self.grid_metadata.get(h3_cell)

        if not cell_meta or cell_meta['data_quality'] == 'sparse':
            # Fall back to parent cell (coarser resolution)
            species_list = self._query_with_resolution_fallback(lat, lon, week)
        else:
            # Query specific H3 cell
            species_list = self._query_h3_cell(h3_cell, week)

        return species_list

    def _query_h3_cell(self, h3_cell: int, week: int) -> list[dict]:
        """Query species for a specific H3 cell."""
        month = self._week_to_month(week)

        query = """
        SELECT
            gs.scientific_name,
            gs.common_name,
            gs.confidence_tier,
            gs.monthly_frequency_json,
            gs.yearly_frequency
        FROM grid_species gs
        WHERE gs.h3_cell = ?
        """

        rows = self.grid_conn.execute(query, (h3_cell,)).fetchall()

        species_list = []
        for row in rows:
            tier = row['confidence_tier']
            monthly_freq = json.loads(row['monthly_frequency_json'])
            current_month_freq = monthly_freq[month - 1]

            # Tier-based filtering
            if tier == 'vagrant' and not self.config.ebird_show_vagrant_species:
                continue  # Skip vagrants by default

            if current_month_freq >= self.config.ebird_min_frequency:
                species_list.append({
                    'name': f"{row['scientific_name']}_{row['common_name']}",
                    'scientific_name': row['scientific_name'],
                    'tier': tier,
                    'frequency': current_month_freq,
                    'yearly_frequency': row['yearly_frequency'],
                })

        return species_list

    def _query_with_resolution_fallback(self, lat: float, lon: float, week: int) -> list[dict]:
        """Query with hierarchical fallback to coarser resolutions."""
        # Try progressively coarser H3 resolutions
        for res in [self.config.ebird_h3_resolution,
                    self.config.ebird_h3_resolution - 1,
                    self.config.ebird_h3_resolution - 2]:
            if res < 0:
                break

            h3_cell = h3.geo_to_h3(lat, lon, res)
            cell_meta = self.grid_metadata.get(h3_cell)

            if cell_meta and cell_meta['total_checklists'] >= 20:
                return self._query_h3_cell(h3_cell, week)

        # Ultimate fallback to BirdNET metadata model
        return self._predict_filter_raw(lat, lon, week)
```

### Distance-Weighted Confidence Adjustment (KEY FEATURE!)

**The hexagonal advantage**: All 6 neighbors are equidistant, making distance weighting mathematically clean.

```python
def apply_distance_weighted_confidence(
    self,
    detections: list[tuple[str, float]],
    lat: float,
    lon: float,
    week: int,
) -> list[tuple[str, float, str]]:
    """
    Adjust confidence scores based on surrounding H3 cells.

    This is the key benefit of using hexagons: all neighbors are
    equidistant, so weighting is uniform and elegant.
    """
    if not self.config.ebird_distance_weighting:
        # Return without distance weighting
        return [(name, conf, 'unknown') for name, conf in detections]

    # Get user's H3 cell
    user_cell = h3.geo_to_h3(lat, lon, self.config.ebird_h3_resolution)
    user_lat, user_lon = lat, lon  # Exact user location

    # Get neighboring cells (k_ring=1 returns center + 6 neighbors)
    neighbor_cells = h3.k_ring(user_cell, self.config.ebird_neighbor_radius)

    month = self._week_to_month(week)
    adjusted_detections = []

    for species_name, raw_confidence in detections:
        # Parse scientific name from BirdNET tensor format
        scientific_name = species_name.split('_')[0]

        # Collect frequencies from all neighboring cells
        cell_frequencies = []

        for cell in neighbor_cells:
            # Get cell center coordinates
            cell_lat, cell_lon = h3.h3_to_geo(cell)

            # Calculate distance from user to cell center (km)
            distance_km = self._haversine_distance(
                user_lat, user_lon, cell_lat, cell_lon
            )

            # Query species frequency for this cell
            row = self.grid_conn.execute("""
                SELECT yearly_frequency, monthly_frequency_json, confidence_tier
                FROM grid_species
                WHERE h3_cell = ? AND scientific_name = ?
            """, (cell, scientific_name)).fetchone()

            if row:
                monthly_freq = json.loads(row['monthly_frequency_json'])
                current_freq = monthly_freq[month - 1]
                tier = row['confidence_tier']

                # Weight: closer cells contribute more
                # Using inverse distance weighting
                weight = 1.0 / (1.0 + distance_km)

                cell_frequencies.append({
                    'frequency': current_freq,
                    'yearly_frequency': row['yearly_frequency'],
                    'weight': weight,
                    'tier': tier,
                    'distance_km': distance_km,
                })

        if not cell_frequencies:
            # Species not in any neighboring cell → likely vagrant
            if raw_confidence >= self.config.ebird_vagrant_confidence_threshold:
                adjusted_detections.append((species_name, raw_confidence, 'vagrant'))
            continue

        # Calculate weighted average frequency
        total_weight = sum(cf['weight'] for cf in cell_frequencies)
        weighted_freq = sum(
            cf['frequency'] * cf['weight'] for cf in cell_frequencies
        ) / total_weight

        # Determine tier (use most optimistic tier from neighbors)
        tiers = [cf['tier'] for cf in cell_frequencies]
        tier = self._select_best_tier(tiers)

        # Adjust confidence based on weighted frequency
        if tier == 'common':  # High local frequency
            boost = 1.0 + (weighted_freq * 0.3)  # Up to 1.3x
        elif tier == 'uncommon':
            boost = 1.0 + (weighted_freq * 0.15)  # Up to 1.15x
        elif tier == 'rare':
            boost = 1.0  # No boost for rare species
        elif tier == 'vagrant':
            if raw_confidence < self.config.ebird_vagrant_confidence_threshold:
                continue  # Filter out unlikely vagrants
            boost = 0.9  # Slight penalty for vagrants

        adjusted_confidence = min(1.0, raw_confidence * boost)

        # Log for debugging
        logger.debug(
            f"{scientific_name}: raw_conf={raw_confidence:.3f}, "
            f"weighted_freq={weighted_freq:.3f}, boost={boost:.2f}, "
            f"adjusted_conf={adjusted_confidence:.3f}, tier={tier}"
        )

        adjusted_detections.append((species_name, adjusted_confidence, tier))

    return adjusted_detections

def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points on Earth (km)."""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    r = 6371  # Earth radius in kilometers
    return c * r

def _select_best_tier(self, tiers: list[str]) -> str:
    """Select most optimistic tier from list."""
    tier_priority = {'common': 0, 'uncommon': 1, 'rare': 2, 'vagrant': 3}
    return min(tiers, key=lambda t: tier_priority[t])

    def _query_expanded_grid(self, lat: float, lon: float, week: int) -> list[str]:
        """Query surrounding grid cells if primary cell is sparse."""
        center_grid_id = self._lat_lon_to_grid_id(lat, lon)
        res = self.config.ebird_grid_resolution
        radius = self.config.ebird_grid_fallback_radius

        # Generate 3×3 (or 5×5) grid of IDs around center
        grid_ids = []
        center_lat, center_lon = map(float, center_grid_id.split('_'))

        for dlat in range(-radius, radius + 1):
            for dlon in range(-radius, radius + 1):
                neighbor_lat = center_lat + (dlat * res)
                neighbor_lon = center_lon + (dlon * res)
                grid_ids.append(f"{neighbor_lat:.2f}_{neighbor_lon:.2f}")

        # Query all neighboring cells
        placeholders = ','.join('?' * len(grid_ids))
        query = f"""
        SELECT
            gs.scientific_name,
            gs.common_name,
            AVG(gs.yearly_frequency) as avg_frequency,
            gs.monthly_frequency_json
        FROM grid_species gs
        WHERE gs.grid_id IN ({placeholders})
        GROUP BY gs.scientific_name
        """

        rows = self.grid_conn.execute(query, grid_ids).fetchall()

        # Process same as single-cell query
        # ... (similar filtering logic)

        return species_list
```

### Post-Detection Filtering

```python
# detections/birdnet.py (continued)
def apply_ebird_confidence_adjustment(
    self,
    detections: list[tuple[str, float]],
    lat: float,
    lon: float,
    week: int,
) -> list[tuple[str, float, str]]:
    """Adjust confidence based on eBird grid data and add tier labels."""

    if not self.grid_conn:
        return [(name, conf, 'unknown') for name, conf in detections]

    grid_id = self._lat_lon_to_grid_id(lat, lon)
    month = self._week_to_month(week)

    # Load species data for this grid
    species_data = {}
    for row in self.grid_conn.execute(
        "SELECT * FROM grid_species WHERE grid_id = ?", (grid_id,)
    ).fetchall():
        species_data[row['scientific_name']] = row

    adjusted_detections = []
    for species_name, confidence in detections:
        # Parse scientific name from BirdNET format
        scientific_name = species_name.split('_')[0]

        if scientific_name in species_data:
            sp = species_data[scientific_name]
            tier = sp['confidence_tier']
            monthly_freq = json.loads(sp['monthly_frequency_json'])

            # Adjust confidence based on tier
            if tier == 'common':
                adjusted_conf = min(1.0, confidence * sp['confidence_boost'])
            elif tier == 'uncommon':
                adjusted_conf = min(1.0, confidence * sp['confidence_boost'])
            elif tier == 'rare':
                adjusted_conf = confidence  # No boost
            elif tier == 'vagrant':
                # Only show if confidence is exceptionally high
                if confidence < self.config.ebird_vagrant_confidence_threshold:
                    continue  # Filter out
                adjusted_conf = confidence * 0.9  # Slight penalty

            adjusted_detections.append((species_name, adjusted_conf, tier))
        else:
            # Species not in grid → likely vagrant
            if confidence >= self.config.ebird_vagrant_confidence_threshold:
                adjusted_detections.append((species_name, confidence, 'vagrant'))

    return adjusted_detections
```

## File Size Analysis

### Size Estimates

**SF Bay Area** (100km × 60km at 5km resolution):
- Grid cells: 20 × 12 = 240
- Avg species per cell: 150 (not all 450 appear everywhere)
- Size per species record: ~250 bytes (with indexes)
- **Total**: 240 × 150 × 250 = **9MB**

**California** (1,400km × 900km at 5km resolution):
- Grid cells: 280 × 180 = 50,400
- Avg species per cell: 100 (sparse in deserts/mountains)
- **Total**: 50,400 × 100 × 250 = **1.26GB** (too large!)

**California with 10km resolution**:
- Grid cells: 140 × 90 = 12,600
- **Total**: 12,600 × 100 × 250 = **315MB** (borderline)

**California with adaptive resolution** (5km urban, 10km suburban, 20km rural):
- Effective cells: ~8,000
- **Total**: 8,000 × 120 × 250 = **240MB**

### Recommended Pack Sizes

| Pack Type | Resolution | Cells | Est. Size | Use Case |
|-----------|------------|-------|-----------|----------|
| **City** (SF, NYC) | 5km | 200-500 | 5-15MB | Urban, high eBird density |
| **Metro** (Bay Area) | 5km adaptive | 500-1000 | 10-25MB | Metro regions |
| **State** (California) | 10km adaptive | 5,000-10,000 | 50-150MB | State-level coverage |
| **Country** (USA) | 20km adaptive | 50,000-100,000 | 500MB-1GB | National fallback |

**User's 15-20MB budget**: Perfect for metro-level packs with 5km resolution (like SF Bay Area, NYC metro, etc.)

## CLI Usage

### Generating Grid-Based Packs

```bash
# High-resolution metro pack (5km)
ebird-region-pack \
  --input ebd_relAug-2025.tar \
  --sampling ebd_sampling_relAug-2025.tar \
  --config regions/us-ca-sf-bay.yaml \
  --output packs/us-ca-sf-bay-grid.db \
  --grid-resolution 0.05 \
  --adaptive-resolution

# Configuration YAML
cat > us-ca-sf-bay.yaml <<EOF
region_id: us-ca-sf-bay-grid
region_name: San Francisco Bay Area (Grid-based)
region_type: custom
bounding_box:
  min_latitude: 37.2
  max_latitude: 38.2
  min_longitude: -122.6
  max_longitude: -121.6
grid_resolution: 0.05  # 5km
adaptive_resolution: true
min_checklists_per_cell: 20
filters:
  approved_only: true
  complete_checklists_only: true
  native_species_only: true
  min_observations: 5
  min_checklists: 3
  min_yearly_frequency: 0.005
  deduplication: group_identifier
EOF
```

### Querying Grid Packs

```bash
# Inspect grid pack
sqlite3 us-ca-sf-bay-grid.db <<SQL
-- Count grid cells
SELECT COUNT(*) FROM grid_metadata;

-- Show grid cell coverage
SELECT
    data_quality,
    COUNT(*) as cell_count,
    AVG(complete_checklists) as avg_checklists
FROM grid_metadata
GROUP BY data_quality;

-- Find species in specific grid cell
SELECT
    scientific_name,
    common_name,
    yearly_frequency,
    confidence_tier
FROM grid_species
WHERE grid_id = '37.75_-122.40'
ORDER BY yearly_frequency DESC;

-- Compare neighboring cells
SELECT
    gs.grid_id,
    gs.scientific_name,
    gs.yearly_frequency
FROM grid_species gs
WHERE gs.scientific_name = 'Cyanocitta stelleri'
  AND gs.grid_id LIKE '37.7%'
ORDER BY gs.yearly_frequency DESC;
SQL
```

## Advantages

1. **Neighborhood-level precision**: Detects species presence variations across 5-10km
2. **True absence data**: Uses complete checklists to identify "expected but not seen"
3. **Tier-based filtering**: Mimics Merlin's "unlikely" warnings
4. **Adaptive resolution**: High resolution where data is rich, coarser where sparse
5. **Scalable**: Can cover metro areas (15MB) or entire states (150MB) with single database

## Migration Path

### Version 1.0 → Version 2.0

**Phase 1**: Generate v1.0 packs (region-aggregated) for initial BirdNET-Pi integration

**Phase 2**: Generate v2.0 packs (grid-based) for enhanced accuracy

**Phase 3**: BirdNET-Pi supports both formats:
```python
if pack_version == "2.0":
    use_grid_based_filtering()
elif pack_version == "1.0":
    use_region_aggregated_filtering()
```

Users can upgrade packs independently.

## Optional Enhancement: SpatiaLite

### Overview

**SpatiaLite** is a spatial extension to SQLite that adds geometry types, spatial indexes (R-tree), and spatial query functions. It can enhance the grid-based approach with elegant spatial queries.

**Benefits**:
- Robust "find nearest grid cells" without manual calculation
- Handle edge cases (user near grid boundaries)
- Enable radius queries ("all cells within 10km")
- Works with adaptive resolution grids

**Cost**:
- Extension size: ~500KB
- No runtime dependencies (bundled with rusqlite/pysqlite3)
- Query overhead: <1ms (negligible)

### Enhanced Schema

```sql
-- Load spatial extension
SELECT load_extension('mod_spatialite');
SELECT InitSpatialMetadata(1);

-- Add geometry column to grid_metadata
SELECT AddGeometryColumn('grid_metadata', 'geometry', 4326, 'POINT', 'XY');

-- Populate geometry from lat/lon
UPDATE grid_metadata
SET geometry = MakePoint(center_lon, center_lat, 4326);

-- Create spatial index
SELECT CreateSpatialIndex('grid_metadata', 'geometry');
```

### Spatial Queries

**Find nearest grid cell:**
```sql
SELECT grid_id
FROM grid_metadata
WHERE ST_Distance(geometry, MakePoint(?, ?)) < 0.2  -- ~20km radius
ORDER BY ST_Distance(geometry, MakePoint(?, ?))
LIMIT 1;
```

**Find cells within radius:**
```sql
SELECT grid_id, ST_Distance(geometry, MakePoint(?, ?)) * 111 as distance_km
FROM grid_metadata
WHERE ST_Distance(geometry, MakePoint(?, ?)) < 0.1  -- ~10km
ORDER BY distance_km;
```

**Find cells in polygon (future - custom regions):**
```sql
SELECT grid_id
FROM grid_metadata
WHERE ST_Within(geometry, GeomFromText('POLYGON((...))', 4326));
```

### Implementation

**Rust (rusqlite with bundled feature):**
```rust
// Cargo.toml
[dependencies]
rusqlite = { version = "0.32", features = ["bundled"] }

// src/region/writer.rs
fn create_spatial_schema(conn: &mut Connection) -> Result<()> {
    conn.execute_batch(
        "SELECT InitSpatialMetadata(1);
         SELECT AddGeometryColumn('grid_metadata', 'geometry', 4326, 'POINT', 'XY');"
    )?;

    Ok(())
}

fn insert_grid_metadata_with_geometry(
    conn: &mut Connection,
    grid_id: &str,
    lat: f64,
    lon: f64,
    ...
) -> Result<()> {
    conn.execute(
        "INSERT INTO grid_metadata (grid_id, center_lat, center_lon, geometry, ...)
         VALUES (?, ?, ?, MakePoint(?, ?, 4326), ...)",
        params![grid_id, lat, lon, lon, lat, ...],
    )?;

    Ok(())
}
```

**Python (pysqlite3 or sqlite3 with spatial support):**
```python
import sqlite3

# Enable SpatiaLite extension
conn = sqlite3.connect('us-ca-sf-bay-grid.db')
conn.enable_load_extension(True)
conn.load_extension('mod_spatialite')

# Query nearest grid cells
user_lat, user_lon = 37.773, -122.431

nearest_cells = conn.execute("""
    SELECT
        grid_id,
        ST_Distance(geometry, MakePoint(?, ?)) * 111 as distance_km
    FROM grid_metadata
    ORDER BY distance_km
    LIMIT 9
""", (user_lon, user_lat)).fetchall()

for grid_id, dist in nearest_cells:
    print(f"Grid {grid_id}: {dist:.2f} km away")
```

### Backward Compatibility

SpatiaLite is **optional**. Packs can include both:
- `center_lat`, `center_lon` columns (for simple lookup)
- `geometry` column (for spatial queries)

Clients without SpatiaLite support can use the simple approach:
```python
grid_id = f"{int(lat/0.05)*0.05:.2f}_{int(lon/0.05)*0.05:.2f}"
```

### When to Use SpatiaLite

**Use SpatiaLite if:**
- Generating packs with adaptive/irregular grids
- Need robust edge case handling
- Want to support future features (polygon regions, custom boundaries)

**Skip SpatiaLite if:**
- Generating simple uniform grids only
- Minimizing dependencies
- Targeting constrained environments

**Recommendation**: Include geometry column in generated packs, but make spatial queries optional in BirdNET-Pi.

## Alternative Approaches Evaluated

### Discriminative ML Model
**Idea**: Train neural network to predict species presence from (lat, lon, week).

**Verdict**: ❌ Not recommended. This replicates BirdNET's existing metadata model problem - we want REAL observations, not ML predictions. Could be useful for sparse grid interpolation in v3.0.

### Vector Database (Pinecone, Weaviate, Milvus)
**Idea**: Encode locations as vectors, use similarity search.

**Verdict**: ❌ Not suitable. Vector DBs solve semantic similarity in high-dimensional spaces. Our problem is simple spatial distance. Also requires server infrastructure (not offline-compatible).

### Graph Database (Neo4j, ArangoDB)
**Idea**: Model as graph - nodes (species, grid cells), edges (observed_in with frequency).

**Verdict**: ❌ Not suitable. Graph DBs excel at multi-hop relationships ("friends of friends"). Our data has simple 1-hop relationships that SQL handles perfectly. Too heavy for Raspberry Pi (200MB+ memory).

### Spatial Database - Raw Points
**Idea**: Store all observations as points, query within radius in real-time.

**Verdict**: ❌ Too large and slow. 5M observations × 90 bytes = 450MB + indexes = 600-700MB (vs. 15MB for grid). R-tree queries on 5M points = 50-100ms (vs. <1ms for grid lookup).

### Chosen Approach: H3 Hexagonal Grid
**Verdict**: ✅ **SELECTED** for v2.0 - Optimal for distance-weighted confidence adjustments, the primary user requirement.

**Why H3 wins**:
- All 6 neighbors equidistant (perfect for distance weighting)
- Smoother spatial transitions
- Industry-proven at scale (Uber, Foursquare)
- Hierarchical parent-child relationships

### Geohash (Considered)
**Verdict**: ⚠️ Good alternative, but H3's hexagons better for distance weighting.

**Why not chosen**:
- 8 neighbors with varying distances (corners 1.41× farther)
- Awkward distance weighting (need to account for edge vs corner)
- File organization advantage offset by user's need for distance-weighted confidence

**When to reconsider**: If file organization/browsability becomes more important than distance weighting.

### Lat/Lon Grid (Considered)
**Verdict**: ⚠️ Simplest, but loses too many advantages.

**Why not chosen**:
- Same distance-weighting issues as geohash (worse: rectangular, not square)
- No hierarchical relationships
- No industry tooling support

## Dependencies

**Rust**:
```toml
[dependencies]
h3o = "0.6"  # Pure Rust H3 implementation, no C bindings!
rusqlite = { version = "0.32", features = ["bundled"] }
serde_json = "1.0"
```

**Python**:
```bash
pip install h3  # Official Uber H3 library
pip install sqlite3  # Built into Python stdlib
```

## References

- **H3 (Uber)**: https://h3geo.org/
  - **Rust crate (h3o)**: https://docs.rs/h3o/
  - **Python library**: https://github.com/uber/h3-py
- **Merlin Bird ID**: https://merlin.allaboutbirds.org
- **eBird Status & Trends** (uses similar grid approach): https://ebird.org/science/status-and-trends
- **auk R package** (presence/absence modeling): https://cornelllabofornithology.github.io/auk/

## Next Steps

1. Implement grid aggregation in Rust pipeline
2. Update region pack specification (v2.0 schema with optional geometry)
3. Add SpatiaLite support to Rust writer (optional)
4. Create test grid pack for SF Bay Area
5. Integrate grid queries into BirdNET-Pi (with/without SpatiaLite)
6. Add UI indicators for rare/vagrant species
7. Generate state-level grid packs with adaptive resolution
