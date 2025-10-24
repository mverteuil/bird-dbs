/// Global taxon concept ID registry for consistent species identification across all packs
///
/// This module provides functionality to build and use a persistent registry that maps
/// normalized species names to their preferred (species-level) taxon_concept_ids.
/// The registry is built once per eBird data release and reused across all pack builds.

use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::File;
use std::path::Path;

/// Information about a species' canonical taxon concept ID
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpeciesTaxonInfo {
    /// The preferred taxon_concept_id (avibase format)
    pub taxon_concept_id: String,
    /// Whether this ID came from a pure species-level record
    pub is_species_level: bool,
    /// Total number of records seen for this species across all variants
    #[serde(default)]
    pub total_records_seen: u64,
}

/// Registry mapping normalized species names to their canonical taxon IDs
#[derive(Debug, Serialize, Deserialize)]
pub struct TaxonRegistry {
    /// eBird data release version (e.g., "2025-08")
    pub ebird_release: String,
    /// Timestamp when registry was generated
    pub generated_at: String,
    /// Total number of unique species in registry
    pub species_count: usize,
    /// Map from normalized species name to taxon info
    pub registry: HashMap<String, SpeciesTaxonInfo>,
}

impl TaxonRegistry {
    /// Create a new empty registry
    pub fn new(ebird_release: String) -> Self {
        Self {
            ebird_release,
            generated_at: chrono::Utc::now().to_rfc3339(),
            species_count: 0,
            registry: HashMap::new(),
        }
    }

    /// Update registry with a record, preferring species-level taxon IDs
    pub fn update_from_record(
        &mut self,
        normalized_name: &str,
        taxon_concept_id: &str,
        is_species_level: bool,
    ) {
        self.registry
            .entry(normalized_name.to_string())
            .and_modify(|info| {
                info.total_records_seen += 1;
                // Only upgrade from non-species to species-level taxon IDs
                if !info.is_species_level && is_species_level {
                    log::info!(
                        "Global taxon ID upgrade for '{}': '{}' (non-species) → '{}' (species-level)",
                        normalized_name,
                        info.taxon_concept_id,
                        taxon_concept_id
                    );
                    info.taxon_concept_id = taxon_concept_id.to_string();
                    info.is_species_level = true;
                }
            })
            .or_insert_with(|| SpeciesTaxonInfo {
                taxon_concept_id: taxon_concept_id.to_string(),
                is_species_level,
                total_records_seen: 1,
            });
    }

    /// Finalize the registry (update species count)
    pub fn finalize(&mut self) {
        self.species_count = self.registry.len();
    }

    /// Get canonical taxon ID for a normalized species name
    pub fn get_canonical_id(&self, normalized_name: &str) -> Option<&str> {
        self.registry
            .get(normalized_name)
            .map(|info| info.taxon_concept_id.as_str())
    }

    /// Load registry from JSON file
    pub fn load_from_file(path: &Path) -> Result<Self> {
        let file = File::open(path)?;
        let registry: TaxonRegistry = serde_json::from_reader(file)?;
        log::info!(
            "Loaded taxon registry: {} species from eBird release {}",
            registry.species_count,
            registry.ebird_release
        );
        Ok(registry)
    }

    /// Save registry to JSON file
    pub fn save_to_file(&self, path: &Path) -> Result<()> {
        let file = File::create(path)?;
        serde_json::to_writer_pretty(file, self)?;
        log::info!("Saved taxon registry: {} species to {:?}", self.species_count, path);
        Ok(())
    }
}

/// Normalize a species name by extracting the primary species from variants
///
/// Handles multiple eBird notation patterns:
/// 1. Parenthetical descriptions: "Anas platyrhynchos (Mallard)" → "Anas platyrhynchos"
/// 2. Slash notation: "Dryobates pubescens/villosus" → "Dryobates pubescens"
/// 3. Hybrids: "Anas platyrhynchos x rubripes" → "Anas platyrhynchos"
/// 4. Spuh indicators: "Alca/Pinguinus sp." → "Alca sp." (preserves " sp.")
///
/// Examples:
/// - "Dryobates pubescens/villosus" → "Dryobates pubescens"
/// - "Anas platyrhynchos (Mallard)" → "Anas platyrhynchos"
/// - "Cairina moschata x Anas platyrhynchos" → "Cairina moschata"
/// - "Alca/Pinguinus sp." → "Alca sp."
pub fn normalize_species_name(name: &str) -> String {
    let mut result = name.to_string();

    // Step 1: Remove parenthetical descriptions first
    // e.g., "Anas platyrhynchos (Mallard)" → "Anas platyrhynchos"
    if let Some(paren_pos) = result.find('(') {
        result = result[..paren_pos].trim().to_string();
    }

    // Step 2: Check for spuh indicator in the current result
    // We'll preserve this after processing slashes/hybrids
    // Handle both " sp." (singular) and " spp." (plural)
    let has_spuh = result.ends_with(" sp.") || result.ends_with(" spp.");

    // Step 3: Handle slash notation (e.g., "Dryobates pubescens/villosus")
    // Example: "Alca/Pinguinus sp." → "Alca" (but we'll add " sp." back later)
    if let Some(slash_pos) = result.find('/') {
        // Extract everything before the slash and trim any trailing whitespace
        result = result[..slash_pos].trim().to_string();
    }

    // Step 4: Handle hybrids (e.g., "Anas platyrhynchos x rubripes")
    // Example: "Genus1 x Genus2 sp." → "Genus1" (but we'll add " sp." back later)
    if let Some(hybrid_pos) = result.find(" x ") {
        // Extract everything before the hybrid marker and trim any trailing whitespace
        result = result[..hybrid_pos].trim().to_string();
    }

    // Step 5: Restore spuh indicator if it was present in the original
    // This ensures "Alca/Pinguinus sp." → "Alca sp." not just "Alca"
    // Always use singular form " sp." (even if input was " spp.")
    if has_spuh && !result.ends_with(" sp.") && !result.ends_with(" spp.") {
        result.push_str(" sp.");
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_species_name() {
        assert_eq!(
            normalize_species_name("Dryobates pubescens/villosus"),
            "Dryobates pubescens"
        );
        assert_eq!(
            normalize_species_name("Anas platyrhynchos"),
            "Anas platyrhynchos"
        );
        assert_eq!(normalize_species_name("Larus sp."), "Larus sp.");
    }

    #[test]
    fn test_registry_update_prefers_species_level() {
        let mut registry = TaxonRegistry::new("2025-08".to_string());

        // Add slash notation first
        registry.update_from_record("Dryobates pubescens", "avibase-SLASH001", false);
        assert_eq!(
            registry.get_canonical_id("Dryobates pubescens"),
            Some("avibase-SLASH001")
        );

        // Add species-level record - should upgrade
        registry.update_from_record("Dryobates pubescens", "avibase-SPECIES01", true);
        assert_eq!(
            registry.get_canonical_id("Dryobates pubescens"),
            Some("avibase-SPECIES01")
        );

        // Verify record count incremented
        let info = registry.registry.get("Dryobates pubescens").unwrap();
        assert_eq!(info.total_records_seen, 2);
    }

    #[test]
    fn test_registry_serialization() {
        let mut registry = TaxonRegistry::new("2025-08".to_string());
        registry.update_from_record("Anas platyrhynchos", "avibase-12345678", true);
        registry.finalize();

        // Serialize to JSON
        let json = serde_json::to_string_pretty(&registry).unwrap();
        assert!(json.contains("Anas platyrhynchos"));
        assert!(json.contains("avibase-12345678"));

        // Deserialize back
        let deserialized: TaxonRegistry = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.species_count, 1);
        assert_eq!(
            deserialized.get_canonical_id("Anas platyrhynchos"),
            Some("avibase-12345678")
        );
    }
}
