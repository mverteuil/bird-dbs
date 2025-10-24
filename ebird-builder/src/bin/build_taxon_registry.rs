/// Standalone tool to build a global taxon concept ID registry from eBird data
///
/// This tool scans the entire eBird dataset once to build a persistent registry
/// mapping normalized species names to their preferred (species-level) taxon_concept_ids.
/// The registry is saved as JSON and can be reused across all future pack builds.

use anyhow::Result;
use birdnetpi_ebird_pack::ebird::EBirdRecord;
use birdnetpi_ebird_pack::taxon_registry::{normalize_species_name, TaxonRegistry};
use clap::Parser;
use log::info;
use std::fs::File;
use std::path::PathBuf;

#[derive(Parser)]
#[command(name = "build-taxon-registry")]
#[command(about = "Build global taxon concept ID registry from eBird data")]
struct Cli {
    /// Input tarball (eBird data)
    #[arg(short, long)]
    input: PathBuf,

    /// Output JSON file for registry
    #[arg(short, long)]
    output: PathBuf,

    /// eBird release version (e.g., "2025-08")
    #[arg(short, long)]
    release: String,

    /// Date range start (YYYY-MM-DD) for filtering records
    #[arg(long, default_value = "2020-01-01")]
    date_start: String,

    /// Date range end (YYYY-MM-DD) for filtering records
    #[arg(long, default_value = "2025-12-31")]
    date_end: String,
}

fn main() -> Result<()> {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let cli = Cli::parse();

    info!("Building taxon registry from eBird release: {}", cli.release);
    info!("Input: {:?}", cli.input);
    info!("Output: {:?}", cli.output);

    // Parse date range
    let date_start = chrono::NaiveDate::parse_from_str(&cli.date_start, "%Y-%m-%d")?;
    let date_end = chrono::NaiveDate::parse_from_str(&cli.date_end, "%Y-%m-%d")?;
    info!("Date range: {} to {}", date_start, date_end);

    // Initialize registry
    let mut registry = TaxonRegistry::new(cli.release);

    // Open tarball
    info!("\nOpening tarball...");
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

    info!("\nScanning dataset to build registry...");
    let gz_decoder = flate2::read::GzDecoder::new(entry);
    let mut rdr = csv::ReaderBuilder::new()
        .delimiter(b'\t')
        .from_reader(gz_decoder);

    let mut record_count = 0u64;
    let mut filtered_count = 0u64;
    let mut last_report = std::time::Instant::now();

    for result in rdr.deserialize() {
        let record: EBirdRecord = result?;
        record_count += 1;

        // Apply date filter (same as pack builder)
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

        // Update registry with this record
        let normalized_name = normalize_species_name(&record.scientific_name);
        let is_exact_species = record.is_species() && record.scientific_name == normalized_name;

        registry.update_from_record(&normalized_name, &record.taxon_concept_id, is_exact_species);

        // Progress reporting
        if record_count % 1_000_000 == 0 {
            let elapsed = last_report.elapsed().as_secs_f64();
            let rate = 1_000_000.0 / elapsed;
            info!(
                "  Processed {} records ({:.0} rec/sec, {} species in registry)",
                record_count,
                rate,
                registry.registry.len()
            );
            last_report = std::time::Instant::now();
        }
    }

    info!("\n✓ Dataset scan complete!");
    info!(
        "  Total records: {} ({} filtered out)",
        record_count, filtered_count
    );
    info!("  Unique species: {}", registry.registry.len());

    // Finalize and save
    registry.finalize();
    registry.save_to_file(&cli.output)?;

    info!("\n✓ Registry saved successfully!");
    info!("  Use with: --taxon-registry {:?}", cli.output);

    Ok(())
}
