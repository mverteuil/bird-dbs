use chrono::NaiveDate;
use serde::Deserialize;

/// Minimal eBird record for density analysis
/// Only includes fields needed for geographic and temporal filtering
#[derive(Debug, Clone, Deserialize)]
pub struct EBirdRecord {
    #[serde(rename = "SCIENTIFIC NAME")]
    pub scientific_name: String,

    #[serde(rename = "LATITUDE")]
    pub latitude: f64,

    #[serde(rename = "LONGITUDE")]
    pub longitude: f64,

    #[serde(rename = "OBSERVATION DATE")]
    pub observation_date: String,

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

    pub fn get_checklist_id(&self) -> String {
        self.group_identifier
            .clone()
            .unwrap_or_else(|| self.sampling_event_id.clone())
    }

    /// Apply quality filters for density analysis
    pub fn passes_quality_filters(&self) -> bool {
        self.is_approved() && self.is_complete_checklist() && self.is_native() && self.is_species()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Datelike;

    fn create_test_record() -> EBirdRecord {
        EBirdRecord {
            scientific_name: "Turdus migratorius".to_string(),
            latitude: 37.7749,
            longitude: -122.4194,
            observation_date: "2025-08-15".to_string(),
            sampling_event_id: "S12345".to_string(),
            group_identifier: Some("G12345".to_string()),
            all_species_reported: "1".to_string(),
            approved: "1".to_string(),
            category: Some("species".to_string()),
            exotic_code: None,
        }
    }

    #[test]
    fn test_parse_date() {
        let record = create_test_record();
        let date = record.parse_date().unwrap();
        assert_eq!(date.year(), 2025);
        assert_eq!(date.month(), 8);
        assert_eq!(date.day(), 15);
    }

    #[test]
    fn test_quality_filters() {
        let record = create_test_record();
        assert!(record.passes_quality_filters());
    }

    #[test]
    fn test_checklist_id_uses_group() {
        let record = create_test_record();
        assert_eq!(record.get_checklist_id(), "G12345");
    }

    #[test]
    fn test_checklist_id_falls_back_to_sampling() {
        let mut record = create_test_record();
        record.group_identifier = None;
        assert_eq!(record.get_checklist_id(), "S12345");
    }
}
