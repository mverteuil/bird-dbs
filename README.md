# BirdNET-Pi Database Extractors

**Reference database builders for BirdNET-Pi**

⚠️ **Note:** This repository is for **DATA MAINTAINERS ONLY**. End users should download pre-built reference databases from BirdNET-Pi releases.

---

## Overview

This repository contains tools for building the reference databases used by [BirdNET-Pi](https://github.com/mcguirepr89/BirdNET-Pi):

1. **IOC Reference** - Multilingual bird names from IOC World Bird List (44 languages)
2. **Wikidata Reference** - Supplemental translations from Wikidata (4 unique languages)
3. **eBird Region Packs** - Regional species lists with H3-based geospatial indexing

These databases are **pre-built assets** distributed with BirdNET-Pi, similar to AI models. Most users will never need to run these extractors.

---

## Who Should Use This Repository?

### ✅ You SHOULD use this repository if you are:
- A data maintainer updating reference databases
- Contributing improvements to extraction logic
- Building custom region packs for new areas
- Researching bird taxonomy and translations

### ❌ You should NOT use this repository if you are:
- An end user installing BirdNET-Pi (download pre-built databases instead)
- A BirdNET-Pi core contributor (work on the main BirdNET-Pi repo)
- Testing BirdNET-Pi (pre-built databases are sufficient)

---

## Architecture

See [docs/architecture-decision-avilistr.md](docs/architecture-decision-avilistr.md) for full architectural details.

### Database Naming Convention
- `ioc_reference.db` - IOC World Bird List translations
- `wikidata_reference.db` - Wikidata supplemental translations
- `ebird_regions/*.db` - Regional species data (H3 grids)

All databases use **Avibase IDs** as stable identifiers across taxonomic changes.

---

## Requirements

### Common Requirements (All Extractors)
- **Avilistr data**: Complete world bird list with taxonomy mappings
  - Download from: https://avibase.bsc-eoc.org/checklist.jsp
  - Save to: `shared/avilistr/world_birds_YYYY-MM-DD.csv`

### IOC Reference Builder
- **Language:** Python 3.8+ with R
- **Dependencies:**
  - Python: sqlalchemy, pandas, requests
  - R: tidyverse, readxl
- **Data Source:** IOC World Bird List (manual download)
  - Excel files: IOC_Names_File_Plus-XX.X.xlsx, IOC_Multiling_Names_File-XX.X.xlsx
  - Download from: https://www.worldbirdnames.org/
- **Hardware:** Any laptop (2GB RAM sufficient)
- **Time:** ~10-20 minutes

### Wikidata Reference Builder
- **Language:** Python 3.8+
- **Dependencies:** requests, SPARQLWrapper
- **Data Source:** Wikidata SPARQL API (live queries)
- **Hardware:** Any laptop with internet connection
- **Time:** ~30-60 minutes (API rate limited)

### eBird Region Pack Builder
- **Language:** Rust (stable toolchain)
- **Dependencies:** cargo, h3ron, csv, rayon
- **Data Source:** eBird Basic Dataset (EBD)
  - **⚠️ RESTRICTED ACCESS:** Requires Cornell Lab research license
  - Request access: https://ebird.org/data/download
  - Size: 200GB+ compressed, 500GB+ uncompressed
- **Hardware:** High-memory server (64GB+ RAM recommended)
- **Storage:** 1TB+ available space (SSD recommended)
- **Time:** 4-8 hours per region pack (depends on region size)

---

## Quick Start

### Phase 1: Data Collection

```bash
# Create data sources directory
mkdir -p shared/avilistr data/ioc data/ebird

# Download Avilistr world bird list
# Visit: https://avibase.bsc-eoc.org/checklist.jsp
# Select: World, All taxonomies, CSV export
# Save to: shared/avilistr/world_birds_2025-10-08.csv

# Download IOC multilingual files (manual)
# Visit: https://www.worldbirdnames.org/
# Download latest version Excel files
# Save to: data/ioc/

# Request eBird EBD access (if building region packs)
# Visit: https://ebird.org/data/download
# Submit research justification
# Download to: data/ebird/ebd_relAug-2025.tar
```

### Phase 2: Build Reference Databases

#### Build IOC Reference

```bash
cd ioc-builder

# Install dependencies
pip install -r requirements.txt  # TODO: Create requirements.txt
Rscript -e "install.packages(c('tidyverse', 'readxl'))"

# Run builder
python3 ioc_database_builder.py \
  --ioc-path ../data/ioc/IOC_Names_File_Plus-14.2.xlsx \
  --multilingual-path ../data/ioc/IOC_Multiling_Names_File-14.2.xlsx \
  --avilistr-path ../shared/avilistr/world_birds_2025-10-08.csv \
  --output ../output/ioc_reference.db

# Expected output: ioc_reference.db (~51 MB, 11,250 species, 297K translations)
```

#### Build Wikidata Reference

```bash
cd wikidata-builder

# Install dependencies
pip install -r requirements.txt  # TODO: Create requirements.txt

# Run builder (full extraction with 4 languages: nb, eu, zh-hans, zh-hant)
python3 run_wikidata_poc.py \
  --full \
  --output ../output/wikidata_reference.db

# Expected output: wikidata_reference.db (~5-7 MB, ~10,500 species, ~18K translations)
```

#### Build eBird Region Pack

```bash
cd ebird-builder

# Build Rust binary
cargo build --release

# Extract region pack (example: Boston, MA - Suffolk County)
./target/release/ebird-pack \
  --input ../data/ebird/ebd_relAug-2025.tar \
  --region us-ma-025 \
  --avilistr ../shared/avilistr/world_birds_2025-10-08.csv \
  --output ../output/ebird_regions/

# Expected output: ebird_regions/us-ma-025.db (~2-5 MB depending on region)
```

---

## Builder Details

### IOC Reference Builder

**Purpose:** Extract IOC World Bird List translations (44 languages)

**Key Features:**
- Parses IOC Excel files (species + multilingual translations)
- Matches IOC scientific names to Avibase IDs (via Avilistr)
- Creates `ioc_reference.db` with `avibase_id` column
- 44 languages with excellent coverage (10,000+ translations each)

**Update Schedule:** Annually (October, when IOC releases new version)

**See:** `ioc-builder/README.md` for detailed usage

### Wikidata Reference Builder

**Purpose:** Extract supplemental translations from Wikidata (4 unique languages)

**Key Features:**
- Queries Wikidata SPARQL API for bird species with Avibase IDs (P2026)
- Filters out scientific name fallbacks (only real translations)
- Extracts 4 languages NOT in IOC: Norwegian Bokmål (nb), Basque (eu), Chinese Simplified/Traditional (zh-hans, zh-hant)
- Creates `wikidata_reference.db` with Avibase IDs

**Update Schedule:** Quarterly or as needed

**See:** `wikidata-builder/README.md` for detailed usage

**Important:** This builder filters out 59% of Wikidata "translations" that are actually just scientific names used as fallback labels. See [docs/wikidata-data-quality-issue.md](docs/wikidata-data-quality-issue.md) for details.

### eBird Region Pack Builder

**Purpose:** Create H3-based regional species occurrence databases

**Key Features:**
- Processes 200GB+ eBird Basic Dataset (EBD)
- Aggregates observations into H3 hexagonal grid cells (resolution 8)
- Calculates species frequency, confidence tiers, seasonal patterns
- Matches eBird/Clements taxonomy to Avibase IDs (via Avilistr)
- Optimized Rust implementation for performance

**Update Schedule:** Annually (August, when eBird releases new EBD)

**See:** `ebird-builder/README.md` for detailed usage

---

## Output Databases

All built databases should be placed in `output/` directory:

```
output/
├── ioc_reference.db           (~51 MB)
├── wikidata_reference.db      (~5-7 MB)
└── ebird_regions/
    ├── us-ca-037.db          (Los Angeles County)
    ├── us-ma-025.db          (Suffolk County / Boston)
    └── ...
```

These files are then uploaded as **release assets** for BirdNET-Pi.

---

## Testing

All three builders include comprehensive test suites to ensure data quality and correctness.

### Quick Start

**IOC Builder:**
```bash
cd ioc-builder
pip install -r requirements.txt
pytest
```

**Wikidata Builder:**
```bash
cd wikidata-builder
pip install -r requirements.txt
pytest
```

**eBird Builder:**
```bash
cd ebird-builder
cargo test
```

### Test Coverage

- **IOC Builder:** >80% coverage - Excel parsing, Avibase mapping, database creation
- **Wikidata Builder:** >85% coverage - SPARQL queries, scientific name filtering (critical)
- **eBird Builder:** >75% coverage - H3 aggregation, species classification, filtering

### Critical Tests

1. **Scientific Name Fallback Filtering** (Wikidata) - Ensures 59% of useless fallback data is excluded
2. **Avibase ID Mapping** (IOC + eBird) - Validates stable identifiers across taxonomic changes
3. **H3 Grid Consistency** (eBird) - Ensures reproducible geographic indexing
4. **Species Filtering** (eBird) - Validates approved, complete, native, species-only filters

**See:** [docs/testing-guide.md](docs/testing-guide.md) for comprehensive testing documentation

---

## Contributing

### Reporting Issues

- **IOC extraction bugs:** File issue in this repo with "ioc-builder" label
- **Wikidata extraction bugs:** File issue with "wikidata-builder" label
- **eBird region pack bugs:** File issue with "ebird-builder" label
- **Architecture questions:** See [docs/architecture-decision-avilistr.md](docs/architecture-decision-avilistr.md)

### Pull Requests

1. Fork this repository
2. Create a feature branch
3. Make your changes
4. Test with sample data (full datasets too large for CI)
5. Submit PR with description of changes

**Note:** CI tests only run with sample data. Full validation requires manual testing with actual IOC files / eBird EBD.

---

## Release Process

1. **Data Collection:** Download latest source data (IOC files, eBird EBD, Avilistr)
2. **Build Databases:** Run all three extractors
3. **Validation:**
   - Verify species counts
   - Check translation quality
   - Test database schema compatibility
4. **Tag Release:** Create git tag (e.g., `v2025.10` for October 2025 release)
5. **Upload Assets:** Attach built databases to GitHub release
6. **Update BirdNET-Pi:** Release manager downloads and distributes via BirdNET-Pi releases

---

## Licenses

### Code License
- Extractor code: [Same as BirdNET-Pi - to be determined]

### Data Source Licenses
- **IOC World Bird List:** CC-BY-4.0 (attribution required)
  - Citation: Gill F, D Donsker & P Rasmussen (Eds). 2024. IOC World Bird List (vXX.X). doi:10.14344/IOC.ML.XX.X
- **Wikidata:** CC0 (public domain)
- **eBird Data:** eBird Basic Dataset Terms of Use
  - Research use only
  - Citation required
  - Cannot redistribute raw EBD data
  - Derived works (region packs) have different terms
- **Avilistr/Avibase:** [Check Avibase terms]

### Important
By using these extractors, you agree to comply with all source data licenses.

---

## Support

- **Documentation:** See `docs/` directory
- **Issues:** https://github.com/[org]/BirdNET-Pi-extractors/issues
- **BirdNET-Pi Main Repo:** https://github.com/mcguirepr89/BirdNET-Pi

---

## Acknowledgments

- **IOC World Bird List** for comprehensive multilingual bird names
- **Wikidata community** for crowd-sourced translations
- **Cornell Lab of Ornithology** for eBird data
- **Avibase** (Denis Lepage) for stable species identifiers and taxonomy mappings
- **BirdNET-Pi contributors** for the amazing bird detection platform

---

**Last Updated:** 2025-10-08
**Repository Status:** Active Development
