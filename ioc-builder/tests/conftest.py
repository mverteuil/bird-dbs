"""Shared test fixtures for IOC builder tests."""

import pytest
import tempfile
from pathlib import Path


@pytest.fixture(scope="session")
def test_data_dir():
    """Path to test data fixtures."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
