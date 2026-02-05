"""Parquet file utilities."""

from pathlib import Path


def get_parquet_files(parquet_dir: Path) -> list[str]:
    """Get list of parquet files, excluding macOS extended attribute files.

    Args:
        parquet_dir: Directory containing parquet files

    Returns:
        Sorted list of parquet file paths as strings
    """
    files = sorted(parquet_dir.glob("*.parquet"))
    return [str(f) for f in files if not f.name.startswith("._")]
