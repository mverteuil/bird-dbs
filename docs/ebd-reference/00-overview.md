# eBird Region Pack Generator - Project Overview

## Mission

Build scientifically-grounded species filters for BirdNET-Pi using real eBird observation data to:
1. **Reduce false positives** - Filter out species never/rarely observed in the deployment region
2. **Increase confidence** - Boost detection confidence for species with high local occurrence rates
3. **Add temporal intelligence** - Account for seasonal migration and occurrence patterns

## Problem Statement

BirdNET-Pi currently uses BirdNET's built-in metadata model for location-based species filtering. This model:
- Is based on synthetic occurrence predictions (ML-generated, not observational)
- Has limited temporal granularity (week 1-48)
- Doesn't reflect actual bird observations in specific regions
- Can include species that have never been documented in the area

**Our solution**: Replace/augment this with **real observational data from eBird**, the world's largest biodiversity database.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     eBird Data (200GB+)                      │
│                  Tab-delimited observation records           │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────────┐
                    │  Rust CLI Tool     │
                    │  ebird-region-pack │
                    │                    │
                    │ - Stream tar.gz    │
                    │ - Filter region    │
                    │ - Aggregate stats  │
                    │ - Generate pack    │
                    └─────────┬──────────┘
                              │
                              ▼
                    ┌──────────────────────┐
                    │   Region Pack JSON   │
                    │   (compressed)       │
                    │                      │
                    │ - Species list       │
                    │ - Frequency data     │
                    │ - Seasonal patterns  │
                    └─────────┬────────────┘
                              │
                              ▼
                    ┌──────────────────────┐
                    │    BirdNET-Pi        │
                    │  (Python/FastAPI)    │
                    │                      │
                    │ - Load region pack   │
                    │ - Filter detections  │
                    │ - Boost confidence   │
                    └──────────────────────┘
```

## Technology Stack

### Data Pipeline (Rust)
- **Rationale**: Streaming 200GB+ datasets efficiently
- **Libraries**:
  - `tar` - Tarball streaming
  - `flate2` - Gzip decompression
  - `csv`/`tsv` - Tab-delimited parsing
  - `serde`, `serde_json` - Serialization
  - `rayon` - Parallel processing
  - `geo` - Geographic operations (optional)

### Integration Layer (Python)
- **Existing**: BirdNET-Pi codebase (Python 3.10+, FastAPI, SQLAlchemy)
- **New modules**: Region pack loader, eBird filter service
- **Configuration**: Add eBird filtering options to config model

## Key Metrics

### Data Scale
- **Full dataset**: 201GB tarball → ~1 billion+ bird observations globally
- **Sampling dataset**: 7.2GB tarball → representative subset
- **Region pack output**: ~500KB - 5MB JSON (gzipped) per region
- **Species coverage**: 6,000+ species globally, 400-800 per region typically

### Performance Targets
- **Region pack generation**: < 30 minutes for full dataset (streaming)
- **BirdNET-Pi load time**: < 100ms to load region pack on startup
- **Memory footprint**: < 50MB for loaded region pack in Python

## Project Phases

### Phase 1: Research & Design ✅ (Current)
- [x] Understand eBird data structure
- [x] Analyze BirdNET-Pi architecture
- [x] Design region pack format
- [ ] Document specifications

### Phase 2: Rust CLI Development
- [ ] Set up Rust project structure
- [ ] Implement tar.gz streaming
- [ ] Build filtering logic
- [ ] Add aggregation pipeline
- [ ] Generate JSON output
- [ ] Write tests

### Phase 3: BirdNET-Pi Integration
- [ ] Add configuration models
- [ ] Implement region pack loader
- [ ] Create eBird filter service
- [ ] Integrate with detection pipeline
- [ ] Add UI controls

### Phase 4: Validation & Deployment
- [ ] Compare against BirdNET metadata model
- [ ] Measure false positive reduction
- [ ] Generate region pack library
- [ ] Documentation & examples
- [ ] Release

## Success Criteria

1. **Accuracy**: 20-50% reduction in false positive detections
2. **Coverage**: No increase in false negatives (missed valid species)
3. **Performance**: < 5ms filtering overhead per detection
4. **Usability**: Simple drop-in region pack installation
5. **Maintainability**: Clear update process as new eBird data releases

## Resources

- **eBird Data**: https://ebird.org/data/download
- **BirdNET-Pi**: https://github.com/mcguirepr89/BirdNET-Pi
- **BirdNET Model**: https://github.com/kahst/BirdNET-Analyzer
- **eBird Taxonomy**: https://ebird.org/science/use-ebird-data/the-ebird-taxonomy
- **IOC World Bird List**: https://www.worldbirdnames.org/
