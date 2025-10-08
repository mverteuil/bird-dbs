#!/usr/bin/env python3
"""Analyze translation overlap between IOC and Wikidata databases.

This script determines:
1. Which languages are truly unique to each database
2. For shared languages, what % of translations are identical
3. Potential size savings by removing duplicate translations
4. Which database to prefer for each shared language

Goal: Reduce distributed asset size by only including unique content.
"""

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any


class TranslationOverlapAnalyzer:
    """Analyze translation overlaps to optimize database sizes."""

    def __init__(self, wikidata_db: str, ioc_db: str):
        """Initialize with database paths."""
        self.wikidata_db = wikidata_db
        self.ioc_db = ioc_db

    def analyze_overlap(self) -> dict[str, Any]:
        """
        Analyze translation overlap between databases.

        Returns comprehensive analysis of overlaps and recommendations.
        """
        print("Loading IOC translations...")
        ioc_data = self._load_ioc_translations()

        print("Loading Wikidata translations...")
        wikidata_data = self._load_wikidata_translations()

        print("\nAnalyzing overlaps...")
        overlap_analysis = self._analyze_language_overlap(ioc_data, wikidata_data)

        print("\nCalculating size savings...")
        size_analysis = self._calculate_size_savings(overlap_analysis, ioc_data, wikidata_data)

        return {
            "overlap_analysis": overlap_analysis,
            "size_analysis": size_analysis,
            "recommendations": self._generate_recommendations(overlap_analysis, size_analysis),
        }

    def _load_ioc_translations(self) -> dict[str, dict[str, dict[str, str]]]:
        """
        Load IOC translations.

        Returns:
            {language_code: {scientific_name: common_name}}
        """
        conn = sqlite3.connect(self.ioc_db)
        cursor = conn.execute("""
            SELECT language_code, scientific_name, common_name
            FROM translations
        """)

        data = defaultdict(dict)
        for lang, sci_name, common_name in cursor.fetchall():
            data[lang][sci_name] = common_name

        conn.close()
        return dict(data)

    def _load_wikidata_translations(self) -> dict[str, dict[str, dict[str, str]]]:
        """
        Load Wikidata translations.

        Returns:
            {language_code: {scientific_name: common_name}}
        """
        conn = sqlite3.connect(self.wikidata_db)
        cursor = conn.execute("""
            SELECT t.language_code, s.scientific_name, t.common_name
            FROM translations t
            JOIN species s ON t.wikidata_id = s.wikidata_id
        """)

        data = defaultdict(dict)
        for lang, sci_name, common_name in cursor.fetchall():
            data[lang][sci_name] = common_name

        conn.close()
        return dict(data)

    def _analyze_language_overlap(
        self,
        ioc_data: dict[str, dict[str, str]],
        wikidata_data: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        """Analyze overlap between IOC and Wikidata by language."""
        ioc_langs = set(ioc_data.keys())
        wd_langs = set(wikidata_data.keys())

        shared_langs = ioc_langs & wd_langs
        ioc_only = ioc_langs - wd_langs
        wd_only = wd_langs - ioc_langs

        language_analysis = {}

        for lang in sorted(shared_langs):
            ioc_species = set(ioc_data[lang].keys())
            wd_species = set(wikidata_data[lang].keys())

            common_species = ioc_species & wd_species

            # For common species, check how many translations are identical
            identical = 0
            different = 0
            identical_examples = []
            different_examples = []

            for species in common_species:
                ioc_name = ioc_data[lang][species]
                wd_name = wikidata_data[lang][species]

                if ioc_name == wd_name:
                    identical += 1
                    if len(identical_examples) < 5:
                        identical_examples.append((species, ioc_name))
                else:
                    different += 1
                    if len(different_examples) < 5:
                        different_examples.append((species, ioc_name, wd_name))

            language_analysis[lang] = {
                "ioc_count": len(ioc_species),
                "wikidata_count": len(wd_species),
                "common_species": len(common_species),
                "identical_translations": identical,
                "different_translations": different,
                "identical_pct": (identical / len(common_species) * 100) if common_species else 0,
                "ioc_only_count": len(ioc_species - wd_species),
                "wikidata_only_count": len(wd_species - ioc_species),
                "identical_examples": identical_examples,
                "different_examples": different_examples,
            }

        return {
            "shared_languages": sorted(shared_langs),
            "ioc_only_languages": sorted(ioc_only),
            "wikidata_only_languages": sorted(wd_only),
            "language_details": language_analysis,
        }

    def _calculate_size_savings(
        self,
        overlap_analysis: dict,
        ioc_data: dict,
        wikidata_data: dict,
    ) -> dict[str, Any]:
        """Calculate potential size savings by removing duplicates."""
        total_ioc_translations = sum(len(species_dict) for species_dict in ioc_data.values())
        total_wd_translations = sum(len(species_dict) for species_dict in wikidata_data.values())

        # Count removable translations (identical in both DBs)
        removable_from_wikidata = 0
        removable_from_ioc = 0

        for _lang, details in overlap_analysis["language_details"].items():
            # Strategy: Keep in IOC (primary), remove from Wikidata if identical
            removable_from_wikidata += details["identical_translations"]

            # Alternative strategy: Keep in Wikidata if it has more species
            if details["wikidata_count"] > details["ioc_count"]:
                removable_from_ioc += details["identical_translations"]

        # Estimate size (rough: ~50 bytes per translation on average)
        bytes_per_translation = 50

        return {
            "total_ioc_translations": total_ioc_translations,
            "total_wikidata_translations": total_wd_translations,
            "removable_from_wikidata": removable_from_wikidata,
            "removable_from_ioc": removable_from_ioc,
            "potential_savings_wikidata_kb": (removable_from_wikidata * bytes_per_translation)
            / 1024,
            "potential_savings_ioc_kb": (removable_from_ioc * bytes_per_translation) / 1024,
            "current_total_estimate_mb": (
                (total_ioc_translations + total_wd_translations) * bytes_per_translation
            )
            / 1024
            / 1024,
        }

    def _generate_recommendations(
        self,
        overlap_analysis: dict,
        size_analysis: dict,
    ) -> list[dict[str, str]]:
        """Generate recommendations for each language."""
        recommendations = []

        # IOC-only languages: Keep in IOC
        for lang in overlap_analysis["ioc_only_languages"]:
            recommendations.append(
                {
                    "language": lang,
                    "action": "keep_in_ioc",
                    "reason": "Unique to IOC",
                }
            )

        # Wikidata-only languages: Keep in Wikidata
        for lang in overlap_analysis["wikidata_only_languages"]:
            recommendations.append(
                {
                    "language": lang,
                    "action": "keep_in_wikidata",
                    "reason": "Unique to Wikidata",
                }
            )

        # Shared languages: Decide based on coverage and identity
        for lang, details in overlap_analysis["language_details"].items():
            identical_pct = details["identical_pct"]
            ioc_count = details["ioc_count"]
            wd_count = details["wikidata_count"]

            if identical_pct > 90:
                # >90% identical: keep only in database with more species
                if ioc_count >= wd_count:
                    recommendations.append(
                        {
                            "language": lang,
                            "action": "keep_in_ioc_only",
                            "reason": f"{identical_pct:.1f}% identical, IOC has {ioc_count} vs WD {wd_count}",
                            "remove_from": "wikidata",
                            "savings": details["identical_translations"],
                        }
                    )
                else:
                    recommendations.append(
                        {
                            "language": lang,
                            "action": "keep_in_wikidata_only",
                            "reason": f"{identical_pct:.1f}% identical, WD has {wd_count} vs IOC {ioc_count}",
                            "remove_from": "ioc",
                            "savings": details["identical_translations"],
                        }
                    )
            elif identical_pct > 50:
                # 50-90% identical: keep both but remove exact duplicates
                recommendations.append(
                    {
                        "language": lang,
                        "action": "keep_both_deduplicate",
                        "reason": f"{identical_pct:.1f}% identical, keep unique translations in each",
                        "remove_from": "wikidata" if ioc_count >= wd_count else "ioc",
                        "savings": details["identical_translations"],
                    }
                )
            else:
                # <50% identical: keep both (different translation sources)
                recommendations.append(
                    {
                        "language": lang,
                        "action": "keep_both",
                        "reason": f"Only {identical_pct:.1f}% identical, different translations",
                    }
                )

        return recommendations


def print_analysis_report(analysis: dict) -> None:
    """Print comprehensive analysis report."""
    overlap = analysis["overlap_analysis"]
    size = analysis["size_analysis"]
    recs = analysis["recommendations"]

    print("=" * 80)
    print("TRANSLATION OVERLAP ANALYSIS: IOC vs WIKIDATA")
    print("=" * 80)
    print()

    # Language distribution
    print("📊 Language Distribution:")
    print(f"  IOC-only languages: {len(overlap['ioc_only_languages'])}")
    print(f"  Wikidata-only languages: {len(overlap['wikidata_only_languages'])}")
    print(f"  Shared languages: {len(overlap['shared_languages'])}")
    print()

    if overlap["ioc_only_languages"]:
        print(f"  IOC-only: {', '.join(overlap['ioc_only_languages'][:20])}")
        if len(overlap["ioc_only_languages"]) > 20:
            print(f"           ...and {len(overlap['ioc_only_languages']) - 20} more")
        print()

    if overlap["wikidata_only_languages"]:
        print(f"  Wikidata-only: {', '.join(overlap['wikidata_only_languages'][:20])}")
        if len(overlap["wikidata_only_languages"]) > 20:
            print(f"                ...and {len(overlap['wikidata_only_languages']) - 20} more")
        print()

    # Shared language analysis
    print("=" * 80)
    print("SHARED LANGUAGE ANALYSIS")
    print("=" * 80)
    print()
    print(
        f"{'Lang':>5} {'IOC':>8} {'WD':>8} {'Common':>8} {'Identical':>10} {'Different':>10} {'Match %':>9}"
    )
    print("-" * 80)

    for lang, details in sorted(
        overlap["language_details"].items(), key=lambda x: x[1]["identical_pct"], reverse=True
    ):
        ioc_count = details["ioc_count"]
        wd_count = details["wikidata_count"]
        common = details["common_species"]
        identical = details["identical_translations"]
        different = details["different_translations"]
        pct = details["identical_pct"]

        print(
            f"{lang:>5} {ioc_count:>8,} {wd_count:>8,} {common:>8,} {identical:>10,} {different:>10,} {pct:>8.1f}%"
        )

    # Size analysis
    print()
    print("=" * 80)
    print("SIZE ANALYSIS")
    print("=" * 80)
    print()
    print(f"Total IOC translations: {size['total_ioc_translations']:,}")
    print(f"Total Wikidata translations: {size['total_wikidata_translations']:,}")
    print(f"Current total estimate: {size['current_total_estimate_mb']:.1f} MB")
    print()
    print(f"Removable from Wikidata (identical): {size['removable_from_wikidata']:,} translations")
    print(f"Potential savings: {size['potential_savings_wikidata_kb']:.1f} KB")
    print()

    # Recommendations
    print("=" * 80)
    print("OPTIMIZATION RECOMMENDATIONS")
    print("=" * 80)
    print()

    # Group by action
    keep_ioc_only = [r for r in recs if r["action"] == "keep_in_ioc_only"]
    keep_wd_only = [r for r in recs if r["action"] == "keep_in_wikidata_only"]
    keep_both_dedup = [r for r in recs if r["action"] == "keep_both_deduplicate"]
    keep_both = [r for r in recs if r["action"] == "keep_both"]

    print(f"✓ Keep in IOC only ({len(keep_ioc_only)} languages):")
    for rec in keep_ioc_only[:10]:
        savings = rec.get("savings", 0)
        print(f"  {rec['language']:>5}: {rec['reason']} (save {savings:,} translations)")
    if len(keep_ioc_only) > 10:
        print(f"  ... and {len(keep_ioc_only) - 10} more")
    print()

    print(f"✓ Keep in Wikidata only ({len(keep_wd_only)} languages):")
    for rec in keep_wd_only[:10]:
        savings = rec.get("savings", 0)
        print(f"  {rec['language']:>5}: {rec['reason']} (save {savings:,} translations)")
    if len(keep_wd_only) > 10:
        print(f"  ... and {len(keep_wd_only) - 10} more")
    print()

    print(f"⚠️  Keep both but deduplicate ({len(keep_both_dedup)} languages):")
    for rec in keep_both_dedup[:10]:
        savings = rec.get("savings", 0)
        print(f"  {rec['language']:>5}: {rec['reason']} (save {savings:,} translations)")
    if len(keep_both_dedup) > 10:
        print(f"  ... and {len(keep_both_dedup) - 10} more")
    print()

    print(f"⚠️  Keep both (different sources) ({len(keep_both)} languages):")
    for rec in keep_both[:10]:
        print(f"  {rec['language']:>5}: {rec['reason']}")
    if len(keep_both) > 10:
        print(f"  ... and {len(keep_both) - 10} more")
    print()

    # Calculate total savings
    total_savings = sum(rec.get("savings", 0) for rec in recs)
    total_savings_kb = (total_savings * 50) / 1024
    total_savings_mb = total_savings_kb / 1024

    print("=" * 80)
    print("TOTAL POTENTIAL SAVINGS")
    print("=" * 80)
    print()
    print(f"Translations to remove: {total_savings:,}")
    print(f"Estimated size savings: {total_savings_mb:.1f} MB")
    print()

    # Show examples of differences
    print("=" * 80)
    print("EXAMPLE TRANSLATION DIFFERENCES")
    print("=" * 80)
    print()

    for lang, details in sorted(overlap["language_details"].items())[:5]:
        if details["different_examples"]:
            print(
                f"\n{lang} (showing {len(details['different_examples'])} of {details['different_translations']} differences):"
            )
            for species, ioc_name, wd_name in details["different_examples"]:
                print(f"  {species}:")
                print(f"    IOC:      {ioc_name}")
                print(f"    Wikidata: {wd_name}")


def main():
    """Main entry point."""
    wikidata_db = "/Volumes/backup/ebird/avibase-builder/data/wikidata_birds_poc.db"
    ioc_db = "/Users/mdeverteuil/Documents/Codebase/birdnet-exploration/BirdNET-Pi/data/database/ioc_reference.db"

    print("Starting translation overlap analysis...")
    print()

    analyzer = TranslationOverlapAnalyzer(wikidata_db, ioc_db)
    analysis = analyzer.analyze_overlap()

    print_analysis_report(analysis)

    # Save to JSON
    import json

    output_path = Path("../data/translation_overlap_analysis.json")
    with open(output_path, "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"\n📄 Detailed analysis saved to: {output_path}")


if __name__ == "__main__":
    main()
