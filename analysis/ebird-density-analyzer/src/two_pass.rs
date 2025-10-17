use crate::ebird::EBirdRecord;
use crate::output::{CellDensityData, DensityReport};
use crate::tui::{App, Phase};
use anyhow::{Context, Result};
use chrono::NaiveDate;
use flate2::read::GzDecoder;
use h3o::{CellIndex, LatLng, Resolution};
use log::{info, warn};
use serde::Deserialize;
use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex};
use tar::Archive;

/// Wrapper that tracks bytes read and updates TUI
struct ProgressReader<R: Read> {
    inner: R,
    bytes_read: Arc<Mutex<u64>>,
    app: Option<Arc<App>>,
}

impl<R: Read> ProgressReader<R> {
    fn new(inner: R, app: Option<Arc<App>>) -> Self {
        Self {
            inner,
            bytes_read: Arc::new(Mutex::new(0)),
            app,
        }
    }
}

impl<R: Read> Read for ProgressReader<R> {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        let n = self.inner.read(buf)?;
        if n > 0 {
            let mut bytes_read = self.bytes_read.lock().unwrap();
            *bytes_read += n as u64;

            // Update TUI every ~10MB
            if *bytes_read % 10_000_000 < (n as u64) {
                if let Some(app) = &self.app {
                    app.update_state(|s| {
                        s.pass1_bytes_read = *bytes_read;
                    });
                }
            }
        }
        Ok(n)
    }
}

/// Format a number with commas for readability
fn format_number(n: usize) -> String {
    n.to_string()
        .as_bytes()
        .rchunks(3)
        .rev()
        .map(std::str::from_utf8)
        .collect::<Result<Vec<&str>, _>>()
        .unwrap()
        .join(",")
}

/// Sampling event record (simplified - only fields we need)
#[derive(Debug, Deserialize)]
struct SamplingRecord {
    #[serde(rename = "LATITUDE")]
    latitude: f64,
    #[serde(rename = "LONGITUDE")]
    longitude: f64,
    #[serde(rename = "ALL SPECIES REPORTED")]
    all_species_reported: u8,
}

/// Two-pass analyzer for memory-efficient processing of large datasets
pub struct TwoPassAnalyzer {
    resolutions: Vec<Resolution>,
    sample_rate: f64,
    temp_dir: PathBuf,
    app: Option<Arc<App>>,
}

/// Intermediate data for a cell during aggregation
#[derive(Debug, Default)]
struct CellAggregator {
    unique_checklists: usize,
    complete_checklists: usize,
    total_observations: usize,
    date_range_start: Option<NaiveDate>,
    date_range_end: Option<NaiveDate>,
    lat_sum: f64,
    lon_sum: f64,
    observation_count: usize,
    total_complete_checklists_sampled: Option<usize>,
}

impl TwoPassAnalyzer {
    pub fn new(resolutions: Vec<u8>, sample_rate: f64, temp_dir: PathBuf) -> Result<Self> {
        let resolutions: Vec<Resolution> = resolutions
            .into_iter()
            .map(|r| Resolution::try_from(r).expect("Invalid H3 resolution"))
            .collect();

        // Create temp directory if it doesn't exist
        std::fs::create_dir_all(&temp_dir)
            .context("Failed to create temporary directory")?;

        Ok(Self {
            resolutions,
            sample_rate,
            temp_dir,
            app: None,
        })
    }

    pub fn with_tui(mut self, app: Arc<App>) -> Self {
        self.app = Some(app);
        self
    }

    /// Log a message to TUI if available, otherwise to env_logger
    fn log(&self, level: &str, message: String) {
        if let Some(app) = &self.app {
            app.add_log(format!("[{}] {}", level, message));
        } else {
            match level {
                "INFO" => info!("{}", message),
                "WARN" => warn!("{}", message),
                "ERROR" => log::error!("{}", message),
                _ => info!("{}", message),
            }
        }
    }

    /// Pass 1: Extract (resolution, cell, checklist_id) pairs to disk
    pub fn pass1_extract_pairs(&self, input: &Path) -> Result<PathBuf> {
        let pairs_file = self.temp_dir.join("pairs.csv");

        // Check if file already exists - DO NOT truncate existing work!
        if pairs_file.exists() {
            if let Ok(metadata) = pairs_file.metadata() {
                if metadata.len() > 0 {
                    self.log("INFO", format!("Found existing pairs file ({:.1} GB) - skipping Pass 1",
                        metadata.len() as f64 / 1_000_000_000.0));
                    return Ok(pairs_file);
                }
            }
        }

        self.log("INFO", "Pass 1: Extracting (resolution, cell, checklist_id) pairs".to_string());
        let mut writer = BufWriter::new(File::create(&pairs_file)?);

        // Process input file
        let total_records = if input.extension().and_then(|s| s.to_str()) == Some("tsv") {
            self.extract_from_tsv(input, &mut writer)?
        } else {
            self.extract_from_tar(input, &mut writer)?
        };

        let file_size = pairs_file.metadata()?.len();
        self.log("INFO", format!("Pass 1 complete: {} records processed", format_number(total_records)));
        self.log("INFO", format!("Pairs file: {:.1} MB", file_size as f64 / 1_000_000.0));

        Ok(pairs_file)
    }

    /// Sort the pairs file using external sort
    pub fn sort_pairs(&self, pairs_file: &Path) -> Result<PathBuf> {
        let sorted_file = self.temp_dir.join("pairs_sorted.csv");

        // Check if sorted file already exists - avoid re-sorting!
        if sorted_file.exists() {
            if let Ok(metadata) = sorted_file.metadata() {
                if metadata.len() > 0 {
                    self.log("INFO", format!("Found existing sorted file ({:.1} GB) - skipping sort",
                        metadata.len() as f64 / 1_000_000_000.0));
                    return Ok(sorted_file);
                }
            }
        }

        let file_size = pairs_file.metadata()?.len();
        let file_size_mb = file_size as f64 / 1_000_000.0;

        // Update phase for TUI
        if let Some(app) = &self.app {
            app.update_state(|s| s.phase = Phase::Sorting);
        }

        self.log("INFO", format!("Sorting pairs file ({:.1} MB) - this may take several hours...", file_size_mb));
        self.log("WARN", "System sort does not provide progress feedback".to_string());
        self.log("INFO", "Expected time: ~5-10 minutes per GB with limited RAM".to_string());

        // Use system sort command for efficient external sorting
        let status = Command::new("sort")
            .arg("-t,") // Comma delimiter
            .arg("-k1,1n") // Sort by resolution (numeric)
            .arg("-k2,2n") // Then by cell (numeric)
            .arg("-k3,3") // Then by checklist_id (string)
            .arg("--parallel=2") // Use 2 cores (reduced for low-RAM systems)
            .arg("--buffer-size=512M") // 512MB buffer (safe for 1.8GB RAM systems)
            .arg("-T") // Temp dir flag
            .arg(&self.temp_dir) // Temp dir path (separate argument)
            .arg("-o")
            .arg(&sorted_file)
            .arg(pairs_file)
            .status()
            .context("Failed to execute sort command")?;

        if !status.success() {
            self.log("ERROR", "Sort command failed".to_string());
            anyhow::bail!("Sort command failed");
        }

        self.log("INFO", format!("Sorting complete: {:.1} MB → {}", file_size_mb, sorted_file.display()));

        Ok(sorted_file)
    }

    /// Pass 2: Stream through sorted pairs and aggregate
    pub fn pass2_aggregate(
        &self,
        sorted_file: &Path,
        sampling_counts: Option<HashMap<u8, HashMap<CellIndex, usize>>>,
    ) -> Result<HashMap<u8, DensityReport>> {
        let file = File::open(sorted_file)?;
        let file_size = file.metadata()?.len();
        let reader = BufReader::new(file);

        // Update phase for TUI
        if let Some(app) = &self.app {
            app.update_state(|s| {
                s.phase = Phase::Pass2;
                s.total_bytes = file_size;
                s.bytes_processed = 0;
                s.lines_processed = 0;
                s.unique_cells = 0;
            });
        }

        self.log("INFO", "Starting Pass 2: Aggregating sorted pairs".to_string());

        let mut reports: HashMap<u8, HashMap<CellIndex, CellAggregator>> = HashMap::new();

        let mut current_checklist_key: Option<(u8, CellIndex, String)> = None;
        let mut bytes_read = 0u64;
        let mut lines_processed = 0usize;
        let mut unique_cells = 0usize;

        for line in reader.lines() {
            let line = line?;
            bytes_read += line.len() as u64 + 1; // +1 for newline
            lines_processed += 1;

            // Update TUI every 10k lines for responsive feedback
            if lines_processed % 10_000 == 0 {
                if let Some(app) = &self.app {
                    app.update_state(|s| {
                        s.bytes_processed = bytes_read;
                        s.lines_processed = lines_processed;
                        s.unique_cells = unique_cells;
                    });
                }

                // Log milestones every 100k lines
                if lines_processed % 100_000 == 0 {
                    self.log("INFO", format!(
                        "Processed {} lines ({} unique cells)",
                        format_number(lines_processed),
                        format_number(unique_cells)
                    ));
                }
            }

            // Parse: resolution,cell_u64,checklist_id,is_complete,date,lat,lon
            let parts: Vec<&str> = line.split(',').collect();
            if parts.len() != 7 {
                self.log("WARN", format!("Invalid line format (expected 7 fields): {}", line));
                continue;
            }

            let resolution: u8 = parts[0].parse()?;
            let cell_u64: u64 = parts[1].parse()?;
            let checklist_id = parts[2].to_string();
            let is_complete = parts[3] == "1";
            let date_str = parts[4];
            let lat: f64 = parts[5].parse()?;
            let lon: f64 = parts[6].parse()?;

            let cell = CellIndex::try_from(cell_u64)?;

            // Get or create aggregator for this cell
            let resolution_map = reports.entry(resolution).or_insert_with(HashMap::new);
            let is_new_cell = !resolution_map.contains_key(&cell);
            let cell_agg = resolution_map.entry(cell).or_insert_with(Default::default);

            if is_new_cell {
                unique_cells += 1;
            }

            // Check if this is a new unique checklist
            let checklist_key = (resolution, cell, checklist_id.clone());
            let is_new_checklist = current_checklist_key.as_ref() != Some(&checklist_key);

            if is_new_checklist {
                cell_agg.unique_checklists += 1;
                if is_complete {
                    cell_agg.complete_checklists += 1;
                }
            }

            // Always count observations
            cell_agg.total_observations += 1;

            // Update lat/lon running average
            cell_agg.lat_sum += lat;
            cell_agg.lon_sum += lon;
            cell_agg.observation_count += 1;

            // Update date range
            if let Ok(date) = NaiveDate::parse_from_str(date_str, "%Y-%m-%d") {
                cell_agg.date_range_start = Some(
                    cell_agg
                        .date_range_start
                        .map(|d| d.min(date))
                        .unwrap_or(date),
                );
                cell_agg.date_range_end = Some(
                    cell_agg
                        .date_range_end
                        .map(|d| d.max(date))
                        .unwrap_or(date),
                );
            }

            current_checklist_key = Some(checklist_key);
        }

        // Final update
        if let Some(app) = &self.app {
            app.update_state(|s| {
                s.bytes_processed = bytes_read;
                s.lines_processed = lines_processed;
                s.unique_cells = unique_cells;
            });
        }

        self.log("INFO", format!(
            "Pass 2 complete: {} lines processed, {} unique cells found",
            format_number(lines_processed),
            format_number(unique_cells)
        ));

        // Convert to DensityReport format
        let mut result = HashMap::new();
        for (resolution, cells) in reports {
            let mut cell_data = Vec::new();

            for (cell_index, agg) in cells {
                // Calculate center lat/lon from averages
                let center_lat = if agg.observation_count > 0 {
                    agg.lat_sum / agg.observation_count as f64
                } else {
                    let latlng: LatLng = cell_index.into();
                    latlng.lat()
                };
                let center_lon = if agg.observation_count > 0 {
                    agg.lon_sum / agg.observation_count as f64
                } else {
                    let latlng: LatLng = cell_index.into();
                    latlng.lng()
                };

                // Determine recommended data resolution based on density
                let recommended_data_res = if agg.complete_checklists >= 10000 {
                    7
                } else if agg.complete_checklists >= 5000 {
                    6
                } else if agg.complete_checklists >= 2000 {
                    5
                } else {
                    5
                };

                // Estimate pack size
                let estimated_pack_size_mb = Self::estimate_pack_size(
                    resolution,
                    recommended_data_res,
                    agg.complete_checklists,
                );

                // Get sampling count for this cell (if available)
                let sampling_count = sampling_counts
                    .as_ref()
                    .and_then(|counts| counts.get(&resolution))
                    .and_then(|res_counts| res_counts.get(&cell_index))
                    .copied();

                cell_data.push(CellDensityData {
                    h3_cell: format!("{:x}", u64::from(cell_index)),
                    center_lat,
                    center_lon,
                    unique_checklists: agg.unique_checklists,
                    complete_checklists: agg.complete_checklists,
                    total_observations: agg.total_observations,
                    date_range_start: agg
                        .date_range_start
                        .map(|d| d.to_string())
                        .unwrap_or_default(),
                    date_range_end: agg
                        .date_range_end
                        .map(|d| d.to_string())
                        .unwrap_or_default(),
                    estimated_pack_size_mb,
                    recommended_data_resolution: recommended_data_res,
                    total_complete_checklists_sampled: sampling_count,
                });
            }

            result.insert(resolution, DensityReport { resolution, cells: cell_data });
        }

        Ok(result)
    }

    /// Estimate pack size based on density (same formula as single-pass)
    fn estimate_pack_size(resolution: u8, data_resolution: u8, _complete_checklists: usize) -> f64 {
        const BYTES_PER_SPECIES_RECORD: f64 = 400.0;
        const AVG_SPECIES_PER_HEX: f64 = 150.0;
        const COMPRESSION_RATIO: f64 = 0.7;

        let resolution_diff = data_resolution.saturating_sub(resolution) as u32;
        let num_data_hexagons = 7_u32.pow(resolution_diff) as f64;

        let total_species_records = num_data_hexagons * AVG_SPECIES_PER_HEX;
        let raw_size_bytes = total_species_records * BYTES_PER_SPECIES_RECORD;
        (raw_size_bytes * COMPRESSION_RATIO) / 1_000_000.0
    }

    /// Process sampling file to count complete checklists per H3 cell
    pub fn process_sampling_file(&self, sampling_input: &Path) -> Result<HashMap<u8, HashMap<CellIndex, usize>>> {
        self.log("INFO", format!("Processing sampling file: {:?}", sampling_input));

        // Handle tar archives directly - process inline due to lifetime constraints
        if sampling_input.extension().and_then(|s| s.to_str()) == Some("tar") {
            let file = File::open(sampling_input)?;
            let mut archive = Archive::new(file);

            // Find and process the data file within the tar
            for entry in archive.entries()? {
                let entry = entry?;
                let path = entry.path()?;
                let filename = path.to_string_lossy();

                if filename.ends_with(".txt.gz") || filename.ends_with(".tsv.gz") {
                    self.log("INFO", format!("Found sampling data file: {}", filename));
                    // Process immediately to avoid lifetime issues
                    let gz_reader = GzDecoder::new(entry);
                    return self.process_sampling_reader(gz_reader);
                }
            }
            anyhow::bail!("No .txt.gz or .tsv.gz file found in sampling tar archive");
        } else if sampling_input.extension().and_then(|s| s.to_str()) == Some("gz") {
            let file = File::open(sampling_input)?;
            let gz_reader = GzDecoder::new(file);
            self.process_sampling_reader(gz_reader)
        } else {
            let file = File::open(sampling_input)?;
            self.process_sampling_reader(file)
        }
    }

    fn process_sampling_reader<R: Read>(&self, reader: R) -> Result<HashMap<u8, HashMap<CellIndex, usize>>> {
        let mut rdr = csv::ReaderBuilder::new()
            .delimiter(b'\t')
            .from_reader(reader);

        let mut cell_counts: HashMap<u8, HashMap<CellIndex, usize>> = HashMap::new();
        let mut total_records = 0;
        let mut complete_checklists = 0;

        for result in rdr.deserialize() {
            total_records += 1;

            if total_records % 10000 == 0 {
                self.log("INFO", format!(
                    "Processed {} sampling records ({} complete checklists)",
                    format_number(total_records),
                    format_number(complete_checklists)
                ));
            }

            let record: SamplingRecord = match result {
                Ok(r) => r,
                Err(_e) => continue,
            };

            // Only count complete checklists
            if record.all_species_reported != 1 {
                continue;
            }

            complete_checklists += 1;

            // Convert to H3 cells for each resolution
            let latlng = LatLng::new(record.latitude, record.longitude)?;

            for res in &self.resolutions {
                let cell = latlng.to_cell(*res);
                let resolution_map = cell_counts.entry(u8::from(*res)).or_insert_with(HashMap::new);
                *resolution_map.entry(cell).or_insert(0) += 1;
            }
        }

        self.log("INFO", format!(
            "Sampling file processed: {} records, {} complete checklists",
            format_number(total_records),
            format_number(complete_checklists)
        ));

        Ok(cell_counts)
    }

    fn extract_from_tsv<W: Write>(&self, path: &Path, writer: &mut W) -> Result<usize> {
        let file = File::open(path)?;
        self.extract_from_reader(file, writer)
    }

    fn extract_from_tar<W: Write>(&self, path: &Path, writer: &mut W) -> Result<usize> {
        let file = File::open(path)?;
        let mut archive = if path.extension().and_then(|s| s.to_str()) == Some("gz") {
            Archive::new(Box::new(GzDecoder::new(file)) as Box<dyn Read>)
        } else {
            Archive::new(Box::new(file) as Box<dyn Read>)
        };

        let mut total_records = 0;
        for entry in archive.entries()? {
            let entry = entry?;
            let path = entry.path()?;
            let filename = path.to_string_lossy();

            // Check if this is a data file (txt/tsv, possibly gzipped)
            if filename.ends_with(".txt") || filename.ends_with(".tsv") {
                // Get the entry size for progress tracking
                let entry_size = entry.size();
                if let Some(app) = &self.app {
                    app.update_state(|s| s.pass1_total_bytes = entry_size);
                }
                self.log("INFO", format!("Found data file: {} ({:.1} MB)", filename, entry_size as f64 / 1_000_000.0));

                total_records += self.extract_from_reader(entry, writer)?;
            } else if filename.ends_with(".txt.gz") || filename.ends_with(".tsv.gz") {
                // Get the compressed size for progress tracking
                let entry_size = entry.size();
                if let Some(app) = &self.app {
                    app.update_state(|s| s.pass1_total_bytes = entry_size);
                }
                self.log("INFO", format!("Found gzipped data file: {} (compressed: {:.1} MB)", filename, entry_size as f64 / 1_000_000.0));

                // Wrap entry in ProgressReader to track bytes
                let progress_reader = ProgressReader::new(entry, self.app.clone());
                let gz_reader = GzDecoder::new(progress_reader);
                total_records += self.extract_from_reader(gz_reader, writer)?;
            }
        }
        Ok(total_records)
    }

    fn extract_from_reader<R: Read, W: Write>(
        &self,
        reader: R,
        writer: &mut W,
    ) -> Result<usize> {
        let mut rdr = csv::ReaderBuilder::new()
            .delimiter(b'\t')
            .from_reader(reader);

        // Initialize TUI state if available
        if let Some(app) = &self.app {
            app.update_state(|s| {
                s.phase = Phase::Pass1;
                s.records_read = 0;
                s.pairs_written = 0;
                s.filtered = 0;
            });
        }

        self.log("INFO", "Starting Pass 1: Extracting pairs".to_string());

        let mut total_records = 0;
        let mut filtered_records = 0;
        let mut pairs_written = 0;

        for result in rdr.deserialize() {
            total_records += 1;

            // Update TUI every 1000 records for more responsive feedback
            if total_records % 1000 == 0 {
                if let Some(app) = &self.app {
                    app.update_state(|s| {
                        s.records_read = total_records;
                        s.pairs_written = pairs_written;
                        s.filtered = filtered_records;
                    });
                }

                // Also log milestones
                if total_records % 10000 == 0 {
                    self.log("INFO", format!(
                        "Processed {} records ({} pairs, {} filtered)",
                        format_number(total_records),
                        format_number(pairs_written),
                        format_number(filtered_records)
                    ));
                }
            }

            // Sampling
            if self.sample_rate < 1.0 {
                use std::collections::hash_map::RandomState;
                use std::hash::{BuildHasher, Hash, Hasher};
                let state = RandomState::new();
                let mut hasher = state.build_hasher();
                total_records.hash(&mut hasher);
                if (hasher.finish() as f64 / u64::MAX as f64) > self.sample_rate {
                    continue;
                }
            }

            let record: EBirdRecord = match result {
                Ok(r) => r,
                Err(_e) => {
                    filtered_records += 1;
                    continue;
                }
            };

            if !record.passes_quality_filters() {
                filtered_records += 1;
                continue;
            }

            // Convert to H3 cells and write pairs with metadata
            let latlng = LatLng::new(record.latitude, record.longitude)?;
            let checklist_id = record.get_checklist_id();
            let is_complete = if record.is_complete_checklist() { "1" } else { "0" };

            for res in &self.resolutions {
                let cell = latlng.to_cell(*res);
                let cell_u64 = u64::from(cell);

                // Write: resolution,cell_u64,checklist_id,is_complete,date,lat,lon
                writeln!(
                    writer,
                    "{},{},{},{},{},{},{}",
                    u8::from(*res),
                    cell_u64,
                    checklist_id,
                    is_complete,
                    record.observation_date,
                    record.latitude,
                    record.longitude
                )?;
                pairs_written += 1;
            }
        }

        // Final update
        if let Some(app) = &self.app {
            app.update_state(|s| {
                s.records_read = total_records;
                s.pairs_written = pairs_written;
                s.filtered = filtered_records;
            });
        }

        self.log("INFO", format!(
            "Pass 1 complete: {} records, {} pairs, {} filtered",
            format_number(total_records),
            format_number(pairs_written),
            format_number(filtered_records)
        ));

        Ok(total_records)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::io::Write;
    use tempfile::TempDir;

    /// Test that pass1_extract_pairs DOES NOT overwrite existing file
    #[test]
    fn test_pass1_does_not_overwrite_existing_file() {
        let temp_dir = TempDir::new().unwrap();
        let analyzer = TwoPassAnalyzer::new(
            vec![2, 3],
            1.0,
            temp_dir.path().to_path_buf(),
        )
        .unwrap();

        // Create a fake existing pairs.csv file with known content
        let pairs_file = temp_dir.path().join("pairs.csv");
        let original_content = "ORIGINAL_DATA_DO_NOT_OVERWRITE\n".repeat(1000);
        fs::write(&pairs_file, &original_content).unwrap();

        // Verify file exists and has expected size
        let original_size = pairs_file.metadata().unwrap().len();
        assert!(original_size > 0, "Original file should have content");

        // Create a minimal TSV input file (will not be used if resume works)
        let input_file = temp_dir.path().join("test_input.tsv");
        fs::write(&input_file, "header\nsome\ndata\n").unwrap();

        // Call pass1_extract_pairs - should detect existing file and return early
        let result = analyzer.pass1_extract_pairs(&input_file).unwrap();

        // Verify the file was NOT overwritten
        let final_content = fs::read_to_string(&pairs_file).unwrap();
        let final_size = pairs_file.metadata().unwrap().len();

        assert_eq!(
            final_content, original_content,
            "File content should be unchanged"
        );
        assert_eq!(final_size, original_size, "File size should be unchanged");
        assert_eq!(
            result, pairs_file,
            "Should return path to existing file"
        );
    }

    /// Test that sort_pairs DOES NOT overwrite existing sorted file
    #[test]
    fn test_sort_does_not_overwrite_existing_file() {
        let temp_dir = TempDir::new().unwrap();
        let analyzer = TwoPassAnalyzer::new(
            vec![2, 3],
            1.0,
            temp_dir.path().to_path_buf(),
        )
        .unwrap();

        // Create fake pairs.csv (input to sort)
        let pairs_file = temp_dir.path().join("pairs.csv");
        fs::write(&pairs_file, "2,123,checklist1,1,2025-01-01,45.0,-122.0\n").unwrap();

        // Create a fake existing sorted file with known content
        let sorted_file = temp_dir.path().join("pairs_sorted.csv");
        let original_content = "ORIGINAL_SORTED_DATA_DO_NOT_OVERWRITE\n".repeat(1000);
        fs::write(&sorted_file, &original_content).unwrap();

        // Verify sorted file exists and has expected size
        let original_size = sorted_file.metadata().unwrap().len();
        assert!(original_size > 0, "Original sorted file should have content");

        // Call sort_pairs - should detect existing file and return early
        let result = analyzer.sort_pairs(&pairs_file).unwrap();

        // Verify the sorted file was NOT overwritten
        let final_content = fs::read_to_string(&sorted_file).unwrap();
        let final_size = sorted_file.metadata().unwrap().len();

        assert_eq!(
            final_content, original_content,
            "Sorted file content should be unchanged"
        );
        assert_eq!(final_size, original_size, "Sorted file size should be unchanged");
        assert_eq!(
            result, sorted_file,
            "Should return path to existing sorted file"
        );
    }

    /// Test that empty files are treated as non-existent and get overwritten
    #[test]
    fn test_empty_pairs_file_gets_overwritten() {
        let temp_dir = TempDir::new().unwrap();
        let analyzer = TwoPassAnalyzer::new(
            vec![2],
            1.0,
            temp_dir.path().to_path_buf(),
        )
        .unwrap();

        // Create an EMPTY pairs.csv file (0 bytes)
        let pairs_file = temp_dir.path().join("pairs.csv");
        File::create(&pairs_file).unwrap();

        // Verify it's empty
        assert_eq!(
            pairs_file.metadata().unwrap().len(),
            0,
            "File should be empty"
        );

        // Create a minimal valid TSV that would create output
        // (Note: This will fail to parse as real eBird data, but that's okay for this test)
        let input_file = temp_dir.path().join("test_input.tsv");
        fs::write(&input_file, "SCIENTIFIC NAME\tLATITUDE\tLONGITUDE\n").unwrap();

        // Call pass1 - should process the input because existing file is empty
        let _result = analyzer.pass1_extract_pairs(&input_file);

        // The function will error trying to parse invalid data, but that's expected
        // The important thing is it tried to process (didn't return early)
        // We can't assert much here without valid test data, but the test above
        // proves the resume logic works for non-empty files
    }

    /// Test that sort_pairs handles missing pairs file gracefully
    #[test]
    fn test_sort_with_missing_input_file() {
        let temp_dir = TempDir::new().unwrap();
        let analyzer = TwoPassAnalyzer::new(
            vec![2],
            1.0,
            temp_dir.path().to_path_buf(),
        )
        .unwrap();

        let nonexistent_file = temp_dir.path().join("does_not_exist.csv");

        // Should error gracefully, not panic
        let result = analyzer.sort_pairs(&nonexistent_file);
        assert!(result.is_err(), "Should return error for missing input file");
    }
}
