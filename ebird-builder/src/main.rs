// mod avilistr; // No longer needed - using TAXON CONCEPT ID from eBird data directly
mod config;
mod db;
mod density_loader;
mod ebird;
mod h3;
mod taxon_registry;
mod temp_storage;

use anyhow::Result;
use clap::Parser;
use log::info;
use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Arc;

use config::{FilterConfig, PackManifest, PackRegistry};
use ebird::parquet_reader::ParquetBatchIterator;
use ebird::EBirdRecord;
use h3::{GridCellPack, StreamingH3Aggregator};
use h3o::CellIndex;

#[derive(Parser)]
#[command(name = "birdnetpi-ebird-pack")]
#[command(about = "Generate H3 grid region packs from eBird data for BirdNET-Pi")]
struct Cli {
    /// Input: tarball (.tar), gzipped file (.gz), plain text (.txt), or directory with Parquet files
    #[arg(short, long)]
    input: PathBuf,

    /// Output directory for region pack databases
    #[arg(short, long)]
    output_dir: PathBuf,

    /// Pack manifest JSON (from pack-planner)
    #[arg(short, long)]
    manifest: PathBuf,

    /// Pack registry JSON (from pack-planner, will be updated with actual sizes)
    #[arg(short = 'r', long)]
    registry: PathBuf,

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

    /// Path to pre-built taxon registry JSON (from build-taxon-registry tool)
    #[arg(short = 't', long)]
    taxon_registry: PathBuf,
}

/// Metadata for a region's streaming aggregator
struct RegionAggregator {
    region_id: String,
    release_name: String,
    h3_resolution: u8,
    boundary_cells: HashSet<CellIndex>,
    boundary_resolution: h3o::Resolution,
    aggregator: StreamingH3Aggregator,
    completed_cells: Vec<GridCellPack>,  // Collect cells as they complete
    total_checklists: HashSet<String>,
    total_observations: usize,
}

fn main() -> Result<()> {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let cli = Cli::parse();

    // Load taxon registry
    info!("Loading taxon registry from {:?}", cli.taxon_registry);
    let registry = Arc::new(taxon_registry::TaxonRegistry::load_from_file(&cli.taxon_registry)?);
    info!(
        "  ✓ Loaded registry: {} species from release {}",
        registry.species_count, registry.ebird_release
    );

    // Define filter configuration for streaming aggregators
    let filter_config = FilterConfig {
        approved_only: true,
        complete_checklists_only: true,
        native_species_only: true,
        min_observations: 5,
        min_checklists: 3,
        min_yearly_frequency: 0.01,
        deduplication: config::DeduplicationMode::GroupIdentifier,
    };

    // Load pack manifest
    info!("Loading pack manifest from {:?}", cli.manifest);
    let manifest_file = File::open(&cli.manifest)?;
    let manifest: PackManifest = serde_json::from_reader(manifest_file)?;

    // Apply region filter if specified
    let regions_to_process: Vec<_> = manifest
        .regions
        .iter()
        .filter(|r| {
            if let Some(ref filter) = cli.region_filter {
                r.region_id.starts_with(filter)
            } else {
                true
            }
        })
        .collect();

    info!(
        "Processing {} regions (of {} total)",
        regions_to_process.len(),
        manifest.regions.len()
    );

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

    // ========================================================================
    // PHASE 1: Create all aggregators in memory (one per region)
    // ========================================================================
    info!("\n=== Phase 1: Initializing {} aggregators ===", regions_to_process.len());

    let mut region_aggregators: Vec<RegionAggregator> = Vec::new();

    for region in &regions_to_process {
        info!("  Initializing aggregator for region: {}", region.region_id);

        // Parse H3 boundary cells for this region
        let boundary_cells: Result<HashSet<CellIndex>, _> = region
            .h3_cells
            .iter()
            .map(|cell_str| CellIndex::from_str(cell_str))
            .collect();
        let boundary_cells = boundary_cells?;

        // Get the boundary resolution
        let boundary_resolution = boundary_cells
            .iter()
            .next()
            .map(|cell| cell.resolution())
            .unwrap_or(h3o::Resolution::Two);

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
            HashMap::new()
        };

        // Create streaming H3 aggregator with filters, registry, and sampling data
        let aggregator = StreamingH3Aggregator::new(
            h3_resolution,
            filter_config.clone(),
            Arc::clone(&registry),
            sampling_data,
        )?;

        region_aggregators.push(RegionAggregator {
            region_id: region.region_id.clone(),
            release_name: region.release_name.clone(),
            h3_resolution,
            boundary_cells,
            boundary_resolution,
            aggregator,
            completed_cells: Vec::new(),  // Initialize empty cell collection
            total_checklists: HashSet::new(),
            total_observations: 0,
        });

        info!(
            "    ✓ Region {} has {} boundary cells at resolution {}",
            region.region_id,
            region_aggregators.last().unwrap().boundary_cells.len(),
            u8::from(boundary_resolution)
        );
    }

    info!("\n✓ All {} aggregators initialized", region_aggregators.len());
    info!("  Estimated memory usage: ~{} MB", region_aggregators.len() * 150);

    // ========================================================================
    // PHASE 2: Streaming pass through SORTED Parquet dataset
    // ========================================================================
    info!("\n=== Phase 2: Streaming sorted Parquet processing ===");
    info!("Opening sorted Parquet directory: {:?}", cli.input);

    // REQUIRE sorted Parquet input for streaming aggregation
    if !cli.input.is_dir() {
        return Err(anyhow::anyhow!(
            "Streaming aggregation requires a directory of sorted Parquet files. Got: {:?}",
            cli.input
        ));
    }

    // Create Parquet batch iterator from sorted directory
    let batch_iterator = ParquetBatchIterator::from_directory(&cli.input, 10_000)?;

    // Sequential streaming processing
    let mut record_count = 0u64;
    let mut filtered_count = 0u64;
    let mut routed_count = 0u64;
    let mut last_report = std::time::Instant::now();

    info!("Processing records sequentially in sorted order...");
    info!("CRITICAL: Data must be sorted by (LAT, LON, GROUP, SAMPLING, TAXON, DATE)");

    for batch_result in batch_iterator {
        let batch = batch_result?;

        for record in batch {
            record_count += 1;

            // Apply date filter
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

            // Convert observation to H3 coordinates
            let obs_latlng = match h3o::LatLng::new(record.latitude, record.longitude) {
                Ok(ll) => ll,
                Err(_) => {
                    filtered_count += 1;
                    continue;
                }
            };

            // Route to ALL matching region aggregators
            for region_agg in &mut region_aggregators {
                let obs_boundary_cell = obs_latlng.to_cell(region_agg.boundary_resolution);

                if region_agg.boundary_cells.contains(&obs_boundary_cell) {
                    // Track totals
                    region_agg.total_checklists.insert(record.get_checklist_id());
                    region_agg.total_observations += 1;

                    // Process record with streaming aggregator
                    // Returns Some(GridCellPack) if a cell was completed
                    match region_agg.aggregator.process_record(&record) {
                        Ok(Some(completed_cell)) => {
                            // Cell completed - add to collection
                            region_agg.completed_cells.push(completed_cell);
                        }
                        Ok(None) => {
                            // Record added to current cell, no cell completed yet
                        }
                        Err(e) => {
                            log::error!("Error processing record: {}", e);
                        }
                    }

                    routed_count += 1;
                }
            }

            // Progress reporting
            if record_count % 1_000_000 == 0 {
                let elapsed = last_report.elapsed().as_secs_f64();
                let rate = 1_000_000.0 / elapsed;
                info!(
                    "  Processed {} records ({:.0} rec/sec, {} routed)",
                    record_count, rate, routed_count
                );
                last_report = std::time::Instant::now();
            }
        }
    }

    info!("\n✓ Dataset pass complete!");
    info!(
        "  Total records: {} ({} filtered out)",
        record_count, filtered_count
    );
    info!("  Total observations routed: {}", routed_count);

    // Finalize all streaming aggregators to get final cells
    info!("\nFinalizing streaming aggregators...");
    for region_agg in &mut region_aggregators {
        let aggregator = std::mem::replace(
            &mut region_agg.aggregator,
            StreamingH3Aggregator::new(region_agg.h3_resolution, filter_config.clone(), Arc::clone(&registry), HashMap::new())?
        );

        match aggregator.finish() {
            Ok(Some(final_cell)) => {
                region_agg.completed_cells.push(final_cell);
                info!(
                    "  ✓ Region {}: {} cells total",
                    region_agg.region_id,
                    region_agg.completed_cells.len()
                );
            }
            Ok(None) => {
                info!(
                    "  ✓ Region {}: {} cells (no final cell)",
                    region_agg.region_id,
                    region_agg.completed_cells.len()
                );
            }
            Err(e) => {
                log::error!("Error finalizing region {}: {}", region_agg.region_id, e);
            }
        }
    }

    // ========================================================================
    // PHASE 3: Write all region databases
    // ========================================================================
    info!("\n=== Phase 3: Writing region databases ===");

    // Track actual file sizes for manifest update
    let mut region_sizes: HashMap<String, f64> = HashMap::new();

    for region_agg in region_aggregators {
        info!("\nProcessing region: {}", region_agg.region_id);

        if region_agg.total_observations == 0 {
            info!("  ⚠ Skipping (no observations)");
            continue;
        }

        info!(
            "  {} observations from {} checklists",
            region_agg.total_observations,
            region_agg.total_checklists.len()
        );

        // Use the completed cells that were collected during streaming
        let grid_cells = region_agg.completed_cells;

        let total_species: usize = grid_cells.iter().map(|c| c.species.len()).sum();
        info!(
            "  {} hexagons with {} species records (from streaming)",
            grid_cells.len(),
            total_species
        );

        // Create RegionConfig for database writing
        let region_config = config::RegionConfig {
            region_id: region_agg.region_id.clone(),
            region_name: region_agg.release_name.clone(),
            region_type: config::RegionType::Custom,
            h3_resolution: region_agg.h3_resolution,
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
            filters: filter_config.clone(),
        };

        // Write to database (gzipped)
        let output_path = cli
            .output_dir
            .join(format!("{}.db.gz", region_agg.release_name));
        info!("  Writing database to {:?}", output_path);

        db::write_region_pack(
            &output_path,
            &region_config,
            &grid_cells,
            region_agg.total_checklists.len(),
            region_agg.total_observations,
        )?;

        // Track actual compressed file size
        if let Ok(metadata) = std::fs::metadata(&output_path) {
            let size_mb = metadata.len() as f64 / (1024.0 * 1024.0);
            region_sizes.insert(region_agg.region_id.clone(), size_mb);
            info!("  File size: {:.2} MB", size_mb);
        }

        info!("  ✓ Region {} complete", region_agg.region_id);
    }

    // ========================================================================
    // PHASE 4: Update registry with actual file sizes
    // ========================================================================
    info!("\n=== Phase 4: Updating registry with actual file sizes ===");

    // Load the registry
    let registry_file = File::open(&cli.registry)?;
    let mut registry: PackRegistry = serde_json::from_reader(registry_file)?;

    let mut updated_count = 0;

    for region in &mut registry.regions {
        if let Some(&actual_size_mb) = region_sizes.get(&region.region_id) {
            let old_size = region.total_size_mb;
            region.total_size_mb = actual_size_mb;
            updated_count += 1;
            info!(
                "  Updated {}: {:.2} MB (was {:.2} MB)",
                region.region_id,
                actual_size_mb,
                old_size
            );
        }
    }

    info!(
        "\n  Updated {} of {} regions with actual sizes",
        updated_count,
        registry.regions.len()
    );

    // Create timestamped backup
    let timestamp = chrono::Utc::now().format("%Y%m%d_%H%M%S");
    let backup_path = cli.registry.with_file_name(format!(
        "pack_registry.backup_{}.json",
        timestamp
    ));

    info!("  Creating backup at {:?}", backup_path);
    std::fs::copy(&cli.registry, &backup_path)?;

    // Write updated registry to original path
    info!("  Writing updated registry to {:?}", cli.registry);
    let registry_file = File::create(&cli.registry)?;
    serde_json::to_writer_pretty(registry_file, &registry)?;

    info!("  ✓ Registry updated successfully");

    info!("\n✓ Done! All regions processed and registry updated.");

    Ok(())
}
