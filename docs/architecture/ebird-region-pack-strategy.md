# eBird Region Pack Generation & Distribution Strategy

**Document Version:** 1.0
**Last Updated:** 2025-10-09
**Status:** Design Document

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Solution Overview](#solution-overview)
3. [H3 Dual-Resolution Architecture](#h3-dual-resolution-architecture)
4. [Generation Pipeline](#generation-pipeline)
5. [Region Partitioning Algorithm](#region-partitioning-algorithm)
6. [Distribution via GitHub Releases](#distribution-via-github-releases)
7. [Pack Registry Structure](#pack-registry-structure)
8. [Client Download Flow](#client-download-flow)
9. [Implementation Roadmap](#implementation-roadmap)
10. [Appendix: Algorithms](#appendix-algorithms)

---

## Problem Statement

BirdNET-Pi needs regional bird species data to filter detections based on what's actually been observed in a user's location. The challenge is generating and distributing this data globally while:

1. **Adapting to density variation**: Dense areas (cities) need fine-grained data; sparse areas (remote regions) need coarse coverage
2. **Avoiding thousands of config files**: Manual region definitions don't scale globally
3. **Minimizing hosting costs**: Hosting 5,000-10,000 database files is expensive
4. **Enabling automatic discovery**: Users shouldn't manually select regions
5. **Staying within GitHub limits**: GitHub Releases have a 2GB per-asset limit

---

## Solution Overview

We solve these challenges through:

1. **H3 hierarchical grid system**: Use H3 cells instead of arbitrary boundaries
2. **Dual-resolution packs**: Coarse boundary cells contain fine-grained data cells
3. **Data-driven partitioning**: Analyze eBird density to determine optimal pack sizes
4. **Geographic clustering**: Group packs into ~100-300 releases that fit within 2GB
5. **Simple registry**: Store region boundaries, not individual pack metadata
6. **GitHub Releases**: Free hosting and CDN for geographic region releases

---

## H3 Dual-Resolution Architecture

### Core Concept

Each region pack uses **two H3 resolutions**:

- **Boundary Resolution** (coarse): Defines geographic extent (res 2-4)
- **Data Resolution** (fine): Internal hexagon granularity (res 5-8)

### Example Pack Structure

```
Pack: h3-r4-599686042433355775-data-r7.db
├── Boundary: Single res 4 hexagon (~1,800 km², SF Bay Area size)
├── Contains: ~343 res 7 hexagons with species data
└── Size: ~5-10 MB compressed
```

### H3 Resolution Reference

| Resolution | Edge Length | Area per Hex | Use Case |
|------------|-------------|--------------|----------|
| 0 | ~1,000 km | ~4,357,449 km² | Continental |
| 1 | ~418 km | ~609,788 km² | Large countries |
| 2 | ~158 km | ~86,745 km² | States/provinces |
| 3 | ~59 km | ~12,392 km² | Large counties |
| 4 | ~22 km | ~1,770 km² | Metro areas (boundary) |
| 5 | ~8.5 km | ~252.9 km² | Cities |
| 6 | ~3.2 km | ~36.1 km² | Districts |
| 7 | ~1.2 km | ~5.16 km² | Neighborhoods (data) |
| 8 | ~461 m | ~0.74 km² | Dense urban |

### Pack Density Strategy

**Dense areas** (10,000+ checklists in res 4):
- Boundary: Res 4 (~22km edge)
- Data: Res 7 (~1.2km hexes)
- Result: Neighborhood-level precision

**Medium areas** (5,000+ checklists in res 3):
- Boundary: Res 3 (~59km edge)
- Data: Res 6 (~3.2km hexes)
- Result: City-level precision

**Sparse areas** (1,000+ checklists in res 2):
- Boundary: Res 2 (~158km edge)
- Data: Res 5 (~8.5km hexes)
- Result: Regional coverage

---

## Generation Pipeline

### Phase 1: Global Density Analysis

**Tool:** `ebird-density-analyzer` (new)

```bash
ebird-density-analyzer \
  --input /Volumes/backup/ebird/ebd_relAug-2025.tar \
  --resolutions 2,3,4,5 \
  --output density_reports/
```

**Process:**
1. Stream through eBird dataset once
2. Count unique checklists per H3 cell at multiple resolutions
3. Output JSON reports with density statistics

**Output:** `global_density_res{2,3,4,5}.json`

```json
{
  "resolution": 4,
  "cells": [
    {
      "h3_cell": "599686042433355775",
      "center_lat": 37.7749,
      "center_lon": -122.4194,
      "unique_checklists": 45678,
      "complete_checklists": 32145,
      "total_observations": 1234567,
      "date_range_start": "2010-01-01",
      "date_range_end": "2025-08-31",
      "estimated_pack_size_mb": 8.2
    }
  ]
}
```

**Size estimation formula:**
```python
estimated_size_mb = (
    num_complete_checklists *
    avg_species_per_checklist *
    bytes_per_species_record
) / 1_000_000

# Empirical approximation:
estimated_size_mb ≈ num_complete_checklists * 0.001
```

### Phase 2: Pack Planning

**Tool:** `pack-planner` (new)

```bash
pack-planner \
  --density-reports density_reports/ \
  --thresholds thresholds.yaml \
  --output pack_manifest.json
```

**Threshold configuration** (`thresholds.yaml`):

```yaml
# Minimum checklists per boundary resolution
thresholds:
  res_2: 1000   # Sparse areas
  res_3: 2000   # Medium areas
  res_4: 5000   # Dense areas
  res_5: 10000  # Very dense areas

# Data resolution based on density
data_resolution_rules:
  - if_checklists_gte: 10000
    use_data_resolution: 7
  - if_checklists_gte: 5000
    use_data_resolution: 6
  - if_checklists_gte: 2000
    use_data_resolution: 5
  - default: 5

# Quality filters
filters:
  approved_only: true
  complete_checklists_only: true
  native_species_only: true
  min_observations_per_species: 5
  min_checklists_per_species: 3
  min_yearly_frequency: 0.01
```

**Output:** `pack_manifest.json`

```json
{
  "packs": [
    {
      "pack_id": "h3-r4-599686042433355775-data-r7",
      "boundary_cell": "599686042433355775",
      "boundary_resolution": 4,
      "data_resolution": 7,
      "center_lat": 37.7749,
      "center_lon": -122.4194,
      "estimated_size_mb": 8.2,
      "num_data_hexagons": 343,
      "total_species": 234,
      "total_checklists": 45678
    }
  ],
  "total_packs": 8547,
  "total_size_gb": 67.3
}
```

### Phase 3: Pack Generation

**Tool:** `ebird-builder` (enhanced)

```bash
ebird-builder \
  --input /Volumes/backup/ebird/ebd_relAug-2025.tar \
  --boundary-cell 599686042433355775 \
  --data-resolution 7 \
  --output h3-r4-599686042433355775-data-r7.db
```

**Enhancements needed:**
- Accept `--boundary-cell` instead of `--config`
- Auto-generate bounding box from H3 cell geometry
- Maintain existing filtering and aggregation logic
- Output filename auto-generated from parameters

**No YAML config files needed** - all configuration derived from H3 cell geometry and thresholds.

---

## Region Partitioning Algorithm

### Goal

Partition ~5,000-10,000 packs into ~100-300 geographic regions, each ≤ 1.95 GB (2GB - 50MB buffer).

### Approach: Greedy Merge with H3 Hierarchy

**Algorithm:**

```python
def partition_into_releases(pack_manifest, max_size_mb=1950):
    """
    Partition packs into regions that fit within GitHub's 2GB limit.

    Returns list of regions, each containing multiple packs.
    """

    # Step 1: Group packs by H3 res 2 parent cells (~1,900 globally)
    regions = {}
    for pack in pack_manifest['packs']:
        # Get parent cell at resolution 2
        parent = h3.h3_to_parent(pack['boundary_cell'], res=2)
        if parent not in regions:
            regions[parent] = {
                'h3_cells': [parent],
                'packs': [],
                'size_mb': 0
            }
        regions[parent]['packs'].append(pack)
        regions[parent]['size_mb'] += pack['estimated_size_mb']

    region_list = list(regions.values())

    # Step 2: Greedily merge adjacent regions
    changed = True
    while changed:
        changed = False
        # Sort by size (merge smallest first to maximize consolidation)
        region_list.sort(key=lambda r: r['size_mb'])

        for i, region_a in enumerate(region_list):
            # Find adjacent regions that fit when merged
            for j, region_b in enumerate(region_list[i+1:], i+1):
                if (are_adjacent_h3(region_a['h3_cells'], region_b['h3_cells']) and
                    region_a['size_mb'] + region_b['size_mb'] <= max_size_mb):

                    # Merge them
                    merged = {
                        'h3_cells': region_a['h3_cells'] + region_b['h3_cells'],
                        'packs': region_a['packs'] + region_b['packs'],
                        'size_mb': region_a['size_mb'] + region_b['size_mb']
                    }

                    # Remove old regions, add merged
                    region_list = [r for r in region_list
                                 if r not in [region_a, region_b]]
                    region_list.append(merged)
                    changed = True
                    break

            if changed:
                break

    return region_list


def are_adjacent_h3(cells_a, cells_b):
    """Check if any cell in set A is adjacent to any cell in set B."""
    for cell_a in cells_a:
        for cell_b in cells_b:
            if h3.h3_indexes_are_neighbors(cell_a, cell_b):
                return True
    return False
```

**Characteristics:**
- **Deterministic**: Same input produces same output
- **Geographic contiguity**: Only merges adjacent H3 cells
- **Greedy optimization**: Minimizes number of regions
- **Respects constraints**: Hard 1.95 GB limit

**Expected results:**
- Start: ~5,000-10,000 packs
- After res 2 grouping: ~1,900 initial regions
- After greedy merge: ~100-300 final regions
- Average region size: 1.5-1.8 GB

---

## Distribution via GitHub Releases

### Release Organization

**One GitHub release per geographic region:**

```
GitHub Releases:
├── na-west-coast-2025.08        (~1.85 GB, 245 packs)
├── na-east-coast-2025.08        (~1.92 GB, 312 packs)
├── na-midwest-2025.08           (~1.78 GB, 198 packs)
├── europe-western-2025.08       (~1.81 GB, 267 packs)
├── south-america-north-2025.08  (~1.45 GB, 156 packs)
└── ... (~100-300 total releases)
```

### Release Naming Convention

**Format:** `{region-slug}-{calver}`

- **region-slug**: Geographic identifier (generated after partitioning)
- **calver**: Calendar versioning (YYYY.MM format)

**Examples:**
- `na-west-coast-2025.08` - North America West Coast, August 2025
- `europe-western-2025.10` - Western Europe, October 2025
- `asia-southeast-2025.08` - Southeast Asia, August 2025

### Region Naming Strategy

After algorithmic partitioning, generate human-readable names:

```python
def name_region(region):
    """Generate human-readable region name from H3 cells."""

    # Calculate geographic center
    centroids = [h3.h3_to_geo(cell) for cell in region['h3_cells']]
    center_lat = sum(c[0] for c in centroids) / len(centroids)
    center_lon = sum(c[1] for c in centroids) / len(centroids)

    # Reverse geocode or use predefined mapping
    # Option 1: Use reverse geocoding service
    name = reverse_geocode(center_lat, center_lon)

    # Option 2: Use continent/subregion mapping
    continent = get_continent(center_lat, center_lon)
    subregion = get_subregion(center_lat, center_lon)
    name = f"{continent}-{subregion}"

    # Slugify for release name
    return name.lower().replace(' ', '-').replace('_', '-')
```

**Predefined geographic mappings** (examples):

```yaml
north_america:
  west_coast: [-125, -122, 32, 49]     # CA, OR, WA, BC
  east_coast: [-80, -70, 35, 45]       # NY, MA, NC, VA
  midwest: [-95, -80, 38, 48]          # IL, OH, MI, IN
  southwest: [-115, -100, 28, 37]      # AZ, NM, TX west

europe:
  western: [-10, 10, 40, 60]           # UK, FR, ES, PT
  central: [5, 20, 45, 55]             # DE, PL, CZ, AT
  northern: [10, 30, 55, 70]           # SE, NO, FI
```

### GitHub Releases Benefits

✅ **Free hosting** - No S3/CDN costs
✅ **Free bandwidth** - GitHub's CDN globally distributed
✅ **Version control** - CalVer releases track updates
✅ **API access** - Automated downloads via GitHub API
✅ **2GB per asset** - Plenty of room for 1.95 GB regions
✅ **Unlimited releases** - Can create as many as needed
✅ **Download statistics** - Track usage per region

---

## Pack Registry Structure

### Minimal Registry Design

**File:** `pack_registry.json` (~100-200 KB)

**Store only region boundaries, not individual packs:**

```json
{
  "version": "2025.08",
  "generated_at": "2025-08-15T00:00:00Z",
  "total_regions": 287,
  "total_packs": 8547,
  "total_size_gb": 67.3,

  "regions": [
    {
      "region_id": "na-west-coast",
      "h3_cells": [
        "8001fffffffffff",
        "8003fffffffffff",
        "8005fffffffffff"
      ],
      "resolution": 2,
      "release_name": "na-west-coast-2025.08",
      "total_size_mb": 1847,
      "pack_count": 245,
      "center": {"lat": 42.5, "lon": -122.0},
      "bbox": {
        "min_lat": 32.5,
        "max_lat": 49.0,
        "min_lon": -125.0,
        "max_lon": -115.0
      }
    },
    {
      "region_id": "europe-western",
      "h3_cells": [
        "801ffffffffffff",
        "8021fffffffffff"
      ],
      "resolution": 2,
      "release_name": "europe-western-2025.08",
      "total_size_mb": 1812,
      "pack_count": 267,
      "center": {"lat": 50.0, "lon": 2.5},
      "bbox": {
        "min_lat": 40.0,
        "max_lat": 60.0,
        "min_lon": -10.0,
        "max_lon": 10.0
      }
    }
  ]
}
```

### Registry Size Comparison

**Old approach (pack-level registry):**
- 8,547 packs × 200 bytes each = ~1.7 MB
- Contains redundant geographic data
- Complex lookup logic

**New approach (region-level registry):**
- 287 regions × 500 bytes each = ~144 KB
- One lookup per user location
- Simple H3 parent-child check

**Reduction: 92% smaller registry**

---

## Client Download Flow

### BirdNET-Pi Implementation

```python
import requests
import h3

def download_region_pack(lat, lon):
    """
    Download appropriate region pack for user's location.

    Args:
        lat: User's latitude
        lon: User's longitude

    Returns:
        Path to downloaded pack file
    """

    # Step 1: Fetch registry (cache locally, refresh weekly)
    registry_url = "https://raw.githubusercontent.com/USERNAME/birdnet-packs/main/pack_registry.json"
    registry = requests.get(registry_url).json()

    # Step 2: Calculate user's H3 cells at multiple resolutions
    user_cells = {
        res: h3.geo_to_h3(lat, lon, res)
        for res in range(0, 9)
    }

    # Step 3: Find matching region
    for region in registry['regions']:
        region_res = region['resolution']

        # Check if user's cell at that resolution matches any region cell
        user_cell_at_res = user_cells[region_res]

        if user_cell_at_res in region['h3_cells']:
            release_name = region['release_name']

            # Step 4: Download entire release
            download_url = (
                f"https://github.com/USERNAME/birdnet-packs/releases/download/"
                f"{release_name}/{release_name}.tar.gz"
            )

            # Download and extract
            local_path = download_and_extract(download_url)

            return local_path

    # No region found
    raise ValueError(f"No region pack available for ({lat}, {lon})")


def download_and_extract(url):
    """Download tar.gz release and extract all pack files."""
    import tarfile

    # Download
    response = requests.get(url, stream=True)
    tar_path = "/tmp/region_pack.tar.gz"

    with open(tar_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    # Extract to region_packs directory
    with tarfile.open(tar_path, 'r:gz') as tar:
        tar.extractall('/var/lib/birdnetpi/region_packs/')

    return '/var/lib/birdnetpi/region_packs/'
```

### Alternative: Individual Pack Downloads

Instead of bundling packs in tar.gz, upload each pack as individual release asset:

```python
def download_specific_pack(lat, lon):
    """Download only the specific pack for user's exact location."""

    # Find region
    region = find_region(lat, lon, registry)

    # Calculate user's pack boundary cell
    # (e.g., if data is res 7, boundary might be res 4)
    user_pack_cell = h3.geo_to_h3(lat, lon, res=7)
    pack_boundary = h3.h3_to_parent(user_pack_cell, res=4)

    # Download specific pack file
    pack_filename = f"h3-r4-{pack_boundary}-data-r7.db"
    download_url = (
        f"https://github.com/USERNAME/birdnet-packs/releases/download/"
        f"{region['release_name']}/{pack_filename}"
    )

    # Download single file
    response = requests.get(download_url)
    pack_path = f"/var/lib/birdnetpi/region_packs/{pack_filename}"

    with open(pack_path, 'wb') as f:
        f.write(response.content)

    return pack_path
```

**Trade-offs:**

| Approach | Pros | Cons |
|----------|------|------|
| **Bundled (tar.gz)** | Single download, all packs in region | Larger initial download |
| **Individual packs** | Minimal bandwidth, precise | Multiple HTTP requests |

**Recommendation:** Individual pack downloads with caching - users only download what they need.

---

## Implementation Roadmap

### Phase 1: Density Analysis Tool

**Goal:** Analyze eBird dataset and estimate pack sizes

**Deliverables:**
- [ ] `ebird-density-analyzer` Rust binary
- [ ] Streaming tar.gz reader for EBD
- [ ] Multi-resolution H3 aggregation (res 2-5)
- [ ] Checklist counting per cell
- [ ] Size estimation from density
- [ ] JSON output format

**Estimated effort:** 2-3 weeks

### Phase 2: Pack Planning Tool

**Goal:** Partition packs into GitHub-release-sized regions

**Deliverables:**
- [ ] `pack-planner` Python tool
- [ ] Greedy merge algorithm implementation
- [ ] H3 adjacency checking
- [ ] Region naming/slugification
- [ ] Pack manifest generation
- [ ] Region registry generation

**Estimated effort:** 1-2 weeks

### Phase 3: Enhanced Pack Generator

**Goal:** Generate packs from H3 cells instead of config files

**Deliverables:**
- [ ] Modify `ebird-builder` to accept `--boundary-cell`
- [ ] Auto-generate bounding box from H3 geometry
- [ ] Maintain existing filtering logic
- [ ] Auto-name output files
- [ ] Batch generation script

**Estimated effort:** 1 week

### Phase 4: Release Automation

**Goal:** Automate GitHub release creation and uploads

**Deliverables:**
- [ ] Release creation script (uses `gh` CLI)
- [ ] Pack upload to releases
- [ ] Registry update automation
- [ ] CalVer versioning
- [ ] CI/CD integration

**Estimated effort:** 1 week

### Phase 5: Client Integration

**Goal:** Update BirdNET-Pi to use new pack system

**Deliverables:**
- [ ] Registry fetch and caching
- [ ] H3-based region lookup
- [ ] Pack download logic
- [ ] Database loading updates
- [ ] Migration from old system

**Estimated effort:** 2-3 weeks (coordinate with BirdNET-Pi maintainers)

**Total estimated effort:** 7-10 weeks

---

## Appendix: Algorithms

### A. Size Estimation from Density

```python
def estimate_pack_size(cell_data):
    """
    Estimate pack database size from checklist density.

    Based on empirical measurements from prototype packs.
    """

    # Constants from empirical data
    BYTES_PER_SPECIES_RECORD = 400  # From db schema
    AVG_SPECIES_PER_HEX = 150
    COMPRESSION_RATIO = 0.7  # SQLite + gzip

    # Calculate data hexagons in pack
    boundary_res = cell_data['boundary_resolution']
    data_res = cell_data['data_resolution']
    resolution_diff = data_res - boundary_res
    num_data_hexagons = 7 ** resolution_diff  # H3 property

    # Estimate species records
    total_species_records = num_data_hexagons * AVG_SPECIES_PER_HEX

    # Calculate size
    raw_size_bytes = total_species_records * BYTES_PER_SPECIES_RECORD
    compressed_size_mb = (raw_size_bytes * COMPRESSION_RATIO) / 1_000_000

    return compressed_size_mb
```

### B. H3 Adjacency Check

```python
def are_adjacent_h3(cells_a, cells_b):
    """
    Check if two sets of H3 cells are adjacent.

    Two regions are adjacent if ANY cell in region A is a neighbor
    of ANY cell in region B.

    Args:
        cells_a: List of H3 cell IDs (strings)
        cells_b: List of H3 cell IDs (strings)

    Returns:
        True if regions are adjacent, False otherwise
    """

    for cell_a in cells_a:
        # Get all neighbors of cell_a
        neighbors = h3.k_ring(cell_a, 1)  # k=1 gives immediate neighbors

        # Check if any neighbor is in cells_b
        if any(neighbor in cells_b for neighbor in neighbors):
            return True

    return False
```

### C. Reverse Geocoding for Region Naming

```python
def name_region_from_cells(h3_cells):
    """
    Generate human-readable region name from H3 cells.

    Uses a combination of geographic center and predefined mappings.
    """

    # Calculate centroid
    centroids = [h3.h3_to_geo(cell) for cell in h3_cells]
    center_lat = sum(lat for lat, lon in centroids) / len(centroids)
    center_lon = sum(lon for lat, lon in centroids) / len(centroids)

    # Determine continent
    if -170 <= center_lon <= -50 and 15 <= center_lat <= 75:
        continent = "na"  # North America
    elif -20 <= center_lon <= 50 and 35 <= center_lat <= 70:
        continent = "europe"
    elif 60 <= center_lon <= 150 and -10 <= center_lat <= 55:
        continent = "asia"
    elif -85 <= center_lon <= -30 and -60 <= center_lat <= 15:
        continent = "sa"  # South America
    elif 10 <= center_lon <= 55 and -35 <= center_lat <= 35:
        continent = "africa"
    elif 110 <= center_lon <= 180 and -50 <= center_lat <= -10:
        continent = "oceania"
    else:
        continent = "unknown"

    # Determine subregion (simplified example)
    if continent == "na":
        if center_lon < -110:
            subregion = "west-coast"
        elif center_lon < -85:
            subregion = "midwest"
        else:
            subregion = "east-coast"
    elif continent == "europe":
        if center_lon < 10:
            subregion = "western"
        elif center_lon < 30:
            subregion = "central"
        else:
            subregion = "eastern"
    else:
        subregion = "main"

    return f"{continent}-{subregion}"
```

---

## References

- [H3 Geospatial Indexing System](https://h3geo.org/)
- [eBird Basic Dataset](https://ebird.org/data/download)
- [GitHub Releases Documentation](https://docs.github.com/en/repositories/releasing-projects-on-github)
- [BirdNET-Pi Repository](https://github.com/mcguirepr89/BirdNET-Pi)

---

**Document Status:** This is a design document. Implementation details may evolve as we build the tools and discover edge cases.

**Contributors:** [Your name/team]
**Review Status:** Draft
**Next Review:** After Phase 1 implementation
