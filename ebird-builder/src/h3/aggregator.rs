use super::grid::H3Grid;
use crate::config::FilterConfig;
use crate::ebird::EBirdRecord;
use crate::taxon_registry::{normalize_species_name, TaxonRegistry};
use anyhow::Result;
use chrono::{Datelike, NaiveDate};
use h3o::CellIndex;
use std::collections::HashMap;

pub struct H3Aggregator {
    pub grid: H3Grid,
    pub cells: HashMap<CellIndex, H3CellData>,
    pub sampling_data: HashMap<CellIndex, usize>,
}

pub struct H3CellData {
    pub h3_cell: CellIndex,
    pub center_lat: f64,
    pub center_lon: f64,
    pub species: HashMap<String, SpeciesAccumulator>,
    pub total_checklists: u32,
    pub complete_checklists: u32,
    pub date_range_start: Option<NaiveDate>,
    pub date_range_end: Option<NaiveDate>,

    // Last-seen tracking for cell-level checklists
    last_checklist_id: Option<String>,
    last_complete_checklist_id: Option<String>,

    // Group deduplication tracking
    // Assumes data is sorted by (LAT, LON, GROUP ID NULLS LAST, SAMPLING ID, TAXON, DATE)
    current_group_id: Option<String>,
    species_in_current_group: std::collections::HashSet<String>,

    // Temporal complete checklist tracking (for correct frequency denominators)
    yearly_complete_checklists: HashMap<u16, u32>,      // year -> count
    quarterly_complete_checklists: [u32; 4],            // Q1-Q4
    monthly_complete_checklists: [u32; 12],             // Jan-Dec
    weekly_complete_checklists: [u32; 48],              // Week 1-48

    // Last-seen tracking for temporal buckets
    last_yearly_checklist: HashMap<u16, Option<String>>,
    last_quarterly_checklist: [Option<String>; 4],
    last_monthly_checklist: [Option<String>; 12],
    last_weekly_checklist: [Option<String>; 48],
}

pub struct SpeciesAccumulator {
    pub avibase_id: String,
    pub scientific_name: String,
    pub is_species_level: bool,  // Track if avibase_id came from species-level record

    // Checklist counters (no longer storing all IDs - using sorted data optimization)
    pub total_checklists: u32,
    pub complete_checklists: u32,

    // Observation dates (for min/max tracking)
    pub first_observation: Option<NaiveDate>,
    pub last_observation: Option<NaiveDate>,

    // High-quality observation dates (approved + complete + native + species-level)
    pub first_high_quality_observation: Option<NaiveDate>,
    pub last_high_quality_observation: Option<NaiveDate>,

    // Quality tracking (incremental)
    pub high_quality_obs: u32,
    pub low_quality_obs: u32,

    // Temporal tracking (incremental counters)
    pub monthly_obs: [u32; 12],
    pub monthly_checklists: [u32; 12],
    pub yearly_data: HashMap<u16, (u32, u32)>, // year -> (obs_count, checklist_count)
    pub quarterly_obs: [u32; 4],
    pub quarterly_checklists: [u32; 4],
    pub weekly_obs: [u32; 48],  // BirdNET uses 48 weeks (365 days / 7.6 days per week)
    pub weekly_checklists: [u32; 48],

    // Last-seen tracking for sorted data optimization
    // Assumes data is sorted by GROUP_IDENTIFIER (or effective checklist ID)
    last_checklist_id: Option<String>,
    last_complete_checklist_id: Option<String>,
    last_monthly_checklist: [Option<String>; 12],
    last_yearly_checklist: HashMap<u16, Option<String>>,
    last_quarterly_checklist: [Option<String>; 4],
    last_weekly_checklist: [Option<String>; 48],
}

pub struct ObservationEvent {
    pub date: NaiveDate,
    pub checklist_id: String,
    #[allow(dead_code)]
    pub count: u32,
    pub is_approved: bool,
    pub is_complete_checklist: bool,
    pub is_native: bool,
    pub is_species: bool,
}

pub struct SpeciesData {
    pub avibase_id: String,
    pub scientific_name: String,
    pub yearly_frequency: f64,
    pub total_observations: u32,
    pub total_checklists: u32,
    pub first_observation: NaiveDate,
    pub last_observation: NaiveDate,
    pub confidence_tier: String,
    pub confidence_boost: f64,
    pub monthly_data: Vec<MonthlyData>,
    pub yearly_data: Vec<YearlyData>,
    pub quarterly_data: Vec<QuarterlyData>,
    pub weekly_data: Vec<WeeklyData>,
    pub quality_score: f64,
    pub high_quality_obs: u32,
    pub low_quality_obs: u32,
}

#[derive(Debug, Clone)]
pub struct MonthlyData {
    pub month: u8,  // 1-12
    pub observations: u32,
    pub checklists: u32,
    pub frequency: f64,
}

#[derive(Debug, Clone)]
pub struct YearlyData {
    pub year: u16,
    pub observations: u32,
    pub checklists: u32,
    pub frequency: f64,
}

#[derive(Debug, Clone)]
pub struct QuarterlyData {
    pub quarter: u8,  // 1-4
    pub observations: u32,
    pub checklists: u32,
    pub frequency: f64,
}

#[derive(Debug, Clone)]
pub struct WeeklyData {
    pub week: u8,  // 1-48 (aligned with BirdNET's 48-week year model)
    pub observations: u32,
    pub checklists: u32,
    pub frequency: f64,
}

pub struct GridCellPack {
    pub h3_cell: CellIndex,
    pub resolution: u8,
    pub center_lat: f64,
    pub center_lon: f64,
    pub total_checklists: usize,
    pub complete_checklists: usize,
    pub total_observations: usize,
    pub date_range_start: NaiveDate,
    pub date_range_end: NaiveDate,
    pub data_quality: String,
    pub species: Vec<SpeciesData>,
    pub total_complete_checklists_sampled: Option<usize>,
}

impl H3Aggregator {
    pub fn new(resolution: u8) -> Result<Self> {
        Ok(Self {
            grid: H3Grid::new(resolution)?,
            cells: HashMap::new(),
            sampling_data: HashMap::new(),
        })
    }

    pub fn new_with_sampling(
        resolution: u8,
        sampling_data: HashMap<CellIndex, usize>,
    ) -> Result<Self> {
        Ok(Self {
            grid: H3Grid::new(resolution)?,
            cells: HashMap::new(),
            sampling_data,
        })
    }

    /// Add a record to the aggregator
    /// The canonical_taxon_id should come from the global TaxonRegistry
    pub fn add_record(&mut self, record: &EBirdRecord, canonical_taxon_id: &str) -> Result<()> {
        let h3_cell = self
            .grid
            .lat_lon_to_cell(record.latitude, record.longitude)?;

        let cell_data = self.cells.entry(h3_cell).or_insert_with(|| {
            let (lat, lon) = self.grid.cell_to_lat_lon(h3_cell);
            H3CellData::new(h3_cell, lat, lon)
        });

        cell_data.add_observation(record, canonical_taxon_id)?;
        Ok(())
    }

    /// Finalize aggregation and produce grid cell packs
    /// The global_registry is used for post-aggregation sync to ensure all cells
    /// have the correct canonical taxon IDs
    pub fn finalize(mut self, config: &FilterConfig, global_registry: &TaxonRegistry) -> Vec<GridCellPack> {
        // CRITICAL: Sync all cell species IDs with the global registry BEFORE finalizing
        // This ensures all cells use the correct species-level taxon IDs regardless of
        // the order in which records were encountered during aggregation
        let mut sync_count = 0;
        for cell in self.cells.values_mut() {
            for (normalized_name, species) in &mut cell.species {
                if let Some(canonical_id) = global_registry.get_canonical_id(normalized_name) {
                    if species.avibase_id != canonical_id {
                        log::debug!(
                            "Post-aggregation sync for '{}' in cell: '{}' → '{}'",
                            normalized_name,
                            species.avibase_id,
                            canonical_id
                        );
                        species.avibase_id = canonical_id.to_string();
                        // Assume canonical ID is always species-level (true by construction)
                        species.is_species_level = true;
                        sync_count += 1;
                    }
                }
            }
        }

        if sync_count > 0 {
            log::info!(
                "Post-aggregation: Synced {} cell-species entries with global registry",
                sync_count
            );
        }

        let sampling_data = &self.sampling_data;
        self.cells
            .into_values()
            .map(|cell| cell.finalize(&self.grid, config, sampling_data))
            .collect()
    }
}

impl H3CellData {
    pub fn new(h3_cell: CellIndex, center_lat: f64, center_lon: f64) -> Self {
        Self {
            h3_cell,
            center_lat,
            center_lon,
            species: HashMap::new(),
            total_checklists: 0,
            complete_checklists: 0,
            date_range_start: None,
            date_range_end: None,
            last_checklist_id: None,
            last_complete_checklist_id: None,
            current_group_id: None,
            species_in_current_group: std::collections::HashSet::new(),
            yearly_complete_checklists: HashMap::new(),
            quarterly_complete_checklists: [0; 4],
            monthly_complete_checklists: [0; 12],
            weekly_complete_checklists: [0; 48],
            last_yearly_checklist: HashMap::new(),
            last_quarterly_checklist: [None, None, None, None],
            last_monthly_checklist: [
                None, None, None, None, None, None,
                None, None, None, None, None, None,
            ],
            last_weekly_checklist: [
                None, None, None, None, None, None, None, None,
                None, None, None, None, None, None, None, None,
                None, None, None, None, None, None, None, None,
                None, None, None, None, None, None, None, None,
                None, None, None, None, None, None, None, None,
                None, None, None, None, None, None, None, None,
            ],
        }
    }

    pub fn add_observation(&mut self, record: &EBirdRecord, canonical_taxon_id: &str) -> Result<()> {
        let checklist_id = record.get_checklist_id();

        // Group-based species deduplication
        // Data is sorted by (LAT, LON, GROUP ID NULLS LAST, SAMPLING ID, TAXON, DATE)
        // If group ID changes, reset the species set. If a species appears multiple
        // times in the same group (from different observers), skip duplicates.
        if let Some(ref group_id) = record.group_identifier {
            // Check if we've moved to a new group
            if self.current_group_id.as_ref() != Some(group_id) {
                // New group - reset species tracking
                self.current_group_id = Some(group_id.clone());
                self.species_in_current_group.clear();
            }

            // Check if we've already seen this species in this group
            let normalized_name = crate::taxon_registry::normalize_species_name(&record.scientific_name);
            if self.species_in_current_group.contains(&normalized_name) {
                // Duplicate species in same group - skip
                return Ok(());
            }
            // Mark species as seen in this group
            self.species_in_current_group.insert(normalized_name.clone());
        } else {
            // Individual checklist (no group) - reset group tracking
            if self.current_group_id.is_some() {
                self.current_group_id = None;
                self.species_in_current_group.clear();
            }
        }

        // Track cell-level checklists with sorted data optimization
        // Only increment if this is a new checklist (different from last seen)
        if self.last_checklist_id.as_ref() != Some(&checklist_id) {
            self.total_checklists += 1;
            self.last_checklist_id = Some(checklist_id.clone());
        }

        // Update date range (needed for temporal tracking)
        let date = record.parse_date()?;

        if record.is_complete_checklist() {
            if self.last_complete_checklist_id.as_ref() != Some(&checklist_id) {
                self.complete_checklists += 1;
                self.last_complete_checklist_id = Some(checklist_id.clone());

                // Track temporal complete checklists for correct frequency denominators
                // Yearly tracking
                let year = date.year() as u16;
                if self.last_yearly_checklist.get(&year) != Some(&Some(checklist_id.clone())) {
                    *self.yearly_complete_checklists.entry(year).or_insert(0) += 1;
                    self.last_yearly_checklist.insert(year, Some(checklist_id.clone()));
                }

                // Quarterly tracking (Q1-Q4)
                let quarter = ((date.month0() / 3) as usize).min(3);
                if self.last_quarterly_checklist[quarter].as_ref() != Some(&checklist_id) {
                    self.quarterly_complete_checklists[quarter] += 1;
                    self.last_quarterly_checklist[quarter] = Some(checklist_id.clone());
                }

                // Monthly tracking (Jan-Dec, 0-indexed)
                let month = date.month0() as usize;
                if self.last_monthly_checklist[month].as_ref() != Some(&checklist_id) {
                    self.monthly_complete_checklists[month] += 1;
                    self.last_monthly_checklist[month] = Some(checklist_id.clone());
                }

                // Weekly tracking (1-48)
                let week = ((date.ordinal0() / 7).min(47)) as usize;
                if self.last_weekly_checklist[week].as_ref() != Some(&checklist_id) {
                    self.weekly_complete_checklists[week] += 1;
                    self.last_weekly_checklist[week] = Some(checklist_id.clone());
                }
            }
        }
        self.date_range_start = Some(self.date_range_start.map(|d| d.min(date)).unwrap_or(date));
        self.date_range_end = Some(self.date_range_end.map(|d| d.max(date)).unwrap_or(date));

        // Normalize species name BEFORE aggregation to treat variants as same species
        // e.g., "Anas platyrhynchos/wyvilliana" → "Anas platyrhynchos"
        let normalized_name = normalize_species_name(&record.scientific_name);

        // Add to species accumulator using normalized name as key
        // Use canonical taxon_concept_id from global registry (already determined at aggregator level)
        let species = self
            .species
            .entry(normalized_name.clone())
            .or_insert_with(|| SpeciesAccumulator {
                avibase_id: canonical_taxon_id.to_string(),
                scientific_name: normalized_name.clone(),
                is_species_level: true, // Canonical ID is always the best one
                total_checklists: 0,
                complete_checklists: 0,
                first_observation: None,
                last_observation: None,
                first_high_quality_observation: None,
                last_high_quality_observation: None,
                high_quality_obs: 0,
                low_quality_obs: 0,
                monthly_obs: [0; 12],
                monthly_checklists: [0; 12],
                yearly_data: HashMap::new(),
                quarterly_obs: [0; 4],
                quarterly_checklists: [0; 4],
                weekly_obs: [0; 48],
                weekly_checklists: [0; 48],
                last_checklist_id: None,
                last_complete_checklist_id: None,
                last_monthly_checklist: std::array::from_fn(|_| None),
                last_yearly_checklist: HashMap::new(),
                last_quarterly_checklist: std::array::from_fn(|_| None),
                last_weekly_checklist: std::array::from_fn(|_| None),
            });

        // CRITICAL: Always sync avibase_id with canonical ID from global registry
        // The global registry may have been upgraded since this cell's species entry was created
        if species.avibase_id != canonical_taxon_id {
            species.avibase_id = canonical_taxon_id.to_string();
            species.is_species_level = true;
        }

        // Update overall dates (all observations)
        species.first_observation = Some(
            species
                .first_observation
                .map(|d| d.min(date))
                .unwrap_or(date),
        );
        species.last_observation = Some(
            species
                .last_observation
                .map(|d| d.max(date))
                .unwrap_or(date),
        );

        // Track species-level checklists with sorted data optimization
        if species.last_checklist_id.as_ref() != Some(&checklist_id) {
            species.total_checklists += 1;
            species.last_checklist_id = Some(checklist_id.clone());
        }

        if record.is_complete_checklist() {
            if species.last_complete_checklist_id.as_ref() != Some(&checklist_id) {
                species.complete_checklists += 1;
                species.last_complete_checklist_id = Some(checklist_id.clone());
            }
        }

        // Update quality tracking
        let is_high_quality = record.is_approved()
            && record.is_complete_checklist()
            && record.is_native()
            && record.is_species();

        if is_high_quality {
            species.high_quality_obs += 1;

            // Update high-quality observation dates separately
            species.first_high_quality_observation = Some(
                species
                    .first_high_quality_observation
                    .map(|d| d.min(date))
                    .unwrap_or(date),
            );
            species.last_high_quality_observation = Some(
                species
                    .last_high_quality_observation
                    .map(|d| d.max(date))
                    .unwrap_or(date),
            );
        } else {
            species.low_quality_obs += 1;
        }

        // Update monthly data with sorted optimization
        let month = (date.month0() as usize).min(11);
        species.monthly_obs[month] += 1;
        if record.is_complete_checklist() {
            if species.last_monthly_checklist[month].as_ref() != Some(&checklist_id) {
                species.monthly_checklists[month] += 1;
                species.last_monthly_checklist[month] = Some(checklist_id.clone());
            }
        }

        // Update yearly data with sorted optimization
        let year = date.year() as u16;
        let yearly_entry = species.yearly_data.entry(year).or_insert((0, 0));
        yearly_entry.0 += 1; // increment observation count

        if record.is_complete_checklist() {
            let yearly_last = species.last_yearly_checklist.entry(year).or_insert(None);
            if yearly_last.as_ref() != Some(&checklist_id) {
                yearly_entry.1 += 1; // increment checklist count (complete only)
                *yearly_last = Some(checklist_id.clone());
            }
        }

        // Update quarterly data with sorted optimization
        let quarter = ((date.month0() / 3) as usize).min(3);
        species.quarterly_obs[quarter] += 1;
        if record.is_complete_checklist() {
            if species.last_quarterly_checklist[quarter].as_ref() != Some(&checklist_id) {
                species.quarterly_checklists[quarter] += 1;
                species.last_quarterly_checklist[quarter] = Some(checklist_id.clone());
            }
        }

        // Update weekly data with sorted optimization
        let day_of_year = date.ordinal() as usize; // 1-366
        let week = ((day_of_year - 1) * 48 / 365).min(47); // Convert to 0-47, then clamp
        species.weekly_obs[week] += 1;
        if record.is_complete_checklist() {
            if species.last_weekly_checklist[week].as_ref() != Some(&checklist_id) {
                species.weekly_checklists[week] += 1;
                species.last_weekly_checklist[week] = Some(checklist_id);
            }
        }

        Ok(())
    }

    pub fn finalize(
        self,
        grid: &H3Grid,
        config: &FilterConfig,
        sampling_data: &HashMap<CellIndex, usize>,
    ) -> GridCellPack {
        let total_complete = self.complete_checklists as f64;
        let total_sampled = sampling_data.get(&self.h3_cell).copied();

        // Use sampling data for frequency calculations if available and reliable
        let _frequency_denominator = if let Some(sampled) = total_sampled {
            if sampled >= 100 {
                sampled as f64
            } else {
                total_complete
            }
        } else {
            total_complete
        };

        let species: Vec<SpeciesData> = self
            .species
            .into_iter()
            .filter_map(|(_, acc)| {
                // Total observations = sum of high + low quality
                let total_obs = acc.high_quality_obs + acc.low_quality_obs;
                let total_lists = acc.total_checklists;
                let complete_lists = acc.complete_checklists;

                // Use total_complete as denominator since complete_lists comes from observation data
                let yearly_frequency = if total_complete > 0.0 {
                    complete_lists as f64 / total_complete
                } else {
                    0.0
                };

                // Check if species meets inclusion thresholds
                let meets_thresholds = total_obs >= config.min_observations
                    && total_lists >= config.min_checklists
                    && yearly_frequency >= config.min_yearly_frequency;

                // Calculate quality score from pre-computed counters
                let total = (acc.high_quality_obs + acc.low_quality_obs) as f64;
                let quality_score = if total > 0.0 {
                    acc.high_quality_obs as f64 / total
                } else {
                    0.0
                };

                // If species doesn't meet thresholds, still include with 'excluded' tier
                let (confidence_tier, confidence_boost) = if !meets_thresholds {
                    ("excluded".to_string(), 1.0)
                } else {
                    let (tier, base_boost) = classify_species(yearly_frequency);

                    // Apply absence penalty if we have strong sampling evidence
                    let absence_penalty = calculate_absence_penalty(
                        total_sampled,
                        yearly_frequency,
                    );

                    // Apply quality multiplier to confidence boost
                    let quality_multiplier = 0.7 + (0.3 * quality_score); // 0.7-1.0 range
                    let final_boost = base_boost * absence_penalty * quality_multiplier;

                    // Clamp to database constraint range (0.8-2.0)
                    let clamped_boost = final_boost.clamp(0.8, 2.0);

                    (tier, clamped_boost)
                };

                // Compute temporal data from pre-computed aggregates
                // Use cell's temporal complete checklists for correct frequency denominators
                let monthly_data = compute_monthly_data_from_aggregates(
                    &acc.monthly_obs,
                    &acc.monthly_checklists,
                    &self.monthly_complete_checklists,
                );
                let yearly_data = compute_yearly_data_from_aggregates(
                    &acc.yearly_data,
                    &self.yearly_complete_checklists,
                );
                let quarterly_data = compute_quarterly_data_from_aggregates(
                    &acc.quarterly_obs,
                    &acc.quarterly_checklists,
                    &self.quarterly_complete_checklists,
                );
                let weekly_data = compute_weekly_data_from_aggregates(
                    &acc.weekly_obs,
                    &acc.weekly_checklists,
                    &self.weekly_complete_checklists,
                );

                // Use avibase_id directly from accumulator (populated from record.taxon_concept_id)
                Some(SpeciesData {
                    avibase_id: acc.avibase_id,
                    scientific_name: acc.scientific_name,
                    yearly_frequency,
                    total_observations: total_obs,
                    total_checklists: total_lists,
                    first_observation: acc.first_observation.unwrap(),
                    last_observation: acc.last_observation.unwrap(),
                    confidence_tier,
                    confidence_boost,
                    monthly_data,
                    yearly_data,
                    quarterly_data,
                    weekly_data,
                    quality_score,
                    high_quality_obs: acc.high_quality_obs,
                    low_quality_obs: acc.low_quality_obs,
                })
            })
            .collect();

        let data_quality = match self.complete_checklists {
            n if n >= 100 => "excellent",
            n if n >= 50 => "good",
            n if n >= 20 => "fair",
            _ => "sparse",
        }
        .to_string();

        let total_observations = species.iter().map(|s| s.total_observations as usize).sum();

        GridCellPack {
            h3_cell: self.h3_cell,
            resolution: grid.resolution(),
            center_lat: self.center_lat,
            center_lon: self.center_lon,
            total_checklists: self.total_checklists as usize,
            complete_checklists: self.complete_checklists as usize,
            total_observations,
            date_range_start: self
                .date_range_start
                .unwrap_or_else(|| NaiveDate::from_ymd_opt(2020, 1, 1).unwrap()),
            date_range_end: self
                .date_range_end
                .unwrap_or_else(|| NaiveDate::from_ymd_opt(2025, 12, 31).unwrap()),
            data_quality,
            species,
            total_complete_checklists_sampled: total_sampled,
        }
    }
}

pub(crate) fn compute_monthly_data_from_aggregates(
    monthly_obs: &[u32; 12],
    monthly_checklists: &[u32; 12],
    monthly_complete_checklists: &[u32; 12], // Cell's complete checklists per month
) -> Vec<MonthlyData> {
    (1..=12)
        .map(|month| {
            let idx = (month - 1) as usize;
            let checklists = monthly_checklists[idx];
            let cell_complete = monthly_complete_checklists[idx] as f64;

            // Calculate frequency as species_checklists / cell_complete_checklists_for_month
            let frequency = if cell_complete > 0.0 {
                checklists as f64 / cell_complete
            } else {
                0.0
            };

            MonthlyData {
                month,
                observations: monthly_obs[idx],
                checklists,
                frequency,
            }
        })
        .filter(|m| m.observations > 0 || m.checklists > 0)
        .collect()
}

pub(crate) fn compute_yearly_data_from_aggregates(
    yearly_data: &HashMap<u16, (u32, u32)>,
    yearly_complete_checklists: &HashMap<u16, u32>, // Cell's complete checklists per year
) -> Vec<YearlyData> {
    let mut results: Vec<YearlyData> = yearly_data
        .iter()
        .map(|(year, (observations, checklists))| {
            // Get cell's complete checklists for this specific year
            let cell_complete = yearly_complete_checklists.get(year).copied().unwrap_or(0) as f64;

            // Calculate frequency as species_checklists / cell_complete_checklists_for_year
            let frequency = if cell_complete > 0.0 {
                *checklists as f64 / cell_complete
            } else {
                0.0
            };

            YearlyData {
                year: *year,
                observations: *observations,
                checklists: *checklists,
                frequency,
            }
        })
        .collect();

    results.sort_by_key(|y| y.year);
    results
}

pub(crate) fn compute_quarterly_data_from_aggregates(
    quarterly_obs: &[u32; 4],
    quarterly_checklists: &[u32; 4],
    quarterly_complete_checklists: &[u32; 4], // Cell's complete checklists per quarter
) -> Vec<QuarterlyData> {
    (1..=4)
        .map(|quarter| {
            let idx = (quarter - 1) as usize;
            let checklists = quarterly_checklists[idx];
            let cell_complete = quarterly_complete_checklists[idx] as f64;

            // Calculate frequency as species_checklists / cell_complete_checklists_for_quarter
            let frequency = if cell_complete > 0.0 {
                checklists as f64 / cell_complete
            } else {
                0.0
            };

            QuarterlyData {
                quarter,
                observations: quarterly_obs[idx],
                checklists,
                frequency,
            }
        })
        .filter(|q| q.observations > 0 || q.checklists > 0)
        .collect()
}

pub(crate) fn compute_weekly_data_from_aggregates(
    weekly_obs: &[u32; 48],
    weekly_checklists: &[u32; 48],
    weekly_complete_checklists: &[u32; 48], // Cell's complete checklists per week
) -> Vec<WeeklyData> {
    (1..=48)
        .map(|week| {
            let idx = (week - 1) as usize;
            let checklists = weekly_checklists[idx];
            let cell_complete = weekly_complete_checklists[idx] as f64;

            // Calculate frequency as species_checklists / cell_complete_checklists_for_week
            let frequency = if cell_complete > 0.0 {
                checklists as f64 / cell_complete
            } else {
                0.0
            };

            WeeklyData {
                week,
                observations: weekly_obs[idx],
                checklists,
                frequency,
            }
        })
        .filter(|w| w.observations > 0 || w.checklists > 0)
        .collect()
}

pub(crate) fn classify_species(yearly_frequency: f64) -> (String, f64) {
    let tier = if yearly_frequency >= 0.20 {
        "common"
    } else if yearly_frequency >= 0.05 {
        "uncommon"
    } else if yearly_frequency >= 0.01 {
        "rare"
    } else {
        "vagrant"
    };

    const MAX_BOOST: f64 = 1.3;
    let boost = 1.0 + (yearly_frequency * (MAX_BOOST - 1.0));

    (tier.to_string(), boost.min(MAX_BOOST))
}

/// Calculate absence penalty based on sampling data
///
/// If we have strong sampling evidence (1000+ complete checklists) and the species
/// has very low frequency (<0.1%), apply a -20% penalty to reduce false positives
pub(crate) fn calculate_absence_penalty(
    total_sampled: Option<usize>,
    yearly_frequency: f64,
) -> f64 {
    // Only apply penalty if we have strong sampling evidence
    if let Some(sampled) = total_sampled {
        // Require 1000+ complete checklists for strong absence signal
        if sampled >= 1000 {
            // Apply penalty for very rare species (< 0.1% frequency)
            // This represents ~1 detection per 1000 complete checklists
            if yearly_frequency < 0.001 {
                // -20% penalty for strong absence evidence
                return 0.8;
            }
        }
    }

    // No penalty - return 1.0 (no modification to boost)
    1.0
}

