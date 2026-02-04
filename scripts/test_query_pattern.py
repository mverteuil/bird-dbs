#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "h3>=3.7.0",
# ]
# ///
"""
Test BirdNET-Pi query patterns against a region pack database.

Verifies the proposed schema supports BirdNET-Pi's actual query patterns efficiently.
Benchmarks single species lookup, neighbor search, and temporal joins.

Performance targets:
- Single lookup: <1ms
- Neighbor search (7 cells): <5ms
- Works on Raspberry Pi 4 (limited resources)

Query patterns tested:
1. Single cell lookup (exact match)
2. Neighbor search (H3 ring distance)
3. Species name lookup
4. Monthly/quarterly/yearly frequency joins
"""

import argparse
import sqlite3
import statistics
import time
from pathlib import Path

import h3


def format_duration(ms: float) -> str:
    """Format milliseconds as human-readable duration."""
    if ms < 1:
        return f"{ms * 1000:.1f} µs"
    elif ms < 1000:
        return f"{ms:.2f} ms"
    else:
        return f"{ms / 1000:.2f} s"


def benchmark(func, iterations: int = 100):
    """Run function multiple times and return timing statistics."""
    times = []
    result = None

    # Warmup
    for _ in range(5):
        result = func()

    # Actual benchmark
    for _ in range(iterations):
        start = time.perf_counter()
        result = func()
        elapsed_ms = (time.perf_counter() - start) * 1000
        times.append(elapsed_ms)

    return {
        "min": min(times),
        "max": max(times),
        "mean": statistics.mean(times),
        "median": statistics.median(times),
        "stdev": statistics.stdev(times) if len(times) > 1 else 0,
        "result": result,
    }


def get_sample_data(conn: sqlite3.Connection) -> dict:
    """Get sample data from database for testing."""
    # Get a random cell with data
    cell = conn.execute("""
        SELECT h3_cell FROM grid_species
        ORDER BY RANDOM() LIMIT 1
    """).fetchone()

    if not cell:
        raise ValueError("No data in grid_species table")

    h3_cell = cell[0]

    # Get a species in that cell
    species = conn.execute("""
        SELECT sl.scientific_name, sl.avibase_id
        FROM grid_species gs
        JOIN species_lookup sl ON gs.avibase_id = sl.avibase_id
        WHERE gs.h3_cell = ?
        ORDER BY RANDOM() LIMIT 1
    """, (h3_cell,)).fetchone()

    if not species:
        raise ValueError("No species data found")

    scientific_name, avibase_id = species

    # Convert cell to hex for H3 operations
    h3_cell_hex = format(h3_cell, 'x')

    return {
        "h3_cell": h3_cell,
        "h3_cell_hex": h3_cell_hex,
        "avibase_id": avibase_id,
        "scientific_name": scientific_name,
    }


def test_single_cell_lookup(
    conn: sqlite3.Connection,
    h3_cell: int,
    avibase_id: str,
    month: int = 5,
) -> tuple[dict | None, float]:
    """
    Pattern 1: Single cell lookup with temporal data.

    This is the query that runs when checking confidence for a detection.
    """
    query = """
        SELECT gs.confidence_tier, gs.confidence_boost, gs.yearly_frequency,
               gs.quality_score, gsm.frequency as month_frequency
        FROM grid_species gs
        LEFT JOIN grid_species_monthly gsm
            ON gs.h3_cell = gsm.h3_cell
            AND gs.avibase_id = gsm.avibase_id
            AND gsm.month = ?
        WHERE gs.h3_cell = ? AND gs.avibase_id = ?
    """

    start = time.perf_counter()
    cursor = conn.execute(query, (month, h3_cell, avibase_id))
    row = cursor.fetchone()
    elapsed_ms = (time.perf_counter() - start) * 1000

    if row:
        result = {
            "confidence_tier": row[0],
            "confidence_boost": row[1],
            "yearly_frequency": row[2],
            "quality_score": row[3],
            "month_frequency": row[4],
        }
    else:
        result = None

    return result, elapsed_ms


def test_neighbor_search(
    conn: sqlite3.Connection,
    h3_cell_hex: str,
    avibase_id: str,
    max_rings: int = 2,
    month: int = 5,
) -> tuple[list, float]:
    """
    Pattern 2: Neighbor search with distance-based confidence.

    Searches the user's cell and surrounding rings for species data.
    """
    # Get neighbor cells
    neighbor_cells = {h3_cell_hex}
    for k in range(1, max_rings + 1):
        neighbor_cells.update(h3.grid_ring(h3_cell_hex, k))

    # Convert to integers
    neighbor_cells_int = [int(cell, 16) for cell in neighbor_cells]

    # Build query with parameter placeholders
    placeholders = ",".join("?" * len(neighbor_cells_int))
    query = f"""
        SELECT gs.h3_cell, gs.confidence_tier, gs.confidence_boost,
               gs.yearly_frequency, gsm.frequency as month_frequency
        FROM grid_species gs
        LEFT JOIN grid_species_monthly gsm
            ON gs.h3_cell = gsm.h3_cell
            AND gs.avibase_id = gsm.avibase_id
            AND gsm.month = ?
        WHERE gs.h3_cell IN ({placeholders})
            AND gs.avibase_id = ?
    """

    params = [month] + neighbor_cells_int + [avibase_id]

    start = time.perf_counter()
    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    elapsed_ms = (time.perf_counter() - start) * 1000

    results = []
    for row in rows:
        cell_hex = format(row[0], 'x')
        distance = h3.grid_distance(h3_cell_hex, cell_hex)
        results.append({
            "h3_cell": cell_hex,
            "distance": distance,
            "confidence_tier": row[1],
            "confidence_boost": row[2],
            "yearly_frequency": row[3],
            "month_frequency": row[4],
        })

    return results, elapsed_ms


def test_species_lookup(
    conn: sqlite3.Connection,
    scientific_name: str,
) -> tuple[str | None, float]:
    """
    Pattern 3: Species name to avibase_id lookup.

    This is used to translate BirdNET species names to database IDs.
    """
    query = """
        SELECT avibase_id
        FROM species_lookup
        WHERE scientific_name = ?
    """

    start = time.perf_counter()
    cursor = conn.execute(query, (scientific_name,))
    row = cursor.fetchone()
    elapsed_ms = (time.perf_counter() - start) * 1000

    return row[0] if row else None, elapsed_ms


def has_table(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check if a table exists in the database."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cursor.fetchone() is not None


def test_full_temporal_lookup(
    conn: sqlite3.Connection,
    h3_cell: int,
    avibase_id: str,
    month: int = 5,
) -> tuple[dict | None, float]:
    """
    Pattern 4: Full lookup with monthly, quarterly, and yearly temporal data.

    This matches the full BirdNET-Pi query with all temporal tables.
    Handles both full and compact pack formats.
    """
    quarter = ((month - 1) // 3) + 1

    # Check if we have the full or compact format
    has_quarterly = has_table(conn, "grid_species_quarterly")
    has_yearly = has_table(conn, "grid_species_yearly")

    if has_quarterly and has_yearly:
        # Full format with all temporal tables
        query = """
            SELECT
                gs.h3_cell,
                gs.confidence_tier,
                gs.confidence_boost as base_boost,
                gs.yearly_frequency,
                gs.quality_score,
                gsm.frequency as month_frequency,
                gsq.frequency as quarter_frequency,
                gsy.frequency as year_frequency
            FROM grid_species gs
            LEFT JOIN grid_species_monthly gsm
                ON gs.h3_cell = gsm.h3_cell
                AND gs.avibase_id = gsm.avibase_id
                AND gsm.month = ?
            LEFT JOIN grid_species_quarterly gsq
                ON gs.h3_cell = gsq.h3_cell
                AND gs.avibase_id = gsq.avibase_id
                AND gsq.quarter = ?
            LEFT JOIN grid_species_yearly gsy
                ON gs.h3_cell = gsy.h3_cell
                AND gs.avibase_id = gsy.avibase_id
            WHERE gs.h3_cell = ?
                AND gs.avibase_id = ?
        """
        params = (month, quarter, h3_cell, avibase_id)
    else:
        # Compact format - only monthly, compute others from that
        query = """
            SELECT
                gs.h3_cell,
                gs.confidence_tier,
                gs.confidence_boost as base_boost,
                gs.yearly_frequency,
                gs.quality_score,
                gsm.frequency as month_frequency,
                NULL as quarter_frequency,
                gs.yearly_frequency as year_frequency
            FROM grid_species gs
            LEFT JOIN grid_species_monthly gsm
                ON gs.h3_cell = gsm.h3_cell
                AND gs.avibase_id = gsm.avibase_id
                AND gsm.month = ?
            WHERE gs.h3_cell = ?
                AND gs.avibase_id = ?
        """
        params = (month, h3_cell, avibase_id)

    start = time.perf_counter()
    cursor = conn.execute(query, params)
    row = cursor.fetchone()
    elapsed_ms = (time.perf_counter() - start) * 1000

    if row:
        result = {
            "h3_cell": format(row[0], 'x'),
            "confidence_tier": row[1],
            "base_boost": row[2],
            "yearly_frequency": row[3],
            "quality_score": row[4],
            "month_frequency": row[5],
            "quarter_frequency": row[6],
            "year_frequency": row[7],
        }
    else:
        result = None

    return result, elapsed_ms


def print_query_plan(conn: sqlite3.Connection, query: str, params: tuple) -> None:
    """Print SQLite query plan for analysis."""
    plan_query = f"EXPLAIN QUERY PLAN {query}"
    cursor = conn.execute(plan_query, params)
    print("  Query Plan:")
    for row in cursor.fetchall():
        print(f"    {row}")


def run_benchmarks(conn: sqlite3.Connection, iterations: int = 100) -> dict:
    """Run all benchmarks and return results."""
    sample = get_sample_data(conn)

    print(f"\nTest Data:")
    print(f"  H3 Cell: {sample['h3_cell_hex']}")
    print(f"  Species: {sample['scientific_name']}")
    print(f"  Avibase ID: {sample['avibase_id']}")
    print()

    results = {}

    # Test 1: Single cell lookup
    print("=" * 60)
    print("Test 1: Single Cell Lookup")
    print("=" * 60)

    def single_lookup():
        return test_single_cell_lookup(
            conn, sample["h3_cell"], sample["avibase_id"], month=5
        )

    stats = benchmark(lambda: single_lookup()[1], iterations)
    result, _ = single_lookup()

    print(f"  Result: {result}")
    print(f"  Timing ({iterations} iterations):")
    print(f"    Min: {format_duration(stats['min'])}")
    print(f"    Max: {format_duration(stats['max'])}")
    print(f"    Mean: {format_duration(stats['mean'])}")
    print(f"    Median: {format_duration(stats['median'])}")
    print(f"  Target: <1ms → {'PASS' if stats['median'] < 1 else 'FAIL'}")
    results["single_lookup"] = stats
    print()

    # Test 2: Neighbor search
    print("=" * 60)
    print("Test 2: Neighbor Search (2 rings)")
    print("=" * 60)

    def neighbor_search():
        return test_neighbor_search(
            conn, sample["h3_cell_hex"], sample["avibase_id"],
            max_rings=2, month=5
        )

    stats = benchmark(lambda: neighbor_search()[1], iterations)
    result, _ = neighbor_search()

    print(f"  Found {len(result)} cells with data")
    if result:
        print(f"  Closest: distance={result[0]['distance']}, tier={result[0]['confidence_tier']}")
    print(f"  Timing ({iterations} iterations):")
    print(f"    Min: {format_duration(stats['min'])}")
    print(f"    Max: {format_duration(stats['max'])}")
    print(f"    Mean: {format_duration(stats['mean'])}")
    print(f"    Median: {format_duration(stats['median'])}")
    print(f"  Target: <5ms → {'PASS' if stats['median'] < 5 else 'FAIL'}")
    results["neighbor_search"] = stats
    print()

    # Test 3: Species lookup
    print("=" * 60)
    print("Test 3: Species Name Lookup")
    print("=" * 60)

    def species_lookup():
        return test_species_lookup(conn, sample["scientific_name"])

    stats = benchmark(lambda: species_lookup()[1], iterations)
    result, _ = species_lookup()

    print(f"  Result: {result}")
    print(f"  Timing ({iterations} iterations):")
    print(f"    Min: {format_duration(stats['min'])}")
    print(f"    Max: {format_duration(stats['max'])}")
    print(f"    Mean: {format_duration(stats['mean'])}")
    print(f"    Median: {format_duration(stats['median'])}")
    print(f"  Target: <1ms → {'PASS' if stats['median'] < 1 else 'FAIL'}")
    results["species_lookup"] = stats
    print()

    # Test 4: Full temporal lookup
    print("=" * 60)
    print("Test 4: Full Temporal Lookup (monthly + quarterly + yearly)")
    print("=" * 60)

    def full_lookup():
        return test_full_temporal_lookup(
            conn, sample["h3_cell"], sample["avibase_id"], month=5
        )

    stats = benchmark(lambda: full_lookup()[1], iterations)
    result, _ = full_lookup()

    print(f"  Result: {result}")
    print(f"  Timing ({iterations} iterations):")
    print(f"    Min: {format_duration(stats['min'])}")
    print(f"    Max: {format_duration(stats['max'])}")
    print(f"    Mean: {format_duration(stats['mean'])}")
    print(f"    Median: {format_duration(stats['median'])}")
    print(f"  Target: <1ms → {'PASS' if stats['median'] < 1 else 'FAIL'}")
    results["full_temporal"] = stats

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Test BirdNET-Pi query patterns against region pack database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="Path to region pack SQLite database",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help="Number of iterations for benchmarking",
    )
    parser.add_argument(
        "--show-plans",
        action="store_true",
        help="Show SQLite query plans",
    )

    args = parser.parse_args()

    if not args.database.exists():
        print(f"Error: Database not found: {args.database}")
        return 1

    # Connect to database
    conn = sqlite3.connect(args.database)

    # Enable WAL mode for better read performance
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # Get database info
    print("=" * 60)
    print("DATABASE INFO")
    print("=" * 60)
    print(f"Path: {args.database}")
    print(f"Size: {args.database.stat().st_size / (1024 * 1024):.2f} MB")

    # Table counts
    tables = ["grid_species", "grid_species_monthly", "grid_species_quarterly",
              "grid_species_yearly", "species_lookup"]
    print("\nTable row counts:")
    for table in tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table}: {count:,}")
        except sqlite3.OperationalError:
            print(f"  {table}: (not found)")

    # Run benchmarks
    results = run_benchmarks(conn, args.iterations)

    # Summary
    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)

    all_pass = True
    for name, stats in results.items():
        target = 5 if name == "neighbor_search" else 1
        passed = stats["median"] < target
        all_pass = all_pass and passed
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {format_duration(stats['median'])} median [{status}]")

    print()
    if all_pass:
        print("ALL TESTS PASSED - Schema supports BirdNET-Pi query patterns")
    else:
        print("SOME TESTS FAILED - Review query performance")

    conn.close()
    return 0 if all_pass else 1


if __name__ == "__main__":
    exit(main())
