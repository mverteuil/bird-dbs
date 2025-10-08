# Wikidata Reference Builder

Build supplemental translation database from Wikidata for languages not in IOC.

## Requirements

- **Python:** 3.8+
- **Package Manager:** uv (recommended) or pip
- **Internet:** Required for SPARQL API queries
- **Data Sources:**
  - Wikidata SPARQL API (live queries)

## Installation

### Install uv (recommended)

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or via pip
pip install uv
```

### Install Dependencies

```bash
# Install Python dependencies using uv
uv sync

# Or install in development mode with test dependencies
uv sync --extra dev
```

### Alternative: Using pip

```bash
pip install -e .

# Or with development dependencies
pip install -e ".[dev]"
```

## Usage

### 1. Full Extraction (Recommended)

Extract all ~10,500 bird species with Avibase IDs:

```bash
uv run python run_wikidata_poc.py \
  --full \
  --output ../output/wikidata_reference.db
```

**Expected runtime:** 30-60 minutes (API rate limited)

**Expected output:**
- Database size: ~5-7 MB
- Species count: ~10,500
- Translation count: ~10,000 (4 languages)
- Languages: 4 (nb, eu, zh-hans, zh-hant)

### 2. Sample Extraction (Testing)

Extract first 100 species for testing:

```bash
uv run python run_wikidata_poc.py \
  --limit 100 \
  --output ../output/wikidata_sample.db
```

**Expected runtime:** 2-5 minutes

### 3. Validate Output

```bash
sqlite3 ../output/wikidata_reference.db "SELECT COUNT(*) FROM species;"
sqlite3 ../output/wikidata_reference.db "SELECT COUNT(*) FROM translations;"
sqlite3 ../output/wikidata_reference.db "SELECT language_code, COUNT(*) FROM translations GROUP BY language_code;"
```

## Database Schema

### `species` table

| Column | Type | Description |
|--------|------|-------------|
| `avibase_id` | TEXT PRIMARY KEY | Stable Avibase identifier |
| `wikidata_id` | TEXT NOT NULL | Wikidata entity ID (e.g., Q123) |
| `scientific_name` | TEXT NOT NULL | Scientific name |

### `translations` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Auto-increment ID |
| `avibase_id` | TEXT NOT NULL | Foreign key to species |
| `language_code` | TEXT NOT NULL | ISO 639 language code |
| `common_name` | TEXT NOT NULL | Translated common name |

**Indexes:**
- `idx_translations_avibase_id` on `avibase_id`
- `idx_translations_language_code` on `language_code`

## Target Languages

Only 4 languages unique to Wikidata (not in IOC):

| Language | Code | Avg Translations | Quality |
|----------|------|------------------|---------|
| Norwegian Bokmål | nb | ~2,500 | Excellent |
| Basque | eu | ~700 | Good |
| Chinese Simplified | zh-hans | ~670 | Good |
| Chinese Traditional | zh-hant | ~670 | Good |

**Total:** ~10,000 real translations (after filtering scientific name fallbacks)

## Scientific Name Fallback Filtering

**Critical:** 59% of Wikidata "translations" are scientific name fallbacks (useless data).

Example:
```
Thalassarche eremita | es | Thalassarche eremita  ❌ Filtered out
Thalassarche eremita | de | Chatham-Albatros      ✓ Kept
```

The builder automatically filters these out to provide only real translations.

See [../docs/wikidata-data-quality-issue.md](../docs/wikidata-data-quality-issue.md) for full analysis.

## Testing

```bash
# Run all tests (uses mocked API responses)
uv run pytest

# Run only unit tests (exclude integration tests)
uv run pytest -m "not integration"

# Run with coverage
uv run pytest --cov=. --cov-report=html

# Run integration tests (requires internet)
uv run pytest -m integration
```

## Advanced Usage

### Custom Language Selection

Edit `TARGET_LANGUAGES` in `wikidata_database_builder.py`:

```python
TARGET_LANGUAGES = [
    "nb",        # Norwegian Bokmål
    "eu",        # Basque
    "zh-hans",   # Chinese Simplified
    "zh-hant",   # Chinese Traditional
]
```

### Debugging API Queries

```bash
# Enable verbose logging
export LOGLEVEL=DEBUG
uv run python run_wikidata_poc.py --limit 10 --output test.db
```

### Custom SPARQL Queries

See `wikidata_database_builder.py`:
- `_build_species_query()` - Query species with Avibase IDs
- `_build_labels_query()` - Query multilingual labels

## API Rate Limits

Wikidata SPARQL endpoint has rate limits:
- Queries limited to ~60 seconds execution time
- Batch processing used to avoid timeouts
- Automatic retry on transient failures

**Tips:**
- Run during off-peak hours for faster responses
- Use `--limit` for testing before full extraction
- Expect 30-60 minutes for full extraction

## Troubleshooting

### Import Error: No module named 'wikidata_database_builder'

```bash
# Install in development mode
uv pip install -e .
```

### API Timeout Errors

```
SPARQLWrapper: Query execution timeout
```

**Solutions:**
- Retry - transient timeouts are common
- Reduce batch size in `_query_multilingual_labels()`
- Run during off-peak hours

### Empty Translations

Check that `TARGET_LANGUAGES` includes languages actually present in Wikidata. Some languages have very few translations.

### Test Failures with API Mocking

Unit tests use mocked API responses. Integration tests require internet:

```bash
# Skip integration tests
uv run pytest -m "not integration"
```

## Data Quality

**Before filtering:** 13,484 "translations" (including fallbacks)
**After filtering:** ~10,000 real translations (59% filtered out)

**Coverage by language (after filtering):**
- Norwegian Bokmål: ~2,500 species (excellent)
- Basque: ~700 species (good)
- Chinese Simplified: ~670 species (good)
- Chinese Traditional: ~670 species (good)

## Contributing

See [../docs/testing-guide.md](../docs/testing-guide.md) for testing documentation.

See [../docs/wikidata-corrected-analysis.md](../docs/wikidata-corrected-analysis.md) for data quality analysis.

## License

Code: [Same as BirdNET-Pi]
Data: Wikidata (CC0 - Public Domain)
