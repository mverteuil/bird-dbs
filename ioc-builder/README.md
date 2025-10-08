# IOC Reference Builder

Build IOC World Bird List reference database with multilingual translations (44 languages).

## Requirements

- **Python:** 3.8+
- **R:** For Excel file processing
- **Package Manager:** uv (recommended) or pip
- **Data Sources:**
  - IOC Excel files (manual download)
  - Avilistr world bird list

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

# Install R dependencies
Rscript -e "install.packages(c('tidyverse', 'readxl'))"
```

### Alternative: Using pip

```bash
pip install -e .

# Or with development dependencies
pip install -e ".[dev]"
```

## Usage

### 1. Download Source Data

See `../scripts/collect_source_data.sh` for automated data collection.

**Manual download:**

1. **IOC Excel files:**
   - Visit: https://www.worldbirdnames.org/
   - Download: `IOC_Names_File_Plus-XX.X.xlsx`
   - Download: `IOC_Multiling_Names_File-XX.X.xlsx`
   - Save to: `../data/ioc/`

2. **Avilistr world bird list:**
   - Visit: https://avibase.bsc-eoc.org/checklist.jsp
   - Select: World, All taxonomies, CSV export
   - Save to: `../shared/avilistr/world_birds_YYYY-MM-DD.csv`

### 2. Build Database

```bash
uv run python ioc_database_builder.py \
  --ioc-path ../data/ioc/IOC_Names_File_Plus-14.2.xlsx \
  --multilingual-path ../data/ioc/IOC_Multiling_Names_File-14.2.xlsx \
  --avilistr-path ../shared/avilistr/world_birds_2025-10-08.csv \
  --output ../output/ioc_reference.db
```

### 3. Validate Output

```bash
# Check database size and contents
sqlite3 ../output/ioc_reference.db "SELECT COUNT(*) FROM species;"
sqlite3 ../output/ioc_reference.db "SELECT COUNT(*) FROM translations;"
sqlite3 ../output/ioc_reference.db "SELECT COUNT(DISTINCT language_code) FROM translations;"
```

**Expected output:**
- Database size: ~51 MB
- Species count: ~11,250
- Translation count: ~297,000
- Languages: 44

## Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=. --cov-report=html

# Run specific test
uv run pytest tests/test_ioc_database_builder.py -v
```

## Database Schema

### `species` table

| Column | Type | Description |
|--------|------|-------------|
| `avibase_id` | TEXT PRIMARY KEY | Stable Avibase identifier |
| `scientific_name` | TEXT NOT NULL | Scientific name (IOC taxonomy) |
| `english_name` | TEXT NOT NULL | English common name |
| `order` | TEXT NOT NULL | Taxonomic order |
| `family` | TEXT NOT NULL | Taxonomic family |
| `genus` | TEXT NOT NULL | Genus |
| `species` | TEXT NOT NULL | Species epithet |

### `translations` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Auto-increment ID |
| `avibase_id` | TEXT NOT NULL | Foreign key to species |
| `language_code` | TEXT NOT NULL | ISO 639-1 language code |
| `common_name` | TEXT NOT NULL | Translated common name |

**Indexes:**
- `idx_translations_avibase_id` on `avibase_id`
- `idx_translations_language_code` on `language_code`

## Languages

44 languages with excellent coverage (>10,000 translations each):

- Afrikaans (af), Bulgarian (bg), Catalan (ca), Czech (cs), Danish (da)
- German (de), English (en), Spanish (es), Estonian (et), Finnish (fi)
- French (fr), Galician (gl), Croatian (hr), Hungarian (hu), Icelandic (is)
- Italian (it), Japanese (ja), Lithuanian (lt), Latvian (lv), Dutch (nl)
- Norwegian (no), Polish (pl), Portuguese (pt), Romanian (ro), Russian (ru)
- Slovak (sk), Slovenian (sl), Serbian (sr), Swedish (sv), Turkish (tr)
- Ukrainian (uk), Chinese (zh)
- And more...

## Troubleshooting

### Import Error: No module named 'ioc_database_builder'

```bash
# Install in development mode
uv pip install -e .
```

### R packages not found

```bash
# Install R dependencies
Rscript -e "install.packages(c('tidyverse', 'readxl'))"
```

### Excel file parsing errors

Check that you downloaded the correct IOC version files. The builder expects:
- `IOC_Names_File_Plus-XX.X.xlsx` (species data)
- `IOC_Multiling_Names_File-XX.X.xlsx` (translations)

### Missing Avibase IDs

Species without Avibase ID mappings in Avilistr will be excluded from the final database. This is expected for newly described species.

## Contributing

See [../docs/testing-guide.md](../docs/testing-guide.md) for testing documentation.

## License

Code: [Same as BirdNET-Pi]
Data: IOC World Bird List (CC-BY-4.0) - Attribution required

**Citation:**
Gill F, D Donsker & P Rasmussen (Eds). 2024. IOC World Bird List (vXX.X). doi:10.14344/IOC.ML.XX.X
