/// Simple benchmark to measure dataset read speed
///
/// Measures:
/// - Tar extraction + gzip decompression speed
/// - CSV parsing speed
/// - Overall throughput
///
/// Usage:
///   cargo run --release --bin read_benchmark -- \
///     --input /path/to/ebd.tar \
///     --sample-records 10000000

use anyhow::{Context, Result};
use clap::Parser;
use std::fs::File;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Parser)]
#[command(name = "read_benchmark")]
#[command(about = "Benchmark dataset read speed")]
struct Cli {
    /// Input tarball (eBird data)
    #[arg(short, long)]
    input: PathBuf,

    /// Number of records to read (0 = all)
    #[arg(short, long, default_value = "10000000")]
    sample_records: usize,
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    println!("=== eBird Dataset Read Benchmark ===\n");
    println!("Input: {:?}", cli.input);
    println!("Sample size: {} records\n", if cli.sample_records == 0 { "ALL".to_string() } else { cli.sample_records.to_string() });

    let start = Instant::now();

    // Open tar file
    let file = File::open(&cli.input)?;
    let file_size = file.metadata()?.len();
    println!("File size: {:.2} GB\n", file_size as f64 / 1_000_000_000.0);

    let mut tar = tar::Archive::new(file);

    // Find .gz entry
    println!("Extracting from tarball...");
    let mut found_entry = None;
    for entry in tar.entries()? {
        let entry = entry?;
        let path = entry.path()?;
        if path.extension().and_then(|s| s.to_str()) == Some("gz") {
            println!("Found: {}", path.display());
            found_entry = Some(entry);
            break;
        }
    }

    let entry = found_entry.context("No .gz file found in tarball")?;

    println!("Decompressing gzip...");
    let gz_decoder = flate2::read::GzDecoder::new(entry);

    println!("Parsing CSV...\n");
    let mut rdr = csv::ReaderBuilder::new()
        .delimiter(b'\t')
        .from_reader(gz_decoder);

    let mut count = 0;
    let mut last_report = Instant::now();

    for result in rdr.records() {
        let _record = result?;
        count += 1;

        if last_report.elapsed().as_secs() >= 5 {
            let elapsed = start.elapsed().as_secs_f64();
            let rate = count as f64 / elapsed;
            println!("  {} records ({:.0} rec/sec)", count, rate);
            last_report = Instant::now();
        }

        if cli.sample_records > 0 && count >= cli.sample_records {
            break;
        }
    }

    let elapsed = start.elapsed();
    let rate_per_sec = count as f64 / elapsed.as_secs_f64();
    let mb_per_sec = (file_size as f64 / elapsed.as_secs_f64()) / 1_000_000.0;

    println!("\n=== Results ===");
    println!("Records processed: {}", count);
    println!("Time: {:.2}s ({:.2} min)", elapsed.as_secs_f64(), elapsed.as_secs_f64() / 60.0);
    println!("Throughput: {:.0} records/sec", rate_per_sec);
    println!("Read speed: {:.2} MB/s", mb_per_sec);

    if cli.sample_records > 0 && count < cli.sample_records {
        println!("\n=== Extrapolation to Full Dataset ===");
        let full_dataset_gb = 201.0;
        let sample_gb = file_size as f64 / 1_000_000_000.0;
        let full_time = elapsed.as_secs_f64() * (full_dataset_gb / sample_gb);
        println!("Estimated time for 201GB: {:.2} hours ({:.0} min)",
            full_time / 3600.0, full_time / 60.0);
    }

    Ok(())
}
