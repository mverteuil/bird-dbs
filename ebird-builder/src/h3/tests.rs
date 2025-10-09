/// Tests for H3 aggregation and grid operations
#[cfg(test)]
mod tests {
    use super::super::aggregator::{
        classify_species, compute_monthly_data, GridCellPack, H3Aggregator, H3CellData,
        ObservationEvent, SpeciesAccumulator,
    };
    use super::super::grid::H3Grid;
    use crate::config::FilterConfig;
    use crate::ebird::EBirdRecord;
    use chrono::NaiveDate;
    use std::collections::{HashMap, HashSet};

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
            min_observations: 2,
            min_checklists: 2,
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
        let aggregator = H3Aggregator::new(8);
        assert!(aggregator.is_ok());
        let aggregator = aggregator.unwrap();
        assert_eq!(aggregator.cells.len(), 0);
    }

    #[test]
    fn test_h3_aggregator_add_record() {
        let mut aggregator = H3Aggregator::new(8).unwrap();
        let record = sample_record();

        let result = aggregator.add_record(&record);
        assert!(result.is_ok());
        assert_eq!(aggregator.cells.len(), 1);
    }

    #[test]
    fn test_h3_aggregator_multiple_records_same_cell() {
        let mut aggregator = H3Aggregator::new(8).unwrap();

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
        let mut aggregator = H3Aggregator::new(8).unwrap();

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
            },
            ObservationEvent {
                date: NaiveDate::from_ymd_opt(2024, 1, 20).unwrap(),
                checklist_id: "S2".to_string(),
                count: 1,
            },
            ObservationEvent {
                date: NaiveDate::from_ymd_opt(2024, 6, 15).unwrap(),
                checklist_id: "S3".to_string(),
                count: 1,
            },
        ];

        let (monthly_freq, monthly_obs) = compute_monthly_data(&observations, 10.0);

        // January has 2 observations from 2 checklists
        assert_eq!(monthly_obs[0], 2);
        assert!((monthly_freq[0] - 0.2).abs() < 0.001); // 2/10

        // June has 1 observation
        assert_eq!(monthly_obs[5], 1);
        assert!((monthly_freq[5] - 0.1).abs() < 0.001); // 1/10

        // Other months should be 0
        assert_eq!(monthly_obs[2], 0);
        assert_eq!(monthly_freq[2], 0.0);
    }

    #[test]
    fn test_finalize_filters_low_observation_count() {
        let grid = H3Grid::new(8).unwrap();
        let cell = grid.lat_lon_to_cell(42.3601, -71.0589).unwrap();
        let (lat, lon) = grid.cell_to_lat_lon(cell);

        let mut cell_data = H3CellData::new(cell, lat, lon);

        // Add only 1 observation (below min_observations threshold)
        let record = sample_record();
        cell_data.add_observation(&record).unwrap();

        let mut config = default_filter_config();
        config.min_observations = 2;

        let pack = cell_data.finalize(&grid, &config);

        // Should have 0 species (filtered out)
        assert_eq!(pack.species.len(), 0);
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

        let pack = cell_data.finalize(&grid, &config);

        // Should have 0 species (filtered out)
        assert_eq!(pack.species.len(), 0);
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

        let pack = cell_data.finalize(&grid, &config);

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
        let pack = cell_data.finalize(&grid, &default_filter_config());
        assert_eq!(pack.data_quality, "excellent");

        // Test "good" (50-99 complete checklists)
        let mut cell_data = H3CellData::new(cell, lat, lon);
        for i in 0..60 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            cell_data.add_observation(&record).unwrap();
        }
        let pack = cell_data.finalize(&grid, &default_filter_config());
        assert_eq!(pack.data_quality, "good");

        // Test "fair" (20-49 complete checklists)
        let mut cell_data = H3CellData::new(cell, lat, lon);
        for i in 0..30 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            cell_data.add_observation(&record).unwrap();
        }
        let pack = cell_data.finalize(&grid, &default_filter_config());
        assert_eq!(pack.data_quality, "fair");

        // Test "sparse" (<20 complete checklists)
        let mut cell_data = H3CellData::new(cell, lat, lon);
        for i in 0..10 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            cell_data.add_observation(&record).unwrap();
        }
        let pack = cell_data.finalize(&grid, &default_filter_config());
        assert_eq!(pack.data_quality, "sparse");
    }

    #[test]
    fn test_integration_aggregator_finalize() {
        let mut aggregator = H3Aggregator::new(8).unwrap();

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
}
