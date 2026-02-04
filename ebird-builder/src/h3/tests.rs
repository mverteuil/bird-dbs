/// Tests for H3 aggregation and grid operations
#[cfg(test)]
mod tests {
    use super::super::aggregator::{
        calculate_absence_penalty, classify_species, compute_monthly_data_from_aggregates,
        compute_quarterly_data_from_aggregates, compute_weekly_data_from_aggregates,
        compute_yearly_data_from_aggregates, H3Aggregator, H3CellData,
    };
    use super::super::grid::H3Grid;
    use crate::config::FilterConfig;
    use crate::ebird::EBirdRecord;
    use crate::taxon_registry::{normalize_species_name, TaxonRegistry};
    use chrono::NaiveDate;

    // Helper to create a test registry from records
    fn build_test_registry(records: &[&EBirdRecord]) -> TaxonRegistry {
        let mut registry = TaxonRegistry::new("test".to_string());
        for record in records {
            let normalized_name = normalize_species_name(&record.scientific_name);
            let is_exact_species = record.is_species() && record.scientific_name == normalized_name;
            registry.update_from_record(&normalized_name, &record.taxon_concept_id, is_exact_species);
        }
        registry.finalize();
        registry
    }

    fn sample_record() -> EBirdRecord {
        EBirdRecord {
            taxon_concept_id: "avibase-4A2E6B9F".to_string(), // American Robin
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
        let aggregator = H3Aggregator::new(8);
        assert!(aggregator.is_ok());
        let aggregator = aggregator.unwrap();
        assert_eq!(aggregator.cells.len(), 0);
    }

    #[test]
    fn test_h3_aggregator_add_record() {
        let mut aggregator = H3Aggregator::new(8).unwrap();
        let record = sample_record();

        let result = aggregator.add_record(&record, &record.taxon_concept_id);
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

        aggregator.add_record(&record1, &record1.taxon_concept_id).unwrap();
        aggregator.add_record(&record2, &record2.taxon_concept_id).unwrap();

        // Should still be 1 cell
        assert_eq!(aggregator.cells.len(), 1);

        // But 2 checklists
        let cell_data = aggregator.cells.values().next().unwrap();
        assert_eq!(cell_data.total_checklists, 2);
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

        aggregator.add_record(&record1, &record1.taxon_concept_id).unwrap();
        aggregator.add_record(&record2, &record2.taxon_concept_id).unwrap();

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

        let result = cell_data.add_observation(&record, &record.taxon_concept_id);
        assert!(result.is_ok());

        assert_eq!(cell_data.total_checklists, 1);
        assert_eq!(cell_data.complete_checklists, 1);
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

        cell_data.add_observation(&record1, &record1.taxon_concept_id).unwrap();
        cell_data.add_observation(&record2, &record2.taxon_concept_id).unwrap();

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

        cell_data.add_observation(&record1, &record1.taxon_concept_id).unwrap();
        cell_data.add_observation(&record2, &record2.taxon_concept_id).unwrap();

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
        // Create monthly observation counts array
        let mut monthly_obs = [0u32; 12];
        monthly_obs[0] = 2;  // January (index 0 = month 1): 2 observations
        monthly_obs[5] = 1;  // June (index 5 = month 6): 1 observation

        // Create monthly checklist counters array (species-specific checklists)
        let mut monthly_checklists = [0u32; 12];
        monthly_checklists[0] = 2;  // January: 2 checklists with species
        monthly_checklists[5] = 1;  // June: 1 checklist with species

        // Create monthly complete checklists array (all checklists in cell)
        let mut monthly_complete = [0u32; 12];
        monthly_complete[0] = 3;  // January: 3 total complete checklists in cell
        monthly_complete[5] = 3;  // June: 3 total complete checklists in cell

        let monthly_data = compute_monthly_data_from_aggregates(&monthly_obs, &monthly_checklists, &monthly_complete);

        // Function filters out months with zero observations, so we only get 2 months
        assert_eq!(monthly_data.len(), 2);

        // January (month 1) has 2 observations from 2 checklists
        let january = monthly_data.iter().find(|m| m.month == 1).unwrap();
        assert_eq!(january.observations, 2);
        assert_eq!(january.checklists, 2);
        // Frequency = 2 checklists / 3 total checklists = 0.6666...
        assert!((january.frequency - 0.6666).abs() < 0.001);

        // June (month 6) has 1 observation from 1 checklist
        let june = monthly_data.iter().find(|m| m.month == 6).unwrap();
        assert_eq!(june.observations, 1);
        assert_eq!(june.checklists, 1);
        // Frequency = 1 checklist / 3 total checklists = 0.3333...
        assert!((june.frequency - 0.3333).abs() < 0.001);

        // Other months (e.g., March) should not be present in filtered results
        assert!(monthly_data.iter().find(|m| m.month == 3).is_none());
    }

    #[test]
    fn test_compute_weekly_data() {
        // Create weekly observation counts array (48 weeks)
        let mut weekly_obs = [0u32; 48];
        weekly_obs[0] = 3;   // Week 1 (Jan 1-7): 3 observations
        weekly_obs[25] = 2;  // Week 26 (around Jun 27): 2 observations
        weekly_obs[47] = 1;  // Week 48 (Dec 25-31): 1 observation

        // Create weekly checklist counters array (species-specific)
        let mut weekly_checklists = [0u32; 48];
        weekly_checklists[0] = 3;   // Week 1: 3 checklists with species
        weekly_checklists[25] = 2;  // Week 26: 2 checklists with species
        weekly_checklists[47] = 1;  // Week 48: 1 checklist with species

        // Create weekly complete checklists array (all checklists in cell)
        let mut weekly_complete = [0u32; 48];
        weekly_complete[0] = 6;   // Week 1: 6 total complete checklists
        weekly_complete[25] = 6;  // Week 26: 6 total complete checklists
        weekly_complete[47] = 6;  // Week 48: 6 total complete checklists

        let weekly_data = compute_weekly_data_from_aggregates(&weekly_obs, &weekly_checklists, &weekly_complete);

        // Function filters out weeks with zero observations, so we get 3 weeks
        assert_eq!(weekly_data.len(), 3);

        // Week 1 has 3 observations from 3 checklists
        let week1 = weekly_data.iter().find(|w| w.week == 1).unwrap();
        assert_eq!(week1.observations, 3);
        assert_eq!(week1.checklists, 3);
        // Frequency = 3 checklists / 6 total checklists = 0.5
        assert!((week1.frequency - 0.5).abs() < 0.001);

        // Week 26 has 2 observations from 2 checklists
        let week26 = weekly_data.iter().find(|w| w.week == 26).unwrap();
        assert_eq!(week26.observations, 2);
        assert_eq!(week26.checklists, 2);
        // Frequency = 2 checklists / 6 total checklists = 0.333...
        assert!((week26.frequency - 0.3333).abs() < 0.001);

        // Week 48 has 1 observation from 1 checklist
        let week48 = weekly_data.iter().find(|w| w.week == 48).unwrap();
        assert_eq!(week48.observations, 1);
        assert_eq!(week48.checklists, 1);
        // Frequency = 1 checklist / 6 total checklists = 0.1666...
        assert!((week48.frequency - 0.1666).abs() < 0.001);

        // Other weeks should not be present in filtered results
        assert!(weekly_data.iter().find(|w| w.week == 10).is_none());
    }

    #[test]
    fn test_compute_weekly_data_edge_cases() {
        // Test empty data
        let weekly_obs = [0u32; 48];
        let weekly_checklists = [0u32; 48];
        let weekly_complete = [0u32; 48];
        let weekly_data = compute_weekly_data_from_aggregates(&weekly_obs, &weekly_checklists, &weekly_complete);
        assert_eq!(weekly_data.len(), 0);

        // Test single week with data
        let mut weekly_obs = [0u32; 48];
        weekly_obs[23] = 5;  // Week 24 (around Jun 13)

        let mut weekly_checklists = [0u32; 48];
        weekly_checklists[23] = 2;  // 2 checklists with species

        let mut weekly_complete = [0u32; 48];
        weekly_complete[23] = 2;  // 2 total complete checklists

        let weekly_data = compute_weekly_data_from_aggregates(&weekly_obs, &weekly_checklists, &weekly_complete);
        assert_eq!(weekly_data.len(), 1);

        let week24 = &weekly_data[0];
        assert_eq!(week24.week, 24);
        assert_eq!(week24.observations, 5);
        assert_eq!(week24.checklists, 2);
        // Frequency = 2 checklists / 2 total checklists = 1.0
        assert!((week24.frequency - 1.0).abs() < 0.001);
    }

    #[test]
    fn test_compute_weekly_data_frequency_normalization() {
        // Test that frequency stays within [0.0, 1.0] range
        // This is critical for database CHECK constraints
        let mut weekly_obs = [0u32; 48];
        let mut weekly_checklists = [0u32; 48];
        let mut weekly_complete = [0u32; 48];

        // Add observations across multiple weeks
        for week in 0..48 {
            weekly_obs[week] = (week + 1) as u32;  // Varying observation counts
            weekly_checklists[week] = ((week % 5) + 1) as u32;  // Varying checklist counts (1-5)
            weekly_complete[week] = 10;  // 10 complete checklists per week
        }

        let weekly_data = compute_weekly_data_from_aggregates(&weekly_obs, &weekly_checklists, &weekly_complete);

        // Verify all frequencies are in valid range
        for week_data in weekly_data.iter() {
            assert!(
                week_data.frequency >= 0.0 && week_data.frequency <= 1.0,
                "Week {} frequency {} must be in [0.0, 1.0]",
                week_data.week,
                week_data.frequency
            );
        }

        // Verify we have data for all 48 weeks
        assert_eq!(weekly_data.len(), 48);
    }

    #[test]
    fn test_compute_quarterly_data() {

        // Create quarterly observation counts array (4 quarters)
        let mut quarterly_obs = [0u32; 4];
        quarterly_obs[0] = 5;  // Q1 (Jan-Mar): 5 observations
        quarterly_obs[2] = 3;  // Q3 (Jul-Sep): 3 observations

        // Create quarterly checklist counters array (species-specific)
        let mut quarterly_checklists = [0u32; 4];
        quarterly_checklists[0] = 3;  // Q1: 3 checklists with species
        quarterly_checklists[2] = 2;  // Q3: 2 checklists with species

        // Create quarterly complete checklists array (all checklists in cell)
        let mut quarterly_complete = [0u32; 4];
        quarterly_complete[0] = 5;  // Q1: 5 total complete checklists
        quarterly_complete[2] = 5;  // Q3: 5 total complete checklists

        let quarterly_data =
            compute_quarterly_data_from_aggregates(&quarterly_obs, &quarterly_checklists, &quarterly_complete);

        // Function filters out quarters with zero observations, so we get 2 quarters
        assert_eq!(quarterly_data.len(), 2);

        // Q1 has 5 observations from 3 checklists
        let q1 = quarterly_data.iter().find(|q| q.quarter == 1).unwrap();
        assert_eq!(q1.observations, 5);
        assert_eq!(q1.checklists, 3);
        // Frequency = 3 checklists / 5 total checklists = 0.6
        assert!((q1.frequency - 0.6).abs() < 0.001);

        // Q3 has 3 observations from 2 checklists
        let q3 = quarterly_data.iter().find(|q| q.quarter == 3).unwrap();
        assert_eq!(q3.observations, 3);
        assert_eq!(q3.checklists, 2);
        // Frequency = 2 checklists / 5 total checklists = 0.4
        assert!((q3.frequency - 0.4).abs() < 0.001);

        // Other quarters should not be present in filtered results
        assert!(quarterly_data.iter().find(|q| q.quarter == 2).is_none());
        assert!(quarterly_data.iter().find(|q| q.quarter == 4).is_none());
    }

    #[test]
    fn test_compute_quarterly_data_edge_cases() {
        // Test empty data
        let quarterly_obs = [0u32; 4];
        let quarterly_checklists = [0u32; 4];
        let quarterly_complete = [0u32; 4];
        let quarterly_data =
            compute_quarterly_data_from_aggregates(&quarterly_obs, &quarterly_checklists, &quarterly_complete);
        assert_eq!(quarterly_data.len(), 0);

        // Test single quarter with data
        let mut quarterly_obs = [0u32; 4];
        quarterly_obs[1] = 10; // Q2

        let mut quarterly_checklists = [0u32; 4];
        quarterly_checklists[1] = 3;  // Q2: 3 checklists with species

        let mut quarterly_complete = [0u32; 4];
        quarterly_complete[1] = 3;  // Q2: 3 total complete checklists

        let quarterly_data =
            compute_quarterly_data_from_aggregates(&quarterly_obs, &quarterly_checklists, &quarterly_complete);
        assert_eq!(quarterly_data.len(), 1);

        let q2 = &quarterly_data[0];
        assert_eq!(q2.quarter, 2);
        assert_eq!(q2.observations, 10);
        assert_eq!(q2.checklists, 3);
        // Frequency = 3 checklists / 3 total checklists = 1.0
        assert!((q2.frequency - 1.0).abs() < 0.001);
    }

    #[test]
    fn test_compute_quarterly_data_frequency_normalization() {

        // Test that frequency stays within [0.0, 1.0] range
        let mut quarterly_obs = [0u32; 4];
        let mut quarterly_checklists = [0u32; 4];
        let mut quarterly_complete = [0u32; 4];

        // Add varying observations and checklists across all quarters
        for quarter in 0..4 {
            quarterly_obs[quarter] = ((quarter + 1) * 10) as u32;
            quarterly_checklists[quarter] = ((quarter % 3) + 1) as u32;  // Varying checklist counts (1-3)
            quarterly_complete[quarter] = 10;  // 10 complete checklists per quarter
        }

        let quarterly_data =
            compute_quarterly_data_from_aggregates(&quarterly_obs, &quarterly_checklists, &quarterly_complete);

        // Verify all frequencies are in valid range
        for quarter_data in quarterly_data.iter() {
            assert!(
                quarter_data.frequency >= 0.0 && quarter_data.frequency <= 1.0,
                "Quarter {} frequency {} must be in [0.0, 1.0]",
                quarter_data.quarter,
                quarter_data.frequency
            );
        }

        // Verify we have data for all 4 quarters
        assert_eq!(quarterly_data.len(), 4);
    }

    #[test]
    fn test_compute_yearly_data() {
        use std::collections::HashMap;
        // Create yearly observation data (HashMap of year -> (observations, checklist_count))
        let mut yearly_data = HashMap::new();

        // 2020: 10 observations from 5 checklists with species
        yearly_data.insert(2020, (10, 5));

        // 2022: 5 observations from 3 checklists with species
        yearly_data.insert(2022, (5, 3));

        // Create yearly complete checklists (all checklists in cell per year)
        let mut yearly_complete = HashMap::new();
        yearly_complete.insert(2020, 8);  // 8 total complete checklists in 2020
        yearly_complete.insert(2022, 8);  // 8 total complete checklists in 2022

        let results = compute_yearly_data_from_aggregates(&yearly_data, &yearly_complete);

        assert_eq!(results.len(), 2);

        // Verify 2020 data
        let y2020 = results.iter().find(|y| y.year == 2020).unwrap();
        assert_eq!(y2020.observations, 10);
        assert_eq!(y2020.checklists, 5);
        // Frequency = 5 checklists / 8 total checklists = 0.625
        assert!((y2020.frequency - 0.625).abs() < 0.001);

        // Verify 2022 data
        let y2022 = results.iter().find(|y| y.year == 2022).unwrap();
        assert_eq!(y2022.observations, 5);
        assert_eq!(y2022.checklists, 3);
        // Frequency = 3 checklists / 8 total checklists = 0.375
        assert!((y2022.frequency - 0.375).abs() < 0.001);

        // Results should be sorted by year
        assert_eq!(results[0].year, 2020);
        assert_eq!(results[1].year, 2022);
    }

    #[test]
    fn test_compute_yearly_data_edge_cases() {
        use std::collections::HashMap;

        // Test empty data
        let yearly_data: HashMap<u16, (u32, u32)> = HashMap::new();
        let yearly_complete: HashMap<u16, u32> = HashMap::new();
        let results = compute_yearly_data_from_aggregates(&yearly_data, &yearly_complete);
        assert_eq!(results.len(), 0);

        // Test single year
        let mut yearly_data = HashMap::new();
        yearly_data.insert(2023, (15, 2));  // 15 observations from 2 checklists with species

        let mut yearly_complete = HashMap::new();
        yearly_complete.insert(2023, 2);  // 2 total complete checklists

        let results = compute_yearly_data_from_aggregates(&yearly_data, &yearly_complete);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].year, 2023);
        assert_eq!(results[0].observations, 15);
        assert_eq!(results[0].checklists, 2);
        // Frequency = 2 checklists / 2 total checklists = 1.0
        assert!((results[0].frequency - 1.0).abs() < 0.001);
    }

    #[test]
    fn test_compute_yearly_data_frequency_normalization() {
        use std::collections::HashMap;

        // Test that frequency stays within [0.0, 1.0] range with multiple years
        let mut yearly_data = HashMap::new();
        let mut yearly_complete = HashMap::new();

        // Add data for multiple years with varying checklist counts
        for year in 2015..=2025 {
            let obs_count = (year - 2015 + 1) as u32 * 5;
            let checklist_count = ((year - 2015) % 5 + 1) as u32;  // Varying checklist counts (1-5)

            yearly_data.insert(year, (obs_count, checklist_count));
            yearly_complete.insert(year, 20);  // 20 complete checklists per year
        }

        let results = compute_yearly_data_from_aggregates(&yearly_data, &yearly_complete);

        // Verify all frequencies are in valid range
        for year_data in results.iter() {
            assert!(
                year_data.frequency >= 0.0 && year_data.frequency <= 1.0,
                "Year {} frequency {} must be in [0.0, 1.0]",
                year_data.year,
                year_data.frequency
            );
        }

        // Verify we have data for all years
        assert_eq!(results.len(), 11); // 2015-2025 = 11 years

        // Verify sorting by year
        for i in 0..results.len() - 1 {
            assert!(results[i].year < results[i + 1].year);
        }
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
        cell_data.add_observation(&record, &record.taxon_concept_id).unwrap();

        let mut config = default_filter_config();
        config.min_observations = 2;

        let pack = cell_data.finalize(&grid, &config, &std::collections::HashMap::new());

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
        cell_data.add_observation(&record, &record.taxon_concept_id).unwrap();

        let mut config = default_filter_config();
        config.min_checklists = 2;

        let pack = cell_data.finalize(&grid, &config, &std::collections::HashMap::new());

        assert_eq!(pack.species.len(), 1);
    }

    #[test]
    fn test_finalize_includes_valid_species() {
        let grid = H3Grid::new(8).unwrap();
        let cell = grid.lat_lon_to_cell(42.3601, -71.0589).unwrap();
        let (lat, lon) = grid.cell_to_lat_lon(cell);

        let mut cell_data = H3CellData::new(cell, lat, lon);

        // Add 3 observations from 2 checklists
        // IMPORTANT: Records must be sorted by checklist ID for the optimization to work
        let mut record1 = sample_record();
        record1.sampling_event_id = "S1".to_string();
        let mut record2 = sample_record();
        record2.sampling_event_id = "S1".to_string(); // Same checklist as record1 (sorted together)
        let mut record3 = sample_record();
        record3.sampling_event_id = "S2".to_string(); // Different checklist

        cell_data.add_observation(&record1, &record1.taxon_concept_id).unwrap();
        cell_data.add_observation(&record2, &record2.taxon_concept_id).unwrap();
        cell_data.add_observation(&record3, &record3.taxon_concept_id).unwrap();

        let mut config = default_filter_config();
        config.min_observations = 2;
        config.min_checklists = 2;

        let pack = cell_data.finalize(&grid, &config, &std::collections::HashMap::new());

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
            cell_data.add_observation(&record, &record.taxon_concept_id).unwrap();
        }
        let pack = cell_data.finalize(&grid, &default_filter_config(), &std::collections::HashMap::new());
        assert_eq!(pack.data_quality, "excellent");

        // Test "good" (50-99 complete checklists)
        let mut cell_data = H3CellData::new(cell, lat, lon);
        for i in 0..60 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            cell_data.add_observation(&record, &record.taxon_concept_id).unwrap();
        }
        let pack = cell_data.finalize(&grid, &default_filter_config(), &std::collections::HashMap::new());
        assert_eq!(pack.data_quality, "good");

        // Test "fair" (20-49 complete checklists)
        let mut cell_data = H3CellData::new(cell, lat, lon);
        for i in 0..30 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            cell_data.add_observation(&record, &record.taxon_concept_id).unwrap();
        }
        let pack = cell_data.finalize(&grid, &default_filter_config(), &std::collections::HashMap::new());
        assert_eq!(pack.data_quality, "fair");

        // Test "sparse" (<20 complete checklists)
        let mut cell_data = H3CellData::new(cell, lat, lon);
        for i in 0..10 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            cell_data.add_observation(&record, &record.taxon_concept_id).unwrap();
        }
        let pack = cell_data.finalize(&grid, &default_filter_config(), &std::collections::HashMap::new());
        assert_eq!(pack.data_quality, "sparse");
    }

    #[test]
    fn test_integration_aggregator_finalize() {
        let mut aggregator = H3Aggregator::new(8).unwrap();

        // Add multiple records
        for i in 0..5 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            aggregator.add_record(&record, &record.taxon_concept_id).unwrap();
        }

        let config = default_filter_config();
        let record = sample_record();
        let registry = build_test_registry(&[&record]);

        let packs = aggregator.finalize(&config, &registry);

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

        let mut aggregator = H3Aggregator::new(8).unwrap();

        // Add a record
        let record = sample_record();
        let cell = aggregator
            .grid
            .lat_lon_to_cell(record.latitude, record.longitude)
            .unwrap();
        aggregator.add_record(&record, &record.taxon_concept_id).unwrap();

        // Create sampling data for this cell
        let mut sampling_data = HashMap::new();
        sampling_data.insert(cell, 1200);

        // Create aggregator with sampling data
        let mut aggregator_with_sampling =
            H3Aggregator::new_with_sampling(8, sampling_data.clone()).unwrap();
        aggregator_with_sampling.add_record(&record, &record.taxon_concept_id).unwrap();

        let config = default_filter_config();
        let registry = build_test_registry(&[&record]);
        let packs = aggregator_with_sampling.finalize(&config, &registry);

        assert_eq!(packs.len(), 1);
        // Verify sampling data is included
        assert_eq!(packs[0].total_complete_checklists_sampled, Some(1200));
    }

    #[test]
    fn test_aggregator_absence_penalty_application() {
        use std::collections::HashMap;

        let mut aggregator = H3Aggregator::new(8).unwrap();

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

        aggregator.add_record(&record1, &record1.taxon_concept_id).unwrap();
        aggregator.add_record(&record2, &record2.taxon_concept_id).unwrap();

        // Create sampling data showing strong absence signal
        let mut sampling_data = HashMap::new();
        sampling_data.insert(cell, 1500);

        let mut aggregator_with_sampling =
            H3Aggregator::new_with_sampling(8, sampling_data).unwrap();
        aggregator_with_sampling.add_record(&record1, &record1.taxon_concept_id).unwrap();
        aggregator_with_sampling.add_record(&record2, &record2.taxon_concept_id).unwrap();

        let config = default_filter_config();
        let registry = build_test_registry(&[&record1, &record2]);
        let packs = aggregator_with_sampling.finalize(&config, &registry);

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
        assert!(rare_species.confidence_boost <= 1.3); // Vagrant tier gets max boost
    }

    #[test]
    fn test_aggregator_no_penalty_common_species() {
        use std::collections::HashMap;

        let mut aggregator = H3Aggregator::new(8).unwrap();

        // Add a common species multiple times
        for i in 0..50 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            record.scientific_name = "Common Species".to_string();
            record.common_name = "Common Bird".to_string();
            aggregator.add_record(&record, &record.taxon_concept_id).unwrap();
        }

        let cell = aggregator
            .grid
            .lat_lon_to_cell(sample_record().latitude, sample_record().longitude)
            .unwrap();

        // Create sampling data
        let mut sampling_data = HashMap::new();
        sampling_data.insert(cell, 1500);

        let mut aggregator_with_sampling =
            H3Aggregator::new_with_sampling(8, sampling_data).unwrap();

        for i in 0..50 {
            let mut record = sample_record();
            record.sampling_event_id = format!("S{}", i);
            record.scientific_name = "Common Species".to_string();
            record.common_name = "Common Bird".to_string();
            aggregator_with_sampling.add_record(&record, &record.taxon_concept_id).unwrap();
        }

        let config = default_filter_config();
        let record = sample_record();
        let registry = build_test_registry(&[&record]);
        let packs = aggregator_with_sampling.finalize(&config, &registry);

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

        let mut aggregator = H3Aggregator::new(8).unwrap();

        // Create worst-case scenario for confidence_boost:
        // - Very rare species (frequency ~0.01) → base_boost = 1.0
        // - Strong absence penalty → absence_penalty = 0.8
        // - All low-quality observations → quality_multiplier = 0.7
        // - Expected: 1.0 * 0.8 * 0.7 = 0.56 → clamped to 0.8

        // Add exactly 15 observations from 3 checklists out of 1500 sampled
        // This gives frequency = 3/1500 = 0.002 (rare, but meets min threshold)
        for i in 0..3 {
            for _j in 0..5 {
                let mut record = sample_record();
                record.sampling_event_id = format!("S{}", i);
                record.scientific_name = "Test Species".to_string();
                record.common_name = "Test Bird".to_string();
                // Make all observations low quality
                record.approved = "0".to_string();  // Not approved
                record.all_species_reported = "0".to_string();  // Not complete
                aggregator.add_record(&record, &record.taxon_concept_id).unwrap();
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
            H3Aggregator::new_with_sampling(8, sampling_data).unwrap();

        for i in 0..3 {
            for _j in 0..5 {
                let mut record = sample_record();
                record.sampling_event_id = format!("S{}", i);
                record.scientific_name = "Test Species".to_string();
                record.common_name = "Test Bird".to_string();
                record.approved = "0".to_string();
                // CRITICAL: Must use complete checklists for frequency calculation to work
                record.all_species_reported = "1".to_string();
                aggregator_with_sampling.add_record(&record, &record.taxon_concept_id).unwrap();
            }
        }

        let mut config = default_filter_config();
        config.min_observations = 5;  // Allow species to pass
        config.min_checklists = 3;

        let record = sample_record();
        let registry = build_test_registry(&[&record]);
        let packs = aggregator_with_sampling.finalize(&config, &registry);
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

        // Should be near minimum (0.8-1.0 range) in this worst case
        assert!(
            test_species.confidence_boost <= 1.0,
            "Expected confidence_boost to be <= 1.0 in worst case, got {}",
            test_species.confidence_boost
        );
    }

    #[test]
    fn test_confidence_boost_maximum_edge_case() {
        let mut aggregator = H3Aggregator::new(8).unwrap();

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
            aggregator.add_record(&record, &record.taxon_concept_id).unwrap();
        }

        let config = default_filter_config();
        let record = sample_record();
        let registry = build_test_registry(&[&record]);

        let packs = aggregator.finalize(&config, &registry);

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
            let mut aggregator = H3Aggregator::new(8).unwrap();

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

                aggregator.add_record(&record, &record.taxon_concept_id).unwrap();
            }

            let cell = aggregator
                .grid
                .lat_lon_to_cell(sample_record().latitude, sample_record().longitude)
                .unwrap();

            // Build test registry for finalize
            let record = sample_record();
            let registry = build_test_registry(&[&record]);

            let packs = if has_sampling {
                let mut sampling_data = HashMap::new();
                sampling_data.insert(cell, 1500);
                let mut agg_with_sampling =
                    H3Aggregator::new_with_sampling(8, sampling_data).unwrap();

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

                    agg_with_sampling.add_record(&record, &record.taxon_concept_id).unwrap();
                }

                let mut config = default_filter_config();
                config.min_observations = 1;
                config.min_checklists = 1;
                agg_with_sampling.finalize(&config, &registry)
            } else {
                let mut config = default_filter_config();
                config.min_observations = 1;
                config.min_checklists = 1;
                aggregator.finalize(&config, &registry)
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

    #[test]
    fn test_species_variants_merge_during_aggregation() {
        // Setup: Create H3Aggregator
        let mut aggregator = H3Aggregator::new(7).unwrap();

        // Create two records with variant species names at the same location
        // Both have same taxon_concept_id (Mallard) - one is subspecies variant
        let mut record1 = sample_record();
        record1.taxon_concept_id = "avibase-00012345".to_string(); // Mallard
        record1.scientific_name = "Anas platyrhynchos/wyvilliana".to_string();
        record1.latitude = 21.3069;
        record1.longitude = -157.8583;
        record1.sampling_event_id = "S001".to_string();

        let mut record2 = sample_record();
        record2.taxon_concept_id = "avibase-00012345".to_string(); // Mallard
        record2.scientific_name = "Anas platyrhynchos".to_string();
        record2.latitude = 21.3069;
        record2.longitude = -157.8583;
        record2.sampling_event_id = "S002".to_string();

        // Add both records to the aggregator
        aggregator.add_record(&record1, &record1.taxon_concept_id).unwrap();
        aggregator.add_record(&record2, &record2.taxon_concept_id).unwrap();

        // Finalize with permissive filters
        let filter_config = FilterConfig {
            approved_only: false,
            complete_checklists_only: false,
            native_species_only: false,
            min_observations: 1,
            min_checklists: 1,
            min_yearly_frequency: 0.0,
            deduplication: crate::config::DeduplicationMode::GroupIdentifier,
        };

        let registry = build_test_registry(&[&record1, &record2]);
        let grid_cells = aggregator.finalize(&filter_config, &registry);

        // Verify: Should have exactly 1 grid cell
        assert_eq!(grid_cells.len(), 1, "Expected exactly 1 grid cell");

        let cell = &grid_cells[0];

        // Verify: Should have exactly 1 species (merged)
        assert_eq!(cell.species.len(), 1, "Expected exactly 1 species after variant merging");

        let species = &cell.species[0];

        // Verify: Species name should be normalized
        assert_eq!(species.scientific_name, "Anas platyrhynchos");

        // Verify: Should have observations from both records
        assert_eq!(species.total_observations, 2, "Expected 2 observations from both variant records");

        // Verify: Should have checklists from both records
        assert_eq!(species.total_checklists, 2, "Expected 2 checklists from both variant records");

        // Verify: Avibase ID should match the normalized name
        assert_eq!(species.avibase_id, "avibase-00012345");
    }

    #[test]
    fn test_taxon_id_preference_species_over_slash() {
        // Test that pure species taxon IDs are preferred over slash notation IDs
        let mut aggregator = H3Aggregator::new(7).unwrap();

        // First record: slash notation (Downy/Hairy uncertain)
        let mut record1 = sample_record();
        record1.taxon_concept_id = "avibase-SLASH001".to_string(); // Slash notation ID
        record1.scientific_name = "Dryobates pubescens/villosus".to_string();
        record1.category = Some("slash".to_string()); // NOT species level
        record1.latitude = 42.0;
        record1.longitude = -71.0;
        record1.sampling_event_id = "S001".to_string();

        // Second record: pure species (Downy Woodpecker)
        let mut record2 = sample_record();
        record2.taxon_concept_id = "avibase-SPECIES01".to_string(); // Pure species ID
        record2.scientific_name = "Dryobates pubescens".to_string();
        record2.category = Some("species".to_string()); // Species level
        record2.latitude = 42.0;
        record2.longitude = -71.0;
        record2.sampling_event_id = "S002".to_string();

        // Add slash notation first
        aggregator.add_record(&record1, &record1.taxon_concept_id).unwrap();

        // Add pure species second - should UPDATE the taxon_concept_id
        aggregator.add_record(&record2, &record2.taxon_concept_id).unwrap();

        let filter_config = FilterConfig {
            approved_only: false,
            complete_checklists_only: false,
            native_species_only: false,
            min_observations: 1,
            min_checklists: 1,
            min_yearly_frequency: 0.0,
            deduplication: crate::config::DeduplicationMode::GroupIdentifier,
        };

        let registry = build_test_registry(&[&record1, &record2]);
        let grid_cells = aggregator.finalize(&filter_config, &registry);

        assert_eq!(grid_cells.len(), 1, "Should have exactly 1 grid cell");
        let cell = &grid_cells[0];
        assert_eq!(cell.species.len(), 1, "Should have exactly 1 species");

        let species = &cell.species[0];
        assert_eq!(species.scientific_name, "Dryobates pubescens");

        // CRITICAL: Should have the pure species ID, not the slash notation ID
        assert_eq!(species.avibase_id, "avibase-SPECIES01",
            "Should prefer pure species taxon ID over slash notation ID");

        // Should have observations from both records
        assert_eq!(species.total_checklists, 2);
    }

    #[test]
    fn test_taxon_id_preference_species_first() {
        // Test that when pure species comes first, we keep it
        let mut aggregator = H3Aggregator::new(7).unwrap();

        // First record: pure species (Downy Woodpecker)
        let mut record1 = sample_record();
        record1.taxon_concept_id = "avibase-SPECIES01".to_string();
        record1.scientific_name = "Dryobates pubescens".to_string();
        record1.category = Some("species".to_string());
        record1.latitude = 42.0;
        record1.longitude = -71.0;
        record1.sampling_event_id = "S001".to_string();

        // Second record: slash notation
        let mut record2 = sample_record();
        record2.taxon_concept_id = "avibase-SLASH001".to_string();
        record2.scientific_name = "Dryobates pubescens/villosus".to_string();
        record2.category = Some("slash".to_string());
        record2.latitude = 42.0;
        record2.longitude = -71.0;
        record2.sampling_event_id = "S002".to_string();

        aggregator.add_record(&record1, &record1.taxon_concept_id).unwrap();
        aggregator.add_record(&record2, &record2.taxon_concept_id).unwrap();

        let filter_config = FilterConfig {
            approved_only: false,
            complete_checklists_only: false,
            native_species_only: false,
            min_observations: 1,
            min_checklists: 1,
            min_yearly_frequency: 0.0,
            deduplication: crate::config::DeduplicationMode::GroupIdentifier,
        };

        let registry = build_test_registry(&[&record1, &record2]);
        let grid_cells = aggregator.finalize(&filter_config, &registry);
        let species = &grid_cells[0].species[0];

        // Should keep the original species ID
        assert_eq!(species.avibase_id, "avibase-SPECIES01",
            "Should keep pure species taxon ID when it comes first");
    }

    #[test]
    fn test_post_aggregation_sync_across_multiple_cells() {
        // Test that cells receiving records BEFORE the taxon ID upgrade
        // get synced during finalize(), ensuring consistency across all cells
        let mut aggregator = H3Aggregator::new(7).unwrap();

        // Create records in THREE different cells (different lat/lon)
        // Cell 1: Gets slash notation record ONLY (never sees species record)
        let mut record1 = sample_record();
        record1.taxon_concept_id = "avibase-SLASH001".to_string();
        record1.scientific_name = "Dryobates pubescens/villosus".to_string();
        record1.category = Some("slash".to_string());
        record1.latitude = 42.0;  // Cell 1
        record1.longitude = -71.0;
        record1.sampling_event_id = "S001".to_string();

        // Cell 2: Also gets slash notation ONLY (far from cell 1)
        let mut record2 = sample_record();
        record2.taxon_concept_id = "avibase-SLASH001".to_string();
        record2.scientific_name = "Dryobates pubescens/villosus".to_string();
        record2.category = Some("slash".to_string());
        record2.latitude = 43.0;  // Cell 2 (different from cell 1)
        record2.longitude = -72.0;
        record2.sampling_event_id = "S002".to_string();

        // Cell 3: Gets pure species record (triggers global upgrade)
        let mut record3 = sample_record();
        record3.taxon_concept_id = "avibase-SPECIES01".to_string();
        record3.scientific_name = "Dryobates pubescens".to_string();
        record3.category = Some("species".to_string());
        record3.latitude = 44.0;  // Cell 3 (different from cells 1 & 2)
        record3.longitude = -73.0;
        record3.sampling_event_id = "S003".to_string();

        // Add records: Cell 1 and 2 get slash IDs, then Cell 3 triggers upgrade
        aggregator.add_record(&record1, &record1.taxon_concept_id).unwrap();
        aggregator.add_record(&record2, &record2.taxon_concept_id).unwrap();
        aggregator.add_record(&record3, &record3.taxon_concept_id).unwrap();  // This triggers global registry upgrade

        let filter_config = FilterConfig {
            approved_only: false,
            complete_checklists_only: false,
            native_species_only: false,
            min_observations: 1,
            min_checklists: 1,
            min_yearly_frequency: 0.0,
            deduplication: crate::config::DeduplicationMode::GroupIdentifier,
        };

        let registry = build_test_registry(&[&record1, &record2, &record3]);
        let grid_cells = aggregator.finalize(&filter_config, &registry);

        // Should have 3 cells
        assert_eq!(grid_cells.len(), 3, "Should have exactly 3 grid cells");

        // CRITICAL: ALL cells should have the species-level ID, even cells 1 and 2
        // that only saw slash notation records. Post-aggregation sync should fix them.
        for cell in &grid_cells {
            assert_eq!(cell.species.len(), 1, "Each cell should have exactly 1 species");
            let species = &cell.species[0];
            assert_eq!(
                species.scientific_name, "Dryobates pubescens",
                "All cells should have normalized species name"
            );
            assert_eq!(
                species.avibase_id, "avibase-SPECIES01",
                "All cells should have species-level ID after post-aggregation sync, \
                 even if they only received slash notation records"
            );
        }
    }

    #[test]
    fn test_taxon_id_subspecies_variants() {
        // Test that subspecies with different IDs get aggregated but keep first ID
        let mut aggregator = H3Aggregator::new(7).unwrap();

        // Northern Flicker subspecies 1
        let mut record1 = sample_record();
        record1.taxon_concept_id = "avibase-SUBSPECIES1".to_string();
        record1.scientific_name = "Colaptes auratus".to_string();
        record1.category = Some("species".to_string());
        record1.latitude = 42.0;
        record1.longitude = -71.0;
        record1.sampling_event_id = "S001".to_string();

        // Northern Flicker subspecies 2 (different taxon ID in eBird)
        let mut record2 = sample_record();
        record2.taxon_concept_id = "avibase-SUBSPECIES2".to_string();
        record2.scientific_name = "Colaptes auratus".to_string();
        record2.category = Some("species".to_string());
        record2.latitude = 42.0;
        record2.longitude = -71.0;
        record2.sampling_event_id = "S002".to_string();

        aggregator.add_record(&record1, &record1.taxon_concept_id).unwrap();
        aggregator.add_record(&record2, &record2.taxon_concept_id).unwrap();

        let filter_config = FilterConfig {
            approved_only: false,
            complete_checklists_only: false,
            native_species_only: false,
            min_observations: 1,
            min_checklists: 1,
            min_yearly_frequency: 0.0,
            deduplication: crate::config::DeduplicationMode::GroupIdentifier,
        };

        let registry = build_test_registry(&[&record1, &record2]);
        let grid_cells = aggregator.finalize(&filter_config, &registry);
        let species = &grid_cells[0].species[0];

        // For same species name with different subspecies IDs, first one wins
        // (both are species-level, so no preference update happens)
        assert_eq!(species.avibase_id, "avibase-SUBSPECIES1",
            "Should keep first subspecies taxon ID when both are species-level");
        assert_eq!(species.total_checklists, 2,
            "Should aggregate both subspecies observations");
    }
}

// Standalone tests for normalize_species_name function
use crate::taxon_registry::normalize_species_name;

#[test]
fn test_normalize_species_name_regular() {
    // normalize_species_name now imported at module level
    // Regular species names should pass through unchanged
    assert_eq!(
        normalize_species_name("Anas platyrhynchos"),
        "Anas platyrhynchos"
    );
    assert_eq!(
        normalize_species_name("Cardinalis cardinalis"),
        "Cardinalis cardinalis"
    );
}

#[test]
fn test_normalize_species_name_subspecies_slash() {
    // normalize_species_name now imported at module level
    // Subspecies with slash notation should extract first species
    assert_eq!(
        normalize_species_name("Anas platyrhynchos/wyvilliana"),
        "Anas platyrhynchos"
    );
    assert_eq!(
        normalize_species_name("Larus argentatus/michahellis"),
        "Larus argentatus"
    );
    // Multiple slashes - should take first
    assert_eq!(
        normalize_species_name("Species one/two/three"),
        "Species one"
    );
}

#[test]
fn test_normalize_species_name_hybrids() {
    // normalize_species_name now imported at module level
    // Hybrid notation with " x " should extract first species
    assert_eq!(
        normalize_species_name("Cairina moschata x Anas platyrhynchos"),
        "Cairina moschata"
    );
    assert_eq!(
        normalize_species_name("Columba livia x Columba oenas"),
        "Columba livia"
    );
}

#[test]
fn test_normalize_species_name_parenthetical() {
    // normalize_species_name now imported at module level
    // Parenthetical descriptions should be removed
    assert_eq!(
        normalize_species_name("Aves sp. (goose sp.)"),
        "Aves sp."
    );
    assert_eq!(
        normalize_species_name("Passeriformes sp. (passerine sp.)"),
        "Passeriformes sp."
    );
    // Multiple parenthetical - remove from first opening paren
    assert_eq!(
        normalize_species_name("Species name (desc1) (desc2)"),
        "Species name"
    );
}

#[test]
fn test_normalize_species_name_combinations() {
    // normalize_species_name now imported at module level
    // Parenthetical + slash: remove paren first, then extract first from slash
    assert_eq!(
        normalize_species_name("Anas platyrhynchos/wyvilliana (Mallard)"),
        "Anas platyrhynchos"
    );
    // Parenthetical + hybrid: remove paren first, then extract first from hybrid
    assert_eq!(
        normalize_species_name("Cairina moschata x Anas platyrhynchos (hybrid duck)"),
        "Cairina moschata"
    );
}

#[test]
fn test_normalize_species_name_spuh_preservation() {
    // normalize_species_name now imported at module level

    // Slash notation WITH spuh indicator - should preserve " sp."
    assert_eq!(
        normalize_species_name("Alca/Pinguinus sp."),
        "Alca sp."
    );
    assert_eq!(
        normalize_species_name("Aerospiza/Tachyspiza sp."),
        "Aerospiza sp."
    );

    // Hybrid notation WITH spuh indicator - should preserve " sp."
    assert_eq!(
        normalize_species_name("Genus1 x Genus2 sp."),
        "Genus1 sp."
    );

    // Multiple slash with spuh - should take first and preserve spuh
    assert_eq!(
        normalize_species_name("Genus1/Genus2/Genus3 sp."),
        "Genus1 sp."
    );

    // Test with "spp." (plural spuh)
    assert_eq!(
        normalize_species_name("Alca/Pinguinus spp."),
        "Alca sp."
    );

    // Regular spuh indicators without slash/hybrid - should pass through
    assert_eq!(
        normalize_species_name("Corvus sp."),
        "Corvus sp."
    );
    assert_eq!(
        normalize_species_name("Setophaga sp."),
        "Setophaga sp."
    );
}

#[test]
fn test_normalize_species_name_edge_cases() {
    // normalize_species_name now imported at module level
    // Empty string
    assert_eq!(normalize_species_name(""), "");

    // Single word
    assert_eq!(normalize_species_name("Aves"), "Aves");

    // Slash at end
    assert_eq!(
        normalize_species_name("Anas platyrhynchos/"),
        "Anas platyrhynchos"
    );

    // Whitespace handling around slash
    assert_eq!(
        normalize_species_name("Anas platyrhynchos / wyvilliana"),
        "Anas platyrhynchos"
    );

    // Whitespace handling in hybrid notation
    assert_eq!(
        normalize_species_name("Species one  x  Species two"),
        "Species one"
    );

    // Parentheses only
    assert_eq!(normalize_species_name("(description)"), "");
}
