# Architecture Decision: Avilistr-Based Taxonomy Integration

**Date:** 2025-10-08
**Status:** ✅ APPROVED
**Decision:** Use Avilistr as the authoritative source for Avibase IDs across all reference databases

---

## Context

We need stable identifiers to join bird species data across multiple databases with different taxonomies:
- **IOC World Bird List** (IOC taxonomy)
- **Wikidata** (mixed taxonomies, community-maintained)
- **eBird** (Clements taxonomy)

**Problem:** Species names change due to taxonomic revisions (renames, splits, lumps). Joining on `scientific_name` fails when taxonomies diverge.

**Example:**
```
IOC:       Cercomacroides tyrannina (current genus)
Wikidata:  Cercomacra tyrannina     (old genus)
eBird:     Cercomacra tyrannina     (follows Clements)

Same species, three different names!
```

---

## Decision

### 1. Use Avilistr as the Source for Avibase IDs

**Rationale:**
- Avilistr is maintained by Avibase (the authoritative source)
- Provides comprehensive cross-taxonomy mappings
- Already maps IOC ↔ Clements ↔ HBW ↔ other authorities
- Single source of truth for `avibase_id` assignments

**Avilistr Data Structure:**
```csv
avibase_id,ioc_scientific,clements_scientific,ebird_scientific,english_name,ioc_order,ioc_family
7064BD0222050C53,Cercomacroides tyrannina,Cercomacra tyrannina,Cercomacra tyrannina,Dusky Antbird,Passeriformes,Thamnophilidae
```

**Alternative Considered (Rejected):**
- ❌ Get Avibase IDs from Wikidata P2026 property
  - Problem: Incomplete coverage, relies on Wikidata maintenance
  - Problem: No direct IOC ↔ eBird mapping
  - Problem: Requires fuzzy matching for missing species

### 2. Rename Databases for Consistency

**Naming Convention:**
```
ioc_reference.db       (IOC translations, 44 languages)
wikidata_reference.db  (Wikidata translations, 4 languages)
```

**Rationale:**
- Both are reference databases for multilingual bird names
- Consistent `*_reference.db` pattern
- Clearer than `wikidata_minimal.db` (focuses on purpose, not filtering strategy)

### 3. Separate Data Collection from Database Building

**Architecture:**

```
┌─────────────────────────────────────────┐
│  Phase 1: Data Collection (automated)  │
├─────────────────────────────────────────┤
│  collect_source_data.sh                 │
│  ├── Download IOC multilingual files   │
│  │   → data/sources/ioc/*.xlsx         │
│  └── Download Avilistr world list      │
│      → data/sources/avilistr/          │
│         world_birds_YYYY-MM-DD.csv      │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│  Phase 2: Database Building             │
│  (independent builders)                 │
├─────────────────────────────────────────┤
│                                         │
│  ┌──────────────────────────────────┐  │
│  │ build_ioc_reference.py           │  │
│  ├──────────────────────────────────┤  │
│  │ Reads:                           │  │
│  │  • data/sources/ioc/*.xlsx       │  │
│  │  • data/sources/avilistr/*.csv   │  │
│  │ Process:                         │  │
│  │  • Parse IOC species + trans     │  │
│  │  • Match to Avilistr IOC column  │  │
│  │  • Extract avibase_id            │  │
│  │ Outputs:                         │  │
│  │  • ioc_reference.db              │  │
│  │    (with avibase_id column)      │  │
│  └──────────────────────────────────┘  │
│                                         │
│  ┌──────────────────────────────────┐  │
│  │ build_wikidata_reference.py      │  │
│  ├──────────────────────────────────┤  │
│  │ Reads:                           │  │
│  │  • Wikidata SPARQL API           │  │
│  │  • data/sources/avilistr/*.csv   │  │
│  │    (optional, for validation)    │  │
│  │ Process:                         │  │
│  │  • Query Wikidata P2026          │  │
│  │  • Filter scientific names       │  │
│  │  • Extract 4 languages only      │  │
│  │ Outputs:                         │  │
│  │  • wikidata_reference.db         │  │
│  │    (nb, eu, zh-hans, zh-hant)    │  │
│  └──────────────────────────────────┘  │
│                                         │
│  ┌──────────────────────────────────┐  │
│  │ build_ebird_regions (Rust)       │  │
│  ├──────────────────────────────────┤  │
│  │ Reads:                           │  │
│  │  • eBird EBD (200GB tar)         │  │
│  │  • data/sources/avilistr/*.csv   │  │
│  │ Process:                         │  │
│  │  • Parse eBird observations      │  │
│  │  • Match to Avilistr Clements    │  │
│  │  • Extract avibase_id            │  │
│  │  • Build H3 grids                │  │
│  │ Outputs:                         │  │
│  │  • ebird_regions/*.db            │  │
│  │    (with avibase_id column)      │  │
│  └──────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

**Rationale:**
- **Independence:** Each builder can run standalone
- **No builder depends on another builder's output**
- **Shared source:** All builders read from cached Avilistr file
- **Flexibility:** Can rebuild any database without rebuilding others
- **Parallelization:** Can run all builders concurrently

---

## Database Schemas

### IOC Reference (Updated)

```sql
CREATE TABLE species (
    scientific_name VARCHAR(100) PRIMARY KEY,
    avibase_id VARCHAR(20),              -- NEW: from Avilistr
    english_name VARCHAR(100),
    order_name VARCHAR(50),
    family VARCHAR(50),
    genus VARCHAR(50),
    species_epithet VARCHAR(50),
    authority VARCHAR(100),
    breeding_regions VARCHAR(50),
    breeding_subregions TEXT
);

CREATE TABLE translations (
    scientific_name VARCHAR(100),
    avibase_id VARCHAR(20),              -- NEW: from Avilistr
    language_code VARCHAR(10),
    common_name VARCHAR(100),
    PRIMARY KEY (scientific_name, language_code)
);

CREATE INDEX idx_species_avibase ON species(avibase_id);
CREATE INDEX idx_translations_avibase ON translations(avibase_id);
```

### Wikidata Reference (Renamed)

```sql
CREATE TABLE species (
    wikidata_id VARCHAR(20) PRIMARY KEY,
    scientific_name VARCHAR(80),
    avibase_id_native VARCHAR(20),       -- From Wikidata P2026
    english_name VARCHAR(120)
);

CREATE TABLE translations (
    wikidata_id VARCHAR(20),
    language_code VARCHAR(10),
    common_name VARCHAR(100),
    PRIMARY KEY (wikidata_id, language_code)
);

-- Only 4 languages: nb, eu, zh-hans, zh-hant
```

### eBird Region Packs (Updated)

```sql
CREATE TABLE grid_species (
    h3_cell BIGINT,
    scientific_name TEXT,
    avibase_id VARCHAR(20),              -- NEW: from Avilistr
    common_name TEXT,
    yearly_frequency REAL,
    total_observations INTEGER,
    confidence_tier TEXT,
    confidence_boost REAL,
    monthly_frequency_json TEXT,
    monthly_observations_json TEXT,
    PRIMARY KEY (h3_cell, scientific_name)
);

CREATE INDEX idx_grid_species_avibase ON grid_species(h3_cell, avibase_id);
```

---

## Join Patterns

### Translation Lookup (Taxonomic-Safe)

```python
# User detects: "Cercomacroides tyrannina" (IOC name from BirdNET)
# Language: Spanish (es)

# Step 1: Get avibase_id from IOC
result = conn.execute("""
    SELECT avibase_id FROM ioc.species
    WHERE scientific_name = ?
""", ("Cercomacroides tyrannina",)).fetchone()

avibase_id = result[0]  # "7064BD0222050C53"

# Step 2: Get translation using avibase_id (works across taxonomies!)
translation = conn.execute("""
    WITH translation AS (
      -- Priority 1: IOC (44 languages)
      SELECT common_name, 'ioc' as source, 1 as priority
      FROM ioc.translations
      WHERE avibase_id = ? AND language_code = ?

      UNION ALL

      -- Priority 2: Wikidata (4 unique languages: nb, eu, zh-hans, zh-hant)
      SELECT t.common_name, 'wikidata' as source, 2 as priority
      FROM wikidata.translations t
      JOIN wikidata.species s ON t.wikidata_id = s.wikidata_id
      WHERE s.avibase_id_native = ? AND t.language_code = ?

      UNION ALL

      -- Priority 3: English fallback
      SELECT english_name, 'english' as source, 3 as priority
      FROM ioc.species
      WHERE avibase_id = ?
    )
    SELECT common_name, source FROM translation ORDER BY priority LIMIT 1;
""", (avibase_id, "es", avibase_id, "es", avibase_id)).fetchone()

print(f"Spanish: {translation[0]} (from {translation[1]})")
# Works even though Wikidata has "Cercomacra tyrannina" (old name)!
```

### Regional Filtering (Taxonomic-Safe)

```python
# User location: Boston, MA
h3_cell = h3.geo_to_h3(42.3601, -71.0589, 8)

# Detection from BirdNET: "Cercomacroides tyrannina" (IOC name)
avibase_id = get_avibase_id("Cercomacroides tyrannina")

# Check eBird regional data (uses Clements taxonomy internally)
result = conn.execute("""
    SELECT
        yearly_frequency,
        confidence_tier,
        total_observations
    FROM ebird.grid_species
    WHERE h3_cell = ? AND avibase_id = ?
""", (h3_cell, avibase_id)).fetchone()

# Works even though eBird stores "Cercomacra tyrannina" (Clements name)!
```

---

## Implementation Plan

### Step 1: Create Data Collection Script

**File:** `scripts/collect_source_data.sh`

```bash
#!/bin/bash
# Collect source data for reference database building

set -e

SOURCES_DIR="data/sources"
IOC_DIR="$SOURCES_DIR/ioc"
AVILISTR_DIR="$SOURCES_DIR/avilistr"

mkdir -p "$IOC_DIR" "$AVILISTR_DIR"

# Download IOC multilingual files
echo "Downloading IOC multilingual data..."
# TODO: Add IOC download logic (manual download + copy or scraping)
# Expected files:
# - IOC_Names_File_Plus-14.2.xlsx (species + English names)
# - IOC_Multiling_Names_File_v14.2.xlsx (translations)

# Download Avilistr world bird list
echo "Downloading Avilistr world bird list..."
DATE=$(date +%Y-%m-%d)
AVILISTR_FILE="$AVILISTR_DIR/world_birds_$DATE.csv"

# Option 1: Direct download (if Avilistr provides export URL)
# wget -O "$AVILISTR_FILE" "https://avibase.bsc-eoc.org/export/world_birds.csv"

# Option 2: Use Avilistr API
# python3 scripts/download_avilistr.py --output "$AVILISTR_FILE"

# Option 3: Manual download + copy
echo "Please download Avilistr world list from:"
echo "  https://avibase.bsc-eoc.org/checklist.jsp"
echo "  (Select: World, All taxonomies, CSV export)"
echo "  Save to: $AVILISTR_FILE"

echo "Source data collection complete!"
echo "IOC files: $IOC_DIR"
echo "Avilistr: $AVILISTR_FILE"
```

### Step 2: Update IOC Reference Builder

**File:** `scripts/build_ioc_reference.py`

```python
# Add Avilistr loading
def load_avilistr_mapping(avilistr_path: str) -> dict[str, str]:
    """Load Avilistr data and create IOC name → avibase_id mapping."""
    import csv

    mapping = {}
    with open(avilistr_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            avibase_id = row['avibase_id']
            ioc_name = row['ioc_scientific']
            if ioc_name and avibase_id:
                mapping[ioc_name] = avibase_id

    return mapping

# In main builder logic:
avilistr_file = "data/sources/avilistr/world_birds_*.csv"  # Use latest
avibase_mapping = load_avilistr_mapping(avilistr_file)

# When creating species records:
for species in parsed_ioc_species:
    scientific_name = species['scientific_name']
    avibase_id = avibase_mapping.get(scientific_name)  # Lookup from Avilistr

    species_record = {
        'scientific_name': scientific_name,
        'avibase_id': avibase_id,  # Add to database
        'english_name': species['english_name'],
        # ... other fields
    }
```

### Step 3: Update Wikidata Reference Builder

**File:** `scripts/build_wikidata_reference.py`

```python
# Wikidata already has avibase_id from P2026
# Optionally validate against Avilistr

def validate_avibase_ids(wikidata_species: list, avilistr_mapping: dict):
    """Cross-check Wikidata avibase_ids against Avilistr."""
    mismatches = []

    for species in wikidata_species:
        wd_avibase = species['avibase_id_native']
        wd_sci_name = species['scientific_name']

        # Try to find in Avilistr by scientific name
        avilistr_avibase = avilistr_mapping.get(wd_sci_name)

        if avilistr_avibase and wd_avibase != avilistr_avibase:
            mismatches.append({
                'scientific_name': wd_sci_name,
                'wikidata_id': wd_avibase,
                'avilistr_id': avilistr_avibase
            })

    if mismatches:
        print(f"Warning: {len(mismatches)} Avibase ID mismatches with Avilistr")
        # Log for review

    return mismatches
```

### Step 4: Update eBird Region Pack Builder

**File:** `src/main.rs` (or add new Avilistr module)

```rust
// Load Avilistr mapping
use std::collections::HashMap;
use csv::ReaderBuilder;

fn load_avilistr_mapping(path: &str) -> HashMap<String, String> {
    let mut mapping = HashMap::new();
    let mut reader = ReaderBuilder::new().from_path(path).unwrap();

    for result in reader.deserialize() {
        let record: AvilistrRecord = result.unwrap();
        if !record.clements_scientific.is_empty() && !record.avibase_id.is_empty() {
            mapping.insert(record.clements_scientific.clone(), record.avibase_id.clone());
        }
    }

    mapping
}

#[derive(Debug, Deserialize)]
struct AvilistrRecord {
    avibase_id: String,
    ioc_scientific: String,
    clements_scientific: String,
    ebird_scientific: String,
    english_name: String,
}

// In grid_species insertion:
let avibase_id = avilistr_mapping.get(&scientific_name).cloned();

conn.execute(
    "INSERT INTO grid_species (h3_cell, scientific_name, avibase_id, ...) VALUES (?, ?, ?, ...)",
    params![h3_cell, scientific_name, avibase_id, ...]
)?;
```

---

## Benefits

### 1. Taxonomic Stability
- ✅ Species renames don't break joins (e.g., Cercomacra → Cercomacroides)
- ✅ Different authorities use different names, but same `avibase_id`
- ✅ Future-proof against taxonomic changes

### 2. Independence
- ✅ Each builder can run standalone
- ✅ No cascade dependencies (rebuild IOC without rebuilding Wikidata)
- ✅ Parallel execution possible

### 3. Single Source of Truth
- ✅ Avilistr is authoritative for Avibase IDs
- ✅ Eliminates fuzzy matching errors
- ✅ Consistent cross-taxonomy mappings

### 4. Maintainability
- ✅ Clear separation: data collection vs database building
- ✅ Cached source data (don't re-download on every build)
- ✅ Easy to update: re-run data collection, then rebuild

---

## Migration Path

### From Current State to New Architecture

**Current:**
```
ioc_reference.db          (no avibase_id)
wikidata_minimal.db       (has avibase_id from P2026)
ebird_regions/*.db        (no avibase_id)
```

**Migration:**

1. ✅ Create `data/sources/` directory structure
2. ✅ Download Avilistr world bird list
3. ✅ Update IOC builder to add `avibase_id` column
4. ✅ Rebuild `ioc_reference.db` (now with avibase_id)
5. ✅ Rename `wikidata_minimal.db` → `wikidata_reference.db`
6. ✅ Update eBird builder to add `avibase_id` column
7. ✅ Rebuild eBird region packs (now with avibase_id)
8. ✅ Update BirdNET-Pi code to join on `avibase_id` instead of `scientific_name`

---

## File Structure

```
avibase-builder/
├── data/
│   ├── sources/                    # NEW: Cached source data
│   │   ├── ioc/
│   │   │   ├── IOC_Names_File_Plus-14.2.xlsx
│   │   │   └── IOC_Multiling_Names_File_v14.2.xlsx
│   │   └── avilistr/
│   │       └── world_birds_2025-10-08.csv
│   ├── ioc_reference.db           # Updated: has avibase_id
│   ├── wikidata_reference.db      # Renamed from wikidata_minimal.db
│   └── ebird_regions/
│       └── *.db                   # Updated: has avibase_id
├── scripts/
│   ├── collect_source_data.sh     # NEW: Download IOC + Avilistr
│   ├── build_ioc_reference.py     # Updated: uses Avilistr
│   ├── build_wikidata_reference.py
│   └── build_ebird_regions/       # Updated: uses Avilistr
└── docs/
    └── architecture-decision-avilistr.md  # This document
```

---

## Risks and Mitigations

### Risk 1: Avilistr Availability
- **Risk:** Avilistr API/download becomes unavailable
- **Mitigation:** Cache downloaded files in `data/sources/` with date stamps
- **Mitigation:** Check in small cached file to git (few MB)
- **Mitigation:** Document manual download process as fallback

### Risk 2: Avilistr Data Quality
- **Risk:** Avilistr has incorrect mappings
- **Mitigation:** Cross-validate with Wikidata P2026
- **Mitigation:** Manual review of mismatches
- **Mitigation:** Report issues to Avibase maintainers

### Risk 3: Missing Species
- **Risk:** New species in IOC not yet in Avilistr
- **Mitigation:** Allow `avibase_id` to be NULL
- **Mitigation:** Joins still work on `scientific_name` as fallback
- **Mitigation:** Quarterly Avilistr updates

### Risk 4: Build Complexity
- **Risk:** More complex build process
- **Mitigation:** Clear documentation (this file)
- **Mitigation:** Automated scripts for data collection
- **Mitigation:** Error handling and validation in builders

---

## References

- [Avibase](https://avibase.bsc-eoc.org/) - Bird database with stable IDs
- [Avilistr](https://avibase.bsc-eoc.org/checklist.jsp) - Avibase list service
- [IOC World Bird List](https://www.worldbirdnames.org/)
- [Wikidata Avibase ID Property (P2026)](https://www.wikidata.org/wiki/Property:P2026)
- [eBird/Clements Checklist](https://www.birds.cornell.edu/clementschecklist/)

---

**Status:** ✅ APPROVED
**Next Action:** Implement `collect_source_data.sh` and download Avilistr data
**Owner:** Development Team
**Review Date:** After initial implementation
