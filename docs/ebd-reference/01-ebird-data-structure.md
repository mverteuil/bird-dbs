# eBird Basic Dataset (EBD) Structure

## Overview

The eBird Basic Dataset is the world's largest biodiversity database for bird observations, managed by the Cornell Lab of Ornithology. Data is released monthly as compressed archives.

## Files in This Directory

```
ebird/
├── ebd_relAug-2025.tar (201GB)           # Full global dataset
├── ebd_sampling_relAug-2025.tar (7.2GB)  # Sampling event metadata
└── CLAUDE.md                             # Working guide
```

## Archive Contents

Each tarball contains:

### Main Data File
- `ebd_relAug-2025.txt.gz` - Tab-delimited, gzipped observation records
- `ebd_sampling_relAug-2025.txt.gz` - Checklist metadata (no species info)

### Reference Tables
- `BCRCodes.txt` - Bird Conservation Region codes
- `IBACodes.txt` - Important Bird Area codes
- `BirdLifeKBACodes.txt` - Key Biodiversity Area codes
- `USFWSCodes.txt` - US Fish & Wildlife Service area codes
- `Protocols.txt` - Survey methodology descriptions

### Documentation
- `eBird_Basic_Dataset_Metadata_v1.16.pdf` - Complete field definitions
- `recommended_citation.txt` - Citation requirements
- `terms_of_use.txt` - Usage terms

## Data Format

### File Characteristics
- **Encoding**: UTF-8 (mandatory for international data)
- **Delimiter**: Tab (`\t`)
- **Header**: First line contains column names
- **Structure**: One row per observation (species + checklist)
- **Compression**: Gzip (within tarball)

### Record Structure

The data follows a hierarchical model:

```
LOCATION (unique lat/lon, locality name)
  └─ CHECKLIST/SUBMISSION (one birding session)
      └─ OBSERVATION (one species sighting)
          └─ Metadata (count, breeding code, etc.)
```

## Key Fields (~50 total)

### Taxonomic Identification
| Field | Type | Description |
|-------|------|-------------|
| `SCIENTIFIC NAME` | string | Primary species identifier |
| `COMMON NAME` | string | English common name |
| `TAXON CONCEPT ID` | string | Stable ID across taxonomy changes (from Avibase) |
| `CATEGORY` | string | species, hybrid, slash, domestic, etc. |
| `TAXONOMIC ORDER` | int | Sort order in eBird/Clements taxonomy |
| `SUBSPECIES SCIENTIFIC NAME` | string | Subspecies/form if reported |
| `SUBSPECIES COMMON NAME` | string | Subspecies common name if reported |

### Observation Details
| Field | Type | Description |
|-------|------|-------------|
| `OBSERVATION COUNT` | int\|X | Number of individuals ('X' = presence only) |
| `OBSERVATION DATE` | date | YYYY-MM-DD format |
| `BREEDING CODE` | string | Breeding behavior code (see Appendix 1 in PDF) |
| `BREEDING CATEGORY` | string | C1-C4 (Observed, Possible, Probable, Confirmed) |
| `BEHAVIOR CODE` | string | Observed behavior code |
| `AGE/SEX` | string | Age/sex combination counts |
| `EXOTIC CODE` | string | N=Naturalized, P=Provisional, X=Escapee, null=native |

### Checklist/Sampling Event
| Field | Type | Description |
|-------|------|-------------|
| `SAMPLING EVENT IDENTIFIER` | string | Unique checklist ID (starts with 'S') |
| `OBSERVATION TYPE` | string | Traveling, Stationary, Incidental, Historical, etc. |
| `PROTOCOL NAME` | string | Specific survey protocol name |
| `PROTOCOL CODE` | string | Protocol code (P20-P89) |
| `DURATION MINUTES` | int | Survey duration |
| `EFFORT DISTANCE KM` | float | Distance traveled (Traveling protocol) |
| `EFFORT AREA HA` | float | Area covered (Area protocol) |
| `NUMBER OBSERVERS` | int | Count of observers |
| `ALL SPECIES REPORTED` | bool | **Critical**: 1=complete list, 0=partial |
| `TIME OBSERVATIONS STARTED` | time | HH:MM (24-hour) |
| `GROUP IDENTIFIER` | string | Links shared checklists (deduplicate!) |

### Location Data
| Field | Type | Description |
|-------|------|-------------|
| `LATITUDE` | float | Decimal degrees |
| `LONGITUDE` | float | Decimal degrees |
| `LOCALITY` | string | Location name |
| `LOCALITY ID` | string | Unique location identifier |
| `LOCALITY TYPE` | string | H=Hotspot, P=Personal, T=Town, PC=Postal Code |
| `COUNTRY` | string | Country name |
| `COUNTRY CODE` | string | ISO 3166-2 code |
| `STATE` | string | State/province name |
| `STATE CODE` | string | ISO 3166-2 code |
| `COUNTY` | string | County name |
| `COUNTY CODE` | string | County code (US format) |
| `IBA CODE` | string | Important Bird Area codes (pipe-delimited if multiple) |
| `BCR CODE` | int | Bird Conservation Region code |
| `USFWS CODE` | string | US Fish & Wildlife area code |

### Data Quality
| Field | Type | Description |
|-------|------|-------------|
| `APPROVED` | bool | 1=accepted by eBird, 0=rejected |
| `REVIEWED` | bool | 1=vetted by expert, 0=automated only |
| `REASON` | string | Why rejected (usually empty in main dataset) |
| `GLOBAL UNIQUE IDENTIFIER` | string | Permanent observation ID |
| `LAST EDITED DATE` | datetime | Most recent edit timestamp |
| `OBSERVER ID` | string | Observer account ID |
| `HAS MEDIA` | bool | Has associated photos/audio |

### Project Metadata (New in v1.16)
| Field | Type | Description |
|-------|------|-------------|
| `PROJECT NAMES` | string | eBird Project names (pipe-delimited) |
| `PROJECT IDENTIFIERS` | string | Project IDs (pipe-delimited) |

### Comments
| Field | Type | Description |
|-------|------|-------------|
| `CHECKLIST COMMENTS` | string | General checklist notes |
| `SPECIES COMMENTS` | string | Species-specific notes |

## Critical Concepts for Our Use Case

### 1. Presence vs. Absence Data

**EBD alone = presence-only** (where birds were seen)

To infer **absence** (species not detected):
- Requires `ALL_SPECIES_REPORTED=1` (complete checklist)
- If species appears in Sampling Event Data but NOT in EBD → inferred zero count
- The `auk` R package automates this

**For region packs**: We only care about presence, so we can ignore absence logic.

### 2. Data Quality Filtering

**Recommended filters for region packs:**

```rust
filter(|record| {
    record.approved == 1 &&                    // Only accepted records
    record.all_species_reported == 1 &&        // Complete checklists only
    record.exotic_code.is_none() &&            // Native species only
    record.category == "species" &&            // No hybrids/slashes
    record.observation_count != "X"            // Actual count (not just presence)
})
```

**Why complete checklists only?**
- Partial lists skew frequency calculations
- Birders often only report "highlights" on partial lists
- Complete lists give unbiased occurrence rates

### 3. Deduplication

**Shared checklists create duplicates:**
- Multiple observers can share the same checklist
- Each gets a copy with the same `GROUP_IDENTIFIER`
- **Must deduplicate** by GROUP_ID for count-based analyses
- Can also deduplicate by SAMPLING_EVENT_IDENTIFIER if ignoring observers

### 4. Taxonomic Stability

- eBird uses **eBird/Clements taxonomy** (updated annually in October)
- Species splits/lumps tracked via `TAXON_CONCEPT_ID`
- `SCIENTIFIC_NAME` is the most stable identifier
- BirdNET may use different taxonomy → need crosswalk

### 5. Geographic Precision

- `LATITUDE`/`LONGITUDE` are location centroid (not exact observation point)
- Hotspots (H) have curated, accurate coordinates
- Personal locations (P) may be approximate for privacy
- For region packs: Use bounding box filtering with small buffer

## Working with Tarballs

**DO NOT extract to disk** - files are too large.

### Stream directly from tarball:

```bash
# List contents
tar -tf ebd_relAug-2025.tar

# Read specific file
tar -xOf ebd_relAug-2025.tar recommended_citation.txt

# Stream data file (peek at first 1000 lines)
tar -xOf ebd_relAug-2025.tar ebd_relAug-2025.txt.gz | gunzip | head -1000

# Extract header for schema reference
tar -xOf ebd_sampling_relAug-2025.tar ebd_sampling_relAug-2025.txt.gz | \
  gunzip | head -1 > header.txt
```

### Rust streaming pattern:

```rust
use flate2::read::GzDecoder;
use std::io::BufReader;
use tar::Archive;

let file = File::open("ebd_relAug-2025.tar")?;
let mut archive = Archive::new(file);

for entry in archive.entries()? {
    let mut entry = entry?;
    let path = entry.path()?;

    if path.to_str().unwrap().ends_with(".txt.gz") {
        let gz = GzDecoder::new(entry);
        let reader = BufReader::new(gz);
        // Parse TSV line-by-line
    }
}
```

## Data Volume Estimates

| Region | Approx Records | Processing Time* |
|--------|---------------|------------------|
| Global | 1B+ | 20-30 min |
| North America | 500M | 10-15 min |
| United States | 400M | 8-12 min |
| California | 50M | 2-3 min |
| SF Bay Area | 5M | 20-40 sec |

*Estimated for streaming Rust pipeline on modern hardware

## Citation

```
eBird Basic Dataset. Version: EBD_relAug-2025.
Cornell Lab of Ornithology, Ithaca, New York. Aug 2025.
```

## Resources

- **eBird Data Access**: https://ebird.org/data/download
- **Status & Science**: https://ebird.org/science/status-and-trends
- **API**: https://documenter.getpostman.com/view/664302/S1ENwy59
- **auk R package**: https://cornelllabofornithology.github.io/auk/
- **Metadata PDF**: /tmp/ebird_metadata.pdf (this session)
