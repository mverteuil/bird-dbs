# BirdNET-Pi Avibase ID Mapping Extractor

An R package to extract Avibase ID mappings from the `avilistr` R package and export them to CSV format for use by other BirdNET-Pi extractors.

## Overview

This package provides the **critical link** between IOC scientific names and stable Avibase IDs by extracting mapping data from the [avilistr](https://cran.r-project.org/package=avilistr) R package. The avilistr package maintains mappings between different taxonomic authorities (IOC, Clements, eBird, etc.) via stable Avibase identifiers.

### Why This Exists

The IOC World Bird List taxonomy changes annually (species splits, lumps, name changes), which makes direct species name matching fragile. Avibase provides stable identifiers that persist across taxonomic revisions, enabling:

1. **Cross-taxonomy mapping**: Link IOC names to eBird, Clements, and other authorities
2. **Historical continuity**: Track species across name changes and splits
3. **Wikidata integration**: Connect to external knowledge bases via stable IDs

### Extractor Pipeline

```
avilistr-builder → CSV → ioc-builder → SQLite
                      ↘
                        wikidata-builder → SQLite
```

## Features

- **Automatic extraction**: Pulls data from installed avilistr R package
- **Authority filtering**: Select which taxonomies to include (IOC, Clements, eBird)
- **Validation**: Built-in checks for data completeness and quality
- **CSV export**: Simple, portable format for downstream consumers
- **Test coverage**: Comprehensive testthat unit tests with covr integration
- **Code quality**: lintr and styler for consistent R code style

## Installation

### Prerequisites

- R >= 4.0.0
- The avilistr R package
- Development dependencies (testthat, covr, lintr, styler)

### Install Dependencies

```bash
make install
```

Or manually:

```r
install.packages(c('devtools', 'testthat', 'covr', 'lintr', 'styler'),
                 repos='https://cloud.r-project.org')
install.packages('avilistr', repos='https://cloud.r-project.org')
devtools::install('.', dependencies=TRUE)
```

## Usage

### Basic Usage

```r
library(avilistBuilder)

# Extract to default location (../shared/avilistr/avilistr_mapping.csv)
extract_avilistr_mapping()
```

### Advanced Usage

```r
# Extract specific taxonomic authorities
extract_avilistr_mapping(
  output_path = "output/custom_mapping.csv",
  authorities = c("ioc", "clements"),  # Only IOC and Clements
  verbose = TRUE
)

# Get package information
info <- get_avilistr_info()
print(info$version)

# Validate extracted data
validation <- validate_mapping("output/custom_mapping.csv", min_species = 10000)
print(validation)
```

### Command Line Usage

```bash
# Extract using default settings
make extract

# Validate the output
make validate
```

## Output Format

The exported CSV contains:

- `scientific_name`: Primary scientific name from avilistr
- `avibase_id`: Stable Avibase identifier (e.g., "52F89CC1A4C51E11")
- `ioc_scientific_name`: IOC taxonomy name (if requested)
- `clements_scientific_name`: Clements taxonomy name (if requested)
- `ebird_scientific_name`: eBird taxonomy name (if requested)

### Example Output

```csv
scientific_name,avibase_id,ioc_scientific_name,clements_scientific_name
Struthio camelus,3E9C6C1ED831C49E,Struthio camelus,Struthio camelus
Rhea americana,8C9C9E9D9A3F4B2A,Rhea americana,Rhea americana
...
```

## Functions

### `extract_avilistr_mapping()`

Main extraction function. Loads the avilistr birdlist dataset and exports to CSV.

**Parameters:**
- `output_path`: Path to output CSV file (default: `../shared/avilistr/avilistr_mapping.csv`)
- `authorities`: Character vector of taxonomies to include (default: `c("ioc", "clements", "ebird")`)
- `verbose`: Print progress messages (default: `TRUE`)

**Returns:** Tibble with mapping data (invisibly)

### `get_avilistr_info()`

Returns version and metadata about the installed avilistr package.

**Returns:** List with:
- `installed`: Logical - whether avilistr is installed
- `version`: Character - package version
- `description`: Character - package description

### `validate_mapping(csv_path, min_species = 10000)`

Validates the extracted CSV for completeness and quality.

**Parameters:**
- `csv_path`: Path to CSV file to validate
- `min_species`: Minimum expected number of species (default: 10000)

**Returns:** List (class `avilistr_validation`) with validation results

### `print.avilistr_validation(x, ...)`

Pretty-prints validation results.

## Testing

### Running Tests

```bash
# Run all testthat unit tests
make test

# Or use R directly
Rscript -e "devtools::test()"
```

### Test Coverage

The project uses `covr` for code coverage reporting.

```bash
# Terminal coverage summary
make coverage

# HTML coverage report (opens in browser)
make coverage-html
```

### Test Suite

The test suite (`tests/testthat/test-extract_avilistr.R`) covers:

- ✅ CSV file creation and content validation
- ✅ Authority filtering (IOC, Clements, eBird)
- ✅ NA avibase_id removal
- ✅ Output directory creation
- ✅ Verbose/quiet modes
- ✅ Graceful failure when avilistr is missing
- ✅ Package info retrieval
- ✅ CSV validation (valid and invalid cases)
- ✅ Missing column detection
- ✅ Species count validation
- ✅ Print method for validation results

### Code Quality

```bash
# Run lintr checks
make lint

# Format code with styler
make format
```

## Integration with Other Builders

### ioc-builder

The ioc-builder consumes the avilistr mapping CSV to link IOC species to Avibase IDs:

```python
# In ioc-builder
mapping_df = pd.read_csv("../shared/avilistr/avilistr_mapping.csv")
ioc_to_avibase = dict(zip(mapping_df["ioc_scientific_name"],
                          mapping_df["avibase_id"]))
```

### wikidata-builder

The wikidata-builder uses Avibase IDs to query Wikidata for additional metadata:

```python
# In wikidata-builder
avibase_id = "52F89CC1A4C51E11"
wikidata_query = f"""
SELECT ?item ?itemLabel WHERE {{
  ?item wdt:P2026 "{avibase_id}" .  # Avibase ID property
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
}}
"""
```

## Development Workflow

1. **Make changes** to R code
2. **Format** with `make format`
3. **Lint** with `make lint`
4. **Test** with `make test`
5. **Check coverage** with `make coverage`
6. **Extract** with `make extract` to verify output
7. **Validate** with `make validate` to check quality

### Pre-commit Hooks

Pre-commit hooks run automatically before each commit:

- `styler`: Formats R code to tidyverse style
- `lintr`: Checks code quality and style
- `parsable-R`: Ensures R files are syntactically valid
- `no-browser-statement`: Prevents debug statements from being committed

Install hooks:

```bash
# In repository root
pre-commit install
```

## Validation Criteria

The `validate_mapping()` function checks:

1. **File exists**: CSV file is present
2. **Row count**: Sufficient species records
3. **Has avibase_id column**: Critical identifier present
4. **Has scientific_name column**: Primary name present
5. **Has IOC mapping**: IOC taxonomy column present (if requested)
6. **Missing avibase_ids**: No NA values in avibase_id
7. **Unique avibase_ids**: Count of unique identifiers
8. **Meets minimum**: Row count ≥ `min_species` parameter

### Example Validation Output

```
Avilistr Mapping Validation
===========================

✓ File exists: TRUE
✓ Row count: 15342
✓ Has avibase_id column: TRUE
✓ Has scientific_name column: TRUE
✓ Has IOC mapping: TRUE
✓ Missing Avibase IDs: 0
✓ Unique Avibase IDs: 15342
✓ Meets minimum species count: TRUE

Overall validation: PASSED ✓
```

## Project Structure

```
avilistr-builder/
├── DESCRIPTION           # R package metadata
├── Makefile             # Development task automation
├── README.md            # This file
├── .lintr               # lintr configuration
├── .Rbuildignore        # Files to exclude from R package build
├── R/
│   └── extract_avilistr.R  # Main extraction functions
├── tests/
│   ├── testthat.R       # Test runner
│   └── testthat/
│       └── test-extract_avilistr.R  # Unit tests
└── output/              # CSV output directory (gitignored)
```

## Output Location

By default, the CSV is written to `../shared/avilistr/avilistr_mapping.csv`, which makes it accessible to all extractors in the monorepo:

```
BirdNET-Pi-extractors/
├── avilistr-builder/    # This package
├── ioc-builder/         # Consumes avilistr CSV
├── wikidata-builder/    # Consumes avilistr CSV
├── ebird-builder/       # May consume in future
└── shared/
    └── avilistr/
        └── avilistr_mapping.csv  # Shared output
```

## Troubleshooting

### avilistr Package Not Found

```r
Error: Package 'avilistr' is required but not installed.
```

**Solution:**
```r
install.packages('avilistr', repos='https://cloud.r-project.org')
```

### Empty or Missing Output

If the CSV is empty or has fewer species than expected:

1. Check avilistr package version: `get_avilistr_info()`
2. Verify avilistr has data: `data("birdlist", package="avilistr"); nrow(birdlist)`
3. Run validation: `validate_mapping("path/to/output.csv")`

### Test Failures

If tests fail with "avilistr not installed":

1. Install avilistr: `install.packages('avilistr')`
2. Tests use `skip_if_not_installed("avilistr")` to gracefully skip when missing

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make help` | Show available targets |
| `make install` | Install package and dependencies |
| `make test` | Run testthat unit tests |
| `make coverage` | Generate coverage report (terminal) |
| `make coverage-html` | Generate HTML coverage report |
| `make lint` | Run lintr code quality checks |
| `make format` | Format code with styler |
| `make clean` | Remove output and coverage artifacts |
| `make all` | Run tests, coverage, and linting |
| `make build` | Build R package tarball |
| `make check` | Run R CMD check (CRAN-style) |
| `make extract` | Run extraction with default settings |
| `make validate` | Validate output CSV |

## License

TBD

## Acknowledgments

- **Avibase** - Denis Lepage - Comprehensive bird database and stable identifiers
- **avilistr R Package** - Provides programmatic access to Avibase mappings
- **Cornell Lab of Ornithology** - eBird taxonomy
- **IOC World Bird List** - International Ornithological Congress taxonomy
- **Clements Checklist** - Clements/eBird taxonomy

## Version History

### 0.1.0 (Initial Release)

- Extract Avibase ID mappings from avilistr package
- Support for IOC, Clements, and eBird taxonomies
- Validation and quality checks
- Comprehensive test coverage with testthat
- Code quality tooling (lintr, styler)
- Pre-commit hooks integration
