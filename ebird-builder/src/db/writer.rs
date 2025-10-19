use crate::config::RegionConfig;
use crate::h3::{GridCellPack, H3Grid};
use anyhow::Result;
use flate2::write::GzEncoder;
use flate2::Compression;
use rusqlite::{params, Connection};
use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;

pub fn write_region_pack(
    output_path: &Path,
    config: &RegionConfig,
    grid_cells: &[GridCellPack],
    total_checklists: usize,
    total_observations: usize,
) -> Result<()> {
    // Derive temp uncompressed DB path from desired output path
    // (e.g., "foo.db.gz" → "foo.db.tmp")
    let temp_db_path = output_path.with_extension("").with_extension("db.tmp");

    {
        let mut conn = Connection::open(&temp_db_path)?;

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
    } // Connection dropped and database closed

    // Gzip the database file
    gzip_file(&temp_db_path, output_path)?;

    // Remove temporary file
    std::fs::remove_file(&temp_db_path)?;

    Ok(())
}

fn gzip_file(input_path: &Path, output_path: &Path) -> Result<()> {
    let mut input_file = File::open(input_path)?;
    let output_file = File::create(output_path)?;
    let mut encoder = GzEncoder::new(output_file, Compression::default());

    let mut buffer = vec![0; 1024 * 1024]; // 1MB buffer
    loop {
        let bytes_read = input_file.read(&mut buffer)?;
        if bytes_read == 0 {
            break;
        }
        encoder.write_all(&buffer[..bytes_read])?;
    }

    encoder.finish()?;
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
            total_observations INTEGER NOT NULL CHECK(total_observations >= 0),
            total_checklists INTEGER NOT NULL CHECK(total_checklists >= 0),
            first_observation DATE NOT NULL,
            last_observation DATE NOT NULL,
            confidence_tier TEXT NOT NULL CHECK(confidence_tier IN ('common', 'uncommon', 'rare', 'vagrant', 'excluded')),
            confidence_boost REAL NOT NULL DEFAULT 1.0 CHECK(confidence_boost >= 0.8 AND confidence_boost <= 2.0),
            quality_score REAL NOT NULL CHECK(quality_score >= 0.0 AND quality_score <= 1.0),
            high_quality_obs INTEGER NOT NULL CHECK(high_quality_obs >= 0),
            low_quality_obs INTEGER NOT NULL CHECK(low_quality_obs >= 0),
            PRIMARY KEY (h3_cell, avibase_id),
            FOREIGN KEY (h3_cell) REFERENCES grid_metadata(h3_cell),
            FOREIGN KEY (avibase_id) REFERENCES species_lookup(avibase_id)
        );

        CREATE INDEX idx_grid_species_freq ON grid_species(h3_cell, yearly_frequency DESC);
        CREATE INDEX idx_grid_species_tier ON grid_species(h3_cell, confidence_tier);
        CREATE INDEX idx_grid_species_avibase ON grid_species(avibase_id);

        CREATE TABLE grid_species_monthly (
            h3_cell BIGINT NOT NULL,
            avibase_id TEXT NOT NULL,
            month INTEGER NOT NULL CHECK(month >= 1 AND month <= 12),
            observations INTEGER NOT NULL CHECK(observations >= 0),
            checklists INTEGER NOT NULL CHECK(checklists >= 0),
            frequency REAL NOT NULL CHECK(frequency >= 0.0 AND frequency <= 1.0),
            PRIMARY KEY (h3_cell, avibase_id, month),
            FOREIGN KEY (h3_cell, avibase_id) REFERENCES grid_species(h3_cell, avibase_id)
        );

        CREATE INDEX idx_grid_species_monthly_cell ON grid_species_monthly(h3_cell);
        CREATE INDEX idx_grid_species_monthly_month ON grid_species_monthly(month);

        CREATE TABLE grid_species_yearly (
            h3_cell BIGINT NOT NULL,
            avibase_id TEXT NOT NULL,
            year INTEGER NOT NULL CHECK(year >= 1900 AND year <= 2100),
            observations INTEGER NOT NULL CHECK(observations >= 0),
            checklists INTEGER NOT NULL CHECK(checklists >= 0),
            frequency REAL NOT NULL CHECK(frequency >= 0.0 AND frequency <= 1.0),
            PRIMARY KEY (h3_cell, avibase_id, year),
            FOREIGN KEY (h3_cell, avibase_id) REFERENCES grid_species(h3_cell, avibase_id)
        );

        CREATE INDEX idx_grid_species_yearly_cell ON grid_species_yearly(h3_cell);
        CREATE INDEX idx_grid_species_yearly_year ON grid_species_yearly(year);

        CREATE TABLE grid_species_quarterly (
            h3_cell BIGINT NOT NULL,
            avibase_id TEXT NOT NULL,
            quarter INTEGER NOT NULL CHECK(quarter >= 1 AND quarter <= 4),
            observations INTEGER NOT NULL CHECK(observations >= 0),
            checklists INTEGER NOT NULL CHECK(checklists >= 0),
            frequency REAL NOT NULL CHECK(frequency >= 0.0 AND frequency <= 1.0),
            PRIMARY KEY (h3_cell, avibase_id, quarter),
            FOREIGN KEY (h3_cell, avibase_id) REFERENCES grid_species(h3_cell, avibase_id)
        );

        CREATE INDEX idx_grid_species_quarterly_cell ON grid_species_quarterly(h3_cell);
        CREATE INDEX idx_grid_species_quarterly_quarter ON grid_species_quarterly(quarter);"
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
             quality_score, high_quality_obs, low_quality_obs) \
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    sp.quality_score,
                    sp.high_quality_obs,
                    sp.low_quality_obs,
                ])?;
            }
        }
    }

    // Insert grid_species_monthly
    {
        let mut stmt = tx.prepare(
            "INSERT INTO grid_species_monthly (h3_cell, avibase_id, month, observations, checklists, frequency) \
             VALUES (?, ?, ?, ?, ?, ?)",
        )?;

        for cell in grid_cells {
            let h3_i64 = grid.cell_to_i64(cell.h3_cell);

            for sp in &cell.species {
                for monthly in &sp.monthly_data {
                    stmt.execute(params![
                        h3_i64,
                        &sp.avibase_id,
                        monthly.month,
                        monthly.observations,
                        monthly.checklists,
                        monthly.frequency,
                    ])?;
                }
            }
        }
    }

    // Insert grid_species_yearly
    {
        let mut stmt = tx.prepare(
            "INSERT INTO grid_species_yearly (h3_cell, avibase_id, year, observations, checklists, frequency) \
             VALUES (?, ?, ?, ?, ?, ?)",
        )?;

        for cell in grid_cells {
            let h3_i64 = grid.cell_to_i64(cell.h3_cell);

            for sp in &cell.species {
                for yearly in &sp.yearly_data {
                    stmt.execute(params![
                        h3_i64,
                        &sp.avibase_id,
                        yearly.year,
                        yearly.observations,
                        yearly.checklists,
                        yearly.frequency,
                    ])?;
                }
            }
        }
    }

    // Insert grid_species_quarterly
    {
        let mut stmt = tx.prepare(
            "INSERT INTO grid_species_quarterly (h3_cell, avibase_id, quarter, observations, checklists, frequency) \
             VALUES (?, ?, ?, ?, ?, ?)",
        )?;

        for cell in grid_cells {
            let h3_i64 = grid.cell_to_i64(cell.h3_cell);

            for sp in &cell.species {
                for quarterly in &sp.quarterly_data {
                    stmt.execute(params![
                        h3_i64,
                        &sp.avibase_id,
                        quarterly.quarter,
                        quarterly.observations,
                        quarterly.checklists,
                        quarterly.frequency,
                    ])?;
                }
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
