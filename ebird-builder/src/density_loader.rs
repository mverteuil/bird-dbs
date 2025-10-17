use crate::config::DensityReport;
use anyhow::{Context, Result};
use h3o::CellIndex;
use log::info;
use std::collections::HashMap;
use std::fs::File;
use std::path::Path;
use std::str::FromStr;

/// Load all density reports from a directory
pub fn load_density_reports(reports_dir: &Path) -> Result<HashMap<u8, DensityReport>> {
    info!("Loading density reports from {:?}", reports_dir);

    let mut reports = HashMap::new();

    // Look for global_density_res*.json files
    for entry in std::fs::read_dir(reports_dir)? {
        let entry = entry?;
        let path = entry.path();

        if let Some(filename) = path.file_name().and_then(|n| n.to_str()) {
            if filename.starts_with("global_density_res") && filename.ends_with(".json") {
                // Extract resolution from filename
                let res_str = filename
                    .trim_start_matches("global_density_res")
                    .trim_end_matches(".json");

                if let Ok(resolution) = res_str.parse::<u8>() {
                    info!("  Loading resolution {} from {:?}", resolution, path);

                    let file = File::open(&path)
                        .with_context(|| format!("Failed to open {:?}", path))?;

                    let report: DensityReport = serde_json::from_reader(file)
                        .with_context(|| format!("Failed to parse {:?}", path))?;

                    info!(
                        "    Loaded {} cells for resolution {}",
                        report.cells.len(),
                        resolution
                    );

                    reports.insert(resolution, report);
                }
            }
        }
    }

    if reports.is_empty() {
        anyhow::bail!(
            "No density reports found in {:?}. Expected files like global_density_res4.json",
            reports_dir
        );
    }

    info!("Loaded {} density reports", reports.len());
    Ok(reports)
}

/// Extract sampling data for a specific region's cells
pub fn extract_sampling_for_region(
    density_reports: &HashMap<u8, DensityReport>,
    boundary_cells: &[CellIndex],
    data_resolution: u8,
) -> Result<HashMap<CellIndex, usize>> {
    let mut sampling_data = HashMap::new();

    // Get the boundary resolution from the first cell
    let boundary_resolution = boundary_cells
        .first()
        .map(|c| u8::from(c.resolution()))
        .ok_or_else(|| anyhow::anyhow!("No boundary cells provided"))?;

    // Get the appropriate density report
    let report = density_reports.get(&boundary_resolution).ok_or_else(|| {
        anyhow::anyhow!(
            "No density report for boundary resolution {}",
            boundary_resolution
        )
    })?;

    info!(
        "Extracting sampling data: {} boundary cells at res {}, data res {}",
        boundary_cells.len(),
        boundary_resolution,
        data_resolution
    );

    // Convert boundary cells to a HashSet for fast lookup
    let boundary_set: std::collections::HashSet<_> = boundary_cells.iter().copied().collect();

    // Extract sampling counts for cells within boundaries
    for cell_data in &report.cells {
        // Parse the H3 cell
        let cell =
            CellIndex::from_str(&cell_data.h3_cell).context("Failed to parse H3 cell")?;

        // Check if this cell is in our boundary set
        if boundary_set.contains(&cell) {
            // If we have sampling data, add it
            if let Some(sampled_count) = cell_data.total_complete_checklists_sampled {
                // If boundary and data resolution differ, we need to get child cells
                if boundary_resolution != data_resolution {
                    // Get all child cells at data resolution
                    let children: Vec<CellIndex> = cell.children(h3o::Resolution::try_from(data_resolution)?).collect();

                    // Distribute sampling count evenly among children
                    // (This is a simplification - in reality, sampling might not be uniform)
                    let count_per_child =
                        sampled_count / children.len().max(1);

                    for child in children {
                        *sampling_data.entry(child).or_insert(0) += count_per_child;
                    }
                } else {
                    // Same resolution - use directly
                    sampling_data.insert(cell, sampled_count);
                }
            }
        }
    }

    info!("  Extracted sampling data for {} cells", sampling_data.len());
    Ok(sampling_data)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    fn create_test_density_report(dir: &Path, resolution: u8, with_sampling: bool) -> Result<()> {
        let report = DensityReport {
            resolution,
            cells: vec![crate::config::CellDensityData {
                h3_cell: "84a8803ffffffff".to_string(),  // San Francisco area, res 4
                center_lat: 37.7749,
                center_lon: -122.4194,
                unique_checklists: 1000,
                complete_checklists: 800,
                total_observations: 5000,
                date_range_start: "2020-01-01".to_string(),
                date_range_end: "2025-12-31".to_string(),
                estimated_pack_size_mb: 10.0,
                recommended_data_resolution: 7,
                total_complete_checklists_sampled: if with_sampling { Some(1200) } else { None },
            }],
        };

        let filename = format!("global_density_res{}.json", resolution);
        let filepath = dir.join(filename);
        let mut file = File::create(filepath)?;
        serde_json::to_writer(&mut file, &report)?;
        file.flush()?;

        Ok(())
    }

    #[test]
    fn test_load_density_reports() -> Result<()> {
        let temp_dir = TempDir::new()?;

        // Create test reports
        create_test_density_report(temp_dir.path(), 4, true)?;
        create_test_density_report(temp_dir.path(), 5, false)?;

        // Load reports
        let reports = load_density_reports(temp_dir.path())?;

        assert_eq!(reports.len(), 2);
        assert!(reports.contains_key(&4));
        assert!(reports.contains_key(&5));

        // Check res 4 has sampling data
        let res4 = &reports[&4];
        assert_eq!(res4.resolution, 4);
        assert_eq!(res4.cells.len(), 1);
        assert_eq!(
            res4.cells[0].total_complete_checklists_sampled,
            Some(1200)
        );

        // Check res 5 has no sampling data
        let res5 = &reports[&5];
        assert_eq!(res5.resolution, 5);
        assert_eq!(res5.cells[0].total_complete_checklists_sampled, None);

        Ok(())
    }

    #[test]
    fn test_extract_sampling_same_resolution() -> Result<()> {
        let temp_dir = TempDir::new()?;
        create_test_density_report(temp_dir.path(), 4, true)?;

        let reports = load_density_reports(temp_dir.path())?;

        // Create boundary cells at res 4
        let boundary_cells = vec![CellIndex::from_str("84a8803ffffffff")?];

        // Extract sampling at same resolution
        let sampling = extract_sampling_for_region(&reports, &boundary_cells, 4)?;

        assert_eq!(sampling.len(), 1);
        let cell = CellIndex::from_str("84a8803ffffffff")?;
        assert_eq!(sampling.get(&cell), Some(&1200));

        Ok(())
    }

    #[test]
    fn test_extract_sampling_different_resolution() -> Result<()> {
        let temp_dir = TempDir::new()?;
        create_test_density_report(temp_dir.path(), 4, true)?;

        let reports = load_density_reports(temp_dir.path())?;

        // Create boundary cells at res 4
        let boundary_cells = vec![CellIndex::from_str("84a8803ffffffff")?];

        // Extract sampling at higher resolution (res 7)
        let sampling = extract_sampling_for_region(&reports, &boundary_cells, 7)?;

        // Should have distributed sampling count among child cells
        assert!(sampling.len() > 0);

        // Total sampling count should be approximately preserved
        let total_sampled: usize = sampling.values().sum();
        assert!(total_sampled > 0);
        assert!(total_sampled <= 1200); // May be less due to integer division

        Ok(())
    }

    #[test]
    fn test_load_empty_directory() {
        let temp_dir = TempDir::new().unwrap();

        let result = load_density_reports(temp_dir.path());
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("No density reports found"));
    }

    #[test]
    fn test_extract_no_boundary_cells() {
        let reports = HashMap::new();
        let boundary_cells: Vec<CellIndex> = vec![];

        let result = extract_sampling_for_region(&reports, &boundary_cells, 7);
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("No boundary cells"));
    }
}
