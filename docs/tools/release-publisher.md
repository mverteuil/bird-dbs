# eBird Region Pack Release Publisher

Automated GitHub release publisher for eBird region pack databases.

## Overview

This tool automates the process of publishing regional eBird species packs to GitHub releases using bundled releases, including:

- Grouping region packs into ≤1950MB bundles using bin-packing algorithm
- Creating GitHub releases for each bundle
- Uploading `.db.gz` files as release assets
- Adding eBird dataset attribution to each release
- Updating registry with download URLs
- Uploading a global registry release for programmatic discovery

## Features

- **Idempotent**: Safe to run multiple times - skips existing releases and assets
- **Concurrent**: Uploads multiple regions in parallel (configurable workers)
- **Resumable**: Can restart from failures without re-uploading
- **Dry-run mode**: Preview changes before executing
- **Proper attribution**: Includes eBird citation in multiple formats for license compliance

## Prerequisites

1. **GitHub CLI (`gh`)** - Must be installed and authenticated
   ```bash
   # Install (macOS)
   brew install gh

   # Authenticate
   gh auth login
   ```

2. **Python 3.11+** with `uv` package manager

## Installation

```bash
cd release-publisher
uv sync
```

## Usage

### Dry Run (Preview)

```bash
uv run release-publisher \
  --registry /path/to/pack_registry.json \
  --db-dir /path/to/region-packs/ \
  --target-repo owner/birdnetpi-ebird-packs \
  --dry-run
```

### Actual Upload

```bash
uv run release-publisher \
  --registry /path/to/pack_registry.json \
  --db-dir /path/to/region-packs/ \
  --target-repo owner/birdnetpi-ebird-packs \
  --workers 16
```

### Options

- `--registry PATH`: Path to pack_registry.json (required)
- `--db-dir PATH`: Directory containing .db files (required)
- `--target-repo OWNER/REPO`: Target GitHub repository (required)
- `--workers N`: Number of concurrent upload workers (default: 8)
- `--dry-run`: Show what would be done without making changes
- `--skip-registry`: Skip uploading the global registry release

## Release Structure

Regions are bundled into releases of ≤1950MB using a bin-packing algorithm:

```
Release: pack-bundle-001-2025.08
Assets:
  - africa-east-2025.08.db.gz (gzipped species database)
  - africa-west-2025.08.db.gz
  - europe-north-2025.08.db.gz
  - ... (more regions)
  - ATTRIBUTION.txt (eBird citation and terms)
```

Each bundle:
- Contains multiple region `.db.gz` files
- Stays under 1950MB total size
- Includes eBird attribution
- Lists all included regions in the release description

Plus one global registry release:

```
Release: registry-2025.08
Assets:
  - pack_registry_with_urls.json (complete region index with download URLs)
```

The registry includes `download_url` for each region pointing to the specific bundle containing that region.

## eBird Attribution

The tool ensures proper attribution for the eBird Basic Dataset and Sampling Dataset:

1. **In release descriptions**: Citation included in each release's notes
2. **ATTRIBUTION.txt**: Detailed attribution file uploaded with each release
3. **In databases**: Attribution embedded in `region_metadata` table (by ebird-builder)
4. **Target repo README**: Auto-generated attribution section (manual step)

## Example Output

```
eBird Region Pack Release Publisher

📄 Loading registry from pack_registry.json
  Found 47 regions

🔧 Initializing GitHub client for owner/birdnetpi-ebird-packs
  ✓ gh CLI authenticated

📦 Collected 47 region files
  Total size: 45678.9 MB

📊 Created 24 release bundles:
  pack-bundle-001-2025.08: 8 regions, 1947.2 MB
  pack-bundle-002-2025.08: 6 regions, 1935.4 MB
  pack-bundle-003-2025.08: 7 regions, 1948.8 MB
  ...

Uploading 24 bundle releases
  Workers: 8
  Dry run: False

  ✓ Created release pack-bundle-001-2025.08
  ✓ Uploaded africa-east-2025.08.db.gz (234.5 MB)
  ✓ Uploaded africa-west-2025.08.db.gz (189.2 MB)
  ...
  ✓ Uploaded ATTRIBUTION.txt

Updating registry with download URLs
  Updated 47 of 47 regions
  ✓ Saved updated registry to pack_registry_with_urls.json

Creating registry release: registry-2025.08
  ✓ Created registry release
  ✓ Uploaded pack_registry_with_urls.json

📊 Summary
  Bundles created: 24
  Bundles skipped: 0
  Regions with download URLs: 47

✅ Upload complete!
```

## Architecture

```
release-publisher/
├── src/release_publisher/
│   ├── cli.py           # Click CLI interface
│   ├── manifest.py      # Pack registry parsing (Pydantic models)
│   ├── bundler.py       # Bin-packing algorithm for bundled releases
│   ├── attribution.py   # eBird citation generation
│   ├── github.py        # gh CLI wrapper
│   └── uploader.py      # Concurrent bundle upload logic
└── pyproject.toml
```

### Key Components

- **bundler.py**: Implements first-fit-decreasing bin packing to group region files into ≤1950MB bundles
- **uploader.py**: Processes bundles concurrently, uploads all regions in each bundle, and tracks download URLs
- **manifest.py**: Pydantic models for pack registry including `download_url` field for each region pointing to the GitHub release asset
- **cli.py**: Orchestrates the workflow: bundle → upload → update registry → upload registry

## Development

```bash
# Install development dependencies
uv sync

# Run linters
uv run pre-commit run --all-files

# Run with local registry
uv run release-publisher --registry ./pack_registry.json --db-dir ./test-packs/ --target-repo test/test-repo --dry-run
```

## License

This tool is part of the BirdNET-Pi ecosystem. The eBird data it publishes is subject to the [eBird Terms of Use](https://www.birds.cornell.edu/home/ebird-data-access-terms-of-use/).
