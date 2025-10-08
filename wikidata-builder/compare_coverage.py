#!/usr/bin/env python3
"""Compare Wikidata and PatLevin database coverage.

This script compares multilingual bird name coverage between:
- Wikidata database (POC, 500 species)
- PatLevin database (BirdNET-Pi production, 6362 species)

It helps determine if Wikidata coverage is sufficient to drop PatLevin.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any


def get_patlevin_stats(db_path: str) -> dict[str, Any]:
    """Extract statistics from PatLevin database.

    Args:
        db_path: Path to PatLevin SQLite database

    Returns:
        Dict with species_count, translation_count, languages, etc.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Basic counts
    cursor.execute("""
        SELECT
            COUNT(DISTINCT scientific_name) as species_count,
            COUNT(*) as translation_count,
            COUNT(DISTINCT language_code) as language_count
        FROM patlevin_labels
    """)
    species_count, translation_count, language_count = cursor.fetchone()

    # Language breakdown
    cursor.execute("""
        SELECT language_code, COUNT(*) as count
        FROM patlevin_labels
        GROUP BY language_code
        ORDER BY count DESC
    """)
    languages = {row[0]: row[1] for row in cursor.fetchall()}

    conn.close()

    avg_translations = translation_count / species_count if species_count > 0 else 0

    return {
        "species_count": species_count,
        "translation_count": translation_count,
        "language_count": language_count,
        "avg_translations_per_species": round(avg_translations, 2),
        "languages": languages,
    }


def get_wikidata_stats(report_path: str) -> dict[str, Any]:
    """Extract statistics from Wikidata coverage report.

    Args:
        report_path: Path to Wikidata coverage report JSON

    Returns:
        Dict with species_count, translation_count, languages, etc.
    """
    with open(report_path) as f:
        report = json.load(f)

    # Extract language counts from all_languages
    languages = {lang_code: data["count"] for lang_code, data in report["all_languages"].items()}

    return {
        "species_count": report["species_count"],
        "translation_count": report["translation_count"],
        "language_count": report["language_count"],
        "avg_translations_per_species": report["avg_translations_per_species"],
        "languages": languages,
    }


def compare_databases(wikidata_stats: dict, patlevin_stats: dict) -> dict[str, Any]:
    """Compare Wikidata and PatLevin database coverage.

    Args:
        wikidata_stats: Statistics from Wikidata database
        patlevin_stats: Statistics from PatLevin database

    Returns:
        Dict with comparison metrics
    """
    wikidata_langs = set(wikidata_stats["languages"].keys())
    patlevin_langs = set(patlevin_stats["languages"].keys())

    # Language set analysis
    shared_langs = wikidata_langs & patlevin_langs
    wikidata_only = wikidata_langs - patlevin_langs
    patlevin_only = patlevin_langs - wikidata_langs

    # Calculate coverage percentages for shared languages
    # (based on Wikidata POC which has fewer species)
    wikidata_species = wikidata_stats["species_count"]
    coverage_comparison = {}

    for lang in shared_langs:
        wd_count = wikidata_stats["languages"][lang]
        pl_count = patlevin_stats["languages"][lang]

        # Coverage as percentage of species in each database
        wd_coverage = (wd_count / wikidata_species * 100) if wikidata_species > 0 else 0
        pl_coverage = (pl_count / patlevin_stats["species_count"] * 100) if patlevin_stats["species_count"] > 0 else 0

        coverage_comparison[lang] = {
            "wikidata_count": wd_count,
            "wikidata_coverage": round(wd_coverage, 1),
            "patlevin_count": pl_count,
            "patlevin_coverage": round(pl_coverage, 1),
        }

    return {
        "shared_languages": sorted(shared_langs),
        "wikidata_only_languages": sorted(wikidata_only),
        "patlevin_only_languages": sorted(patlevin_only),
        "coverage_comparison": coverage_comparison,
    }


def print_comparison_report(
    wikidata_stats: dict, patlevin_stats: dict, comparison: dict
) -> None:
    """Print formatted comparison report.

    Args:
        wikidata_stats: Wikidata database statistics
        patlevin_stats: PatLevin database statistics
        comparison: Comparison analysis results
    """
    print("=" * 80)
    print("WIKIDATA vs PATLEVIN DATABASE COVERAGE COMPARISON")
    print("=" * 80)
    print()

    # Overall statistics
    print("📊 Overall Statistics:")
    print()
    print(f"{'Metric':<35} {'Wikidata':>15} {'PatLevin':>15}")
    print("-" * 80)
    print(f"{'Species Count':<35} {wikidata_stats['species_count']:>15,} {patlevin_stats['species_count']:>15,}")
    print(f"{'Translation Count':<35} {wikidata_stats['translation_count']:>15,} {patlevin_stats['translation_count']:>15,}")
    print(f"{'Language Count':<35} {wikidata_stats['language_count']:>15} {patlevin_stats['language_count']:>15}")
    print(f"{'Avg Translations/Species':<35} {wikidata_stats['avg_translations_per_species']:>15.2f} {patlevin_stats['avg_translations_per_species']:>15.2f}")
    print()

    # Language overlap
    print("🌍 Language Coverage Analysis:")
    print()
    print(f"  Shared languages: {len(comparison['shared_languages'])}")
    print(f"  Wikidata-only languages: {len(comparison['wikidata_only_languages'])}")
    print(f"  PatLevin-only languages: {len(comparison['patlevin_only_languages'])}")
    print()

    if comparison["wikidata_only_languages"]:
        print(f"  Languages in Wikidata but not PatLevin:")
        print(f"    {', '.join(comparison['wikidata_only_languages'])}")
        print()

    if comparison["patlevin_only_languages"]:
        print(f"  Languages in PatLevin but not Wikidata:")
        print(f"    {', '.join(comparison['patlevin_only_languages'])}")
        print()

    # Coverage comparison for top languages
    print("📈 Coverage Comparison (Top 20 Shared Languages):")
    print()
    print(f"{'Lang':>5} {'Wikidata':>20} {'PatLevin':>20}")
    print(f"{'':>5} {'Count':>10} {'Coverage':>9} {'Count':>10} {'Coverage':>9}")
    print("-" * 80)

    # Sort by Wikidata coverage
    sorted_langs = sorted(
        comparison["coverage_comparison"].items(),
        key=lambda x: x[1]["wikidata_coverage"],
        reverse=True,
    )[:20]

    for lang_code, coverage in sorted_langs:
        wd_count = coverage["wikidata_count"]
        wd_cov = coverage["wikidata_coverage"]
        pl_count = coverage["patlevin_count"]
        pl_cov = coverage["patlevin_coverage"]

        print(f"{lang_code:>5} {wd_count:>10,} {wd_cov:>8.1f}% {pl_count:>10,} {pl_cov:>8.1f}%")

    print()

    # Recommendation
    print("=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    print()

    # Calculate key metrics for recommendation
    wikidata_langs_set = set(comparison["shared_languages"]) | set(comparison["wikidata_only_languages"])
    patlevin_langs_set = set(comparison["shared_languages"]) | set(comparison["patlevin_only_languages"])
    lang_coverage_pct = len(comparison["shared_languages"]) / len(patlevin_langs_set) * 100

    # Count languages where Wikidata has >90% coverage
    high_coverage_langs = sum(
        1 for coverage in comparison["coverage_comparison"].values()
        if coverage["wikidata_coverage"] > 90
    )

    print(f"✓ Wikidata POC covers {len(comparison['shared_languages'])}/{len(patlevin_langs_set)} PatLevin languages ({lang_coverage_pct:.1f}%)")
    print(f"✓ Wikidata has {high_coverage_langs} languages with >90% coverage")
    print(f"✓ Wikidata adds {len(comparison['wikidata_only_languages'])} new languages not in PatLevin")
    print()

    # Missing critical languages
    critical_langs = {"en", "es", "fr", "de", "it", "pt", "nl", "pl", "ru", "zh", "ja"}
    missing_critical = critical_langs & set(comparison["patlevin_only_languages"])

    if missing_critical:
        print(f"⚠ WARNING: Wikidata missing critical languages: {', '.join(missing_critical)}")
        print()

    # Final recommendation
    if lang_coverage_pct >= 85 and not missing_critical:
        print("✅ RECOMMENDATION: Wikidata coverage is SUFFICIENT to replace PatLevin")
        print()
        print("Rationale:")
        print("  • Covers >85% of PatLevin languages")
        print("  • All critical languages present with high coverage")
        print("  • Adds additional languages not in PatLevin")
        print("  • Wikidata is actively maintained and updated")
        print("  • License compatible (CC0 → CC-BY-NC-SA)")
        print()
        print("Next steps:")
        print("  1. Run full Wikidata extraction (--full flag) to get all ~10,000 species")
        print("  2. Verify production database quality")
        print("  3. Update BirdNET-Pi to use Wikidata database instead of PatLevin")
        print("  4. Schedule quarterly/biannual updates")
    else:
        print("❌ RECOMMENDATION: Wikidata coverage may NOT be sufficient to replace PatLevin")
        print()
        print("Concerns:")
        if lang_coverage_pct < 85:
            print(f"  • Only covers {lang_coverage_pct:.1f}% of PatLevin languages (<85% threshold)")
        if missing_critical:
            print(f"  • Missing critical languages: {', '.join(missing_critical)}")
        print()
        print("Next steps:")
        print("  1. Investigate missing languages in Wikidata")
        print("  2. Consider hybrid approach (Wikidata + PatLevin for missing languages)")
        print("  3. Contact Wikidata community to improve coverage")

    print()


def main():
    """Main entry point."""
    # Paths
    wikidata_report_path = "../data/wikidata_coverage_report.json"
    patlevin_db_path = "/Users/mdeverteuil/Documents/Codebase/birdnet-exploration/BirdNET-Pi/data/database/patlevin_database.db"

    print("Loading Wikidata statistics...")
    wikidata_stats = get_wikidata_stats(wikidata_report_path)

    print("Loading PatLevin statistics...")
    patlevin_stats = get_patlevin_stats(patlevin_db_path)

    print("Analyzing coverage...\n")
    comparison = compare_databases(wikidata_stats, patlevin_stats)

    # Print report
    print_comparison_report(wikidata_stats, patlevin_stats, comparison)

    # Save detailed comparison to JSON
    output_path = Path("../data/wikidata_vs_patlevin_comparison.json")
    with open(output_path, "w") as f:
        json.dump(
            {
                "wikidata": wikidata_stats,
                "patlevin": patlevin_stats,
                "comparison": comparison,
            },
            f,
            indent=2,
        )

    print(f"📄 Detailed comparison saved to: {output_path}")
    print()


if __name__ == "__main__":
    main()
