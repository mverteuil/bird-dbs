/// Tests for eBird record parsing and filtering
#[cfg(test)]
mod tests {
    use super::super::record::EBirdRecord;
    use chrono::NaiveDate;

    fn sample_record() -> EBirdRecord {
        EBirdRecord {
            scientific_name: "Turdus migratorius".to_string(),
            common_name: "American Robin".to_string(),
            observation_count: "2".to_string(),
            latitude: 42.3601,
            longitude: -71.0589,
            observation_date: "2024-10-15".to_string(),
            sampling_event_id: "S123456".to_string(),
            group_identifier: None,
            all_species_reported: "1".to_string(),
            approved: "1".to_string(),
            category: Some("species".to_string()),
            exotic_code: None,
        }
    }

    #[test]
    fn test_parse_date_valid() {
        let record = sample_record();
        let date = record.parse_date();
        assert!(date.is_ok());
        assert_eq!(
            date.unwrap(),
            NaiveDate::from_ymd_opt(2024, 10, 15).unwrap()
        );
    }

    #[test]
    fn test_parse_date_invalid() {
        let mut record = sample_record();
        record.observation_date = "invalid-date".to_string();
        let date = record.parse_date();
        assert!(date.is_err());
    }

    #[test]
    fn test_is_complete_checklist_true() {
        let record = sample_record();
        assert!(record.is_complete_checklist());
    }

    #[test]
    fn test_is_complete_checklist_false() {
        let mut record = sample_record();
        record.all_species_reported = "0".to_string();
        assert!(!record.is_complete_checklist());
    }

    #[test]
    fn test_is_approved_true() {
        let record = sample_record();
        assert!(record.is_approved());
    }

    #[test]
    fn test_is_approved_false() {
        let mut record = sample_record();
        record.approved = "0".to_string();
        assert!(!record.is_approved());
    }

    #[test]
    fn test_is_native_no_exotic_code() {
        let record = sample_record();
        assert!(record.is_native());
    }

    #[test]
    fn test_is_native_empty_exotic_code() {
        let mut record = sample_record();
        record.exotic_code = Some("".to_string());
        assert!(record.is_native());
    }

    #[test]
    fn test_is_native_with_exotic_code() {
        let mut record = sample_record();
        record.exotic_code = Some("N".to_string());
        assert!(!record.is_native());
    }

    #[test]
    fn test_is_species_true() {
        let record = sample_record();
        assert!(record.is_species());
    }

    #[test]
    fn test_is_species_false() {
        let mut record = sample_record();
        record.category = Some("hybrid".to_string());
        assert!(!record.is_species());
    }

    #[test]
    fn test_is_species_none_category() {
        let mut record = sample_record();
        record.category = None;
        assert!(record.is_species()); // Default to true
    }

    #[test]
    fn test_get_count_numeric() {
        let record = sample_record();
        assert_eq!(record.get_count(), 2);
    }

    #[test]
    fn test_get_count_x() {
        let mut record = sample_record();
        record.observation_count = "X".to_string();
        assert_eq!(record.get_count(), 1);
    }

    #[test]
    fn test_get_count_invalid() {
        let mut record = sample_record();
        record.observation_count = "invalid".to_string();
        assert_eq!(record.get_count(), 1); // Default to 1
    }

    #[test]
    fn test_get_checklist_id_with_group() {
        let mut record = sample_record();
        record.group_identifier = Some("G789".to_string());
        assert_eq!(record.get_checklist_id(), "G789");
    }

    #[test]
    fn test_get_checklist_id_without_group() {
        let record = sample_record();
        assert_eq!(record.get_checklist_id(), "S123456");
    }

    #[test]
    fn test_record_filtering_chain() {
        let record = sample_record();

        // All filters should pass
        assert!(record.is_approved());
        assert!(record.is_complete_checklist());
        assert!(record.is_native());
        assert!(record.is_species());
    }

    #[test]
    fn test_record_filtering_reject_unapproved() {
        let mut record = sample_record();
        record.approved = "0".to_string();

        assert!(!record.is_approved());
        assert!(record.is_complete_checklist());
        assert!(record.is_native());
        assert!(record.is_species());
    }

    #[test]
    fn test_record_filtering_reject_incomplete() {
        let mut record = sample_record();
        record.all_species_reported = "0".to_string();

        assert!(record.is_approved());
        assert!(!record.is_complete_checklist());
        assert!(record.is_native());
        assert!(record.is_species());
    }

    #[test]
    fn test_record_filtering_reject_exotic() {
        let mut record = sample_record();
        record.exotic_code = Some("N".to_string());

        assert!(record.is_approved());
        assert!(record.is_complete_checklist());
        assert!(!record.is_native());
        assert!(record.is_species());
    }

    #[test]
    fn test_record_filtering_reject_non_species() {
        let mut record = sample_record();
        record.category = Some("slash".to_string());

        assert!(record.is_approved());
        assert!(record.is_complete_checklist());
        assert!(record.is_native());
        assert!(!record.is_species());
    }
}
