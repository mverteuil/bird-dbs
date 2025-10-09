"""Shared test fixtures for Wikidata builder tests."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests


@pytest.fixture(scope="session")
def test_data_dir():
    """Path to test data fixtures."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(scope="session")
def target_languages():
    """Target languages for Wikidata extraction."""
    return ["nb", "eu", "zh-hans", "zh-hant"]


@pytest.fixture
def http_response_factory():
    """Factory for creating mock HTTP responses with common patterns."""

    def _create_response(
        status_code=200,
        content=b"test content",
        json_data=None,
        raise_for_status_error=None,
    ):
        response = MagicMock(spec=requests.Response)
        response.status_code = status_code
        response.content = content

        if json_data is not None:
            response.json = MagicMock(spec=callable, return_value=json_data)

        if raise_for_status_error:
            response.raise_for_status = MagicMock(spec=callable, side_effect=raise_for_status_error)
        else:
            response.raise_for_status = MagicMock(spec=callable)

        return response

    return _create_response


@pytest.fixture
def temp_db():
    """Create a temporary database for testing with automatic cleanup."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def sparql_response_factory():
    """Factory for creating SPARQL query responses."""

    def _create_response(bindings=None):
        if bindings is None:
            bindings = []

        return {"results": {"bindings": bindings}}

    return _create_response


@pytest.fixture
def sample_sparql_species_response():
    """Sample SPARQL response for species query."""
    return {
        "results": {
            "bindings": [
                {
                    "species": {"value": "http://www.wikidata.org/entity/Q123"},
                    "avibaseID": {"value": "ABC123DEF456"},
                    "scientificName": {"value": "Struthio camelus"},
                },
                {
                    "species": {"value": "http://www.wikidata.org/entity/Q456"},
                    "avibaseID": {"value": "GHI789JKL012"},
                    "scientificName": {"value": "Thalassarche eremita"},
                },
            ]
        }
    }


@pytest.fixture
def sample_sparql_labels_response():
    """Sample SPARQL response for multilingual labels query."""
    return {
        "results": {
            "bindings": [
                # Real translations
                {
                    "species": {"value": "http://www.wikidata.org/entity/Q123"},
                    "label": {"value": "Common Ostrich"},
                    "lang": {"value": "en"},
                },
                {
                    "species": {"value": "http://www.wikidata.org/entity/Q123"},
                    "label": {"value": "Avestruz Común"},
                    "lang": {"value": "es"},
                },
                # Scientific name fallback (should be filtered)
                {
                    "species": {"value": "http://www.wikidata.org/entity/Q456"},
                    "label": {"value": "Thalassarche eremita"},
                    "lang": {"value": "es"},
                },
                # Real translation
                {
                    "species": {"value": "http://www.wikidata.org/entity/Q456"},
                    "label": {"value": "Chatham Albatross"},
                    "lang": {"value": "en"},
                },
            ]
        }
    }
