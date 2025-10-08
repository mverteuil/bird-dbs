# Testing Guide

**Comprehensive testing documentation for BirdNET-Pi database extractors**

---

## Overview

This repository includes comprehensive test suites for all three database builders:

1. **IOC Builder** (Python + pytest)
2. **Wikidata Builder** (Python + pytest)
3. **eBird Builder** (Rust + cargo test)

---

## Quick Start

### IOC Builder Tests

```bash
cd ioc-builder

# Install dependencies (including test dependencies)
pip install -r requirements.txt

# Run all tests
pytest

# Run with coverage report
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_ioc_database_builder.py

# Run specific test
pytest tests/test_ioc_database_builder.py::TestIOCDatabaseBuilder::test_parse_species_data
```

### Wikidata Builder Tests

```bash
cd wikidata-builder

# Install dependencies
pip install -r requirements.txt

# Run all tests (uses mocked API responses)
pytest

# Run only unit tests (exclude integration tests)
pytest -m "not integration"

# Run with coverage
pytest --cov=. --cov-report=html

# View coverage report
open htmlcov/index.html
```

### eBird Builder Tests

```bash
cd ebird-builder

# Run all tests
cargo test

# Run with output
cargo test -- --nocapture

# Run specific test
cargo test test_parse_date_valid

# Run tests in specific module
cargo test ebird::tests

# Run with coverage (requires cargo-tarpaulin)
cargo install cargo-tarpaulin
cargo tarpaulin --out Html
```

---

## Test Structure

### IOC Builder

```
ioc-builder/
├── tests/
│   ├── __init__.py
│   ├── conftest.py                    # Shared fixtures
│   ├── test_ioc_database_builder.py   # Main builder tests
│   └── fixtures/
│       ├── README.md
│       └── sample_avilistr.csv        # Sample Avibase mappings
├── pytest.ini                         # Pytest configuration
└── requirements.txt                   # Includes pytest
```

**Test Coverage:**
- ✅ Excel parsing (species + multilingual)
- ✅ Avilistr mapping
- ✅ Database creation
- ✅ Translation extraction
- ✅ Data validation
- ✅ Duplicate handling
- ✅ Case-insensitive matching

### Wikidata Builder

```
wikidata-builder/
├── tests/
│   ├── __init__.py
│   ├── conftest.py                         # Shared fixtures
│   ├── test_wikidata_database_builder.py   # Main builder tests
│   └── fixtures/
│       └── README.md                       # Mock data documentation
├── pytest.ini
└── requirements.txt
```

**Test Coverage:**
- ✅ SPARQL query construction
- ✅ Scientific name fallback filtering (CRITICAL)
- ✅ Avibase ID extraction
- ✅ Database creation
- ✅ Language filtering
- ✅ API error handling
- ✅ Duplicate handling

### eBird Builder

```
ebird-builder/
└── src/
    ├── ebird/
    │   ├── mod.rs
    │   ├── record.rs
    │   └── tests.rs        # eBird record tests
    └── h3/
        ├── mod.rs
        ├── aggregator.rs
        ├── grid.rs
        └── tests.rs        # H3 aggregation tests
```

**Test Coverage:**
- ✅ CSV record parsing
- ✅ Record filtering (approved, complete, native, species)
- ✅ H3 grid operations
- ✅ H3 aggregation
- ✅ Species classification (common, uncommon, rare, vagrant)
- ✅ Monthly frequency calculation
- ✅ Data quality classification

---

## Test Categories

### Unit Tests

Test individual functions and methods in isolation.

```bash
# Python
pytest -m unit

# Rust
cargo test --lib
```

### Integration Tests

Test interactions between components or with external systems.

```bash
# Python (requires API access for Wikidata)
pytest -m integration

# Rust
cargo test --test '*'
```

### Slow Tests

Tests that take >1 second to run.

```bash
# Skip slow tests for quick feedback
pytest -m "not slow"
```

---

## Critical Test Cases

### 1. Scientific Name Fallback Filtering (Wikidata)

**Why critical:** 59% of Wikidata "translations" are scientific name fallbacks (useless data)

**Test:**
```python
def test_filter_scientific_name_fallbacks(builder):
    """Verify that labels matching scientific names are filtered out."""
    species_data = [{
        "wikidata_id": "Q456",
        "avibase_id": "GHI789",
        "scientific_name": "Thalassarche eremita",
    }]

    labels = [
        {"wikidata_id": "Q456", "language_code": "es", "common_name": "Thalassarche eremita"},  # Fallback
        {"wikidata_id": "Q456", "language_code": "de", "common_name": "Chatham-Albatros"},      # Real
    ]

    # Filter should remove scientific name
    filtered = [l for l in labels if l["common_name"] != species_data[0]["scientific_name"]]

    assert len(filtered) == 1
    assert filtered[0]["common_name"] == "Chatham-Albatros"
```

### 2. Avibase ID Mapping (IOC + eBird)

**Why critical:** Stable identifiers across taxonomic changes

**Test:**
```python
def test_map_avibase_ids(builder, sample_ioc_species_data, sample_avilistr_data):
    """Verify that IOC species are correctly mapped to Avibase IDs."""
    species_list = builder._parse_species_data(sample_ioc_species_data)
    mapped = builder._map_avibase_ids(species_list, sample_avilistr_data)

    assert mapped[0]["avibase_id"] == "ABC123DEF456"
```

### 3. H3 Grid Consistency (eBird)

**Why critical:** Ensures reproducible geographic indexing

**Test:**
```rust
#[test]
fn test_h3_grid_same_location_same_cell() {
    let grid = H3Grid::new(8).unwrap();
    let cell1 = grid.lat_lon_to_cell(42.3601, -71.0589).unwrap();
    let cell2 = grid.lat_lon_to_cell(42.3602, -71.0590).unwrap();

    // Very close coordinates should map to same cell
    assert_eq!(cell1, cell2);
}
```

### 4. Species Filtering (eBird)

**Why critical:** Ensures only valid observations are included

**Test:**
```rust
#[test]
fn test_record_filtering_chain() {
    let record = sample_record();

    assert!(record.is_approved());
    assert!(record.is_complete_checklist());
    assert!(record.is_native());
    assert!(record.is_species());
}
```

---

## Coverage Goals

### Target Coverage

- **IOC Builder:** >80% line coverage
- **Wikidata Builder:** >85% line coverage (critical filtering logic)
- **eBird Builder:** >75% line coverage

### Generating Coverage Reports

**Python (pytest-cov):**
```bash
pytest --cov=. --cov-report=html --cov-report=term-missing
open htmlcov/index.html
```

**Rust (cargo-tarpaulin):**
```bash
cargo install cargo-tarpaulin
cargo tarpaulin --out Html --output-dir coverage
open coverage/index.html
```

---

## Continuous Integration

### Recommended CI Workflow

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test-ioc:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install R
        run: sudo apt-get install -y r-base
      - name: Install dependencies
        run: |
          cd ioc-builder
          pip install -r requirements.txt
      - name: Run tests
        run: |
          cd ioc-builder
          pytest --cov=. --cov-report=xml
      - uses: codecov/codecov-action@v3

  test-wikidata:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          cd wikidata-builder
          pip install -r requirements.txt
      - name: Run tests
        run: |
          cd wikidata-builder
          pytest -m "not integration" --cov=. --cov-report=xml
      - uses: codecov/codecov-action@v3

  test-ebird:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions-rs/toolchain@v1
        with:
          toolchain: stable
      - name: Run tests
        run: |
          cd ebird-builder
          cargo test --verbose
```

---

## Troubleshooting

### Python Tests Fail with Import Errors

**Problem:** `ModuleNotFoundError: No module named 'ioc_database_builder'`

**Solution:**
```bash
# Install package in development mode
cd ioc-builder
pip install -e .
```

Or add parent directory to PYTHONPATH:
```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
pytest
```

### Wikidata Tests Timeout

**Problem:** Integration tests hit Wikidata API rate limits

**Solution:**
```bash
# Skip integration tests
pytest -m "not integration"

# Or increase timeout in pytest.ini
[pytest]
timeout = 300
```

### Rust Tests Fail with Missing Dependencies

**Problem:** `error: could not compile h3o`

**Solution:**
```bash
# Update Rust toolchain
rustup update stable

# Clean and rebuild
cargo clean
cargo build
cargo test
```

### Coverage Report Not Generated

**Problem:** `pytest --cov` produces no report

**Solution:**
```bash
# Ensure pytest-cov is installed
pip install pytest-cov

# Use explicit coverage config
pytest --cov=. --cov-config=.coveragerc
```

---

## Best Practices

### 1. Test Naming

Use descriptive test names that explain what is being tested:

```python
# Good
def test_filter_scientific_name_fallbacks()

# Bad
def test_filtering()
```

### 2. Fixtures Over Setup/Teardown

Use pytest fixtures for reusable test data:

```python
@pytest.fixture
def sample_species():
    return {"avibase_id": "ABC123", "scientific_name": "Test species"}

def test_something(sample_species):
    assert sample_species["avibase_id"] == "ABC123"
```

### 3. Test One Thing

Each test should verify one specific behavior:

```python
# Good
def test_is_approved_true()
def test_is_approved_false()

# Bad
def test_all_filters()  # Tests 10 different things
```

### 4. Mock External Dependencies

Don't hit real APIs in unit tests:

```python
@patch("wikidata_database_builder.SPARQLWrapper")
def test_query_species_data(mock_sparql, builder):
    mock_wrapper = MagicMock()
    mock_wrapper.query.return_value.convert.return_value = {"results": {...}}
    mock_sparql.return_value = mock_wrapper

    # Test uses mocked data
    species_data = builder._query_species_data()
```

### 5. Use Test Markers

Organize tests with markers:

```python
@pytest.mark.slow
def test_full_database_build():
    # Long-running test
    pass

@pytest.mark.integration
def test_wikidata_api():
    # Requires API access
    pass
```

---

## Writing New Tests

### Template: Python Test

```python
import pytest
from my_module import MyClass

@pytest.fixture
def my_instance():
    """Create test instance."""
    return MyClass(param="test")

class TestMyClass:
    """Tests for MyClass."""

    def test_method_returns_expected_value(self, my_instance):
        """Test that method returns expected value."""
        result = my_instance.my_method()
        assert result == "expected"

    def test_method_raises_on_invalid_input(self, my_instance):
        """Test that method raises error on invalid input."""
        with pytest.raises(ValueError):
            my_instance.my_method(invalid="input")
```

### Template: Rust Test

```rust
#[cfg(test)]
mod tests {
    use super::*;

    fn sample_data() -> MyStruct {
        MyStruct {
            field: "test".to_string(),
        }
    }

    #[test]
    fn test_method_returns_expected_value() {
        let data = sample_data();
        let result = data.my_method();
        assert_eq!(result, "expected");
    }

    #[test]
    #[should_panic(expected = "invalid input")]
    fn test_method_panics_on_invalid_input() {
        let data = sample_data();
        data.my_method_that_panics();
    }
}
```

---

## Additional Resources

- **pytest documentation:** https://docs.pytest.org/
- **Rust testing guide:** https://doc.rust-lang.org/book/ch11-00-testing.html
- **Coverage.py:** https://coverage.readthedocs.io/
- **cargo-tarpaulin:** https://github.com/xd009642/tarpaulin

---

**Last Updated:** 2025-10-08
