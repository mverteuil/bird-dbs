mod density;
mod ebird;
mod kway_merge;
mod output;
mod tui;
mod two_pass;

use anyhow::Result;
use clap::Parser;
use log::info;
use std::path::PathBuf;
use std::sync::Arc;
use std::thread;

use density::DensityAnalyzer;
use kway_merge::KWayMergeAggregator;
use tui::{App, Phase};
use two_pass::TwoPassAnalyzer;

#[derive(Parser)]
#[command(name = "ebird-density-analyzer")]
#[command(about = "Analyze eBird dataset density for H3-based region pack generation")]
#[command(version)]
struct Cli {
    /// Input eBird data file (.tar, .tar.gz, or .tsv) - not required for k-way merge
    #[arg(short, long)]
    input: Option<PathBuf>,

    /// Sampling event data file (.tar, .tar.gz, or .tsv) - optional, for survey effort tracking
    #[arg(long)]
    sampling_input: Option<PathBuf>,

    /// H3 resolutions to analyze (comma-separated, e.g., "2,3,4,5")
    #[arg(short, long, value_delimiter = ',', default_value = "2,3,4,5")]
    resolutions: Vec<u8>,

    /// Output directory for density reports
    #[arg(short, long)]
    output: PathBuf,

    /// Sample rate (0.0-1.0) for faster analysis
    #[arg(short, long, default_value = "1.0")]
    sample_rate: f64,

    /// Use two-pass mode for memory-efficient processing of large datasets
    #[arg(long)]
    two_pass: bool,

    /// Temporary directory for intermediate files (two-pass mode only)
    #[arg(long, default_value = "/tmp/ebird-density")]
    temp_dir: PathBuf,

    /// Use k-way merge on snapshot directory (skips waiting for full sort)
    #[arg(long)]
    kway_merge: bool,

    /// Snapshot directory containing sorted chunks (for k-way merge)
    #[arg(long)]
    snapshot_dir: Option<PathBuf>,

    /// Enable TUI (Terminal UI) for enhanced progress visualization
    #[arg(long)]
    tui: bool,
}

fn main() -> Result<()> {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let cli = Cli::parse();

    // Validate inputs (skip if using k-way merge)
    if !cli.kway_merge {
        let input = cli.input.as_ref()
            .ok_or_else(|| anyhow::anyhow!("--input required (unless using --kway-merge)"))?;
        if !input.exists() {
            anyhow::bail!("Input file does not exist: {:?}", input);
        }
    }

    if cli.sample_rate <= 0.0 || cli.sample_rate > 1.0 {
        anyhow::bail!("Sample rate must be between 0.0 and 1.0");
    }

    // Validate resolutions
    for res in &cli.resolutions {
        if *res > 15 {
            anyhow::bail!("H3 resolution {} is too high (max 15)", res);
        }
    }

    // Create output directory if needed
    std::fs::create_dir_all(&cli.output)?;

    if !cli.kway_merge {
        info!(
            "Analyzing eBird data from {:?} at resolutions {:?}",
            cli.input, cli.resolutions
        );
        info!("Sample rate: {:.1}%", cli.sample_rate * 100.0);
        if cli.two_pass {
            info!("Mode: Two-pass (memory-efficient)");
            info!("Temp directory: {:?}", cli.temp_dir);
        } else {
            info!("Mode: Single-pass (in-memory)");
        }
    }

    if cli.kway_merge {
        // K-way merge mode: aggregate from snapshot directory
        let snapshot_dir = cli.snapshot_dir.as_ref()
            .ok_or_else(|| anyhow::anyhow!("--snapshot-dir required with --kway-merge"))?;

        if !snapshot_dir.exists() {
            anyhow::bail!("Snapshot directory does not exist: {:?}", snapshot_dir);
        }

        info!("Mode: K-way merge aggregation");
        info!("Snapshot directory: {:?}", snapshot_dir);

        // Create TUI if requested
        let app = if cli.tui {
            Some(Arc::new(App::new()))
        } else {
            None
        };

        // Spawn TUI thread if enabled
        let tui_handle = if let Some(app) = &app {
            let app_clone = app.clone();
            Some(thread::spawn(move || {
                if let Err(e) = tui::run_tui(app_clone) {
                    eprintln!("TUI terminated: {}", e);
                    eprintln!("Processing continues in background. Check logs for completion.");
                }
            }))
        } else {
            None
        };

        // Create aggregator
        let mut aggregator = KWayMergeAggregator::new(
            cli.resolutions.clone(),
            snapshot_dir.clone(),
        )?;

        if let Some(app) = &app {
            aggregator = aggregator.with_tui(app.clone());
        }

        // Run aggregation
        let reports = aggregator.aggregate()?;

        // Signal completion to TUI
        if let Some(app) = &app {
            app.update_state(|s| s.phase = Phase::Complete);
            app.add_log("[INFO] K-way merge complete!".to_string());
        }

        // Wait for TUI to finish if it was running
        if let Some(handle) = tui_handle {
            let _ = handle.join();
        }

        // Write reports
        for (res, report) in reports {
            let output_file = cli.output.join(format!("global_density_res{}.json", res));

            info!(
                "Writing report for resolution {} ({} cells with data)",
                res,
                report.cells.len()
            );

            output::write_json_report(&report, &output_file)?;

            // Print summary stats
            if !report.cells.is_empty() {
                let total_checklists: usize =
                    report.cells.iter().map(|c| c.unique_checklists).sum();
                let avg_checklists = total_checklists / report.cells.len();

                info!(
                    "  Resolution {}: {} cells, {} total checklists, {} avg/cell",
                    res,
                    report.cells.len(),
                    total_checklists,
                    avg_checklists
                );
            }
        }
    } else if cli.two_pass {
        // Two-pass mode for large datasets

        // Create TUI if requested
        let app = if cli.tui {
            Some(Arc::new(App::new()))
        } else {
            None
        };

        // Spawn TUI thread if enabled
        let tui_handle = if let Some(app) = &app {
            let app_clone = app.clone();
            Some(thread::spawn(move || {
                if let Err(e) = tui::run_tui(app_clone) {
                    // TUI errors are non-fatal - processing continues
                    eprintln!("TUI terminated: {}", e);
                    eprintln!("Processing continues in background. Check logs for completion.");
                }
            }))
        } else {
            None
        };

        // Clone temp_dir for resume checks before moving into analyzer
        let temp_dir = cli.temp_dir.clone();

        // Create analyzer and attach TUI if present
        let mut analyzer = TwoPassAnalyzer::new(
            cli.resolutions.clone(),
            cli.sample_rate,
            cli.temp_dir,
        )?;

        if let Some(app) = &app {
            analyzer = analyzer.with_tui(app.clone());
        }

        // Check if pairs file already exists (resume capability)
        let pairs_file = temp_dir.join("pairs.csv");
        let pairs_file = if pairs_file.exists() && pairs_file.metadata()?.len() > 0 {
            info!("Found existing pairs file ({} bytes), skipping Pass 1", pairs_file.metadata()?.len());
            if let Some(app) = &app {
                app.add_log(format!("[INFO] Resuming: Found existing pairs file ({:.1} GB)",
                    pairs_file.metadata()?.len() as f64 / 1_000_000_000.0));
            }
            pairs_file
        } else {
            // Pass 1: Extract pairs
            let input = cli.input.as_ref().unwrap(); // Safe: validated above
            analyzer.pass1_extract_pairs(input)?
        };

        // Check if sorted file already exists
        let sorted_file = temp_dir.join("pairs_sorted.csv");
        let sorted_file = if sorted_file.exists() && sorted_file.metadata()?.len() > 0 {
            info!("Found existing sorted file ({} bytes), skipping sort", sorted_file.metadata()?.len());
            if let Some(app) = &app {
                app.add_log(format!("[INFO] Resuming: Found existing sorted file ({:.1} GB)",
                    sorted_file.metadata()?.len() as f64 / 1_000_000_000.0));
            }
            sorted_file
        } else {
            // Sort pairs
            analyzer.sort_pairs(&pairs_file)?
        };

        // Process sampling file if provided
        let sampling_counts = if let Some(sampling_path) = &cli.sampling_input {
            if sampling_path.exists() {
                info!("Processing sampling file: {:?}", sampling_path);
                Some(analyzer.process_sampling_file(sampling_path)?)
            } else {
                anyhow::bail!("Sampling file does not exist: {:?}", sampling_path);
            }
        } else {
            None
        };

        // Pass 2: Aggregate
        let reports = analyzer.pass2_aggregate(&sorted_file, sampling_counts)?;

        // Signal completion to TUI
        if let Some(app) = &app {
            app.update_state(|s| s.phase = Phase::Complete);
            app.add_log("[INFO] Analysis complete!".to_string());
        }

        // Wait for TUI to finish if it was running
        if let Some(handle) = tui_handle {
            let _ = handle.join();
        }

        // Write reports
        for (res, report) in reports {
            let output_file = cli.output.join(format!("global_density_res{}.json", res));

            info!(
                "Writing report for resolution {} ({} cells with data)",
                res,
                report.cells.len()
            );

            output::write_json_report(&report, &output_file)?;

            // Print summary stats
            if !report.cells.is_empty() {
                let total_checklists: usize =
                    report.cells.iter().map(|c| c.unique_checklists).sum();
                let avg_checklists = total_checklists / report.cells.len();

                info!(
                    "  Resolution {}: {} cells, {} total checklists, {} avg/cell",
                    res,
                    report.cells.len(),
                    total_checklists,
                    avg_checklists
                );
            }
        }
    } else {
        // Single-pass mode (original)
        let mut analyzer = DensityAnalyzer::new(cli.resolutions.clone(), cli.sample_rate);

        // Process input file
        let input = cli.input.as_ref().unwrap(); // Safe: validated above
        let total_records = if input.extension().and_then(|s| s.to_str()) == Some("tsv") {
            info!("Reading TSV file");
            analyzer.process_tsv_file(input)?
        } else {
            info!("Reading tar/tar.gz archive");
            analyzer.process_tar_file(input)?
        };

        info!(
            "Processed {} total records ({} after filtering)",
            total_records,
            analyzer.get_observation_count()
        );

        // Generate reports for each resolution
        for res in &cli.resolutions {
            let report = analyzer.generate_report(*res)?;

            let output_file = cli.output.join(format!("global_density_res{}.json", res));

            info!(
                "Writing report for resolution {} ({} cells with data)",
                res,
                report.cells.len()
            );

            output::write_json_report(&report, &output_file)?;

            // Print summary stats
            if !report.cells.is_empty() {
                let total_checklists: usize =
                    report.cells.iter().map(|c| c.unique_checklists).sum();
                let avg_checklists = total_checklists / report.cells.len();

                info!(
                    "  Resolution {}: {} cells, {} total checklists, {} avg/cell",
                    res,
                    report.cells.len(),
                    total_checklists,
                    avg_checklists
                );
            }
        }
    }

    info!("Done! Reports written to {:?}", cli.output);

    Ok(())
}
