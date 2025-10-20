mod avilistr;
mod config;
mod db;
mod density_loader;
mod ebird;
mod h3;
mod temp_storage;

use anyhow::Result;
use clap::Parser;
use log::info;
use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::{Arc, Mutex};

use config::PackManifest;
use ebird::EBirdRecord;
use h3::H3Aggregator;
use h3o::CellIndex;

#[derive(Parser)]
#[command(name = "birdnetpi-ebird-pack")]
#[command(about = "Generate H3 grid region packs from eBird data for BirdNET-Pi")]
struct Cli {
    /// Input tarball (eBird data)
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

    /// Avilistr mapping CSV (scientific_name -> avibase_id)
    #[arg(short = 'a', long)]
    avilistr: PathBuf,

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

/// Metadata for a region's aggregator
struct RegionAggregator {
    region_id: String,
    release_name: String,
    h3_resolution: u8,
    boundary_cells: HashSet<CellIndex>,
    boundary_resolution: h3o::Resolution,
    aggregator: H3Aggregator,
    total_checklists: HashSet<String>,
    total_observations: usize,
}

fn main() -> Result<()> {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let cli = Cli::parse();

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

    // Load avibase ID mapping
    info!("Loading avibase ID mapping from {:?}", cli.avilistr);
    let avibase_mapping = avilistr::load_avibase_mapping(&cli.avilistr)?;

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

        // Create H3 aggregator with sampling data
        let aggregator = if sampling_data.is_empty() {
            H3Aggregator::new(h3_resolution, avibase_mapping.clone())?
        } else {
            H3Aggregator::new_with_sampling(h3_resolution, sampling_data, avibase_mapping.clone())?
        };

        region_aggregators.push(RegionAggregator {
            region_id: region.region_id.clone(),
            release_name: region.release_name.clone(),
            h3_resolution,
            boundary_cells,
            boundary_resolution,
            aggregator,
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
    // PHASE 2: Single pass through dataset - route to all matching aggregators
    // ========================================================================
    info!("\n=== Phase 2: Single-pass dataset processing ===");
    info!("Opening tarball: {:?}", cli.input);

    let file = File::open(&cli.input)?;
    let mut tar = tar::Archive::new(file);

    // Find .gz entry
    info!("Extracting from tarball...");
    let mut found_entry = None;
    for entry in tar.entries()? {
        let entry = entry?;
        let path = entry.path()?;
        if path.extension().and_then(|s| s.to_str()) == Some("gz") {
            info!("  Found: {}", path.display());
            found_entry = Some(entry);
            break;
        }
    }

    let entry = found_entry.ok_or_else(|| anyhow::anyhow!("No .gz file found in tarball"))?;

    info!("Decompressing gzip and parsing CSV with parallel processing...");

    let gz_decoder = flate2::read::GzDecoder::new(entry);
    let mut rdr = csv::ReaderBuilder::new()
        .delimiter(b'\t')
        .from_reader(gz_decoder);

    // Wrap aggregators in Arc<Mutex<>> for thread safety
    let shared_aggregators: Vec<Arc<Mutex<RegionAggregator>>> = region_aggregators
        .into_iter()
        .map(|agg| Arc::new(Mutex::new(agg)))
        .collect();

    // Shared counters
    let record_count = Arc::new(Mutex::new(0u64));
    let filtered_count = Arc::new(Mutex::new(0u64));
    let routed_count = Arc::new(Mutex::new(0u64));
    let last_report = Arc::new(Mutex::new(std::time::Instant::now()));

    // Create channel for batched records
    let (tx, rx) = crossbeam_channel::bounded::<Vec<EBirdRecord>>(100);

    // Clone references for the processing thread
    let proc_aggregators = shared_aggregators.clone();
    let proc_record_count = record_count.clone();
    let proc_filtered_count = filtered_count.clone();
    let proc_routed_count = routed_count.clone();
    let proc_last_report = last_report.clone();

    // Spawn processing thread pool
    let processor_handle = std::thread::spawn(move || {
        use rayon::prelude::*;

        rx.into_iter().par_bridge().for_each(|batch| {
            let batch_size = batch.len();
            let mut batch_filtered = 0;
            let mut batch_routed = 0;

            for record in batch {
                // Apply ONLY critical filters - quality is tracked per-observation
                // Date filter
                let date = match record.parse_date() {
                    Ok(d) => d,
                    Err(_) => {
                        batch_filtered += 1;
                        continue;
                    }
                };

                if date < date_start || date > date_end {
                    batch_filtered += 1;
                    continue;
                }

                // Convert observation to H3 coordinates once
                let obs_latlng = match h3o::LatLng::new(record.latitude, record.longitude) {
                    Ok(ll) => ll,
                    Err(_) => {
                        batch_filtered += 1;
                        continue;
                    }
                };

                // Route to ALL matching region aggregators
                for shared_agg in &proc_aggregators {
                    let mut agg = shared_agg.lock().unwrap();
                    let obs_boundary_cell = obs_latlng.to_cell(agg.boundary_resolution);

                    if agg.boundary_cells.contains(&obs_boundary_cell) {
                        // Track totals
                        agg.total_checklists.insert(record.get_checklist_id());
                        agg.total_observations += 1;

                        // Add to aggregator
                        if let Err(e) = agg.aggregator.add_record(&record) {
                            log::error!("Error adding record: {}", e);
                        }
                        batch_routed += 1;
                    }
                }
            }

            // Update shared counters
            {
                let mut count = proc_record_count.lock().unwrap();
                *count += batch_size as u64;
                let current_count = *count;

                let mut filtered = proc_filtered_count.lock().unwrap();
                *filtered += batch_filtered;

                let mut routed = proc_routed_count.lock().unwrap();
                *routed += batch_routed;
                let current_routed = *routed;

                // Progress reporting
                if current_count % 1_000_000 < batch_size as u64 {
                    let mut last_rep = proc_last_report.lock().unwrap();
                    let elapsed = last_rep.elapsed().as_secs_f64();
                    let rate = 1_000_000.0 / elapsed;
                    info!(
                        "  Processed {} records ({:.0} rec/sec, {} routed)",
                        current_count, rate, current_routed
                    );
                    *last_rep = std::time::Instant::now();
                }
            }
        });
    });

    // Read and send batches from main thread
    let mut batch = Vec::with_capacity(10_000);

    for result in rdr.deserialize() {
        let record: EBirdRecord = result?;
        batch.push(record);

        if batch.len() >= 10_000 {
            if tx.send(batch.clone()).is_err() {
                break;  // Receiver dropped
            }
            batch.clear();
        }
    }

    // Send final partial batch
    if !batch.is_empty() {
        let _ = tx.send(batch);
    }

    // Drop sender to signal end
    drop(tx);

    // Wait for processing to complete
    processor_handle.join().expect("Processor thread panicked");

    // Extract final counts
    let final_record_count = *record_count.lock().unwrap();
    let final_filtered_count = *filtered_count.lock().unwrap();
    let final_routed_count = *routed_count.lock().unwrap();

    // Unwrap aggregators from Arc<Mutex<>>
    let mut region_aggregators: Vec<RegionAggregator> = shared_aggregators
        .into_iter()
        .map(|arc| {
            Arc::try_unwrap(arc)
                .ok()
                .expect("Failed to unwrap Arc - still has multiple references")
                .into_inner()
                .expect("Failed to unwrap Mutex - poisoned")
        })
        .collect();

    info!("\n✓ Dataset pass complete!");
    info!(
        "  Total records: {} ({} filtered out)",
        final_record_count, final_filtered_count
    );
    info!("  Total observations routed: {}", final_routed_count);

    // ========================================================================
    // PHASE 3: Finalize and write all region databases
    // ========================================================================
    info!("\n=== Phase 3: Finalizing and writing region databases ===");

    let default_filters = config::FilterConfig {
        approved_only: true,
        complete_checklists_only: true,
        native_species_only: true,
        min_observations: 5,
        min_checklists: 3,
        min_yearly_frequency: 0.01,
        deduplication: config::DeduplicationMode::GroupIdentifier,
    };

    // Track actual file sizes for manifest update
    let mut region_sizes: HashMap<String, f64> = HashMap::new();

    for mut region_agg in region_aggregators {
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

        // Finalize aggregation
        let grid_cells = region_agg.aggregator.finalize(&default_filters);

        let total_species: usize = grid_cells.iter().map(|c| c.species.len()).sum();
        info!(
            "  Generated {} hexagons with {} species records",
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
            filters: default_filters.clone(),
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
    // PHASE 4: Update manifest with actual file sizes
    // ========================================================================
    info!("\n=== Phase 4: Updating manifest with actual file sizes ===");

    let mut updated_manifest = manifest.clone();
    let mut updated_count = 0;

    for region in &mut updated_manifest.regions {
        if let Some(&actual_size_mb) = region_sizes.get(&region.region_id) {
            let old_estimate = region.size_mb;
            region.size_mb = actual_size_mb;
            updated_count += 1;
            info!(
                "  Updated {}: {:.2} MB (was {:.2} MB estimated)",
                region.region_id,
                actual_size_mb,
                old_estimate
            );
        }
    }

    info!(
        "\n  Updated {} of {} regions with actual sizes",
        updated_count,
        updated_manifest.regions.len()
    );

    // Write updated manifest
    let updated_manifest_path = cli.manifest.with_file_name("pack_manifest_updated.json");
    info!("  Writing updated manifest to {:?}", updated_manifest_path);

    let manifest_file = File::create(&updated_manifest_path)?;
    serde_json::to_writer_pretty(manifest_file, &updated_manifest)?;

    info!("  ✓ Manifest updated successfully");

    info!("\n✓ Done! All regions processed and manifest updated.");

    Ok(())
}
