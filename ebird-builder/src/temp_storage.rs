#![allow(dead_code)]

/// Temporary storage for observations during single-pass processing
///
/// Writes observations to a single temporary SQLite database with region_id tags.
/// This avoids:
/// - OOM from keeping 165 H3Aggregators in memory
/// - File handle limits from 165 simultaneous SQLite connections
/// - 165x dataset re-reading
///
/// After the single dataset pass, we can query observations by region_id and process them.

use crate::ebird::EBirdRecord;
use anyhow::Result;
use rusqlite::{params, Connection};
use std::path::Path;

pub struct TempObservationStorage {
    conn: Connection,
    batch: Vec<ObservationRow>,
    batch_size: usize,
}

struct ObservationRow {
    region_id: String,
    taxon_concept_id: String,
    scientific_name: String,
    latitude: f64,
    longitude: f64,
    observation_date: String,
    checklist_id: String,
    observation_count: Option<i32>,
}

impl TempObservationStorage {
    pub fn new(temp_db_path: &Path) -> Result<Self> {
        let conn = Connection::open(temp_db_path)?;

        // Optimize SQLite for bulk writes
        conn.execute_batch(
            "PRAGMA journal_mode = WAL;
             PRAGMA synchronous = NORMAL;
             PRAGMA cache_size = -64000;  -- 64MB cache
             PRAGMA temp_store = MEMORY;",
        )?;

        // Create table to store raw observations with region tags
        conn.execute(
            "CREATE TABLE observations (
                region_id TEXT NOT NULL,
                taxon_concept_id TEXT NOT NULL,
                scientific_name TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                observation_date TEXT NOT NULL,
                checklist_id TEXT NOT NULL,
                observation_count INTEGER
            )",
            [],
        )?;

        Ok(Self {
            conn,
            batch: Vec::with_capacity(10000),
            batch_size: 10000,
        })
    }

    pub fn add_observation(&mut self, region_id: &str, record: &EBirdRecord) -> Result<()> {
        let observation_count = if record.observation_count == "X" {
            None
        } else {
            Some(record.observation_count.parse().unwrap_or(1))
        };

        self.batch.push(ObservationRow {
            region_id: region_id.to_string(),
            taxon_concept_id: record.taxon_concept_id.clone(),
            scientific_name: record.scientific_name.clone(),
            latitude: record.latitude,
            longitude: record.longitude,
            observation_date: record.observation_date.clone(),
            checklist_id: record.get_checklist_id(),
            observation_count,
        });

        if self.batch.len() >= self.batch_size {
            self.flush_batch()?;
        }

        Ok(())
    }

    fn flush_batch(&mut self) -> Result<()> {
        if self.batch.is_empty() {
            return Ok(());
        }

        let tx = self.conn.transaction()?;
        {
            let mut stmt = tx.prepare_cached(
                "INSERT INTO observations (
                    region_id, taxon_concept_id, scientific_name, latitude, longitude,
                    observation_date, checklist_id, observation_count
                ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            )?;

            for row in &self.batch {
                stmt.execute(params![
                    row.region_id,
                    row.taxon_concept_id,
                    row.scientific_name,
                    row.latitude,
                    row.longitude,
                    row.observation_date,
                    row.checklist_id,
                    row.observation_count,
                ])?;
            }
        }
        tx.commit()?;
        self.batch.clear();
        Ok(())
    }

    pub fn finalize(mut self) -> Result<()> {
        // Flush remaining batch
        self.flush_batch()?;

        // Create index for faster per-region queries
        self.conn.execute(
            "CREATE INDEX idx_region ON observations(region_id)",
            [],
        )?;

        // Optimize database
        self.conn.execute("ANALYZE", [])?;

        Ok(())
    }

    /// Get iterator over observations for a specific region
    pub fn get_region_observations(
        conn: &Connection,
        region_id: &str,
    ) -> Result<Vec<EBirdRecord>> {
        let mut stmt = conn.prepare(
            "SELECT taxon_concept_id, scientific_name, latitude, longitude, observation_date,
                    checklist_id, observation_count
             FROM observations
             WHERE region_id = ?1",
        )?;

        let rows = stmt.query_map(params![region_id], |row| {
            let count_int: Option<i32> = row.get(6)?;
            let observation_count = match count_int {
                Some(n) => n.to_string(),
                None => "X".to_string(),
            };

            Ok(EBirdRecord {
                taxon_concept_id: row.get(0)?,
                scientific_name: row.get(1)?,
                common_name: String::new(), // Not stored
                latitude: row.get(2)?,
                longitude: row.get(3)?,
                observation_date: row.get(4)?,
                sampling_event_id: row.get(5)?,
                group_identifier: None,
                observation_count,
                // These fields were already filtered in pass 1
                all_species_reported: "1".to_string(),
                approved: "1".to_string(),
                category: Some("species".to_string()),
                exotic_code: None,
            })
        })?;

        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }
}
