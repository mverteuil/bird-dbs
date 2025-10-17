use super::grid::H3Grid;
use crate::config::FilterConfig;
use crate::ebird::EBirdRecord;
use anyhow::Result;
use chrono::{Datelike, NaiveDate};
use h3o::CellIndex;
use std::collections::{HashMap, HashSet};

pub struct H3Aggregator {
    pub grid: H3Grid,
    pub cells: HashMap<CellIndex, H3CellData>,
    pub sampling_data: HashMap<CellIndex, usize>,
    pub avibase_mapping: HashMap<String, String>,
}

pub struct H3CellData {
    pub h3_cell: CellIndex,
    pub center_lat: f64,
    pub center_lon: f64,
    pub species: HashMap<String, SpeciesAccumulator>,
    pub total_checklists: HashSet<String>,
    pub complete_checklists: HashSet<String>,
    pub date_range_start: Option<NaiveDate>,
    pub date_range_end: Option<NaiveDate>,
}

pub struct SpeciesAccumulator {
    pub scientific_name: String,
    pub observations: Vec<ObservationEvent>,
    pub checklists: HashSet<String>,
}

pub struct ObservationEvent {
    pub date: NaiveDate,
    pub checklist_id: String,
    #[allow(dead_code)]
    pub count: u32,
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
    pub monthly_frequency: [f64; 12],
    pub monthly_observations: [u32; 12],
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
    pub fn new(resolution: u8, avibase_mapping: HashMap<String, String>) -> Result<Self> {
        Ok(Self {
            grid: H3Grid::new(resolution)?,
            cells: HashMap::new(),
            sampling_data: HashMap::new(),
            avibase_mapping,
        })
    }

    pub fn new_with_sampling(
        resolution: u8,
        sampling_data: HashMap<CellIndex, usize>,
        avibase_mapping: HashMap<String, String>,
    ) -> Result<Self> {
        Ok(Self {
            grid: H3Grid::new(resolution)?,
            cells: HashMap::new(),
            sampling_data,
            avibase_mapping,
        })
    }

    pub fn add_record(&mut self, record: &EBirdRecord) -> Result<()> {
        let h3_cell = self
            .grid
            .lat_lon_to_cell(record.latitude, record.longitude)?;

        let cell_data = self.cells.entry(h3_cell).or_insert_with(|| {
            let (lat, lon) = self.grid.cell_to_lat_lon(h3_cell);
            H3CellData::new(h3_cell, lat, lon)
        });

        cell_data.add_observation(record)?;
        Ok(())
    }

    pub fn finalize(self, config: &FilterConfig) -> Vec<GridCellPack> {
        let sampling_data = &self.sampling_data;
        let avibase_mapping = &self.avibase_mapping;
        self.cells
            .into_values()
            .map(|cell| cell.finalize(&self.grid, config, sampling_data, avibase_mapping))
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
            total_checklists: HashSet::new(),
            complete_checklists: HashSet::new(),
            date_range_start: None,
            date_range_end: None,
        }
    }

    pub fn add_observation(&mut self, record: &EBirdRecord) -> Result<()> {
        let checklist_id = record.get_checklist_id();

        // Track checklists
        self.total_checklists.insert(checklist_id.clone());
        if record.is_complete_checklist() {
            self.complete_checklists.insert(checklist_id.clone());
        }

        // Update date range
        let date = record.parse_date()?;
        self.date_range_start = Some(self.date_range_start.map(|d| d.min(date)).unwrap_or(date));
        self.date_range_end = Some(self.date_range_end.map(|d| d.max(date)).unwrap_or(date));

        // Add to species accumulator
        let species = self
            .species
            .entry(record.scientific_name.clone())
            .or_insert_with(|| SpeciesAccumulator {
                scientific_name: record.scientific_name.clone(),
                observations: Vec::new(),
                checklists: HashSet::new(),
            });

        species.observations.push(ObservationEvent {
            date,
            checklist_id: checklist_id.clone(),
            count: record.get_count(),
        });
        species.checklists.insert(checklist_id);

        Ok(())
    }

    pub fn finalize(
        self,
        grid: &H3Grid,
        config: &FilterConfig,
        sampling_data: &HashMap<CellIndex, usize>,
        avibase_mapping: &HashMap<String, String>,
    ) -> GridCellPack {
        let total_complete = self.complete_checklists.len() as f64;
        let total_sampled = sampling_data.get(&self.h3_cell).copied();

        // Use sampling data for frequency calculations if available and reliable
        let frequency_denominator = if let Some(sampled) = total_sampled {
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
                let total_obs = acc.observations.len() as u32;
                let total_lists = acc.checklists.len() as u32;

                // Apply minimum thresholds
                if total_obs < config.min_observations || total_lists < config.min_checklists {
                    return None;
                }

                let yearly_frequency = if frequency_denominator > 0.0 {
                    total_lists as f64 / frequency_denominator
                } else {
                    0.0
                };

                if yearly_frequency < config.min_yearly_frequency {
                    return None;
                }

                // Compute monthly frequencies
                let monthly_data = compute_monthly_data(&acc.observations, total_complete);

                // Classify confidence tier and get base boost
                let (confidence_tier, base_confidence_boost) =
                    classify_species(yearly_frequency);

                // Apply absence penalty if we have strong sampling evidence
                let absence_penalty = calculate_absence_penalty(
                    total_sampled,
                    yearly_frequency,
                );

                let final_confidence_boost = base_confidence_boost * absence_penalty;

                // Look up avibase_id from scientific_name
                let avibase_id = avibase_mapping
                    .get(&acc.scientific_name)
                    .cloned()
                    .unwrap_or_else(|| {
                        log::warn!(
                            "No avibase_id found for species: {}",
                            acc.scientific_name
                        );
                        format!("unknown-{}", acc.scientific_name)
                    });

                Some(SpeciesData {
                    avibase_id,
                    scientific_name: acc.scientific_name,
                    yearly_frequency,
                    total_observations: total_obs,
                    total_checklists: total_lists,
                    first_observation: acc.observations.iter().map(|o| o.date).min().unwrap(),
                    last_observation: acc.observations.iter().map(|o| o.date).max().unwrap(),
                    confidence_tier,
                    confidence_boost: final_confidence_boost,
                    monthly_frequency: monthly_data.0,
                    monthly_observations: monthly_data.1,
                })
            })
            .collect();

        let data_quality = match self.complete_checklists.len() {
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
            total_checklists: self.total_checklists.len(),
            complete_checklists: self.complete_checklists.len(),
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

pub(crate) fn compute_monthly_data(
    observations: &[ObservationEvent],
    total_complete_checklists: f64,
) -> ([f64; 12], [u32; 12]) {
    let mut monthly_obs = [0u32; 12];
    let mut monthly_checklists: [HashSet<String>; 12] = Default::default();

    for obs in observations {
        let month = (obs.date.month0() as usize).min(11);
        monthly_obs[month] += 1;
        monthly_checklists[month].insert(obs.checklist_id.clone());
    }

    let monthly_frequency = monthly_checklists.map(|set| {
        if total_complete_checklists > 0.0 {
            set.len() as f64 / total_complete_checklists
        } else {
            0.0
        }
    });

    (monthly_frequency, monthly_obs)
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
