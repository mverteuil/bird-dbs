mod config;
mod db;
mod density_loader;
mod ebird;
mod h3;

use anyhow::Result;
use clap::Parser;
use log::info;
use std::collections::HashSet;
use std::fs::File;
use std::path::PathBuf;
use std::str::FromStr;

use config::PackManifest;
use ebird::EBirdRecord;
use h3::H3Aggregator;
use h3o::CellIndex;

#[derive(Parser)]
#[command(name = "birdnetpi-ebird-pack")]
#[command(about = "Generate H3 grid region packs from eBird data for BirdNET-Pi")]
struct Cli {
    /// Input CSV file (eBird data)
    #[arg(short, long)]
    input: PathBuf,

    /// Output directory for region pack databases
    #[arg(short, long)]
    output_dir: PathBuf,

    /// Pack manifest JSON (from pack-planner)
    #[arg(short, long)]
    manifest: PathBuf,

    /// Density reports directory (from ebird-density-analyzer, optional)
    #[arg(short = 'd', long)]
    density_reports: Option<PathBuf>,

    /// Date range start (YYYY-MM-DD)
    #[arg(long, default_value = "2020-01-01")]
    date_start: String,

    /// Date range end (YYYY-MM-DD)
    #[arg(long, default_value = "2025-12-31")]
    date_end: String,

    /// Only process regions matching this prefix (optional, for testing)
    #[arg(long)]
    region_filter: Option<String>,
}

fn main() -> Result<()> {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let cli = Cli::parse();

    // Load pack manifest
    info!("Loading pack manifest from {:?}", cli.manifest);
    let manifest_file = File::open(&cli.manifest)?;
    let manifest: PackManifest = serde_json::from_reader(manifest_file)?;

    info!("Found {} regions in manifest", manifest.regions.len());

    // Create output directory
    std::fs::create_dir_all(&cli.output_dir)?;

    // Parse date range
    let date_start = chrono::NaiveDate::parse_from_str(&cli.date_start, "%Y-%m-%d")?;
    let date_end = chrono::NaiveDate::parse_from_str(&cli.date_end, "%Y-%m-%d")?;

    // Load density reports if provided (for sampling data)
    let density_reports = if let Some(ref reports_dir) = cli.density_reports {
        info!("Loading density reports from {:?}", reports_dir);
        Some(density_loader::load_density_reports(reports_dir)?)
    } else {
        info!("No density reports provided - proceeding without sampling data");
        None
    };

    // Process each region
    for region in &manifest.regions {
        // Apply region filter if specified
        if let Some(ref filter) = cli.region_filter {
            if !region.region_id.starts_with(filter) {
                continue;
            }
        }

        info!("Processing region: {}", region.region_id);

        // Parse H3 boundary cells for this region (used for filtering observations)
        let boundary_cells: Result<HashSet<CellIndex>, _> = region
            .h3_cells
            .iter()
            .map(|cell_str| CellIndex::from_str(cell_str))
            .collect();
        let boundary_cells = boundary_cells?;

        // Get the boundary resolution (resolution of the cells we're filtering against)
        let boundary_resolution = boundary_cells
            .iter()
            .next()
            .map(|cell| cell.resolution())
            .unwrap_or(h3o::Resolution::Two);

        info!("  Region has {} boundary cells at resolution {}", boundary_cells.len(), u8::from(boundary_resolution));

        // Determine H3 resolution from first pack (for aggregation)
        let h3_resolution = region.packs.first().map(|p| p.data_resolution).unwrap_or(7);

        // Extract sampling data if density reports are available
        let sampling_data = if let Some(ref reports) = density_reports {
            let boundary_vec: Vec<CellIndex> = boundary_cells.iter().copied().collect();
            density_loader::extract_sampling_for_region(
                reports,
                &boundary_vec,
                h3_resolution,
            )?
        } else {
            std::collections::HashMap::new()
        };

        // Create H3 aggregator with sampling data
        let mut aggregator = if sampling_data.is_empty() {
            H3Aggregator::new(h3_resolution)?
        } else {
            H3Aggregator::new_with_sampling(h3_resolution, sampling_data)?
        };
        let mut total_checklists = HashSet::new();
        let mut total_observations = 0;

        // Process CSV file
        let file = File::open(&cli.input)?;
        let mut rdr = csv::ReaderBuilder::new().delimiter(b'\t').from_reader(file);

        let mut record_count = 0;
        let mut filtered_count = 0;
        let mut h3_check_count = 0;

        for result in rdr.deserialize() {
            let record: EBirdRecord = result?;
            record_count += 1;

            if record_count % 100000 == 0 {
                info!(
                    "  Processed {} records ({} filtered)",
                    record_count, filtered_count
                );
            }

            // Apply basic filters
            if !record.is_approved() {
                filtered_count += 1;
                continue;
            }
            if !record.is_complete_checklist() {
                filtered_count += 1;
                continue;
            }
            if !record.is_native() {
                filtered_count += 1;
                continue;
            }
            if !record.is_species() {
                filtered_count += 1;
                continue;
            }

            // Date filter
            let date = match record.parse_date() {
                Ok(d) => d,
                Err(_) => {
                    filtered_count += 1;
                    continue;
                }
            };

            if date < date_start || date > date_end {
                filtered_count += 1;
                continue;
            }

            // H3 cell filter - check if observation falls within any boundary cell
            h3_check_count += 1;
            let obs_latlng = h3o::LatLng::new(record.latitude, record.longitude)?;
            let obs_boundary_cell = obs_latlng.to_cell(boundary_resolution);

            // Debug first few cells
            if h3_check_count <= 5 {
                info!("  [DEBUG] Observation at ({}, {}): cell={:x}, expected={:x}",
                    record.latitude, record.longitude,
                    u64::from(obs_boundary_cell),
                    u64::from(*boundary_cells.iter().next().unwrap()));
            }

            if !boundary_cells.contains(&obs_boundary_cell) {
                filtered_count += 1;
                continue;
            }

            // Convert to data resolution for aggregation
            let _obs_cell = obs_latlng.to_cell(h3o::Resolution::try_from(h3_resolution)?);

            // Track totals
            total_checklists.insert(record.get_checklist_id());
            total_observations += 1;

            // Add to aggregator
            aggregator.add_record(&record)?;
        }

        info!(
            "  Finished: {} records processed, {} passed filters to H3 check, {} in region",
            record_count, h3_check_count, total_observations
        );

        if total_observations == 0 {
            info!("  Skipping region {} (no observations)", region.region_id);
            continue;
        }

        // Finalize aggregation with default filters
        let default_filters = config::FilterConfig {
            approved_only: true,
            complete_checklists_only: true,
            native_species_only: true,
            min_observations: 5,
            min_checklists: 3,
            min_yearly_frequency: 0.01,
            deduplication: config::DeduplicationMode::GroupIdentifier,
        };

        let grid_cells = aggregator.finalize(&default_filters);

        let total_species: usize = grid_cells.iter().map(|c| c.species.len()).sum();
        info!(
            "  Generated {} hexagons with {} species records",
            grid_cells.len(),
            total_species
        );

        // Create RegionConfig for database writing
        let region_config = config::RegionConfig {
            region_id: region.region_id.clone(),
            region_name: region.release_name.clone(),
            region_type: config::RegionType::Custom,
            h3_resolution,
            bounding_box: config::BoundingBox {
                min_latitude: -90.0,
                max_latitude: 90.0,
                min_longitude: -180.0,
                max_longitude: 180.0,
            },
            date_range: config::DateRange {
                start: date_start,
                end: date_end,
            },
            filters: default_filters,
        };

        // Write to database
        let output_path = cli
            .output_dir
            .join(format!("{}.db", region.release_name));
        info!("  Writing database to {:?}", output_path);
        db::write_region_pack(
            &output_path,
            &region_config,
            &grid_cells,
            total_checklists.len(),
            total_observations,
        )?;

        info!("  ✓ Region {} complete", region.region_id);
    }

    info!("Done! All regions processed.");

    Ok(())
}
