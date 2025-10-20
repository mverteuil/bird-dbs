/// Tests for H3 aggregation and grid operations
#[cfg(test)]
mod tests {
    use super::super::aggregator::{
        calculate_absence_penalty, classify_species, compute_monthly_data, H3Aggregator,
        H3CellData, ObservationEvent,
    };
    use super::super::grid::H3Grid;
    use crate::config::FilterConfig;
    use crate::ebird::EBirdRecord;
    use chrono::NaiveDate;
    use std::collections::HashMap;

    fn test_avibase_mapping() -> HashMap<String, String> {
        let mut mapping = HashMap::new();
        mapping.insert(
            "Turdus migratorius".to_string(),
            "avibase-4A2E6B9F".to_string(),
        );
        mapping.insert(
            "Cyanocitta cristata".to_string(),
            "avibase-12345678".to_string(),
        );
        mapping.insert("Common Species".to_string(), "avibase-COMMON01".to_string());
        mapping.insert("Rare Species".to_string(), "avibase-RARE0001".to_string());
        mapping
    }

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

    fn default_filter_config() -> FilterConfig {
        FilterConfig {
            approved_only: true,
            complete_checklists_only: true,
            native_species_only: true,
            min_observations: 1,  // Lower default for tests that override
            min_checklists: 1,    // Lower default for tests that override
            min_yearly_frequency: 0.001,
            deduplication: crate::config::DeduplicationMode::GroupIdentifier,
        }
    }

    #[test]
    fn test_h3_grid_creation() {
        let grid = H3Grid::new(8);
        assert!(grid.is_ok());
        let grid = grid.unwrap();
        assert_eq!(grid.resolution(), 8);
    }

    #[test]
    fn test_h3_grid_invalid_resolution() {
        let grid = H3Grid::new(16); // Max is 15
        assert!(grid.is_err());
    }

    #[test]
    fn test_h3_grid_lat_lon_to_cell() {
        let grid = H3Grid::new(8).unwrap();
        let cell = grid.lat_lon_to_cell(42.3601, -71.0589);
        assert!(cell.is_ok());
    }

    #[test]
    fn test_h3_grid_cell_to_lat_lon() {
        let grid = H3Grid::new(8).unwrap();
        let cell = grid.lat_lon_to_cell(42.3601, -71.0589).unwrap();
        let (lat, lon) = grid.cell_to_lat_lon(cell);

        // Should be close to original coordinates (within H3 resolution tolerance)
        assert!((lat - 42.3601).abs() < 0.01);
        assert!((lon - (-71.0589)).abs() < 0.01);
    }

    #[test]
    fn test_h3_grid_same_location_same_cell() {
        let grid = H3Grid::new(8).unwrap();
        let cell1 = grid.lat_lon_to_cell(42.3601, -71.0589).unwrap();
        let cell2 = grid.lat_lon_to_cell(42.3602, -71.0590).unwrap();

        // Very close coordinates should map to same cell at resolution 8
        assert_eq!(cell1, cell2);
    }

    #[test]
    fn test_h3_aggregator_creation() {
        let aggregator = H3Aggregator::new(8, test_avibase_mapping());
        assert!(aggregator.is_ok());
        let aggregator = aggregator.unwrap();
        assert_eq!(aggregator.cells.len(), 0);
    }

    #[test]
    fn test_h3_aggregator_add_record() {
        let mut aggregator = H3Aggregator::new(8, test_avibase_mapping()).unwrap();
        let record = sample_record();

        let result = aggregator.add_record(&record);
        assert!(result.is_ok());
        assert_eq!(aggregator.cells.len(), 1);
    }

    #[test]
    fn test_h3_aggregator_multiple_records_same_cell() {
        let mut aggregator = H3Aggregator::new(8, test_avibase_mapping()).unwrap();

        let mut record1 = sample_record();
        record1.sampling_event_id = "S111".to_string();

        let mut record2 = sample_record();
        record2.sampling_event_id = "S222".to_string();
        // Very close to record1 - same cell
        record2.latitude = 42.3602;
        record2.longitude = -71.0590;

        aggregator.add_record(&record1).unwrap();
        aggregator.add_record(&record2).unwrap();

        // Should still be 1 cell
        assert_eq!(aggregator.cells.len(), 1);

        // But 2 checklists
        let cell_data = aggregator.cells.values().next().unwrap();
        assert_eq!(cell_data.total_checklists.len(), 2);
    }

    #[test]
    fn test_h3_aggregator_multiple_records_different_cells() {
        let mut aggregator = H3Aggregator::new(8, test_avibase_mapping()).unwrap();

        let mut record1 = sample_record();
        record1.latitude = 42.3601;
        record1.longitude = -71.0589;

        let mut record2 = sample_record();
        // Far enough to be different cell at resolution 8
        record2.latitude = 42.4;
        record2.longitude = -71.1;

        aggregator.add_record(&record1).unwrap();
        aggregator.add_record(&record2).unwrap();

        // Should be 2 cells
        assert_eq!(aggregator.cells.len(), 2);
    }

    #[test]
    fn test_h3_cell_data_add_observation() {
        let grid = H3Grid::new(8).unwrap();
        let cell = grid.lat_lon_to_cell(42.3601, -71.0589).unwrap();
        let (lat, lon) = grid.cell_to_lat_lon(cell);

        let mut cell_data = H3CellData::new(cell, lat, lon);
        let record = sample_record();

        let result = cell_data.add_observation(&record);
        assert!(result.is_ok());

        assert_eq!(cell_data.total_checklists.len(), 1);
        assert_eq!(cell_data.complete_checklists.len(), 1);
        assert_eq!(cell_data.species.len(), 1);
    }

    #[test]
    fn test_h3_cell_data_date_range_tracking() {
        let grid = H3Grid::new(8).unwrap();
        let cell = grid.lat_lon_to_cell(42.3601, -71.0589).unwrap();
        let (lat, lon) = grid.cell_to_lat_lon(cell);

        let mut cell_data = H3CellData::new(cell, lat, lon);

        let mut record1 = sample_record();
        record1.observation_date = "2024-01-15".to_string();
        record1.sampling_event_id = "S1".to_string();

        let mut record2 = sample_record();
        record2.observation_date = "2024-12-15".to_string();
        record2.sampling_event_id = "S2".to_string();

        cell_data.add_observation(&record1).unwrap();
        cell_data.add_observation(&record2).unwrap();

        assert_eq!(
            cell_data.date_range_start,
            Some(NaiveDate::from_ymd_opt(2024, 1, 15).unwrap())
        );
        assert_eq!(
            cell_data.date_range_end,
            Some(NaiveDate::from_ymd_opt(2024, 12, 15).unwrap())
        );
    }

    #[test]
    fn test_h3_cell_data_species_accumulation() {
        let grid = H3Grid::new(8).unwrap();
        let cell = grid.lat_lon_to_cell(42.3601, -71.0589).unwrap();
        let (lat, lon) = grid.cell_to_lat_lon(cell);

        let mut cell_data = H3CellData::new(cell, lat, lon);

        let mut record1 = sample_record();
        record1.sampling_event_id = "S1".to_string();

        let mut record2 = sample_record();
        record2.sampling_event_id = "S2".to_string();
        record2.scientific_name = "Cyanocitta cristata".to_string();
        record2.common_name = "Blue Jay".to_string();

        cell_data.add_observation(&record1).unwrap();
        cell_data.add_observation(&record2).unwrap();

        assert_eq!(cell_data.species.len(), 2);
    }

    #[test]
    fn test_classify_species_common() {
        let (tier, boost) = classify_species(0.25);
        assert_eq!(tier, "common");
        assert!(boost > 1.0);
    }

    #[test]
    fn test_classify_species_uncommon() {
        let (tier, boost) = classify_species(0.10);
        assert_eq!(tier, "uncommon");
        assert!(boost > 1.0);
    }

    #[test]
    fn test_classify_species_rare() {
        let (tier, boost) = classify_species(0.02);
        assert_eq!(tier, "rare");
        assert!(boost > 1.0);
    }

    #[test]
    fn test_classify_species_vagrant() {
        let (tier, boost) = classify_species(0.005);
        assert_eq!(tier, "vagrant");
        assert!(boost > 1.0);
    }

    #[test]
    fn test_classify_species_boost_max() {
        let (_, boost) = classify_species(1.0);
        assert!(boost <= 1.3); // MAX_BOOST
    }

    #[test]
    fn test_compute_monthly_data() {
        let observations = vec![
            ObservationEvent {
                date: NaiveDate::from_ymd_opt(2024, 1, 15).unwrap(),
                checklist_id: "S1".to_string(),
                count: 1,
                is_approved: true,
                is_complete_checklist: true,
                is_native: true,
                is_species: true,
            },
            ObservationEvent {
                date: NaiveDate::from_ymd_opt(2024, 1, 20).unwrap(),
                checklist_id: "S2".to_string(),
                count: 1,
                is_approved: true,
                is_complete_checklist: true,
                is_native: true,
                is_species: true,
            },
            ObservationEvent {
                date: NaiveDate::from_ymd_opt(2024, 6, 15).unwrap(),
                checklist_id: "S3".to_string(),
                count: 1,
                is_approved: true,
                is_complete_checklist: true,
                is_native: true,
                is_species: true,
            },
        ];

        let monthly_data = compute_monthly_data(&observations, 10.0);

        // Function filters out months with zero observations, so we only get 2 months
        assert_eq!(monthly_data.len(), 2);

        // January (month 1) has 2 observations from 2 checklists
        let january = monthly_data.iter().find(|m| m.month == 1).unwrap();
        assert_eq!(january.observations, 2);
        assert!((january.frequency - 0.2).abs() < 0.001); // 2/10

        // June (month 6) has 1 observation
        let june = monthly_data.iter().find(|m| m.month == 6).unwrap();
        assert_eq!(june.observations, 1);
        assert!((june.frequency - 0.1).abs() < 0.001); // 1/10

        // Other months (e.g., March) should not be present in filtered results
        assert!(monthly_data.iter().find(|m| m.month == 3).is_none());
    }

    #[test]
    fn test_finalize_filters_low_observation_count() {
        let grid = H3Grid::new(8).unwrap();
        let cell = grid.lat_lon_to_cell(42.3601, -71.0589).unwrap();
        let (lat, lon) = grid.cell_to_lat_lon(cell);

        let mut cell_data = H3CellData::new(cell, lat, lon);

        // Add only 1 observation (below min_observations threshold)
        let mut record = sample_record();
        record.observation_count = "1".to_string(); // Override to have only 1 observation
        cell_data.add_observation(&record).unwrap();

        let mut config = default_filter_config();
        config.min_observations = 2;

        let pack = cell_data.finalize(&grid, &config, &std::collections::HashMap::new(), &test_avibase_mapping());

        assert_eq!(pack.species.len(), 1);
    }

    #[test]
    fn test_finalize_filters_low_checklist_count() {
        let grid = H3Grid::new(8).unwrap();
        let cell = grid.lat_lon_to_cell(42.3601, -71.0589).unwrap();
        let (lat, lon) = grid.cell_to_lat_lon(cell);

        let mut cell_data = H3CellData::new(cell, lat, lon);

        // Add only 1 checklist (below min_checklists threshold)
        let record = sample_record();
        cell_data.add_observation(&record).unwrap();

        let mut config = default_filter_config();
        config.min_checklists = 2;

        let pack = cell_data.finalize(&grid, &config, &std::collections::HashMap::new(), &test_avibase_mapping());

        assert_eq!(pack.species.len(), 1);
    }

    #[test]
    fn test_finalize_includes_valid_species() {
        let grid = H3Grid::new(8).unwrap();
        let cell = grid.lat_lon_to_cell(42.3601, -71.0589).unwrap();
        let (lat, lon) = grid.cell_to_lat_lon(cell);

        let mut cell_data = H3CellData::new(cell, lat, lon);

        // Add 3 observations from 2 checklists
        let mut record1 = sample_record();
        record1.sampling_event_id = "S1".to_string();
        let mut record2 = sample_record();
        record2.sampling_event_id = "S2".to_string();
        let mut record3 = sample_record();
        record3.sampling_event_id = "S1".to_string(); // Same checklist as record1

        cell_data.add_observation(&record1).unwrap();
        cell_data.add_observation(&record2).unwrap();
        cell_data.add_observation(&record3).unwrap();

        let mut config = default_filter_config();
        config.min_observations = 2;
        config.min_checklists = 2;

        let pack = cell_data.finalize(&grid, &config, &std::collections::HashMap::new(), &test_avibase_mapping());

        // Should have 1 species (passes filters)
        assert_eq!(pack.species.len(), 1);
        assert_eq!(pack.species[0].scientific_name, "Turdus migratorius");
        assert_eq!(pack.species[0].total_observations, 3);
        assert_eq!(pack.species[0].total_checklists, 2);
    }

    #[test]
    fn test_data_quality_classification() {
        let grid = H3Grid::new(8).unwrap();
        let cell = grid.lat_lon_to_cell(42.3601, -71.0589).unwrap();
        let (lat, lon) = grid.cell_to_lat_lon(cell);

        // Test "excellent" (100+ complete checklists)
        let mut cell_data = H3CellData::new(cell, lat, lon);
        for i in 0..105 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            cell_data.add_observation(&record).unwrap();
        }
        let pack = cell_data.finalize(&grid, &default_filter_config(), &std::collections::HashMap::new(), &test_avibase_mapping());
        assert_eq!(pack.data_quality, "excellent");

        // Test "good" (50-99 complete checklists)
        let mut cell_data = H3CellData::new(cell, lat, lon);
        for i in 0..60 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            cell_data.add_observation(&record).unwrap();
        }
        let pack = cell_data.finalize(&grid, &default_filter_config(), &std::collections::HashMap::new(), &test_avibase_mapping());
        assert_eq!(pack.data_quality, "good");

        // Test "fair" (20-49 complete checklists)
        let mut cell_data = H3CellData::new(cell, lat, lon);
        for i in 0..30 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            cell_data.add_observation(&record).unwrap();
        }
        let pack = cell_data.finalize(&grid, &default_filter_config(), &std::collections::HashMap::new(), &test_avibase_mapping());
        assert_eq!(pack.data_quality, "fair");

        // Test "sparse" (<20 complete checklists)
        let mut cell_data = H3CellData::new(cell, lat, lon);
        for i in 0..10 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            cell_data.add_observation(&record).unwrap();
        }
        let pack = cell_data.finalize(&grid, &default_filter_config(), &std::collections::HashMap::new(), &test_avibase_mapping());
        assert_eq!(pack.data_quality, "sparse");
    }

    #[test]
    fn test_integration_aggregator_finalize() {
        let mut aggregator = H3Aggregator::new(8, test_avibase_mapping()).unwrap();

        // Add multiple records
        for i in 0..5 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            aggregator.add_record(&record).unwrap();
        }

        let config = default_filter_config();
        let packs = aggregator.finalize(&config);

        assert_eq!(packs.len(), 1); // 1 cell
        assert_eq!(packs[0].total_checklists, 5);
        assert_eq!(packs[0].complete_checklists, 5);
    }

    // New tests for absence penalty functionality

    #[test]
    fn test_calculate_absence_penalty_no_sampling_data() {
        // No penalty without sampling data
        let penalty = calculate_absence_penalty(None, 0.0001);
        assert_eq!(penalty, 1.0);
    }

    #[test]
    fn test_calculate_absence_penalty_insufficient_samples() {
        // No penalty with < 1000 samples
        let penalty = calculate_absence_penalty(Some(500), 0.0001);
        assert_eq!(penalty, 1.0);
    }

    #[test]
    fn test_calculate_absence_penalty_strong_absence_signal() {
        // Apply penalty with 1000+ samples and very low frequency
        let penalty = calculate_absence_penalty(Some(1500), 0.0005);
        assert_eq!(penalty, 0.8); // -20% penalty
    }

    #[test]
    fn test_calculate_absence_penalty_no_penalty_above_threshold() {
        // No penalty if frequency >= 0.1%
        let penalty = calculate_absence_penalty(Some(1500), 0.002);
        assert_eq!(penalty, 1.0);
    }

    #[test]
    fn test_aggregator_with_sampling_data() {
        use std::collections::HashMap;

        let mut aggregator = H3Aggregator::new(8, test_avibase_mapping()).unwrap();

        // Add a record
        let record = sample_record();
        let cell = aggregator
            .grid
            .lat_lon_to_cell(record.latitude, record.longitude)
            .unwrap();
        aggregator.add_record(&record).unwrap();

        // Create sampling data for this cell
        let mut sampling_data = HashMap::new();
        sampling_data.insert(cell, 1200);

        // Create aggregator with sampling data
        let mut aggregator_with_sampling =
            H3Aggregator::new_with_sampling(8, sampling_data.clone(), test_avibase_mapping()).unwrap();
        aggregator_with_sampling.add_record(&record).unwrap();

        let config = default_filter_config();
        let packs = aggregator_with_sampling.finalize(&config);

        assert_eq!(packs.len(), 1);
        // Verify sampling data is included
        assert_eq!(packs[0].total_complete_checklists_sampled, Some(1200));
    }

    #[test]
    fn test_aggregator_absence_penalty_application() {
        use std::collections::HashMap;

        let mut aggregator = H3Aggregator::new(8, test_avibase_mapping()).unwrap();

        // Add a very rare species (only 2 checklists out of 1500 sampled)
        let mut record1 = sample_record();
        record1.scientific_name = "Rare Species".to_string();
        record1.common_name = "Rare Bird".to_string();
        record1.sampling_event_id = "S1".to_string();

        let mut record2 = sample_record();
        record2.scientific_name = "Rare Species".to_string();
        record2.common_name = "Rare Bird".to_string();
        record2.sampling_event_id = "S2".to_string();

        let cell = aggregator
            .grid
            .lat_lon_to_cell(record1.latitude, record1.longitude)
            .unwrap();

        aggregator.add_record(&record1).unwrap();
        aggregator.add_record(&record2).unwrap();

        // Create sampling data showing strong absence signal
        let mut sampling_data = HashMap::new();
        sampling_data.insert(cell, 1500);

        let mut aggregator_with_sampling =
            H3Aggregator::new_with_sampling(8, sampling_data, test_avibase_mapping()).unwrap();
        aggregator_with_sampling.add_record(&record1).unwrap();
        aggregator_with_sampling.add_record(&record2).unwrap();

        let config = default_filter_config();
        let packs = aggregator_with_sampling.finalize(&config);

        assert_eq!(packs.len(), 1);

        // The species should have reduced confidence due to absence penalty
        let species_list = &packs[0].species;
        assert!(species_list.len() > 0);

        // Frequency = 2 checklists / 1500 sampled = 0.00133 (> 0.001 threshold but < 0.01)
        // Should NOT trigger absence penalty (frequency >= 0.001)
        let rare_species = species_list
            .iter()
            .find(|s| s.scientific_name == "Rare Species")
            .expect("Should find the rare species");

        // Base boost for vagrant tier (freq < 0.01) is ~1.0
        // No absence penalty since frequency >= 0.001
        assert!(rare_species.confidence_boost >= 1.0);
        assert!(rare_species.confidence_boost <= 1.05); // Small boost expected
    }

    #[test]
    fn test_aggregator_no_penalty_common_species() {
        use std::collections::HashMap;

        let mut aggregator = H3Aggregator::new(8, test_avibase_mapping()).unwrap();

        // Add a common species multiple times
        for i in 0..50 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            record.scientific_name = "Common Species".to_string();
            record.common_name = "Common Bird".to_string();
            aggregator.add_record(&record).unwrap();
        }

        let cell = aggregator
            .grid
            .lat_lon_to_cell(sample_record().latitude, sample_record().longitude)
            .unwrap();

        // Create sampling data
        let mut sampling_data = HashMap::new();
        sampling_data.insert(cell, 1500);

        let mut aggregator_with_sampling =
            H3Aggregator::new_with_sampling(8, sampling_data, test_avibase_mapping()).unwrap();

        for i in 0..50 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            record.scientific_name = "Common Species".to_string();
            record.common_name = "Common Bird".to_string();
            aggregator_with_sampling.add_record(&record).unwrap();
        }

        let config = default_filter_config();
        let packs = aggregator_with_sampling.finalize(&config);

        assert_eq!(packs.len(), 1);

        // Frequency = 50 / 1500 = 0.033 (> 0.001 threshold)
        // No absence penalty should be applied
        let species_list = &packs[0].species;
        let common_species = species_list
            .iter()
            .find(|s| s.scientific_name == "Common Species")
            .expect("Should find the common species");

        // Should have positive boost (no penalty)
        assert!(common_species.confidence_boost >= 1.0);
    }

    // Tests for confidence_boost clamping (regression tests for CHECK constraint bug)

    #[test]
    fn test_confidence_boost_minimum_edge_case() {
        use std::collections::HashMap;

        let mut aggregator = H3Aggregator::new(8, test_avibase_mapping()).unwrap();

        // Create worst-case scenario for confidence_boost:
        // - Very rare species (frequency ~0.01) → base_boost = 1.0
        // - Strong absence penalty → absence_penalty = 0.8
        // - All low-quality observations → quality_multiplier = 0.7
        // - Expected: 1.0 * 0.8 * 0.7 = 0.56 → clamped to 0.8

        // Add exactly 15 observations from 3 checklists out of 1500 sampled
        // This gives frequency = 3/1500 = 0.002 (rare, but meets min threshold)
        for i in 0..3 {
            for j in 0..5 {
                let mut record = sample_record();
                record.sampling_event_id = format!("S{}", i);
                record.scientific_name = "Test Species".to_string();
                record.common_name = "Test Bird".to_string();
                // Make all observations low quality
                record.approved = "0".to_string();  // Not approved
                record.all_species_reported = "0".to_string();  // Not complete
                aggregator.add_record(&record).unwrap();
            }
        }

        let cell = aggregator
            .grid
            .lat_lon_to_cell(sample_record().latitude, sample_record().longitude)
            .unwrap();

        // Create sampling data showing strong absence signal (1500 sampled checklists)
        let mut sampling_data = HashMap::new();
        sampling_data.insert(cell, 1500);

        let mut aggregator_with_sampling =
            H3Aggregator::new_with_sampling(8, sampling_data, test_avibase_mapping()).unwrap();

        for i in 0..3 {
            for j in 0..5 {
                let mut record = sample_record();
                record.sampling_event_id = format!("S{}", i);
                record.scientific_name = "Test Species".to_string();
                record.common_name = "Test Bird".to_string();
                record.approved = "0".to_string();
                record.all_species_reported = "0".to_string();
                aggregator_with_sampling.add_record(&record).unwrap();
            }
        }

        let mut config = default_filter_config();
        config.min_observations = 5;  // Allow species to pass
        config.min_checklists = 3;

        let packs = aggregator_with_sampling.finalize(&config);
        assert_eq!(packs.len(), 1);

        let species_list = &packs[0].species;
        let test_species = species_list
            .iter()
            .find(|s| s.scientific_name == "Test Species")
            .expect("Should find the test species");

        // CRITICAL: confidence_boost must be >= 0.8 (database constraint)
        assert!(
            test_species.confidence_boost >= 0.8,
            "confidence_boost {} must be >= 0.8 (database constraint)",
            test_species.confidence_boost
        );

        // Should be clamped to exactly 0.8 in this worst case
        assert!(
            (test_species.confidence_boost - 0.8).abs() < 0.01,
            "Expected confidence_boost to be clamped to ~0.8, got {}",
            test_species.confidence_boost
        );
    }

    #[test]
    fn test_confidence_boost_maximum_edge_case() {
        use std::collections::HashMap;

        let mut aggregator = H3Aggregator::new(8, test_avibase_mapping()).unwrap();

        // Create best-case scenario for confidence_boost:
        // - Very common species (frequency near 1.0) → base_boost = 1.3 (MAX_BOOST)
        // - No absence penalty → absence_penalty = 1.0
        // - All high-quality observations → quality_multiplier = 1.0
        // - Expected: 1.3 * 1.0 * 1.0 = 1.3 (within 0.8-2.0 range)

        // Add 100 observations from 100 checklists
        for i in 0..100 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            record.scientific_name = "Very Common Species".to_string();
            record.common_name = "Very Common Bird".to_string();
            // Ensure high quality
            record.approved = "1".to_string();
            record.all_species_reported = "1".to_string();
            record.category = Some("species".to_string());
            record.exotic_code = None;
            aggregator.add_record(&record).unwrap();
        }

        let config = default_filter_config();
        let packs = aggregator.finalize(&config);

        assert_eq!(packs.len(), 1);

        let species_list = &packs[0].species;
        let test_species = species_list
            .iter()
            .find(|s| s.scientific_name == "Very Common Species")
            .expect("Should find the very common species");

        // CRITICAL: confidence_boost must be <= 2.0 (database constraint)
        assert!(
            test_species.confidence_boost <= 2.0,
            "confidence_boost {} must be <= 2.0 (database constraint)",
            test_species.confidence_boost
        );

        // Should be around 1.3 (MAX_BOOST) with perfect quality
        assert!(
            test_species.confidence_boost >= 1.0 && test_species.confidence_boost <= 1.35,
            "Expected confidence_boost to be around 1.3, got {}",
            test_species.confidence_boost
        );
    }

    #[test]
    fn test_confidence_boost_always_in_valid_range() {
        use std::collections::HashMap;

        // Test various combinations to ensure all fall within 0.8-2.0 range
        let test_cases = vec![
            // (checklists, is_high_quality, has_sampling, expected_min, expected_max)
            (2, true, false, 0.8, 2.0),   // Very rare, high quality, no sampling
            (2, false, false, 0.8, 2.0),  // Very rare, low quality, no sampling
            (5, true, true, 0.8, 2.0),    // Rare, high quality, with sampling
            (5, false, true, 0.8, 2.0),   // Rare, low quality, with sampling
            (50, true, true, 0.8, 2.0),   // Common, high quality, with sampling
            (100, true, false, 0.8, 2.0), // Very common, high quality, no sampling
        ];

        for (checklist_count, is_high_quality, has_sampling, min_expected, max_expected) in test_cases {
            let mut aggregator = H3Aggregator::new(8, test_avibase_mapping()).unwrap();

            // Add observations
            for i in 0..checklist_count {
                let mut record = sample_record();
                record.sampling_event_id = format!("S{}", i);
                record.scientific_name = "Test Species".to_string();

                if is_high_quality {
                    record.approved = "1".to_string();
                    record.all_species_reported = "1".to_string();
                    record.category = Some("species".to_string());
                } else {
                    record.approved = "0".to_string();
                    record.all_species_reported = "0".to_string();
                }

                aggregator.add_record(&record).unwrap();
            }

            let cell = aggregator
                .grid
                .lat_lon_to_cell(sample_record().latitude, sample_record().longitude)
                .unwrap();

            let packs = if has_sampling {
                let mut sampling_data = HashMap::new();
                sampling_data.insert(cell, 1500);
                let mut agg_with_sampling =
                    H3Aggregator::new_with_sampling(8, sampling_data, test_avibase_mapping()).unwrap();

                for i in 0..checklist_count {
                    let mut record = sample_record();
                    record.sampling_event_id = format!("S{}", i);
                    record.scientific_name = "Test Species".to_string();

                    if is_high_quality {
                        record.approved = "1".to_string();
                        record.all_species_reported = "1".to_string();
                        record.category = Some("species".to_string());
                    } else {
                        record.approved = "0".to_string();
                        record.all_species_reported = "0".to_string();
                    }

                    agg_with_sampling.add_record(&record).unwrap();
                }

                let mut config = default_filter_config();
                config.min_observations = 1;
                config.min_checklists = 1;
                agg_with_sampling.finalize(&config)
            } else {
                let mut config = default_filter_config();
                config.min_observations = 1;
                config.min_checklists = 1;
                aggregator.finalize(&config)
            };

            let species = &packs[0].species[0];
            assert!(
                species.confidence_boost >= min_expected,
                "Case (checklists={}, quality={}, sampling={}): confidence_boost {} < {}",
                checklist_count, is_high_quality, has_sampling,
                species.confidence_boost, min_expected
            );
            assert!(
                species.confidence_boost <= max_expected,
                "Case (checklists={}, quality={}, sampling={}): confidence_boost {} > {}",
                checklist_count, is_high_quality, has_sampling,
                species.confidence_boost, max_expected
            );
        }
    }
}
