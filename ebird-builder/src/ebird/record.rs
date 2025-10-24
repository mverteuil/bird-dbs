use chrono::NaiveDate;
use serde::Deserialize;

/// Simplified eBird record for POC
/// Full implementation would have all ~50 fields from EBD
#[derive(Debug, Clone, Deserialize)]
pub struct EBirdRecord {
    #[serde(rename = "TAXON CONCEPT ID")]
    pub taxon_concept_id: String, // Avibase ID (e.g., "avibase-C6B5497C")

    #[serde(rename = "SCIENTIFIC NAME")]
    pub scientific_name: String,

    #[serde(rename = "COMMON NAME")]
    #[allow(dead_code)]
    pub common_name: String,

    #[serde(rename = "OBSERVATION COUNT")]
    pub observation_count: String, // "X" or number

    #[serde(rename = "LATITUDE")]
    pub latitude: f64,

    #[serde(rename = "LONGITUDE")]
    pub longitude: f64,

    #[serde(rename = "OBSERVATION DATE")]
    pub observation_date: String, // Will parse to NaiveDate

    #[serde(rename = "SAMPLING EVENT IDENTIFIER")]
    pub sampling_event_id: String,

    #[serde(rename = "GROUP IDENTIFIER", default)]
    pub group_identifier: Option<String>,

    #[serde(rename = "ALL SPECIES REPORTED")]
    pub all_species_reported: String, // "1" or "0"

    #[serde(rename = "APPROVED")]
    pub approved: String, // "1" or "0"

    #[serde(rename = "CATEGORY", default)]
    pub category: Option<String>,

    #[serde(rename = "EXOTIC CODE", default)]
    pub exotic_code: Option<String>,
}

impl EBirdRecord {
    pub fn parse_date(&self) -> Result<NaiveDate, chrono::ParseError> {
        NaiveDate::parse_from_str(&self.observation_date, "%Y-%m-%d")
    }

    pub fn is_complete_checklist(&self) -> bool {
        self.all_species_reported == "1"
    }

    pub fn is_approved(&self) -> bool {
        self.approved == "1"
    }

    pub fn is_native(&self) -> bool {
        self.exotic_code.is_none()
            || self
                .exotic_code
                .as_ref()
                .map(|s| s.is_empty())
                .unwrap_or(true)
    }

    pub fn is_species(&self) -> bool {
        self.category
            .as_ref()
            .map(|c| c == "species")
            .unwrap_or(true)
    }

    pub fn get_count(&self) -> u32 {
        if self.observation_count == "X" {
            1
        } else {
            self.observation_count.parse().unwrap_or(1)
        }
    }

    pub fn get_checklist_id(&self) -> String {
        self.group_identifier
            .clone()
            .unwrap_or_else(|| self.sampling_event_id.clone())
    }
}
