use crate::ebird::EBirdRecord;
use crate::output::DensityReport;
use anyhow::Result;
use chrono::NaiveDate;
use flate2::read::GzDecoder;
use h3o::{CellIndex, LatLng, Resolution};
use indicatif::{ProgressBar, ProgressStyle};
use log::{info, warn};
use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::io::Read;
use std::path::Path;
use tar::Archive;

pub struct DensityAnalyzer {
    resolutions: Vec<Resolution>,
    sample_rate: f64,
    // Per-resolution data: resolution -> (cell_id -> CellDensity)
    cell_data: HashMap<Resolution, HashMap<CellIndex, CellDensity>>,
    total_observations: usize,
}

#[derive(Debug, Clone)]
pub struct CellDensity {
    pub unique_checklists: HashSet<String>,
    pub complete_checklists: HashSet<String>,
    pub total_observations: usize,
    pub date_range_start: Option<NaiveDate>,
    pub date_range_end: Option<NaiveDate>,
}

impl CellDensity {
    fn new() -> Self {
        Self {
            unique_checklists: HashSet::new(),
            complete_checklists: HashSet::new(),
            total_observations: 0,
            date_range_start: None,
            date_range_end: None,
        }
    }

    fn add_observation(&mut self, record: &EBirdRecord) {
        let checklist_id = record.get_checklist_id();

        self.unique_checklists.insert(checklist_id.clone());

        if record.is_complete_checklist() {
            self.complete_checklists.insert(checklist_id);
        }

        self.total_observations += 1;

        // Update date range
        if let Ok(date) = record.parse_date() {
            self.date_range_start =
                Some(self.date_range_start.map(|d| d.min(date)).unwrap_or(date));
            self.date_range_end = Some(self.date_range_end.map(|d| d.max(date)).unwrap_or(date));
        }
    }

    fn estimate_pack_size_mb(&self, resolution: u8, data_resolution: u8) -> f64 {
        // Empirical formula from design doc
        const BYTES_PER_SPECIES_RECORD: f64 = 400.0;
        const AVG_SPECIES_PER_HEX: f64 = 150.0;
        const COMPRESSION_RATIO: f64 = 0.7;

        let resolution_diff = data_resolution.saturating_sub(resolution) as u32;
        let num_data_hexagons = 7_u32.pow(resolution_diff) as f64;

        let total_species_records = num_data_hexagons * AVG_SPECIES_PER_HEX;
        let raw_size_bytes = total_species_records * BYTES_PER_SPECIES_RECORD;
        let compressed_size_mb = (raw_size_bytes * COMPRESSION_RATIO) / 1_000_000.0;

        compressed_size_mb
    }
}

impl DensityAnalyzer {
    pub fn new(resolutions: Vec<u8>, sample_rate: f64) -> Self {
        let resolutions: Vec<Resolution> = resolutions
            .into_iter()
            .map(|r| Resolution::try_from(r).expect("Invalid H3 resolution"))
            .collect();

        Self {
            resolutions,
            sample_rate,
            cell_data: HashMap::new(),
            total_observations: 0,
        }
    }

    pub fn get_observation_count(&self) -> usize {
        self.total_observations
    }

    pub fn process_tsv_file(&mut self, path: &Path) -> Result<usize> {
        let file = File::open(path)?;
        self.process_csv_reader(file)
    }

    pub fn process_tar_file(&mut self, path: &Path) -> Result<usize> {
        let file = File::open(path)?;

        // Try to detect if it's gzipped
        let mut archive = if path.extension().and_then(|s| s.to_str()) == Some("gz") {
            info!("Detected gzip compression");
            let decoder = GzDecoder::new(file);
            Archive::new(Box::new(decoder) as Box<dyn Read>)
        } else {
            Archive::new(Box::new(file) as Box<dyn Read>)
        };

        let mut total_records = 0;

        for entry in archive.entries()? {
            let entry = entry?;
            let path = entry.path()?;

            // Look for .txt or .tsv files in the archive
            if let Some(ext) = path.extension() {
                if ext == "txt" || ext == "tsv" {
                    info!("Processing archive entry: {:?}", path);
                    total_records += self.process_csv_reader(entry)?;
                }
            }
        }

        Ok(total_records)
    }

    fn process_csv_reader<R: Read>(&mut self, reader: R) -> Result<usize> {
        let mut rdr = csv::ReaderBuilder::new()
            .delimiter(b'\t')
            .from_reader(reader);

        let mut total_records = 0;
        let mut filtered_records = 0;

        // Create progress bar
        let pb = ProgressBar::new_spinner();
        pb.set_style(
            ProgressStyle::default_spinner()
                .template("{spinner:.green} [{elapsed_precise}] {msg}")
                .unwrap(),
        );

        for result in rdr.deserialize() {
            total_records += 1;

            if total_records % 10000 == 0 {
                pb.set_message(format!(
                    "Processed {} records ({} filtered)",
                    total_records, filtered_records
                ));
            }

            // Sampling
            if self.sample_rate < 1.0 {
                use std::collections::hash_map::RandomState;
                use std::hash::{BuildHasher, Hash, Hasher};

                let state = RandomState::new();
                let mut hasher = state.build_hasher();
                total_records.hash(&mut hasher);
                let hash_val = hasher.finish();

                if (hash_val as f64 / u64::MAX as f64) > self.sample_rate {
                    continue;
                }
            }

            let record: EBirdRecord = match result {
                Ok(r) => r,
                Err(e) => {
                    warn!("Failed to parse record: {}", e);
                    filtered_records += 1;
                    continue;
                }
            };

            // Apply quality filters
            if !record.passes_quality_filters() {
                filtered_records += 1;
                continue;
            }

            // Add to H3 cells at all resolutions
            self.add_observation(&record)?;
        }

        pb.finish_with_message(format!(
            "Done: {} records processed, {} filtered",
            total_records, filtered_records
        ));

        Ok(total_records)
    }

    fn add_observation(&mut self, record: &EBirdRecord) -> Result<()> {
        // Convert lat/lon to H3 cells at each resolution
        let latlng = LatLng::new(record.latitude, record.longitude)?;

        for res in &self.resolutions {
            let cell = latlng.to_cell(*res);

            let density_map = self.cell_data.entry(*res).or_insert_with(HashMap::new);

            let cell_density = density_map.entry(cell).or_insert_with(CellDensity::new);

            cell_density.add_observation(record);
        }

        self.total_observations += 1;

        Ok(())
    }

    pub fn generate_report(&self, resolution: u8) -> Result<DensityReport> {
        let res = Resolution::try_from(resolution)?;

        let cell_data = self
            .cell_data
            .get(&res)
            .ok_or_else(|| anyhow::anyhow!("No data for resolution {}", resolution))?;

        let mut cells = Vec::new();

        for (cell_index, density) in cell_data {
            let latlng: LatLng = (*cell_index).into();

            // Determine recommended data resolution based on density
            let recommended_data_res = if density.complete_checklists.len() >= 10000 {
                7
            } else if density.complete_checklists.len() >= 5000 {
                6
            } else if density.complete_checklists.len() >= 2000 {
                5
            } else {
                5
            };

            let estimated_pack_size_mb =
                density.estimate_pack_size_mb(resolution, recommended_data_res);

            cells.push(crate::output::CellDensityData {
                h3_cell: format!("{:x}", u64::from(*cell_index)),
                center_lat: latlng.lat(),
                center_lon: latlng.lng(),
                unique_checklists: density.unique_checklists.len(),
                complete_checklists: density.complete_checklists.len(),
                total_observations: density.total_observations,
                date_range_start: density
                    .date_range_start
                    .map(|d| d.to_string())
                    .unwrap_or_default(),
                date_range_end: density
                    .date_range_end
                    .map(|d| d.to_string())
                    .unwrap_or_default(),
                estimated_pack_size_mb,
                recommended_data_resolution: recommended_data_res,
                total_complete_checklists_sampled: None,
            });
        }

        Ok(DensityReport { resolution, cells })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_record(lat: f64, lon: f64, checklist_id: &str) -> EBirdRecord {
        EBirdRecord {
            scientific_name: "Turdus migratorius".to_string(),
            latitude: lat,
            longitude: lon,
            observation_date: "2025-08-15".to_string(),
            sampling_event_id: checklist_id.to_string(),
            group_identifier: Some(checklist_id.to_string()),
            all_species_reported: "1".to_string(),
            approved: "1".to_string(),
            category: Some("species".to_string()),
            exotic_code: None,
        }
    }

    #[test]
    fn test_cell_density_aggregation() {
        let mut density = CellDensity::new();
        let record = create_test_record(37.7749, -122.4194, "S123");

        density.add_observation(&record);

        assert_eq!(density.unique_checklists.len(), 1);
        assert_eq!(density.complete_checklists.len(), 1);
        assert_eq!(density.total_observations, 1);
    }

    #[test]
    fn test_analyzer_multiple_resolutions() {
        let mut analyzer = DensityAnalyzer::new(vec![2, 3, 4], 1.0);

        let record = create_test_record(37.7749, -122.4194, "S123");
        analyzer.add_observation(&record).unwrap();

        assert_eq!(analyzer.get_observation_count(), 1);
        assert_eq!(analyzer.cell_data.len(), 3); // 3 resolutions
    }
}
