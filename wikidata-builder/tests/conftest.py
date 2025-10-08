"""Shared test fixtures for Wikidata builder tests."""

import tempfile
from pathlib import Path

import pytest


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
