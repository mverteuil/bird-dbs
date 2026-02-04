# BirdNET-Pi Database Builders Documentation

Central documentation for all components of the BirdNET-Pi database building infrastructure.

---

## Quick Navigation

| Section | Description |
|---------|-------------|
| [eBird Reference](#ebird-reference) | eBird data format and system design specifications |
| [Architecture](#architecture) | System design decisions and strategies |
| [Pipeline](#pipeline) | Data processing methodology |
| [Tools](#tools) | Individual component documentation |
| [Testing](#testing) | Testing guides and expected results |
| [Wikidata](#wikidata-analysis) | Wikidata data quality analysis |

---

## eBird Reference

Comprehensive documentation for the eBird Basic Dataset and region pack system design.

| Document | Description |
|----------|-------------|
| [Overview](ebd-reference/00-overview.md) | Project goals and high-level system overview |
| [eBird Data Structure](ebd-reference/01-ebird-data-structure.md) | EBD file format, columns, and data organization |
| [BirdNET-Pi Architecture](ebd-reference/02-birdnet-pi-architecture.md) | How BirdNET-Pi consumes region packs |
| [Region Pack Specification](ebd-reference/03-region-pack-specification.md) | SQLite schema, H3 indexing, and pack format |
| [Rust Pipeline Design](ebd-reference/04-rust-pipeline-design.md) | Streaming processing architecture |
| [Format Decision](ebd-reference/05-format-decision.md) | Why SQLite over Parquet for client-side |
| [Grid-Based Architecture](ebd-reference/06-grid-based-architecture.md) | H3 hexagonal grid design and resolution choices |

---

## Architecture

High-level design decisions and system architecture.

| Document | Description |
|----------|-------------|
| [Avilistr Architecture Decision](architecture/architecture-decision-avilistr.md) | Use of Avibase IDs as stable cross-taxonomy identifiers |
| [eBird Region Pack Strategy](architecture/ebird-region-pack-strategy.md) | H3-based region pack generation and GitHub distribution |

---

## Pipeline

Data processing methodology and algorithms.

| Document | Description |
|----------|-------------|
| [Mathematical Methodology](pipeline/mathematical-methodology.md) | Complete mathematical foundations for eBird analysis: H3 indexing, streaming algorithms, frequency estimation, and partitioning |

---

## Tools

Documentation for each component in the system.

### Builders (Primary Output Generators)

| Tool | Description |
|------|-------------|
| [ioc-builder](tools/ioc-builder.md) | Build IOC World Bird List reference database (44 languages, ~51MB) |
| [wikidata-builder](tools/wikidata-builder.md) | Build supplemental translation database from Wikidata (4 unique languages) |
| [ebird-builder](tools/ebird-builder.md) | Generate H3-based region pack SQLite databases from eBird data |

### Analysis Tools

| Tool | Description |
|------|-------------|
| [ebird-density-analyzer](tools/ebird-density-analyzer.md) | Analyze eBird observation density across H3 cells (Rust) |
| [ebird-density-analyzer (Progress Feedback)](tools/ebird-density-analyzer-progress.md) | Two-pass mode progress feedback documentation |
| [pack-planner](tools/pack-planner.md) | Partition density data into GitHub-release-sized regions (Python) |
| [benchmark](tools/benchmark.md) | Compare Rust vs R/auk implementations |

### Support Tools

| Tool | Description |
|------|-------------|
| [avilistr-builder](tools/avilistr-builder.md) | Extract Avibase ID mappings from avilistr R package |
| [pack-manifest-visualizer](tools/pack-manifest-visualizer.md) | Interactive H3 hexagon visualization (TypeScript) |
| [release-publisher](tools/release-publisher.md) | Automated GitHub release publisher for region packs |

---

## Testing

Testing guides and validation data.

| Document | Description |
|----------|-------------|
| [Testing Guide](testing/testing-guide.md) | Comprehensive testing documentation for all builders |
| [Expected Results](testing/EXPECTED_RESULTS.md) | Ground truth calculations for 10-record test |
| [Expected Results (Expanded)](testing/EXPECTED_RESULTS_EXPANDED.md) | Extended test case documentation |

---

## Wikidata Analysis

Analysis of Wikidata data quality for bird name translations.

| Document | Description |
|----------|-------------|
| [Data Quality Issue](wikidata/wikidata-data-quality-issue.md) | Discovery of scientific name fallback problem (59% useless data) |
| [Corrected Analysis](wikidata/wikidata-corrected-analysis.md) | Revised analysis after filtering, recommendations for 4 languages |

---

## Data Flow Overview

```
External Data Sources                Processing Pipeline                  Output
====================                 ===================                  ======

IOC Excel Files ─────────────────> ioc-builder ──────────────────────> ioc_reference.db
                                                                         (44 languages)

Wikidata SPARQL API ─────────────> wikidata-builder ─────────────────> wikidata_reference.db
                                                                         (4 languages)

avilistr R package ──────────────> avilistr-builder ─────────────────> shared/avilistr/*.csv
         │                                                                    │
         └──────────────────────────────────────────────────────────> (used by all builders)

eBird EBD (~200GB) ──────────────> ebird-density-analyzer ────────────> density_reports/*.json
                                          │
                                          v
                                    pack-planner ─────────────────────> pack_manifest.json
                                          │
                                          v
                                    ebird-builder ────────────────────> region-packs/*.db
                                          │
                                          v
                                    release-publisher ────────────────> GitHub Releases
```

---

## Quick Start

### 1. Set Up Avilistr Mapping (One-time)

```bash
cd avilistr-builder
make install
make extract
```

### 2. Build Reference Databases

```bash
# IOC Reference (44 languages)
cd ioc-builder
uv sync
uv run python ioc_database_builder.py \
  --ioc-path ../data/ioc/IOC_Names_File_Plus-14.2.xlsx \
  --multilingual-path ../data/ioc/IOC_Multiling_Names_File-14.2.xlsx \
  --avilistr-path ../shared/avilistr/avilistr_mapping.csv \
  --output ../output/ioc_reference.db

# Wikidata Reference (4 languages)
cd wikidata-builder
uv sync
uv run python run_wikidata_poc.py --full --output ../output/wikidata_reference.db
```

### 3. Analyze eBird Density

```bash
cd analysis/ebird-density-analyzer
cargo build --release
./target/release/ebird-density-analyzer \
  --input /path/to/ebd.tar \
  --resolutions 2,3,4,5 \
  --output density_reports/ \
  --two-pass \
  --temp-dir /tmp/temp/
```

### 4. Plan Region Packs

```bash
cd analysis/pack-planner
uv sync
uv run pack-planner \
  --density-reports density_reports/ \
  --output-manifest pack_manifest.json \
  --output-registry pack_registry.json
```

### 5. Publish to GitHub

```bash
cd release-publisher
uv sync
uv run release-publisher \
  --registry pack_registry.json \
  --db-dir region-packs/ \
  --target-repo owner/birdnetpi-ebird-packs
```

---

## Related Documentation

- **Main README**: [../README.md](../README.md) - Project overview and status
- **CLAUDE.md**: [../../CLAUDE.md](../../CLAUDE.md) - LLM instructions (project root)

---

## Contributing

See [testing/testing-guide.md](testing/testing-guide.md) for testing requirements before submitting changes.
