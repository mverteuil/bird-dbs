/// Benchmark tool to validate Option 1 (two-pass) performance estimates
///
/// This tool will:
/// 1. Read first N records from the dataset
/// 2. Measure tar/gzip decompression speed
/// 3. Measure SQLite write performance (batched)
/// 4. Measure SQLite read performance
/// 5. Estimate total time for full dataset
///
/// Usage:
///   cargo run --release --bin benchmark -- \
///     --input /path/to/ebd.tar \
///     --sample-size 10000000 \
///     --temp-db /path/to/benchmark.db

use anyhow::{Context, Result};
use birdnetpi_ebird_pack::{ebird::EBirdRecord, temp_storage::TempObservationStorage};
use clap::Parser;
use std::fs::File;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Parser)]
#[command(name = "benchmark")]
#[command(about = "Benchmark Option 1 performance")]
struct Cli {
    /// Input tarball (eBird data)
    #[arg(short, long)]
    input: PathBuf,

    /// Number of records to process for benchmark
    #[arg(short, long, default_value = "10000000")]
    sample_size: usize,

    /// Temporary database path
    #[arg(short, long)]
    temp_db: PathBuf,
}

fn main() -> Result<()> {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let cli = Cli::parse();

    println!("=== eBird Pack Builder Benchmark ===\n");
    println!("Sample size: {} records", cli.sample_size);
    println!("Temp DB: {:?}\n", cli.temp_db);

    // Clean up any existing benchmark DB
    let _ = std::fs::remove_file(&cli.temp_db);

    // Phase 1: Measure tar/gzip decompression + CSV parsing speed
    println!("Phase 1: Measuring dataset read speed...");
    let (read_time, records_read, bytes_read) = benchmark_read(&cli.input, cli.sample_size)?;

    let read_rate_mbs = (bytes_read as f64 / read_time.as_secs_f64()) / 1_000_000.0;
    let records_per_sec = records_read as f64 / read_time.as_secs_f64();

    println!("  ✓ Read {} records in {:.2}s", records_read, read_time.as_secs_f64());
    println!("  ✓ Read {} MB at {:.2} MB/s", bytes_read / 1_000_000, read_rate_mbs);
    println!("  ✓ Processed {:.0} records/sec\n", records_per_sec);

    // Phase 2: Measure SQLite write performance
    println!("Phase 2: Measuring SQLite write speed...");
    let write_time = benchmark_write(&cli.input, &cli.temp_db, cli.sample_size)?;

    let write_records_per_sec = records_read as f64 / write_time.as_secs_f64();

    println!("  ✓ Wrote {} records in {:.2}s", records_read, write_time.as_secs_f64());
    println!("  ✓ Write speed: {:.0} records/sec\n", write_records_per_sec);

    // Phase 3: Measure SQLite read performance
    println!("Phase 3: Measuring SQLite read speed...");
    let read_back_time = benchmark_read_back(&cli.temp_db)?;

    let read_back_rate = records_read as f64 / read_back_time.as_secs_f64();

    println!("  ✓ Read back {} records in {:.2}s", records_read, read_back_time.as_secs_f64());
    println!("  ✓ Read speed: {:.0} records/sec\n", read_back_rate);

    // Phase 4: Calculate estimates for full dataset
    println!("=== Estimates for Full Dataset ===\n");

    let full_dataset_size_gb = 201.0;
    let sample_size_gb = (bytes_read as f64) / 1_000_000_000.0;
    let scaling_factor = full_dataset_size_gb / sample_size_gb;

    println!("Sample represents {:.2}% of full dataset", (1.0 / scaling_factor) * 100.0);

    // Estimate Pass 1: Read + Write
    let estimated_read_time = read_time.as_secs_f64() * scaling_factor;
    let estimated_write_time = write_time.as_secs_f64() * scaling_factor;
    let estimated_pass1 = estimated_read_time.max(estimated_write_time); // Overlapped

    println!("\nPass 1 (Read dataset + Write temp DB):");
    println!("  Estimated time: {:.2} hours ({:.0} min)",
        estimated_pass1 / 3600.0, estimated_pass1 / 60.0);

    // Estimate Pass 2: Read from temp DB + Aggregate + Write final DBs
    // Assume we process 165 regions sequentially from temp DB
    let estimated_pass2 = (read_back_time.as_secs_f64() * scaling_factor) * 165.0 / 165.0; // All records, once
    let estimated_aggregate = estimated_pass2 * 0.3; // Aggregation overhead
    let estimated_final_write = 20.0 * 60.0; // ~20 min to write 165 final DBs

    println!("\nPass 2 (Query temp DB + Aggregate + Write final DBs):");
    println!("  Query per region: {:.2} min", (read_back_time.as_secs_f64() * scaling_factor) / 60.0);
    println!("  All 165 regions: {:.2} hours ({:.0} min)",
        estimated_pass2 / 3600.0, estimated_pass2 / 60.0);
    println!("  Aggregation: {:.2} hours ({:.0} min)",
        estimated_aggregate / 3600.0, estimated_aggregate / 60.0);
    println!("  Final writes: {:.2} min", estimated_final_write / 60.0);

    let total_pass2 = estimated_pass2 + estimated_aggregate + estimated_final_write;
    println!("  Pass 2 total: {:.2} hours ({:.0} min)",
        total_pass2 / 3600.0, total_pass2 / 60.0);

    // Total estimate
    let total_time = estimated_pass1 + total_pass2;
    println!("\n=== TOTAL ESTIMATED TIME ===");
    println!("{:.2} hours ({:.0} min)", total_time / 3600.0, total_time / 60.0);

    // Cleanup
    let _ = std::fs::remove_file(&cli.temp_db);

    println!("\n✓ Benchmark complete!");

    Ok(())
}

fn benchmark_read(input: &PathBuf, sample_size: usize) -> Result<(std::time::Duration, usize, usize)> {
    let start = Instant::now();

    let file = File::open(input)?;
    let mut tar = tar::Archive::new(file);

    // Find .gz entry
    let mut found_entry = None;
    for entry in tar.entries()? {
        let entry = entry?;
        let path = entry.path()?;
        if path.extension().and_then(|s| s.to_str()) == Some("gz") {
            found_entry = Some(entry);
            break;
        }
    }

    let entry = found_entry.context("No .gz file found in tarball")?;
    let gz_decoder = flate2::read::GzDecoder::new(entry);
    let mut rdr = csv::ReaderBuilder::new()
        .delimiter(b'\t')
        .from_reader(gz_decoder);

    let mut count = 0;
    let mut bytes_processed = 0;

    for result in rdr.deserialize::<EBirdRecord>() {
        let _record = result?;
        bytes_processed += std::mem::size_of::<EBirdRecord>(); // Approximate
        count += 1;

        if count >= sample_size {
            break;
        }

        if count % 1_000_000 == 0 {
            println!("  Processed {} records...", count);
        }
    }

    let elapsed = start.elapsed();
    Ok((elapsed, count, bytes_processed))
}

fn benchmark_write(input: &PathBuf, temp_db: &PathBuf, sample_size: usize) -> Result<std::time::Duration> {
    let start = Instant::now();

    let mut storage = TempObservationStorage::new(temp_db)?;

    let file = File::open(input)?;
    let mut tar = tar::Archive::new(file);

    let mut found_entry = None;
    for entry in tar.entries()? {
        let entry = entry?;
        let path = entry.path()?;
        if path.extension().and_then(|s| s.to_str()) == Some("gz") {
            found_entry = Some(entry);
            break;
        }
    }

    let entry = found_entry.context("No .gz file found")?;
    let gz_decoder = flate2::read::GzDecoder::new(entry);
    let mut rdr = csv::ReaderBuilder::new()
        .delimiter(b'\t')
        .from_reader(gz_decoder);

    let mut count = 0;

    for result in rdr.deserialize::<EBirdRecord>() {
        let record = result?;

        // Simulate routing to a region (just use "benchmark" as region_id)
        storage.add_observation("benchmark", &record)?;

        count += 1;

        if count >= sample_size {
            break;
        }

        if count % 1_000_000 == 0 {
            println!("  Wrote {} records...", count);
        }
    }

    storage.finalize()?;

    Ok(start.elapsed())
}

fn benchmark_read_back(temp_db: &PathBuf) -> Result<std::time::Duration> {
    use rusqlite::Connection;

    let start = Instant::now();

    let conn = Connection::open(temp_db)?;

    let records = TempObservationStorage::get_region_observations(&conn, "benchmark")?;

    println!("  Read back {} records", records.len());

    Ok(start.elapsed())
}
