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
    BCR,
    #[serde(rename = "iba")]
    IBA,
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
