"""Verify integrity of Parquet datasets.

Checks:
- File readability (Parquet footer intact)
- Row counts
- Schema consistency across files in a directory
- Comparison between datasets
"""

from pathlib import Path

import duckdb


def verify_directory(dir_path: Path, verbose: bool = False) -> dict | None:
    """Verify a directory of Parquet files.

    Args:
        dir_path: Directory to verify
        verbose: Show per-file details

    Returns:
        Dict with stats, or None if verification failed
    """
    print(f"\nVerifying: {dir_path}")
    print("-" * 60)

    if not dir_path.exists():
        print("  Directory does not exist")
        return None

    # Find all Parquet files (exclude macOS resource fork files)
    parquet_files = sorted(f for f in dir_path.glob("*.parquet") if not f.name.startswith("._"))

    if not parquet_files:
        print("  No .parquet files found")
        return None

    print(f"  Files found: {len(parquet_files)}")

    con = duckdb.connect()
    total_rows = 0
    total_size = 0
    schemas: list[tuple[str, list]] = []
    failed_files: list[tuple[str, str]] = []

    for pf in parquet_files:
        try:
            # Try to read file (verifies footer is intact)
            result = con.execute(f"SELECT COUNT(*) FROM read_parquet('{pf}')").fetchone()
            row_count = result[0] if result else 0
            total_rows += row_count

            # Get file size
            file_size = pf.stat().st_size
            total_size += file_size

            # Get schema
            schema_result = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{pf}')").fetchall()
            schemas.append((pf.name, schema_result))

            if verbose:
                print(f"    {pf.name}: {row_count:,} rows, {file_size / 1e6:.1f} MB")

        except Exception as e:
            failed_files.append((pf.name, str(e)))
            print(f"    FAILED {pf.name}: {e}")

    if failed_files:
        print(f"\n  {len(failed_files)} files failed verification:")
        for name, error in failed_files:
            print(f"     - {name}: {error}")
        return None

    # Check schema consistency
    if schemas:
        first_schema = schemas[0][1]
        inconsistent = []
        for name, schema in schemas[1:]:
            if schema != first_schema:
                inconsistent.append(name)

        if inconsistent:
            print(f"\n  WARNING: Schema inconsistency in {len(inconsistent)} files")
            if verbose:
                for name in inconsistent[:5]:
                    print(f"     - {name}")

    # Summary
    total_size_gb = total_size / (1024**3)
    print(f"\n  All {len(parquet_files)} files verified successfully")
    print(f"  Total rows: {total_rows:,}")
    print(f"  Total size: {total_size_gb:.2f} GB")

    # Get column count from first schema
    col_count = len(schemas[0][1]) if schemas else 0
    print(f"  Columns: {col_count}")

    return {
        "path": str(dir_path),
        "files": len(parquet_files),
        "rows": total_rows,
        "size_bytes": total_size,
        "columns": col_count,
    }


def compare_datasets(stats_list: list[dict]) -> bool:
    """Compare row counts across datasets.

    Args:
        stats_list: List of verification stats dicts

    Returns:
        True if all counts match the first dataset
    """
    if len(stats_list) < 2:
        return True

    print("\n" + "=" * 60)
    print("COMPARISON SUMMARY")
    print("=" * 60)

    # Find max width for formatting
    max_name_len = max(len(Path(s["path"]).name) for s in stats_list)

    print(f"\n{'Dataset':<{max_name_len}}  {'Rows':>15}  {'Size (GB)':>10}  {'Files':>6}")
    print("-" * (max_name_len + 40))

    for stats in stats_list:
        name = Path(stats["path"]).name
        rows = stats["rows"]
        size_gb = stats["size_bytes"] / (1024**3)
        files = stats["files"]
        print(f"{name:<{max_name_len}}  {rows:>15,}  {size_gb:>10.2f}  {files:>6}")

    # Check if all row counts match the first
    reference_rows = stats_list[0]["rows"]
    all_match = all(s["rows"] == reference_rows for s in stats_list)

    print()
    if all_match:
        print("All datasets have matching row counts")
    else:
        print("WARNING: Row counts differ between datasets!")
        for stats in stats_list:
            if stats["rows"] != reference_rows:
                diff = stats["rows"] - reference_rows
                sign = "+" if diff > 0 else ""
                print(f"   {Path(stats['path']).name}: {sign}{diff:,} rows vs reference")

    return all_match


def verify_parquet_integrity(
    directories: list[Path],
    verbose: bool = False,
) -> dict:
    """Verify integrity of one or more Parquet directories.

    Args:
        directories: List of directories to verify
        verbose: Show per-file details

    Returns:
        Dict with verification results
    """
    all_stats = []
    any_failed = False

    for dir_path in directories:
        stats = verify_directory(dir_path, verbose=verbose)
        if stats is None:
            any_failed = True
        else:
            all_stats.append(stats)

    # Compare if multiple directories
    counts_match = True
    if len(all_stats) > 1:
        counts_match = compare_datasets(all_stats)
        if not counts_match:
            any_failed = True

    print()
    if any_failed:
        print("Verification completed with errors")
    else:
        print("All verifications passed")

    return {
        "passed": not any_failed,
        "directories_verified": len(all_stats),
        "counts_match": counts_match,
        "stats": all_stats,
    }
