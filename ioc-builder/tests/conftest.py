"""Shared test fixtures for IOC builder tests."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
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
def sample_ioc_species_data():
    """Factory for creating sample IOC species test data."""
    return pd.DataFrame(
        {
            "Order": ["STRUTHIONIFORMES", "STRUTHIONIFORMES"],
            "Family": ["Struthionidae", "Struthionidae"],
            "Genus": ["Struthio", "Struthio"],
            "Species": ["camelus", "molybdophanes"],
            "English name": ["Common Ostrich", "Somali Ostrich"],
            "Authority": ["Linnaeus, 1758", "Reichenow, 1883"],
        }
    )


@pytest.fixture
def sample_ioc_multilingual_data():
    """Factory for creating sample IOC multilingual translation data."""
    return pd.DataFrame(
        {
            "Scientific name": [
                "Struthio camelus",
                "Struthio camelus",
                "Struthio molybdophanes",
                "Struthio molybdophanes",
            ],
            "LanguageCode": ["es", "fr", "es", "fr"],
            "CommonName": [
                "Avestruz Común",
                "Autruche d'Afrique",
                "Avestruz Somalí",
                "Autruche de Somalie",
            ],
        }
    )


@pytest.fixture
def sample_avilistr_data():
    """Factory for creating sample Avilistr data with Avibase ID mappings."""
    return pd.DataFrame(
        {
            "scientific_name": ["Struthio camelus", "Struthio molybdophanes"],
            "avibase_id": ["ABC123DEF456", "GHI789JKL012"],
            "ioc_scientific_name": ["Struthio camelus", "Struthio molybdophanes"],
            "clements_scientific_name": ["Struthio camelus", "Struthio molybdophanes"],
        }
    )
