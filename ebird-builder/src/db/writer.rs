use crate::config::RegionConfig;
use crate::h3::{GridCellPack, H3Grid};
use anyhow::Result;
use rusqlite::{params, Connection};
use std::path::Path;

pub fn write_region_pack(
    output_path: &Path,
    config: &RegionConfig,
    grid_cells: &[GridCellPack],
    total_checklists: usize,
    total_observations: usize,
) -> Result<()> {
    let mut conn = Connection::open(output_path)?;

    // Create schema
    create_schema(&mut conn)?;

    // Insert metadata
    insert_metadata(
        &mut conn,
        config,
        grid_cells,
        total_checklists,
        total_observations,
    )?;

    // Insert grid data
    insert_grid_data(&mut conn, grid_cells, config.h3_resolution)?;

    // Optimize database
    optimize_database(&mut conn)?;

    Ok(())
}

fn create_schema(conn: &mut Connection) -> Result<()> {
    conn.execute_batch(
        "CREATE TABLE region_metadata (
            key TEXT PRIMARY KEY NOT NULL,
            value TEXT NOT NULL
        );

        CREATE INDEX idx_region_metadata_key ON region_metadata(key);

        CREATE TABLE grid_metadata (
            h3_cell BIGINT PRIMARY KEY NOT NULL,
            resolution INTEGER NOT NULL,
            center_lat REAL NOT NULL,
            center_lon REAL NOT NULL,
            total_checklists INTEGER NOT NULL,
            complete_checklists INTEGER NOT NULL,
            total_observations INTEGER NOT NULL,
            date_range_start DATE NOT NULL,
            date_range_end DATE NOT NULL,
            data_quality TEXT DEFAULT 'good',
            total_complete_checklists_sampled INTEGER
        );

        CREATE INDEX idx_grid_resolution ON grid_metadata(resolution);
        CREATE INDEX idx_grid_quality ON grid_metadata(data_quality);
        CREATE INDEX idx_grid_latlon ON grid_metadata(center_lat, center_lon);

        CREATE TABLE species_lookup (
            avibase_id TEXT PRIMARY KEY NOT NULL,
            scientific_name TEXT NOT NULL UNIQUE
        );

        CREATE INDEX idx_species_scientific ON species_lookup(scientific_name);

        CREATE TABLE grid_species (
            h3_cell BIGINT NOT NULL,
            avibase_id TEXT NOT NULL,
            yearly_frequency REAL NOT NULL CHECK(yearly_frequency >= 0.0 AND yearly_frequency <= 1.0),
            total_observations INTEGER NOT NULL CHECK(total_observations > 0),
            total_checklists INTEGER NOT NULL CHECK(total_checklists > 0),
            first_observation DATE NOT NULL,
            last_observation DATE NOT NULL,
            confidence_tier TEXT NOT NULL CHECK(confidence_tier IN ('common', 'uncommon', 'rare', 'vagrant')),
            confidence_boost REAL NOT NULL DEFAULT 1.0 CHECK(confidence_boost >= 1.0 AND confidence_boost <= 2.0),
            monthly_frequency_json TEXT NOT NULL,
            monthly_observations_json TEXT NOT NULL,
            PRIMARY KEY (h3_cell, avibase_id),
            FOREIGN KEY (h3_cell) REFERENCES grid_metadata(h3_cell),
            FOREIGN KEY (avibase_id) REFERENCES species_lookup(avibase_id)
        );

        CREATE INDEX idx_grid_species_freq ON grid_species(h3_cell, yearly_frequency DESC);
        CREATE INDEX idx_grid_species_tier ON grid_species(h3_cell, confidence_tier);
        CREATE INDEX idx_grid_species_avibase ON grid_species(avibase_id);"
    )?;
    Ok(())
}

fn insert_metadata(
    conn: &mut Connection,
    config: &RegionConfig,
    grid_cells: &[GridCellPack],
    total_checklists: usize,
    total_observations: usize,
) -> Result<()> {
    let tx = conn.transaction()?;

    {
        let mut stmt = tx.prepare("INSERT INTO region_metadata (key, value) VALUES (?, ?)")?;

        stmt.execute(params!["version", "2.0"])?;
        stmt.execute(params!["region_id", &config.region_id])?;
        stmt.execute(params!["region_name", &config.region_name])?;
        stmt.execute(params!["region_type", format!("{:?}", config.region_type)])?;
        stmt.execute(params!["h3_resolution", &config.h3_resolution.to_string()])?;
        stmt.execute(params!["generated_at", chrono::Utc::now().to_rfc3339()])?;
        stmt.execute(params![
            "generator",
            format!("birdnetpi-ebird-pack v{}", env!("CARGO_PKG_VERSION"))
        ])?;
        stmt.execute(params![
            "date_range_start",
            &config.date_range.start.to_string()
        ])?;
        stmt.execute(params![
            "date_range_end",
            &config.date_range.end.to_string()
        ])?;
        stmt.execute(params!["total_checklists", &total_checklists.to_string()])?;
        stmt.execute(params![
            "total_observations",
            &total_observations.to_string()
        ])?;
        stmt.execute(params!["total_h3_cells", &grid_cells.len().to_string()])?;
        stmt.execute(params![
            "min_latitude",
            &config.bounding_box.min_latitude.to_string()
        ])?;
        stmt.execute(params![
            "max_latitude",
            &config.bounding_box.max_latitude.to_string()
        ])?;
        stmt.execute(params![
            "min_longitude",
            &config.bounding_box.min_longitude.to_string()
        ])?;
        stmt.execute(params![
            "max_longitude",
            &config.bounding_box.max_longitude.to_string()
        ])?;
        stmt.execute(params![
            "filter_approved_only",
            if config.filters.approved_only {
                "true"
            } else {
                "false"
            }
        ])?;
        stmt.execute(params![
            "filter_complete_checklists_only",
            if config.filters.complete_checklists_only {
                "true"
            } else {
                "false"
            }
        ])?;
        stmt.execute(params![
            "filter_native_species_only",
            if config.filters.native_species_only {
                "true"
            } else {
                "false"
            }
        ])?;
        stmt.execute(params![
            "filter_min_observations",
            &config.filters.min_observations.to_string()
        ])?;
        stmt.execute(params![
            "filter_min_checklists",
            &config.filters.min_checklists.to_string()
        ])?;
        stmt.execute(params![
            "filter_deduplication",
            format!("{:?}", config.filters.deduplication)
        ])?;
    }

    tx.commit()?;
    Ok(())
}

fn insert_grid_data(
    conn: &mut Connection,
    grid_cells: &[GridCellPack],
    resolution: u8,
) -> Result<()> {
    let grid = H3Grid::new(resolution)?;
    let tx = conn.transaction()?;

    // Collect unique species for species_lookup table
    let mut species_lookup: std::collections::HashMap<String, String> =
        std::collections::HashMap::new();
    for cell in grid_cells {
        for sp in &cell.species {
            species_lookup
                .entry(sp.avibase_id.clone())
                .or_insert_with(|| sp.scientific_name.clone());
        }
    }

    // Insert species_lookup
    {
        let mut stmt = tx.prepare(
            "INSERT OR IGNORE INTO species_lookup (avibase_id, scientific_name) VALUES (?, ?)",
        )?;

        for (avibase_id, scientific_name) in species_lookup {
            stmt.execute(params![avibase_id, scientific_name])?;
        }
    }

    // Insert grid_metadata
    {
        let mut stmt = tx.prepare(
            "INSERT INTO grid_metadata (h3_cell, resolution, center_lat, center_lon, \
             total_checklists, complete_checklists, total_observations, \
             date_range_start, date_range_end, data_quality, total_complete_checklists_sampled) \
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )?;

        for cell in grid_cells {
            let h3_i64 = grid.cell_to_i64(cell.h3_cell);

            stmt.execute(params![
                h3_i64,
                cell.resolution,
                cell.center_lat,
                cell.center_lon,
                cell.total_checklists,
                cell.complete_checklists,
                cell.total_observations,
                cell.date_range_start.to_string(),
                cell.date_range_end.to_string(),
                &cell.data_quality,
                cell.total_complete_checklists_sampled,
            ])?;
        }
    }

    // Insert grid_species
    {
        let mut stmt = tx.prepare(
            "INSERT INTO grid_species (h3_cell, avibase_id, \
             yearly_frequency, total_observations, total_checklists, \
             first_observation, last_observation, confidence_tier, confidence_boost, \
             monthly_frequency_json, monthly_observations_json) \
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )?;

        for cell in grid_cells {
            let h3_i64 = grid.cell_to_i64(cell.h3_cell);

            for sp in &cell.species {
                stmt.execute(params![
                    h3_i64,
                    &sp.avibase_id,
                    sp.yearly_frequency,
                    sp.total_observations,
                    sp.total_checklists,
                    sp.first_observation.to_string(),
                    sp.last_observation.to_string(),
                    &sp.confidence_tier,
                    sp.confidence_boost,
                    serde_json::to_string(&sp.monthly_frequency)?,
                    serde_json::to_string(&sp.monthly_observations)?,
                ])?;
            }
        }
    }

    tx.commit()?;
    Ok(())
}

fn optimize_database(conn: &mut Connection) -> Result<()> {
    conn.execute_batch(
        "PRAGMA page_size = 4096;
         PRAGMA journal_mode = DELETE;
         VACUUM;
         PRAGMA optimize;",
    )?;
    Ok(())
}
