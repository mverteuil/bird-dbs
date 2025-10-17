use crate::output::{CellDensityData, DensityReport};
use crate::tui::{App, Phase};
use anyhow::{Context, Result};
use chrono::NaiveDate;
use h3o::{CellIndex, LatLng, Resolution};
use std::cmp::Ordering;
use std::collections::{BinaryHeap, HashMap};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// Record from a sorted chunk file
#[derive(Debug, Clone)]
struct ChunkRecord {
    resolution: u8,
    cell_u64: u64,
    checklist_id: String,
    is_complete: bool,
    date: String,
    lat: f64,
    lon: f64,
    chunk_id: usize, // Which file this came from
}

impl ChunkRecord {
    fn parse(line: &str, chunk_id: usize) -> Result<Self> {
        let parts: Vec<&str> = line.split(',').collect();
        if parts.len() != 7 {
            anyhow::bail!("Invalid line format: expected 7 fields");
        }

        Ok(Self {
            resolution: parts[0].parse()?,
            cell_u64: parts[1].parse()?,
            checklist_id: parts[2].to_string(),
            is_complete: parts[3] == "1",
            date: parts[4].to_string(),
            lat: parts[5].parse()?,
            lon: parts[6].parse()?,
            chunk_id,
        })
    }

    /// Sort key: (resolution, cell, checklist_id)
    fn sort_key(&self) -> (u8, u64, &str) {
        (self.resolution, self.cell_u64, &self.checklist_id)
    }
}

/// Wrapper for BinaryHeap (reverses ordering for min-heap)
struct MinRecord(ChunkRecord);

impl PartialEq for MinRecord {
    fn eq(&self, other: &Self) -> bool {
        self.0.sort_key() == other.0.sort_key()
    }
}

impl Eq for MinRecord {}

impl PartialOrd for MinRecord {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for MinRecord {
    fn cmp(&self, other: &Self) -> Ordering {
        // Reverse ordering for min-heap
        other.0.sort_key().cmp(&self.0.sort_key())
    }
}

/// Aggregator for a single H3 cell
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
}

/// K-way merge aggregator
pub struct KWayMergeAggregator {
    resolutions: Vec<Resolution>,
    snapshot_dir: PathBuf,
    app: Option<Arc<App>>,
}

impl KWayMergeAggregator {
    pub fn new(resolutions: Vec<u8>, snapshot_dir: PathBuf) -> Result<Self> {
        let resolutions: Vec<Resolution> = resolutions
            .into_iter()
            .map(|r| Resolution::try_from(r).expect("Invalid H3 resolution"))
            .collect();

        Ok(Self {
            resolutions,
            snapshot_dir,
            app: None,
        })
    }

    pub fn with_tui(mut self, app: Arc<App>) -> Self {
        self.app = Some(app);
        self
    }

    fn log(&self, level: &str, message: String) {
        if let Some(app) = &self.app {
            app.add_log(format!("[{}] {}", level, message));
        } else {
            match level {
                "INFO" => log::info!("{}", message),
                "WARN" => log::warn!("{}", message),
                "ERROR" => log::error!("{}", message),
                _ => log::info!("{}", message),
            }
        }
    }

    /// Perform k-way merge and aggregation
    pub fn aggregate(&self) -> Result<HashMap<u8, DensityReport>> {
        self.log("INFO", "Starting k-way merge aggregation".to_string());

        // Collect all chunk files
        let mut chunk_files: Vec<PathBuf> = std::fs::read_dir(&self.snapshot_dir)?
            .filter_map(|entry| entry.ok())
            .map(|entry| entry.path())
            .filter(|path| {
                path.file_name()
                    .and_then(|n| n.to_str())
                    .map(|s| s.starts_with("sort"))
                    .unwrap_or(false)
            })
            .collect();

        chunk_files.sort(); // Consistent ordering
        let num_chunks = chunk_files.len();

        self.log(
            "INFO",
            format!("Found {} sorted chunk files to merge", num_chunks),
        );

        // Open all chunk files
        let mut readers: Vec<BufReader<File>> = Vec::new();
        for path in &chunk_files {
            let file = File::open(path).context("Failed to open chunk file")?;
            readers.push(BufReader::new(file));
        }

        // Initialize heap with first record from each file
        let mut heap: BinaryHeap<MinRecord> = BinaryHeap::new();
        let mut lines: Vec<String> = vec![String::new(); num_chunks];

        for (chunk_id, reader) in readers.iter_mut().enumerate() {
            if reader.read_line(&mut lines[chunk_id])? > 0 {
                if let Ok(record) = ChunkRecord::parse(&lines[chunk_id].trim(), chunk_id) {
                    heap.push(MinRecord(record));
                }
                lines[chunk_id].clear();
            }
        }

        self.log("INFO", format!("Initialized heap with {} records", heap.len()));

        // Update TUI state
        if let Some(app) = &self.app {
            app.update_state(|s| {
                s.phase = Phase::Pass2;
                s.lines_processed = 0;
                s.unique_cells = 0;
            });
        }

        // Aggregation state
        let mut reports: HashMap<u8, HashMap<CellIndex, CellAggregator>> = HashMap::new();
        let mut current_checklist_key: Option<(u8, CellIndex, String)> = None;
        let mut lines_processed = 0usize;
        let mut unique_cells = 0usize;

        // Process records in sorted order
        while let Some(MinRecord(record)) = heap.pop() {
            lines_processed += 1;

            // Update TUI every 10k lines
            if lines_processed % 10_000 == 0 {
                if let Some(app) = &self.app {
                    app.update_state(|s| {
                        s.lines_processed = lines_processed;
                        s.unique_cells = unique_cells;
                    });
                }

                if lines_processed % 100_000 == 0 {
                    self.log(
                        "INFO",
                        format!(
                            "Processed {} lines ({} unique cells)",
                            Self::format_number(lines_processed),
                            Self::format_number(unique_cells)
                        ),
                    );
                }
            }

            // Aggregate record
            let cell = CellIndex::try_from(record.cell_u64)?;
            let resolution_map = reports.entry(record.resolution).or_insert_with(HashMap::new);
            let is_new_cell = !resolution_map.contains_key(&cell);
            let cell_agg = resolution_map.entry(cell).or_insert_with(Default::default);

            if is_new_cell {
                unique_cells += 1;
            }

            // Check if this is a new unique checklist
            let checklist_key = (record.resolution, cell, record.checklist_id.clone());
            let is_new_checklist = current_checklist_key.as_ref() != Some(&checklist_key);

            if is_new_checklist {
                cell_agg.unique_checklists += 1;
                if record.is_complete {
                    cell_agg.complete_checklists += 1;
                }
            }

            // Always count observations
            cell_agg.total_observations += 1;

            // Update lat/lon running average
            cell_agg.lat_sum += record.lat;
            cell_agg.lon_sum += record.lon;
            cell_agg.observation_count += 1;

            // Update date range
            if let Ok(date) = NaiveDate::parse_from_str(&record.date, "%Y-%m-%d") {
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

            // Read next record from the same chunk
            let chunk_id = record.chunk_id;
            if readers[chunk_id].read_line(&mut lines[chunk_id])? > 0 {
                if let Ok(next_record) = ChunkRecord::parse(&lines[chunk_id].trim(), chunk_id) {
                    heap.push(MinRecord(next_record));
                }
                lines[chunk_id].clear();
            }
        }

        // Final TUI update
        if let Some(app) = &self.app {
            app.update_state(|s| {
                s.lines_processed = lines_processed;
                s.unique_cells = unique_cells;
            });
        }

        self.log(
            "INFO",
            format!(
                "K-way merge complete: {} lines processed, {} unique cells",
                Self::format_number(lines_processed),
                Self::format_number(unique_cells)
            ),
        );

        // Convert to DensityReport format
        self.build_density_reports(reports)
    }

    fn build_density_reports(
        &self,
        reports: HashMap<u8, HashMap<CellIndex, CellAggregator>>,
    ) -> Result<HashMap<u8, DensityReport>> {
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
                let estimated_pack_size_mb =
                    Self::estimate_pack_size(resolution, recommended_data_res);

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
                    total_complete_checklists_sampled: None,
                });
            }

            result.insert(
                resolution,
                DensityReport {
                    resolution,
                    cells: cell_data,
                },
            );
        }

        Ok(result)
    }

    fn estimate_pack_size(resolution: u8, data_resolution: u8) -> f64 {
        const BYTES_PER_SPECIES_RECORD: f64 = 400.0;
        const AVG_SPECIES_PER_HEX: f64 = 150.0;
        const COMPRESSION_RATIO: f64 = 0.7;

        let resolution_diff = data_resolution.saturating_sub(resolution) as u32;
        let num_data_hexagons = 7_u32.pow(resolution_diff) as f64;

        let total_species_records = num_data_hexagons * AVG_SPECIES_PER_HEX;
        let raw_size_bytes = total_species_records * BYTES_PER_SPECIES_RECORD;
        (raw_size_bytes * COMPRESSION_RATIO) / 1_000_000.0
    }

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
}
