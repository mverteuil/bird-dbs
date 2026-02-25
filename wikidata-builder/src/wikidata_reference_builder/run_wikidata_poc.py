#!/usr/bin/env python3
"""POC: Extract bird species multilingual names from Wikidata.

This script:
1. Queries Wikidata for bird species with Avibase IDs (P2026)
2. Extracts multilingual common names in 50+ languages
3. Builds SQLite database with species and translations
4. Generates coverage report
5. Compares with PatLevin database coverage

Usage:
    python run_wikidata_poc.py [--limit N] [--full]

Options:
    --limit N    Fetch only N species (for testing, default: 500)
    --full       Fetch all bird species (may take 30-60 minutes)
"""

import argparse
import json
import sys
from pathlib import Path

from wikidata_reference_builder.wikidata_database_builder import WikidataDatabaseBuilder


def main():
    parser = argparse.ArgumentParser(description="Wikidata bird species extraction POC")
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Limit number of species to fetch (default: 500)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Fetch all bird species (ignores --limit)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="../data/wikidata_birds_poc.db",
        help="Output database path",
    )

    args = parser.parse_args()

    # Determine limit
    limit = None if args.full else args.limit

    print("=" * 80)
    print("WIKIDATA BIRD SPECIES MULTILINGUAL DATABASE - POC")
    print("=" * 80)
    print()
    print(f"Output: {args.output}")
    print(f"Mode: {'FULL (all species)' if args.full else f'LIMITED ({limit} species)'}")
    print()

    # Build database
    builder = WikidataDatabaseBuilder(args.output)

    try:
        species_count, translation_count = builder.populate_from_wikidata(
            limit=limit,
            sample_mode=not args.full,
        )

        print("\n" + "=" * 80)
        print("COVERAGE REPORT")
        print("=" * 80)

        # Generate coverage report
        report = builder.generate_coverage_report()

        print("\n📊 Basic Statistics:")
        print(f"  Species: {report['species_count']:,}")
        print(f"  Translations: {report['translation_count']:,}")
        print(f"  Languages: {report['language_count']}")
        print(f"  Avg translations/species: {report['avg_translations_per_species']}")

        print("\n🌍 Top 20 Languages by Coverage:")
        for lang_code, lang_data in report["top_languages"]:
            name = lang_data["name"]
            count = lang_data["count"]
            percentage = (
                (count / report["species_count"] * 100) if report["species_count"] > 0 else 0
            )
            print(f"  {lang_code:5s} {name:15s} {count:6,} ({percentage:5.1f}%)")

        # Save report to JSON
        report_path = Path(args.output).parent / "wikidata_coverage_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n📄 Full report saved to: {report_path}")

        # Compare with PatLevin if available
        print("\n" + "=" * 80)
        print("COMPARISON WITH PATLEVIN DATABASE")
        print("=" * 80)
        print("\nTo compare coverage with PatLevin database, run:")
        print("  python compare_coverage.py")

        print("\n✓ POC COMPLETE!")
        print(f"\nDatabase: {args.output}")
        print(f"Size: {Path(args.output).stat().st_size / 1024 / 1024:.2f} MB")

        return 0

    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
