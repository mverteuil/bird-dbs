mod config;
mod db;
mod ebird;
mod h3;

use anyhow::Result;
use clap::Parser;
use log::{info, warn};
use std::collections::HashSet;
use std::fs::File;
use std::path::PathBuf;

use config::RegionConfig;
use ebird::EBirdRecord;
use h3::H3Aggregator;

#[derive(Parser)]
#[command(name = "birdnetpi-ebird-pack")]
#[command(about = "Generate H3 grid region packs from eBird data for BirdNET-Pi")]
struct Cli {
    /// Input CSV file (eBird data)
    #[arg(short, long)]
    input: PathBuf,

    /// Output SQLite database path (.db)
    #[arg(short, long)]
    output: PathBuf,

    /// Region configuration (YAML)
    #[arg(short, long)]
    config: PathBuf,
}

fn main() -> Result<()> {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let cli = Cli::parse();

    // Load configuration
    info!("Loading configuration from {:?}", cli.config);
    let config_file = File::open(&cli.config)?;
    let config: RegionConfig = serde_yaml::from_reader(config_file)?;

    info!(
        "Processing region: {} (H3 resolution {})",
        config.region_name, config.h3_resolution
    );

    // Create H3 aggregator
    let mut aggregator = H3Aggregator::new(config.h3_resolution)?;
    let mut total_checklists = HashSet::new();
    let mut total_observations = 0;

    // Process CSV file
    info!("Reading eBird data from {:?}", cli.input);
    let file = File::open(&cli.input)?;
    let mut rdr = csv::ReaderBuilder::new().delimiter(b'\t').from_reader(file);

    let mut record_count = 0;
    let mut filtered_count = 0;

    for result in rdr.deserialize() {
        let record: EBirdRecord = result?;
        record_count += 1;

        if record_count % 10000 == 0 {
            info!(
                "Processed {} records ({} filtered)",
                record_count, filtered_count
            );
        }

        // Apply filters
        if config.filters.approved_only && !record.is_approved() {
            filtered_count += 1;
            continue;
        }

        if config.filters.complete_checklists_only && !record.is_complete_checklist() {
            filtered_count += 1;
            continue;
        }

        if config.filters.native_species_only && !record.is_native() {
            filtered_count += 1;
            continue;
        }

        if !record.is_species() {
            filtered_count += 1;
            continue;
        }

        // Geographic filter
        if !config
            .bounding_box
            .contains(record.latitude, record.longitude)
        {
            filtered_count += 1;
            continue;
        }

        // Date filter
        let date = match record.parse_date() {
            Ok(d) => d,
            Err(_) => {
                warn!("Failed to parse date: {}", record.observation_date);
                filtered_count += 1;
                continue;
            }
        };

        if !config.date_range.contains(&date) {
            filtered_count += 1;
            continue;
        }

        // Track totals
        total_checklists.insert(record.get_checklist_id());
        total_observations += 1;

        // Add to aggregator
        aggregator.add_record(&record)?;
    }

    info!(
        "Finished processing {} records ({} filtered)",
        record_count, filtered_count
    );
    info!("Total checklists: {}", total_checklists.len());
    info!("Total observations: {}", total_observations);

    // Finalize aggregation
    info!("Finalizing grid cell data");
    let grid_cells = aggregator.finalize(&config.filters);

    let total_species: usize = grid_cells.iter().map(|c| c.species.len()).sum();
    info!(
        "Generated {} hexagons with {} total species records",
        grid_cells.len(),
        total_species
    );

    // Write to database
    info!("Writing region pack to {:?}", cli.output);
    db::write_region_pack(
        &cli.output,
        &config,
        &grid_cells,
        total_checklists.len(),
        total_observations,
    )?;

    info!("Done!");

    Ok(())
}
