# eBird Region Pack Generator - Documentation

This directory contains comprehensive documentation for the eBird Region Pack project, which generates scientifically-grounded species filters for BirdNET-Pi using real observational data from the eBird Basic Dataset.

## Documentation Index

### [00-overview.md](00-overview.md)
**Project mission, architecture, and roadmap**

High-level project goals, technology stack decisions, and development phases. Start here to understand what we're building and why.

Key sections:
- Problem statement and solution
- Architecture diagram
- Phase-by-phase roadmap
- Success criteria

### [01-ebird-data-structure.md](01-ebird-data-structure.md)
**Complete reference for eBird Basic Dataset format**

Detailed breakdown of the eBird data structure, field definitions, and data quality considerations. Essential reading before implementing the Rust pipeline.

Key sections:
- File format and encoding
- ~50 field definitions with examples
- Critical concepts (presence/absence, deduplication, filtering)
- Streaming tar.gz commands
- Data volume estimates

### [02-birdnet-pi-architecture.md](02-birdnet-pi-architecture.md)
**BirdNET-Pi system architecture and integration points**

Deep dive into how BirdNET-Pi works, where species filtering happens, and how to integrate region packs.

Key sections:
- System architecture diagram
- BirdDetectionService details
- Species parsing and taxonomy
- Three integration strategies
- Configuration extension proposal

### [03-region-pack-specification.md](03-region-pack-specification.md)
**SQLite database specification for region packs**

Complete specification of the region pack database format, including schema, required fields, validation rules, and examples.

Key sections:
- SQLite schema with indexes
- Metadata and species table definitions
- Field-by-field definitions
- Frequency threshold recommendations
- Temporal filtering (BirdNET week → month mapping)
- Hierarchical pack strategy
- Validation rules and query examples

### [04-rust-pipeline-design.md](04-rust-pipeline-design.md)
**Implementation design for the Rust CLI tool**

Detailed technical design of the Rust pipeline, including data structures, processing flow, and code examples.

Key sections:
- Project structure
- Dependencies (Cargo.toml with rusqlite)
- Core data structures (with code)
- Processing pipeline (5 stages)
- SQLite writer implementation
- Performance optimizations
- CLI usage examples

### [05-format-decision.md](05-format-decision.md)
**Data format evaluation and SQLite selection**

Comprehensive analysis of data format options (JSON, Parquet, DuckDB, SQLite) and rationale for choosing SQLite.

Key sections:
- Performance comparison table
- Evaluation criteria (loading, architecture fit, dependencies, debuggability)
- SQLite schema design
- Integration patterns for BirdNET-Pi
- Rust pipeline changes
- Database optimization strategies

### [06-grid-based-architecture.md](06-grid-based-architecture.md)
**H3 hexagonal grid region packs for neighborhood-level precision (Version 2.0)**

Enhanced architecture providing Merlin Bird ID-like spatial precision using H3 hexagonal grids instead of broad regional aggregation.

Key sections:
- **H3 hexagonal grid system** (~5km resolution, equidistant neighbors)
- **Distance-weighted confidence adjustments** using surrounding hexagons
- Confidence tier system (common/uncommon/rare/vagrant)
- Three-table SQLite schema (region_metadata, grid_metadata, grid_species)
- Using both EBD datasets (presence + absence data)
- BirdNET-Pi integration with H3-aware queries
- Why H3 over geohash/lat-lon grids (perfect for distance weighting)
- Alternative approaches evaluated (ML models, vector/graph/spatial databases)
- Multi-resolution strategy (6/7/8/9 for different area densities)

## Quick Start

1. **Understand the mission**: Read [00-overview.md](00-overview.md)
2. **Learn the data**: Study [01-ebird-data-structure.md](01-ebird-data-structure.md)
3. **Plan integration**: Review [02-birdnet-pi-architecture.md](02-birdnet-pi-architecture.md)
4. **Understand format decision**: Read [05-format-decision.md](05-format-decision.md)
5. **Design grid-based approach**: Study [06-grid-based-architecture.md](06-grid-based-architecture.md) ⭐ **Enhanced v2.0**
6. **Design output**: Reference [03-region-pack-specification.md](03-region-pack-specification.md)
7. **Build pipeline**: Implement using [04-rust-pipeline-design.md](04-rust-pipeline-design.md)

## Development Workflow

```
┌──────────────────┐
│ eBird Data       │ → Read 01-ebird-data-structure.md
│ (200GB tarballs) │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Rust CLI Tool    │ → Implement 04-rust-pipeline-design.md
│ (streaming)      │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Region Pack JSON │ → Validate against 03-region-pack-specification.md
│ (compressed)     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ BirdNET-Pi       │ → Integrate using 02-birdnet-pi-architecture.md
│ (Python)         │
└──────────────────┘
```

## Data Files

The parent directory (`/Volumes/backup/ebird/`) contains:

```
ebird/
├── ebd_relAug-2025.tar (201GB)           # Full global dataset
├── ebd_sampling_relAug-2025.tar (7.2GB)  # Sampling dataset
├── CLAUDE.md                             # Working guide
└── docs/                                 # This directory
    ├── README.md                         # You are here
    ├── 00-overview.md
    ├── 01-ebird-data-structure.md
    ├── 02-birdnet-pi-architecture.md
    ├── 03-region-pack-specification.md
    └── 04-rust-pipeline-design.md
```

## Key Concepts

### Region Pack (Version 2.0 = H3 Grid)
A SQLite database containing species occurrence data organized in H3 hexagonal grid cells, derived from real eBird observations. Each hexagon (~5km) has its own species frequency data, enabling neighborhood-level spatial precision and distance-weighted confidence adjustments in BirdNET-Pi.

**Format**: SQLite database with three tables (region_metadata, grid_metadata, grid_species)

### Frequency-Based Filtering
Species are included/excluded based on how often they're observed in complete checklists:
- **High frequency** (>20%): Common residents
- **Medium frequency** (5-20%): Seasonal or uncommon
- **Low frequency** (1-5%): Rare but expected
- **Very low** (<1%): Vagrants (optionally excluded)

### Temporal Intelligence
Monthly frequency arrays enable seasonal filtering:
- Migratory species have distinct peaks
- Resident species show stable frequencies
- Maps BirdNET's "week 1-48" to calendar months

### Confidence Boosting
Species with high local occurrence get confidence multipliers:
- Common species: 1.2-1.3x boost
- Rare species: 1.0x (no boost)
- Prevents over-filtering while reducing false positives

## Technical Decisions

### Why Rust for the Pipeline?
- **Data scale**: Streaming 200GB efficiently without loading into memory
- **Performance**: Process full dataset in 20-30 minutes
- **Safety**: Strong type system prevents data corruption
- **Portability**: Single binary, no runtime dependencies
- **H3 support**: Pure Rust h3o crate (no C bindings needed)

### Why SQLite for Region Packs?
- **Performance**: 2-4x faster loading than JSON (15-30ms vs 80-120ms)
- **Zero integration cost**: BirdNET-Pi already uses SQLite for IOC/Avibase databases
- **No new dependencies**: sqlite3 in Python standard library
- **Query flexibility**: SQL enables complex H3 grid queries without loading into memory
- **Debuggability**: Standard SQLite tools (sqlite3 CLI, DB Browser, DataGrip)
- **Schema evolution**: ALTER TABLE support for backward-compatible updates

### Why H3 Hexagonal Grids?
- **Equidistant neighbors**: All 6 neighbors same distance from center (perfect for distance-weighted confidence)
- **Hierarchical resolution**: Parent-child relationships enable fallback from sparse to dense areas
- **Spatial precision**: ~5km hexagons provide Merlin Bird ID-like neighborhood-level accuracy
- **Pure Rust**: h3o crate has no C dependencies, making deployment easier

### Why Scientific Name as Primary Key?
- **Stable across taxonomies**: eBird/Clements vs BirdNET
- **Unambiguous**: Common names vary by region/language
- **Future-proof**: Robust to taxonomy updates

## Common Workflows

### Generate an H3 Grid Region Pack

```bash
# 1. Create config YAML
cat > us-ca-sf-bay-h3.yaml <<EOF
region_id: us-ca-sf-bay-h3
region_name: San Francisco Bay Area (H3 Grid)
region_type: metro
h3_resolution: 7  # Resolution 7 = ~5km hexagons
bounding_box:
  min_latitude: 37.4
  max_latitude: 38.0
  min_longitude: -122.5
  max_longitude: -121.8
date_range:
  start: 2020-01-01
  end: 2025-08-01
filters:
  approved_only: true
  complete_checklists_only: true
  native_species_only: true
  min_observations: 10
  min_checklists: 5
  min_yearly_frequency: 0.01
  deduplication: group_identifier
EOF

# 2. Run generator (once implemented)
ebird-region-pack \
  --input ebd_relAug-2025.tar \
  --config us-ca-sf-bay-h3.yaml \
  --output us-ca-sf-bay-h3.db

# 3. Validate output
sqlite3 us-ca-sf-bay-h3.db "SELECT value FROM region_metadata WHERE key='total_h3_cells';"
sqlite3 us-ca-sf-bay-h3.db "SELECT COUNT(*) FROM grid_metadata;"
sqlite3 us-ca-sf-bay-h3.db "SELECT COUNT(DISTINCT scientific_name) FROM grid_species;"
```

### Integrate with BirdNET-Pi

```bash
# 1. Copy region pack to BirdNET-Pi
cp us-ca-sf-bay-h3.db ~/birdnet-pi/region_packs/

# 2. Update config (in birdnet.yaml):
enable_ebird_filtering: true
ebird_region_pack: region_packs/us-ca-sf-bay-h3.db
ebird_h3_resolution: 7
ebird_neighbor_radius: 1  # Use k_ring=1 (center + 6 neighbors)
ebird_filter_mode: supplement
ebird_min_frequency: 0.01

# 3. Restart BirdNET-Pi
systemctl restart birdnet-pi
```

## FAQ

### Q: Do I need to extract the tarballs?
**A: No!** Stream directly from the tar files using the commands in [01-ebird-data-structure.md](01-ebird-data-structure.md).

### Q: How much disk space do I need?
**A: ~210GB** for the tarballs, ~1-2MB per H3 grid region pack (SQLite). The Rust pipeline streams data and doesn't need temp space.

### Q: Can I use the sampling dataset for testing?
**A: Yes!** The 7.2GB sampling dataset is perfect for development. Production packs should use the full dataset.

### Q: What if my region has too few observations?
**A: Use hierarchical fallback.** If a small region lacks data, fall back to state → country → continent packs.

### Q: How often should I update region packs?
**A: Every 6-12 months** when eBird releases new data. Bird ranges shift due to climate change and taxonomy updates.

### Q: Will this work for locations outside the US?
**A: Absolutely!** eBird is global. The same pipeline works worldwide, just adjust bounding boxes.

## Resources

- **eBird**: https://ebird.org
- **BirdNET-Pi**: https://github.com/mcguirepr89/BirdNET-Pi
- **BirdNET**: https://github.com/kahst/BirdNET-Analyzer
- **IOC World Bird List**: https://www.worldbirdnames.org
- **H3 Geospatial Indexing**: https://h3geo.org
- **h3o (Rust H3)**: https://docs.rs/h3o/
- **h3-py (Python H3)**: https://uber.github.io/h3-py/
- **Rust Book**: https://doc.rust-lang.org/book/
- **rusqlite**: https://docs.rs/rusqlite/
- **Serde JSON**: https://docs.rs/serde_json/

## Contributing

This is documentation for an in-progress project. If you're implementing:

1. Follow the designs in these docs
2. Update docs when you discover needed changes
3. Add examples and edge cases you encounter
4. Document performance measurements
5. Share lessons learned

## License

This documentation follows the same license as the eBird Region Pack project (TBD). eBird data usage must comply with eBird's Terms of Use.

## Acknowledgments

- **Cornell Lab of Ornithology** - eBird Basic Dataset
- **Patrick McGuire** - Original BirdNET-Pi creator
- **Stefan Kahl** - BirdNET model and framework
- **Uber Technologies** - H3 Hexagonal Hierarchical Geospatial Indexing System
- **IOC** - World Bird List taxonomy
- **Avibase** - Cross-taxonomy linkages
