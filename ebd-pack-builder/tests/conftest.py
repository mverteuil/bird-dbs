"""Pytest fixtures for ebd-pack-builder tests."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for pipeline state."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return state_dir


@pytest.fixture
def sample_boundary_cells(tmp_path: Path) -> Path:
    """Create a sample boundary_cells.json for testing."""
    data = {
        "cells": [
            {
                "boundary_cell": "842b9bdffffffff",
                "boundary_cell_int": 596538839548346367,
                "observation_count": 1000000,
                "checklist_count": 100000,
                "species_count": 500,
                "lat_min": 43.5,
                "lat_max": 44.5,
                "lon_min": -80.0,
                "lon_max": -79.0,
            },
            {
                "boundary_cell": "842b9adffffffff",
                "boundary_cell_int": 596538822368477183,
                "observation_count": 500000,
                "checklist_count": 50000,
                "species_count": 400,
                "lat_min": 43.0,
                "lat_max": 44.0,
                "lon_min": -79.5,
                "lon_max": -78.5,
            },
        ]
    }

    path = tmp_path / "boundary_cells.json"
    with open(path, "w") as f:
        json.dump(data, f)

    return path


@pytest.fixture
def sample_pack_manifest(tmp_path: Path) -> Path:
    """Create a sample pack manifest for testing."""
    data = {
        "regions": [
            {
                "region_id": "test-region-1",
                "center": {"lat": 44.0, "lon": -79.5},
                "packs": [
                    {"boundary_cell": "842b9bdffffffff"},
                    {"boundary_cell": "842b9adffffffff"},
                ],
            }
        ],
        "total_regions": 1,
        "data_resolutions": [5, 4, 2],
        "resolution_penalties": {"5": 1.0, "4": 0.8, "2": 0.5},
    }

    path = tmp_path / "pack_manifest.json"
    with open(path, "w") as f:
        json.dump(data, f)

    return path
