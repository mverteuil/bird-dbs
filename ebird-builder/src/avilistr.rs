use anyhow::{Context, Result};
use std::collections::HashMap;
use std::fs::File;
use std::path::Path;

/// Load Avibase ID mappings from avilistr CSV
///
/// The avilistr mapping file provides stable Avibase IDs for bird species,
/// allowing consistent species identification across multiple databases.
///
/// Format: Scientific_name,AvibaseID,English_name_AviList,English_name_Clements_v2024,Species_code_Cornell_Lab,Birds_of_the_World_URL
pub fn load_avibase_mapping(csv_path: &Path) -> Result<HashMap<String, String>> {
    let file = File::open(csv_path)
        .with_context(|| format!("Failed to open avilistr mapping: {:?}", csv_path))?;

    let mut reader = csv::Reader::from_reader(file);
    let mut mapping = HashMap::new();

    for result in reader.records() {
        let record = result.context("Failed to read CSV record")?;

        // CSV format: Scientific_name,AvibaseID,English_name_AviList,...
        if record.len() < 2 {
            continue; // Skip malformed records
        }

        let scientific_name = record[0].to_string();
        let avibase_id = record[1].to_string();

        // Validate avibase_id format
        if !avibase_id.starts_with("avibase-") || avibase_id.len() != 16 {
            log::warn!(
                "Invalid avibase_id format for {}: {}",
                scientific_name,
                avibase_id
            );
            continue;
        }

        mapping.insert(scientific_name, avibase_id);
    }

    log::info!("Loaded {} avibase_id mappings", mapping.len());

    Ok(mapping)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn test_load_avibase_mapping() -> Result<()> {
        // Create test CSV
        let mut temp_file = NamedTempFile::new()?;
        writeln!(
            temp_file,
            "Scientific_name,AvibaseID,English_name_AviList,English_name_Clements_v2024,Species_code_Cornell_Lab,Birds_of_the_World_URL"
        )?;
        writeln!(
            temp_file,
            "Struthio camelus,avibase-2247CB05,Common Ostrich,Common Ostrich,ostric2,https://birdsoftheworld.org/bow/species/ostric2/"
        )?;
        writeln!(
            temp_file,
            "Turdus migratorius,avibase-4A2E6B9F,American Robin,American Robin,amerob,https://birdsoftheworld.org/bow/species/amerob/"
        )?;
        temp_file.flush()?;

        let mapping = load_avibase_mapping(temp_file.path())?;

        assert_eq!(mapping.len(), 2);
        assert_eq!(
            mapping.get("Struthio camelus"),
            Some(&"avibase-2247CB05".to_string())
        );
        assert_eq!(
            mapping.get("Turdus migratorius"),
            Some(&"avibase-4A2E6B9F".to_string())
        );

        Ok(())
    }

    #[test]
    fn test_invalid_avibase_id_format() -> Result<()> {
        let mut temp_file = NamedTempFile::new()?;
        writeln!(temp_file, "Scientific_name,AvibaseID")?;
        writeln!(temp_file, "Invalid Species,invalid-format")?; // Wrong format
        writeln!(temp_file, "Valid Species,avibase-12345678")?; // Valid
        temp_file.flush()?;

        let mapping = load_avibase_mapping(temp_file.path())?;

        // Should only load the valid one
        assert_eq!(mapping.len(), 1);
        assert!(mapping.contains_key("Valid Species"));
        assert!(!mapping.contains_key("Invalid Species"));

        Ok(())
    }
}
