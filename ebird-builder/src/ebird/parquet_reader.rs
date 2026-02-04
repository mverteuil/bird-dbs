use super::EBirdRecord;
use anyhow::Result;
use arrow::array::{Array, StringArray, LargeStringArray};
use arrow::datatypes::DataType;
use arrow::record_batch::RecordBatch;
use log::info;
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use std::fs::File;
use std::path::{Path, PathBuf};

/// Iterator over Parquet files that yields batches of EBirdRecords
pub struct ParquetBatchIterator {
    files: Vec<PathBuf>,
    current_file_idx: usize,
    current_reader: Option<parquet::arrow::arrow_reader::ParquetRecordBatchReader>,
    batch_size: usize,
}

impl ParquetBatchIterator {
    /// Create a new iterator from a directory containing Parquet files
    pub fn from_directory(dir: &Path, batch_size: usize) -> Result<Self> {
        let mut files: Vec<PathBuf> = std::fs::read_dir(dir)?
            .filter_map(|entry| {
                let entry = entry.ok()?;
                let path = entry.path();

                // Skip macOS resource fork files (._*)
                if let Some(filename) = path.file_name() {
                    if filename.to_string_lossy().starts_with("._") {
                        return None;
                    }
                }

                if path.extension()? == "parquet" {
                    Some(path)
                } else {
                    None
                }
            })
            .collect();

        // Sort for consistent ordering
        files.sort();

        info!("Found {} Parquet files in {:?}", files.len(), dir);

        Ok(Self {
            files,
            current_file_idx: 0,
            current_reader: None,
            batch_size,
        })
    }

    /// Open the next file and create a reader
    fn open_next_file(&mut self) -> Result<bool> {
        if self.current_file_idx >= self.files.len() {
            return Ok(false);  // No more files
        }

        let file_path = &self.files[self.current_file_idx];
        info!("Opening Parquet file: {:?}", file_path);

        let file = File::open(file_path)?;
        let builder = ParquetRecordBatchReaderBuilder::try_new(file)?;
        let reader = builder.with_batch_size(self.batch_size).build()?;

        self.current_reader = Some(reader);
        self.current_file_idx += 1;

        Ok(true)
    }

    /// Convert a RecordBatch to a Vec<EBirdRecord>
    fn convert_batch(&self, batch: RecordBatch) -> Result<Vec<EBirdRecord>> {
        let schema = batch.schema();
        let num_rows = batch.num_rows();

        // Helper to get string value from any string column type
        let get_string_value = |col_idx: usize, row_idx: usize| -> Result<&str> {
            let column = batch.column(col_idx);
            match column.data_type() {
                DataType::Utf8 => {
                    let arr = column.as_any().downcast_ref::<StringArray>()
                        .ok_or_else(|| anyhow::anyhow!("Failed to downcast Utf8 column"))?;
                    Ok(arr.value(row_idx))
                }
                DataType::LargeUtf8 => {
                    let arr = column.as_any().downcast_ref::<LargeStringArray>()
                        .ok_or_else(|| anyhow::anyhow!("Failed to downcast LargeUtf8 column"))?;
                    Ok(arr.value(row_idx))
                }
                _ => Err(anyhow::anyhow!("Column is not a string type: {:?}", column.data_type()))
            }
        };

        // Get column indices
        let taxon_id_idx = schema.index_of("TAXON CONCEPT ID")?;
        let scientific_name_idx = schema.index_of("SCIENTIFIC NAME")?;
        let common_name_idx = schema.index_of("COMMON NAME")?;
        let obs_count_idx = schema.index_of("OBSERVATION COUNT")?;
        let latitude_idx = schema.index_of("LATITUDE")?;
        let longitude_idx = schema.index_of("LONGITUDE")?;
        let obs_date_idx = schema.index_of("OBSERVATION DATE")?;
        let sampling_event_idx = schema.index_of("SAMPLING EVENT IDENTIFIER")?;
        let group_id_idx = schema.index_of("GROUP IDENTIFIER")?;
        let all_species_idx = schema.index_of("ALL SPECIES REPORTED")?;
        let approved_idx = schema.index_of("APPROVED")?;
        let category_idx = schema.index_of("CATEGORY")?;
        let exotic_code_idx = schema.index_of("EXOTIC CODE")?;

        let mut records = Vec::with_capacity(num_rows);

        for i in 0..num_rows {
            // Parse latitude/longitude from strings
            let lat = get_string_value(latitude_idx, i)?
                .parse::<f64>()
                .unwrap_or(0.0);
            let lon = get_string_value(longitude_idx, i)?
                .parse::<f64>()
                .unwrap_or(0.0);

            // Handle optional fields
            let group_id_val = get_string_value(group_id_idx, i)?;
            let category_val = get_string_value(category_idx, i)?;
            let exotic_val = get_string_value(exotic_code_idx, i)?;

            records.push(EBirdRecord {
                taxon_concept_id: get_string_value(taxon_id_idx, i)?.to_string(),
                scientific_name: get_string_value(scientific_name_idx, i)?.to_string(),
                common_name: get_string_value(common_name_idx, i)?.to_string(),
                observation_count: get_string_value(obs_count_idx, i)?.to_string(),
                latitude: lat,
                longitude: lon,
                observation_date: get_string_value(obs_date_idx, i)?.to_string(),
                sampling_event_id: get_string_value(sampling_event_idx, i)?.to_string(),
                group_identifier: if group_id_val.is_empty() {
                    None
                } else {
                    Some(group_id_val.to_string())
                },
                all_species_reported: get_string_value(all_species_idx, i)?.to_string(),
                approved: get_string_value(approved_idx, i)?.to_string(),
                category: if category_val.is_empty() {
                    None
                } else {
                    Some(category_val.to_string())
                },
                exotic_code: if exotic_val.is_empty() {
                    None
                } else {
                    Some(exotic_val.to_string())
                },
            });
        }

        Ok(records)
    }
}

impl Iterator for ParquetBatchIterator {
    type Item = Result<Vec<EBirdRecord>>;

    fn next(&mut self) -> Option<Self::Item> {
        loop {
            // Try to read from current reader
            if let Some(ref mut reader) = self.current_reader {
                match reader.next() {
                    Some(Ok(batch)) => {
                        // Convert batch and return
                        return Some(self.convert_batch(batch));
                    }
                    Some(Err(e)) => {
                        // Error reading batch
                        return Some(Err(e.into()));
                    }
                    None => {
                        // Current file exhausted, try next file
                        self.current_reader = None;
                    }
                }
            }

            // No current reader, open next file
            match self.open_next_file() {
                Ok(true) => {
                    // File opened successfully, loop to read from it
                    continue;
                }
                Ok(false) => {
                    // No more files
                    return None;
                }
                Err(e) => {
                    // Error opening file
                    return Some(Err(e));
                }
            }
        }
    }
}
