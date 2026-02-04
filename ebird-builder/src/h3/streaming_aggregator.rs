use super::aggregator::{H3CellData, GridCellPack};
use super::grid::H3Grid;
use crate::config::FilterConfig;
use crate::ebird::EBirdRecord;
use crate::taxon_registry::TaxonRegistry;
use anyhow::Result;
use h3o::CellIndex;
use std::collections::HashMap;
use std::sync::Arc;

/// Streaming aggregator that processes sorted Parquet data with O(1) memory usage.
///
/// **CRITICAL**: This aggregator assumes data is sorted by (LATITUDE, LONGITUDE, TAXON, DATE)
///
/// Data flow with sorted input:
/// ```
/// Cell 1, Species A, all dates
/// Cell 1, Species B, all dates
/// Cell 1, Species C, all dates
/// Cell 2, Species A, all dates  ← Cell changed! Finalize Cell 1
/// Cell 2, Species D, all dates
/// ...
/// ```
///
/// When the H3 cell changes (lat/lon maps to different cell), we:
/// 1. Finalize and output the previous cell's data
/// 2. Clear memory (only keeping current cell data)
/// 3. Start accumulating the new cell
///
/// This enables O(1) memory usage instead of O(n) because we only keep
/// ONE cell in memory at a time, regardless of total dataset size.
pub struct StreamingH3Aggregator {
    grid: H3Grid,

    /// Current cell being accumulated (None if we haven't seen any data yet)
    current_cell: Option<CellIndex>,
    current_cell_data: Option<H3CellData>,

    /// Configuration for filtering and thresholds
    config: FilterConfig,

    /// Global taxon registry for canonical species IDs (shared via Arc)
    taxon_registry: Arc<TaxonRegistry>,

    /// Sampling data (complete checklists per cell)
    sampling_data: HashMap<CellIndex, usize>,

    /// Statistics
    cells_output: usize,
    records_processed: usize,
}

impl StreamingH3Aggregator {
    pub fn new(
        resolution: u8,
        config: FilterConfig,
        taxon_registry: Arc<TaxonRegistry>,
        sampling_data: HashMap<CellIndex, usize>,
    ) -> Result<Self> {
        Ok(Self {
            grid: H3Grid::new(resolution)?,
            current_cell: None,
            current_cell_data: None,
            config,
            taxon_registry,
            sampling_data,
            cells_output: 0,
            records_processed: 0,
        })
    }

    /// Process a record from sorted Parquet data.
    ///
    /// Returns Some(GridCellPack) if a cell was completed and output.
    /// Returns None if the record was added to the current cell.
    ///
    /// **CRITICAL**: Data must be sorted by (LATITUDE, LONGITUDE, TAXON, DATE)
    pub fn process_record(&mut self, record: &EBirdRecord) -> Result<Option<GridCellPack>> {
        // Get canonical taxon ID from global registry
        let normalized_name = crate::taxon_registry::normalize_species_name(&record.scientific_name);
        let canonical_id = self.taxon_registry.get_canonical_id(&normalized_name)
            .unwrap_or(&record.taxon_concept_id);

        // Compute H3 cell for this record's location
        let h3_cell = self.grid.lat_lon_to_cell(record.latitude, record.longitude)?;

        // Check if we've moved to a new cell
        let cell_changed = self.current_cell.map_or(false, |current| current != h3_cell);

        let mut output = None;

        if cell_changed {
            // Finalize and output previous cell
            if let Some(cell_data) = self.current_cell_data.take() {
                let pack = cell_data.finalize(&self.grid, &self.config, &self.sampling_data);
                self.cells_output += 1;

                log::info!(
                    "Finalized cell {} with {} species ({} records processed so far)",
                    pack.h3_cell,
                    pack.species.len(),
                    self.records_processed
                );

                output = Some(pack);
            }

            // Start new cell
            let (lat, lon) = self.grid.cell_to_lat_lon(h3_cell);
            self.current_cell = Some(h3_cell);
            self.current_cell_data = Some(H3CellData::new(h3_cell, lat, lon));
        } else if self.current_cell.is_none() {
            // First record - initialize first cell
            let (lat, lon) = self.grid.cell_to_lat_lon(h3_cell);
            self.current_cell = Some(h3_cell);
            self.current_cell_data = Some(H3CellData::new(h3_cell, lat, lon));
        }

        // Add record to current cell
        if let Some(ref mut cell_data) = self.current_cell_data {
            cell_data.add_observation(record, canonical_id)?;
        }

        self.records_processed += 1;

        Ok(output)
    }

    /// Finalize and output the last cell.
    ///
    /// Call this after processing all records to ensure the final cell is output.
    pub fn finish(mut self) -> Result<Option<GridCellPack>> {
        if let Some(cell_data) = self.current_cell_data.take() {
            let pack = cell_data.finalize(&self.grid, &self.config, &self.sampling_data);
            self.cells_output += 1;

            log::info!(
                "Finalized final cell {} with {} species",
                pack.h3_cell,
                pack.species.len()
            );
            log::info!(
                "Streaming aggregation complete: {} cells output, {} records processed",
                self.cells_output,
                self.records_processed
            );

            Ok(Some(pack))
        } else {
            Ok(None)
        }
    }

    pub fn cells_output(&self) -> usize {
        self.cells_output
    }

    pub fn records_processed(&self) -> usize {
        self.records_processed
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ebird::EBirdRecord;

    #[test]
    fn test_streaming_aggregator_detects_cell_changes() {
        let config = FilterConfig::default();
        let registry = TaxonRegistry::new();
        let sampling = HashMap::new();

        let mut agg = StreamingH3Aggregator::new(8, config, registry, sampling).unwrap();

        // Create records in different cells
        let record1 = EBirdRecord {
            taxon_concept_id: "avibase-123".to_string(),
            scientific_name: "Species A".to_string(),
            common_name: "Common A".to_string(),
            observation_count: "1".to_string(),
            latitude: 40.0,
            longitude: -74.0,
            observation_date: "2025-01-01".to_string(),
            sampling_event_id: "S001".to_string(),
            group_identifier: None,
            all_species_reported: "1".to_string(),
            approved: "1".to_string(),
            category: Some("species".to_string()),
            exotic_code: None,
        };

        // Same cell as record1
        let record2 = EBirdRecord {
            latitude: 40.0001,
            longitude: -74.0001,
            scientific_name: "Species B".to_string(),
            ..record1.clone()
        };

        // Different cell
        let record3 = EBirdRecord {
            latitude: 41.0,  // Different location
            longitude: -75.0,
            scientific_name: "Species C".to_string(),
            ..record1.clone()
        };

        // Process first record - should not output anything
        let output1 = agg.process_record(&record1).unwrap();
        assert!(output1.is_none(), "First record should not output");

        // Process second record (same cell) - should not output anything
        let output2 = agg.process_record(&record2).unwrap();
        assert!(output2.is_none(), "Same cell should not output");

        // Process third record (different cell) - should output previous cell
        let output3 = agg.process_record(&record3).unwrap();
        assert!(output3.is_some(), "Cell change should output previous cell");

        let pack = output3.unwrap();
        assert_eq!(pack.species.len(), 2, "Previous cell should have 2 species");

        // Finish should output final cell
        let final_output = agg.finish().unwrap();
        assert!(final_output.is_some(), "Finish should output final cell");

        let final_pack = final_output.unwrap();
        assert_eq!(final_pack.species.len(), 1, "Final cell should have 1 species");
    }
}
