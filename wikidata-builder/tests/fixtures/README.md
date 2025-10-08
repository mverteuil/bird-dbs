# Test Fixtures for Wikidata Builder

This directory contains sample data files for testing the Wikidata database builder.

## Mock Data

Wikidata builder tests use **mocked API responses** rather than fixture files, since the data comes from live SPARQL queries.

## Sample Response Structures

### Species Query Response

```json
{
  "results": {
    "bindings": [
      {
        "species": {"value": "http://www.wikidata.org/entity/Q123"},
        "avibaseID": {"value": "ABC123DEF456"},
        "scientificName": {"value": "Struthio camelus"}
      }
    ]
  }
}
```

### Multilingual Labels Query Response

```json
{
  "results": {
    "bindings": [
      {
        "species": {"value": "http://www.wikidata.org/entity/Q123"},
        "label": {"value": "Common Ostrich"},
        "lang": {"value": "en"}
      }
    ]
  }
}
```

## Testing Strategy

1. **Unit tests**: Use mocked SPARQL responses (see `test_wikidata_database_builder.py`)
2. **Integration tests**: Use `@pytest.mark.integration` for tests requiring actual Wikidata API access
3. **Scientific name filtering**: Critical test - verify fallbacks are excluded

## Running Tests

```bash
# Run all tests (with mocks)
pytest

# Run only unit tests (skip integration)
pytest -m "not integration"

# Run integration tests (requires internet)
pytest -m integration
```
