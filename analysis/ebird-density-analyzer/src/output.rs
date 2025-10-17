use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::Write;
use std::path::Path;

#[derive(Debug, Serialize, Deserialize)]
pub struct DensityReport {
    pub resolution: u8,
    pub cells: Vec<CellDensityData>,
}

#[derive(Debug, Serialize, Deserialize)]
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

pub fn write_json_report(report: &DensityReport, path: &Path) -> Result<()> {
    let json = serde_json::to_string_pretty(report)?;

    let mut file = File::create(path)?;
    file.write_all(json.as_bytes())?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::NamedTempFile;

    #[test]
    fn test_write_and_read_report() {
        let report = DensityReport {
            resolution: 4,
            cells: vec![CellDensityData {
                h3_cell: "599686042433355775".to_string(),
                center_lat: 37.7749,
                center_lon: -122.4194,
                unique_checklists: 45678,
                complete_checklists: 32145,
                total_observations: 1234567,
                date_range_start: "2010-01-01".to_string(),
                date_range_end: "2025-08-31".to_string(),
                estimated_pack_size_mb: 8.2,
                recommended_data_resolution: 7,
                total_complete_checklists_sampled: None,
            }],
        };

        let temp_file = NamedTempFile::new().unwrap();
        write_json_report(&report, temp_file.path()).unwrap();

        // Read it back
        let file = File::open(temp_file.path()).unwrap();
        let read_report: DensityReport = serde_json::from_reader(file).unwrap();

        assert_eq!(read_report.resolution, 4);
        assert_eq!(read_report.cells.len(), 1);
        assert_eq!(read_report.cells[0].h3_cell, "599686042433355775");
    }
}
