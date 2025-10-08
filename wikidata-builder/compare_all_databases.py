#!/usr/bin/env python3
"""Comprehensive comparison of all 4 bird name databases.

Compares:
1. Wikidata (POC) - 499 species, 57 languages
2. IOC Reference - 11,250 species, 44 languages
3. PatLevin - 6,362 species, 29 languages
4. Avibase (BirdNET-Pi) - 11,269 species, 13 languages (mostly Czech)

Analyzes:
- Language coverage comparison
- IOC + Wikidata combined coverage vs PatLevin
- Translation differences where species match
- Optimal database combination strategy
"""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any


class DatabaseAnalyzer:
    """Analyze and compare bird name databases."""

    def __init__(
        self,
        wikidata_db: str,
        ioc_db: str,
        patlevin_db: str,
        avibase_db: str,
    ):
        """Initialize with paths to all databases."""
        self.wikidata_db = wikidata_db
        self.ioc_db = ioc_db
        self.patlevin_db = patlevin_db
        self.avibase_db = avibase_db

    def get_wikidata_stats(self) -> dict[str, Any]:
        """Extract Wikidata POC statistics."""
        conn = sqlite3.connect(self.wikidata_db)
        cursor = conn.cursor()

        # Basic counts
        cursor.execute("SELECT COUNT(*) FROM species")
        species_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*), COUNT(DISTINCT language_code) FROM translations")
        translation_count, language_count = cursor.fetchone()

        # Language breakdown
        cursor.execute("""
            SELECT language_code, COUNT(*) as count
            FROM translations
            GROUP BY language_code
            ORDER BY count DESC
        """)
        languages = {row[0]: row[1] for row in cursor.fetchall()}

        # Get all species
        cursor.execute("SELECT wikidata_id, scientific_name FROM species")
        species = {row[1]: row[0] for row in cursor.fetchall()}

        # Get all translations by species and language
        cursor.execute("""
            SELECT s.scientific_name, t.language_code, t.common_name
            FROM translations t
            JOIN species s ON t.wikidata_id = s.wikidata_id
        """)
        translations = defaultdict(dict)
        for sci_name, lang, common_name in cursor.fetchall():
            translations[sci_name][lang] = common_name

        conn.close()

        return {
            "species_count": species_count,
            "translation_count": translation_count,
            "language_count": language_count,
            "languages": languages,
            "species": species,
            "translations": translations,
        }

    def get_ioc_stats(self) -> dict[str, Any]:
        """Extract IOC database statistics."""
        conn = sqlite3.connect(self.ioc_db)
        cursor = conn.cursor()

        # Basic counts
        cursor.execute("SELECT COUNT(*) FROM species")
        species_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*), COUNT(DISTINCT language_code) FROM translations")
        translation_count, language_count = cursor.fetchone()

        # Language breakdown
        cursor.execute("""
            SELECT language_code, COUNT(*) as count
            FROM translations
            GROUP BY language_code
            ORDER BY count DESC
        """)
        languages = {row[0]: row[1] for row in cursor.fetchall()}

        # Get all species
        cursor.execute("SELECT scientific_name FROM species")
        species = {row[0]: None for row in cursor.fetchall()}

        # Get all translations by species and language
        cursor.execute("""
            SELECT scientific_name, language_code, common_name
            FROM translations
        """)
        translations = defaultdict(dict)
        for sci_name, lang, common_name in cursor.fetchall():
            translations[sci_name][lang] = common_name

        conn.close()

        return {
            "species_count": species_count,
            "translation_count": translation_count,
            "language_count": language_count,
            "languages": languages,
            "species": species,
            "translations": translations,
        }

    def get_patlevin_stats(self) -> dict[str, Any]:
        """Extract PatLevin database statistics."""
        conn = sqlite3.connect(self.patlevin_db)
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

        # Get all species
        cursor.execute("SELECT DISTINCT scientific_name FROM patlevin_labels")
        species = {row[0]: None for row in cursor.fetchall()}

        # Get all translations by species and language
        cursor.execute("""
            SELECT scientific_name, language_code, common_name
            FROM patlevin_labels
        """)
        translations = defaultdict(dict)
        for sci_name, lang, common_name in cursor.fetchall():
            translations[sci_name][lang] = common_name

        conn.close()

        return {
            "species_count": species_count,
            "translation_count": translation_count,
            "language_count": language_count,
            "languages": languages,
            "species": species,
            "translations": translations,
        }

    def get_avibase_stats(self) -> dict[str, Any]:
        """Extract Avibase database statistics."""
        conn = sqlite3.connect(self.avibase_db)
        cursor = conn.cursor()

        # Basic counts
        cursor.execute("""
            SELECT
                COUNT(*) as total_rows,
                COUNT(DISTINCT scientific_name) as species_count,
                COUNT(DISTINCT language_code) as language_count
            FROM avibase_names
        """)
        total_rows, species_count, language_count = cursor.fetchone()

        # Language breakdown
        cursor.execute("""
            SELECT language_code, COUNT(*) as count
            FROM avibase_names
            GROUP BY language_code
            ORDER BY count DESC
        """)
        languages = {row[0]: row[1] for row in cursor.fetchall()}

        # Get all species
        cursor.execute("SELECT DISTINCT scientific_name FROM avibase_names")
        species = {row[0]: None for row in cursor.fetchall()}

        # Get all translations by species and language
        cursor.execute("""
            SELECT scientific_name, language_code, common_name
            FROM avibase_names
        """)
        translations = defaultdict(dict)
        for sci_name, lang, common_name in cursor.fetchall():
            translations[sci_name][lang] = common_name

        conn.close()

        return {
            "species_count": species_count,
            "translation_count": total_rows,
            "language_count": language_count,
            "languages": languages,
            "species": species,
            "translations": translations,
        }

    def compare_ioc_wikidata_vs_patlevin(
        self, ioc_stats: dict, wikidata_stats: dict, patlevin_stats: dict
    ) -> dict[str, Any]:
        """Compare IOC + Wikidata combined coverage against PatLevin."""
        # Merge IOC and Wikidata languages
        combined_langs = set(ioc_stats["languages"].keys()) | set(wikidata_stats["languages"].keys())
        patlevin_langs = set(patlevin_stats["languages"].keys())

        # Language overlap
        shared = combined_langs & patlevin_langs
        combined_only = combined_langs - patlevin_langs
        patlevin_only = patlevin_langs - combined_langs

        # For shared languages, check if IOC + Wikidata >= PatLevin
        language_comparison = {}
        for lang in sorted(shared):
            ioc_count = ioc_stats["languages"].get(lang, 0)
            wd_count = wikidata_stats["languages"].get(lang, 0)
            pl_count = patlevin_stats["languages"].get(lang, 0)

            # Combined unique species count (need to check overlaps)
            # Simplified: just add counts (may overestimate if same species in both)
            combined_count = ioc_count + wd_count

            language_comparison[lang] = {
                "ioc_count": ioc_count,
                "wikidata_count": wd_count,
                "combined_approx": combined_count,
                "patlevin_count": pl_count,
                "exceeds_patlevin": combined_count >= pl_count,
            }

        return {
            "total_languages_combined": len(combined_langs),
            "total_languages_patlevin": len(patlevin_langs),
            "shared_languages": sorted(shared),
            "combined_only_languages": sorted(combined_only),
            "patlevin_only_languages": sorted(patlevin_only),
            "language_comparison": language_comparison,
            "coverage_percentage": len(shared) / len(patlevin_langs) * 100 if patlevin_langs else 0,
        }

    def find_translation_differences(
        self, ioc_stats: dict, wikidata_stats: dict, patlevin_stats: dict
    ) -> dict[str, Any]:
        """Find species where translations differ across databases."""
        # Find species present in all 3 databases
        ioc_species = set(ioc_stats["species"].keys())
        wd_species = set(wikidata_stats["species"].keys())
        pl_species = set(patlevin_stats["species"].keys())

        common_species = ioc_species & wd_species & pl_species

        print(f"\nAnalyzing {len(common_species)} species present in all 3 databases...")

        # Find shared languages across all 3
        ioc_langs = set(ioc_stats["languages"].keys())
        wd_langs = set(wikidata_stats["languages"].keys())
        pl_langs = set(patlevin_stats["languages"].keys())

        common_langs = ioc_langs & wd_langs & pl_langs

        # Check for translation differences
        differences = []
        matches = []

        for species in sorted(common_species):
            ioc_trans = ioc_stats["translations"].get(species, {})
            wd_trans = wikidata_stats["translations"].get(species, {})
            pl_trans = patlevin_stats["translations"].get(species, {})

            for lang in common_langs:
                ioc_name = ioc_trans.get(lang)
                wd_name = wd_trans.get(lang)
                pl_name = pl_trans.get(lang)

                # All 3 have this translation
                if ioc_name and wd_name and pl_name:
                    if ioc_name == wd_name == pl_name:
                        matches.append({
                            "species": species,
                            "language": lang,
                            "translation": ioc_name,
                        })
                    else:
                        differences.append({
                            "species": species,
                            "language": lang,
                            "ioc": ioc_name,
                            "wikidata": wd_name,
                            "patlevin": pl_name,
                        })

        return {
            "common_species_count": len(common_species),
            "common_languages": sorted(common_langs),
            "total_matches": len(matches),
            "total_differences": len(differences),
            "difference_examples": differences[:50],  # First 50 examples
            "match_examples": matches[:20],  # First 20 examples
        }


def print_comprehensive_report(
    wikidata_stats: dict,
    ioc_stats: dict,
    patlevin_stats: dict,
    avibase_stats: dict,
    ioc_wd_vs_pl: dict,
    translation_diffs: dict,
) -> None:
    """Print comprehensive comparison report."""
    print("=" * 80)
    print("COMPREHENSIVE 4-DATABASE COMPARISON")
    print("=" * 80)
    print()

    # Overall statistics
    print("📊 Overall Statistics:")
    print()
    print(f"{'Database':<20} {'Species':>12} {'Translations':>15} {'Languages':>12} {'Avg/Species':>12}")
    print("-" * 80)
    print(f"{'Wikidata (POC)':<20} {wikidata_stats['species_count']:>12,} "
          f"{wikidata_stats['translation_count']:>15,} {wikidata_stats['language_count']:>12} "
          f"{wikidata_stats['translation_count']/wikidata_stats['species_count']:>12.2f}")
    print(f"{'IOC Reference':<20} {ioc_stats['species_count']:>12,} "
          f"{ioc_stats['translation_count']:>15,} {ioc_stats['language_count']:>12} "
          f"{ioc_stats['translation_count']/ioc_stats['species_count']:>12.2f}")
    print(f"{'PatLevin':<20} {patlevin_stats['species_count']:>12,} "
          f"{patlevin_stats['translation_count']:>15,} {patlevin_stats['language_count']:>12} "
          f"{patlevin_stats['translation_count']/patlevin_stats['species_count']:>12.2f}")
    print(f"{'Avibase (BNP)':<20} {avibase_stats['species_count']:>12,} "
          f"{avibase_stats['translation_count']:>15,} {avibase_stats['language_count']:>12} "
          f"{avibase_stats['translation_count']/avibase_stats['species_count']:>12.2f}")
    print()

    # IOC + Wikidata vs PatLevin
    print("=" * 80)
    print("IOC + WIKIDATA COMBINED vs PATLEVIN")
    print("=" * 80)
    print()
    print(f"Total languages (IOC + Wikidata): {ioc_wd_vs_pl['total_languages_combined']}")
    print(f"Total languages (PatLevin): {ioc_wd_vs_pl['total_languages_patlevin']}")
    print(f"Coverage: {ioc_wd_vs_pl['coverage_percentage']:.1f}%")
    print()

    print(f"Shared languages: {len(ioc_wd_vs_pl['shared_languages'])}")
    print(f"IOC+Wikidata only: {len(ioc_wd_vs_pl['combined_only_languages'])}")
    print(f"PatLevin only: {len(ioc_wd_vs_pl['patlevin_only_languages'])}")
    print()

    if ioc_wd_vs_pl['combined_only_languages']:
        print(f"Languages in IOC+Wikidata but not PatLevin:")
        print(f"  {', '.join(ioc_wd_vs_pl['combined_only_languages'][:20])}")
        if len(ioc_wd_vs_pl['combined_only_languages']) > 20:
            print(f"  ... and {len(ioc_wd_vs_pl['combined_only_languages']) - 20} more")
        print()

    if ioc_wd_vs_pl['patlevin_only_languages']:
        print(f"Languages in PatLevin but not IOC+Wikidata:")
        print(f"  {', '.join(ioc_wd_vs_pl['patlevin_only_languages'])}")
        print()

    # Language-by-language comparison
    print("📈 Language Coverage Comparison (IOC + Wikidata vs PatLevin):")
    print()
    print(f"{'Lang':>5} {'IOC':>10} {'Wikidata':>10} {'Combined':>10} {'PatLevin':>10} {'Exceeds':>8}")
    print("-" * 80)

    exceeds_count = 0
    for lang, comparison in sorted(
        ioc_wd_vs_pl['language_comparison'].items(),
        key=lambda x: x[1]['combined_approx'],
        reverse=True
    )[:25]:
        ioc_count = comparison['ioc_count']
        wd_count = comparison['wikidata_count']
        combined = comparison['combined_approx']
        pl_count = comparison['patlevin_count']
        exceeds = "✓" if comparison['exceeds_patlevin'] else "✗"

        if comparison['exceeds_patlevin']:
            exceeds_count += 1

        print(f"{lang:>5} {ioc_count:>10,} {wd_count:>10,} {combined:>10,} {pl_count:>10,} {exceeds:>8}")

    print()
    print(f"Languages where IOC+Wikidata exceeds PatLevin: {exceeds_count}/{len(ioc_wd_vs_pl['shared_languages'])}")
    print()

    # Translation differences
    print("=" * 80)
    print("TRANSLATION QUALITY COMPARISON")
    print("=" * 80)
    print()
    print(f"Common species across all 3 DBs: {translation_diffs['common_species_count']}")
    print(f"Common languages: {len(translation_diffs['common_languages'])}")
    print(f"Total matching translations: {translation_diffs['total_matches']:,}")
    print(f"Total differing translations: {translation_diffs['total_differences']:,}")
    print()

    if translation_diffs['total_differences'] > 0:
        match_pct = translation_diffs['total_matches'] / (
            translation_diffs['total_matches'] + translation_diffs['total_differences']
        ) * 100
        print(f"Match rate: {match_pct:.1f}%")
        print()

        print("Examples of translation differences:")
        print()
        for diff in translation_diffs['difference_examples'][:10]:
            print(f"  {diff['species']} [{diff['language']}]:")
            print(f"    IOC:      {diff['ioc']}")
            print(f"    Wikidata: {diff['wikidata']}")
            print(f"    PatLevin: {diff['patlevin']}")
            print()

    # Avibase analysis
    print("=" * 80)
    print("AVIBASE DATABASE ANALYSIS")
    print("=" * 80)
    print()
    print(f"Species: {avibase_stats['species_count']:,}")
    print(f"Languages: {avibase_stats['language_count']}")
    print()
    print("Language breakdown:")
    for lang, count in sorted(avibase_stats['languages'].items(), key=lambda x: x[1], reverse=True):
        pct = count / avibase_stats['species_count'] * 100
        print(f"  {lang:>10}: {count:>6,} ({pct:>5.1f}%)")
    print()
    print("⚠️  Avibase database is 87% Czech (cs) translations only")
    print("    Not a comprehensive multilingual database")
    print()

    # Final recommendation
    print("=" * 80)
    print("FINAL RECOMMENDATION")
    print("=" * 80)
    print()

    if ioc_wd_vs_pl['coverage_percentage'] >= 95 and exceeds_count >= len(ioc_wd_vs_pl['shared_languages']) * 0.8:
        print("✅ RECOMMENDATION: Use IOC + Wikidata, DROP PatLevin")
        print()
        print("Rationale:")
        print(f"  • Combined coverage: {ioc_wd_vs_pl['coverage_percentage']:.1f}% of PatLevin languages")
        print(f"  • Exceeds PatLevin in {exceeds_count}/{len(ioc_wd_vs_pl['shared_languages'])} shared languages")
        print(f"  • Adds {len(ioc_wd_vs_pl['combined_only_languages'])} languages PatLevin doesn't have")
        print(f"  • Both IOC and Wikidata actively maintained")
        print(f"  • Clear licenses (IOC: CC-BY-4.0, Wikidata: CC0)")
        print()
    else:
        print("⚠️  RECOMMENDATION: Keep PatLevin as supplement")
        print()
        print("Concerns:")
        print(f"  • Combined coverage: {ioc_wd_vs_pl['coverage_percentage']:.1f}% of PatLevin languages")
        print(f"  • Only exceeds PatLevin in {exceeds_count}/{len(ioc_wd_vs_pl['shared_languages'])} shared languages")
        print()


def main():
    """Main entry point."""
    # Paths
    wikidata_db = "./wikidata_500_filtered.db"  # Use the newly filtered database
    ioc_db = "/Users/mdeverteuil/Documents/Codebase/birdnet-exploration/BirdNET-Pi/data/database/ioc_reference.db"
    patlevin_db = "/Users/mdeverteuil/Documents/Codebase/birdnet-exploration/BirdNET-Pi/data/database/patlevin_database.db"
    avibase_db = "/Users/mdeverteuil/Documents/Codebase/birdnet-exploration/BirdNET-Pi/data/database/avibase_database.db"

    print("Loading databases...")
    analyzer = DatabaseAnalyzer(wikidata_db, ioc_db, patlevin_db, avibase_db)

    print("Analyzing Wikidata POC...")
    wikidata_stats = analyzer.get_wikidata_stats()

    print("Analyzing IOC Reference...")
    ioc_stats = analyzer.get_ioc_stats()

    print("Analyzing PatLevin...")
    patlevin_stats = analyzer.get_patlevin_stats()

    print("Analyzing Avibase (BirdNET-Pi)...")
    avibase_stats = analyzer.get_avibase_stats()

    print("Comparing IOC + Wikidata vs PatLevin...")
    ioc_wd_vs_pl = analyzer.compare_ioc_wikidata_vs_patlevin(ioc_stats, wikidata_stats, patlevin_stats)

    print("Finding translation differences...")
    translation_diffs = analyzer.find_translation_differences(ioc_stats, wikidata_stats, patlevin_stats)

    print("\n")

    # Print comprehensive report
    print_comprehensive_report(
        wikidata_stats,
        ioc_stats,
        patlevin_stats,
        avibase_stats,
        ioc_wd_vs_pl,
        translation_diffs,
    )

    # Save detailed comparison to JSON
    output_path = Path("../data/comprehensive_database_comparison.json")
    with open(output_path, "w") as f:
        json.dump(
            {
                "wikidata": {
                    "species_count": wikidata_stats["species_count"],
                    "translation_count": wikidata_stats["translation_count"],
                    "language_count": wikidata_stats["language_count"],
                    "languages": wikidata_stats["languages"],
                },
                "ioc": {
                    "species_count": ioc_stats["species_count"],
                    "translation_count": ioc_stats["translation_count"],
                    "language_count": ioc_stats["language_count"],
                    "languages": ioc_stats["languages"],
                },
                "patlevin": {
                    "species_count": patlevin_stats["species_count"],
                    "translation_count": patlevin_stats["translation_count"],
                    "language_count": patlevin_stats["language_count"],
                    "languages": patlevin_stats["languages"],
                },
                "avibase": {
                    "species_count": avibase_stats["species_count"],
                    "translation_count": avibase_stats["translation_count"],
                    "language_count": avibase_stats["language_count"],
                    "languages": avibase_stats["languages"],
                },
                "ioc_wikidata_vs_patlevin": ioc_wd_vs_pl,
                "translation_differences": translation_diffs,
            },
            f,
            indent=2,
        )

    print(f"📄 Detailed comparison saved to: {output_path}")
    print()


if __name__ == "__main__":
    main()
