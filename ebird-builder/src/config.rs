use chrono::NaiveDate;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RegionConfig {
    pub region_id: String,
    pub region_name: String,
    pub region_type: RegionType,
    pub h3_resolution: u8,
    pub bounding_box: BoundingBox,
    pub date_range: DateRange,
    pub filters: FilterConfig,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum RegionType {
    Custom,
    State,
    County,
    #[serde(rename = "bcr")]
    Bcr,
    #[serde(rename = "iba")]
    Iba,
    Country,
    Metro,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct BoundingBox {
    pub min_latitude: f64,
    pub max_latitude: f64,
    pub min_longitude: f64,
    pub max_longitude: f64,
}

impl BoundingBox {
    pub fn contains(&self, lat: f64, lon: f64) -> bool {
        lat >= self.min_latitude
            && lat <= self.max_latitude
            && lon >= self.min_longitude
            && lon <= self.max_longitude
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct DateRange {
    pub start: NaiveDate,
    pub end: NaiveDate,
}

impl DateRange {
    pub fn contains(&self, date: &NaiveDate) -> bool {
        date >= &self.start && date <= &self.end
    }
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
#[serde(rename_all = "snake_case")]
pub enum DeduplicationMode {
    GroupIdentifier,
    SamplingEvent,
    None,
}

// Pack manifest structures (from pack-planner output)
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PackManifest {
    pub regions: Vec<RegionManifest>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RegionManifest {
    pub region_id: String,
    pub release_name: String,
    pub h3_cells: Vec<String>,
    pub packs: Vec<Pack>,
    pub size_mb: f64,
    pub pack_count: usize,
    pub center: Center,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Pack {
    pub pack_id: String,
    pub boundary_cell: String,
    pub boundary_resolution: u8,
    pub data_resolution: u8,
    pub center_lat: f64,
    pub center_lon: f64,
    pub estimated_size_mb: f64,
    pub total_checklists: usize,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Center {
    pub lat: f64,
    pub lon: f64,
}

// Density report structures (from ebird-density-analyzer output)
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct DensityReport {
    pub resolution: u8,
    pub cells: Vec<CellDensityData>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CellDensityData {
    pub h3_cell: String,
    pub center_lat: f64,
    pub center_lon: f64,
    pub unique_checklists: usize,
    pub complete_checklists: usize,
    pub total_observations: usize,
    pub date_range_start: String,
    pub date_range_end: String,
    pub estimated_pack_size_mb: f64,
    pub recommended_data_resolution: u8,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total_complete_checklists_sampled: Option<usize>,
}

// Pack registry structures (for BirdNET-Pi runtime lookup)
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PackRegistry {
    pub version: String,
    pub generated_at: String,
    pub total_regions: usize,
    pub total_packs: usize,
    pub regions: Vec<RegistryRegion>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RegistryRegion {
    pub region_id: String,
    pub release_name: String,
    pub h3_cells: Vec<String>,
    pub pack_count: usize,
    pub total_size_mb: f64,
    pub resolution: u8,
    pub center: Center,
    pub bbox: BBox,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct BBox {
    pub min_lat: f64,
    pub max_lat: f64,
    pub min_lon: f64,
    pub max_lon: f64,
}
