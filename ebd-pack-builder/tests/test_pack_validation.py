"""Test framework for validating species frequency data in region packs.

This tests that:
1. Common species are correctly identified as common in their range
2. Rare/vagrant species are correctly downgraded
3. Absent species return no data (detection should be heavily penalized)
4. Monthly patterns are correct for migratory species
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import h3
import pytest

# Path to built packs
PACKS_DIR = Path("/Volumes/Lightroom/ebird_packs")


@dataclass
class SpeciesTestCase:
    """A test case for species frequency validation."""

    name: str
    scientific_name: str
    lat: float
    lon: float
    expected_tier: str  # common, uncommon, rare, vagrant, absent
    month: int | None = None  # For seasonal tests
    notes: str = ""


# Ground truth test matrix
# These are well-known species with predictable occurrence patterns
TEST_CASES = [
    # ===== North America - Common Species =====
    SpeciesTestCase(
        name="American Robin in NYC (common resident)",
        scientific_name="Turdus migratorius",
        lat=40.78,
        lon=-73.97,  # Central Park
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Northern Cardinal in NYC (common resident)",
        scientific_name="Cardinalis cardinalis",
        lat=40.78,
        lon=-73.97,
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="House Sparrow in NYC (common resident)",
        scientific_name="Passer domesticus",
        lat=40.78,
        lon=-73.97,
        expected_tier="common",
    ),
    # ===== North America - Seasonal/Migratory =====
    SpeciesTestCase(
        name="Snowy Owl in NYC (rare winter visitor)",
        scientific_name="Bubo scandiacus",
        lat=40.78,
        lon=-73.97,
        expected_tier="rare",  # or vagrant
        month=1,  # January
        notes="Irruptive; some winters more common",
    ),
    SpeciesTestCase(
        name="Ruby-throated Hummingbird in NYC (summer)",
        scientific_name="Archilochus colubris",
        lat=40.78,
        lon=-73.97,
        expected_tier="uncommon",
        month=7,  # July
    ),
    SpeciesTestCase(
        name="Ruby-throated Hummingbird in NYC (winter - seasonally absent)",
        scientific_name="Archilochus colubris",
        lat=40.78,
        lon=-73.97,
        expected_tier="seasonal_absent",  # Special tier for seasonal tests
        month=1,  # January - no monthly data should exist
    ),
    # ===== North America - Wrong Continent (vagrant or absent) =====
    # Note: Some species ARE recorded as vagrants in eBird - this is correct!
    SpeciesTestCase(
        name="European Robin in NYC (vagrant - actually recorded!)",
        scientific_name="Erithacus rubecula",
        lat=40.78,
        lon=-73.97,
        expected_tier="vagrant",  # Vagrants are real sightings
        notes="European species recorded as vagrant in North America",
    ),
    SpeciesTestCase(
        name="Common Blackbird in NYC (truly absent)",
        scientific_name="Turdus merula",
        lat=40.78,
        lon=-73.97,
        expected_tier="absent",
    ),
    # ===== Europe - Common Species =====
    SpeciesTestCase(
        name="European Robin in London (common resident)",
        scientific_name="Erithacus rubecula",
        lat=51.51,
        lon=-0.13,  # London
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Common Blackbird in London (common resident)",
        scientific_name="Turdus merula",
        lat=51.51,
        lon=-0.13,
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Eurasian Blue Tit in London (common resident)",
        scientific_name="Cyanistes caeruleus",
        lat=51.51,
        lon=-0.13,
        expected_tier="common",
    ),
    # ===== Europe - Wrong Continent =====
    SpeciesTestCase(
        name="American Robin in London (vagrant - actually recorded!)",
        scientific_name="Turdus migratorius",
        lat=51.51,
        lon=-0.13,
        expected_tier="vagrant",  # Recorded as vagrant in UK
        notes="American species recorded as vagrant in Europe",
    ),
    SpeciesTestCase(
        name="Northern Cardinal in London (wrong continent)",
        scientific_name="Cardinalis cardinalis",
        lat=51.51,
        lon=-0.13,
        expected_tier="absent",
    ),
    # ===== Australia - Common Species =====
    SpeciesTestCase(
        name="Australian Magpie in Sydney (common resident)",
        scientific_name="Gymnorhina tibicen",
        lat=-33.87,
        lon=151.21,  # Sydney
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Rainbow Lorikeet in Sydney (common resident)",
        scientific_name="Trichoglossus moluccanus",
        lat=-33.87,
        lon=151.21,
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Laughing Kookaburra in Sydney (common resident)",
        scientific_name="Dacelo novaeguineae",
        lat=-33.87,
        lon=151.21,
        expected_tier="common",
    ),
    # ===== Australia - Wrong Continent =====
    SpeciesTestCase(
        name="American Robin in Sydney (wrong continent)",
        scientific_name="Turdus migratorius",
        lat=-33.87,
        lon=151.21,
        expected_tier="absent",
    ),
    # ===== South Africa - Common Species =====
    SpeciesTestCase(
        name="Hadeda Ibis in Cape Town (common resident)",
        scientific_name="Bostrychia hagedash",
        lat=-33.93,
        lon=18.42,  # Cape Town
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Cape Weaver in Cape Town (common resident)",
        scientific_name="Ploceus capensis",
        lat=-33.93,
        lon=18.42,
        expected_tier="common",
    ),
    # ===== South America - Common Species =====
    SpeciesTestCase(
        name="Rufous Hornero in Buenos Aires (common resident)",
        scientific_name="Furnarius rufus",
        lat=-34.60,
        lon=-58.38,  # Buenos Aires
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Monk Parakeet in Buenos Aires (common resident)",
        scientific_name="Myiopsitta monachus",
        lat=-34.60,
        lon=-58.38,
        expected_tier="common",
    ),
    # ===== Asia - Common Species =====
    SpeciesTestCase(
        name="Oriental Magpie-Robin in Singapore (common resident)",
        scientific_name="Copsychus saularis",
        lat=1.35,
        lon=103.82,  # Singapore
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Javan Myna in Singapore (common resident)",
        scientific_name="Acridotheres javanicus",
        lat=1.35,
        lon=103.82,
        expected_tier="common",
    ),
    # ===== Edge Cases =====
    SpeciesTestCase(
        name="House Sparrow in remote Alaska (likely absent/rare)",
        scientific_name="Passer domesticus",
        lat=64.84,
        lon=-147.72,  # Fairbanks
        expected_tier="rare",  # Present but uncommon in remote areas
        notes="Introduced species, common near human habitation",
    ),
    SpeciesTestCase(
        name="Rock Pigeon in Tokyo (common cosmopolitan)",
        scientific_name="Columba livia",
        lat=35.68,
        lon=139.76,  # Tokyo
        expected_tier="common",
    ),
    # ===== Additional North America Tests =====
    SpeciesTestCase(
        name="Bald Eagle in Seattle (common resident)",
        scientific_name="Haliaeetus leucocephalus",
        lat=47.61,
        lon=-122.33,  # Seattle
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Anna's Hummingbird in San Francisco (common resident)",
        scientific_name="Calypte anna",
        lat=37.77,
        lon=-122.42,  # San Francisco
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Greater Roadrunner in Phoenix (common resident)",
        scientific_name="Geococcyx californianus",
        lat=33.45,
        lon=-112.07,  # Phoenix
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="California Condor in Los Angeles (rare - recovering)",
        scientific_name="Gymnogyps californianus",
        lat=34.05,
        lon=-118.24,  # Los Angeles
        expected_tier="rare",
        notes="Endangered species, small population",
    ),
    SpeciesTestCase(
        name="Painted Bunting in Texas (summer breeder)",
        scientific_name="Passerina ciris",
        lat=29.76,
        lon=-95.37,  # Houston
        expected_tier="uncommon",
        month=6,
    ),
    SpeciesTestCase(
        name="Painted Bunting in Texas (winter - absent)",
        scientific_name="Passerina ciris",
        lat=29.76,
        lon=-95.37,
        expected_tier="seasonal_absent",
        month=1,
    ),
    # ===== Central America =====
    SpeciesTestCase(
        name="Resplendent Quetzal in Costa Rica (uncommon resident)",
        scientific_name="Pharomachrus mocinno",
        lat=10.02,
        lon=-84.11,  # Monteverde area
        expected_tier="uncommon",
    ),
    SpeciesTestCase(
        name="Keel-billed Toucan in Costa Rica (common)",
        scientific_name="Ramphastos sulfuratus",
        lat=10.02,
        lon=-84.11,
        expected_tier="common",
    ),
    # ===== South America =====
    SpeciesTestCase(
        name="Andean Condor in Peru (uncommon)",
        scientific_name="Vultur gryphus",
        lat=-13.53,
        lon=-71.97,  # Cusco area
        expected_tier="uncommon",
    ),
    SpeciesTestCase(
        name="Hyacinth Macaw in Pantanal (rare)",
        scientific_name="Anodorhynchus hyacinthinus",
        lat=-19.03,
        lon=-57.65,  # Pantanal, Brazil
        expected_tier="rare",
        notes="Endangered, localized",
    ),
    # ===== Europe Additional =====
    SpeciesTestCase(
        name="Eurasian Hoopoe in Spain (common summer)",
        scientific_name="Upupa epops",
        lat=40.42,
        lon=-3.70,  # Madrid
        expected_tier="common",
        month=6,
    ),
    SpeciesTestCase(
        name="Atlantic Puffin in Iceland (common breeder)",
        scientific_name="Fratercula arctica",
        lat=64.15,
        lon=-21.95,  # Reykjavik area
        expected_tier="common",
        month=7,
    ),
    SpeciesTestCase(
        name="White Stork in Germany (common summer)",
        scientific_name="Ciconia ciconia",
        lat=52.52,
        lon=13.40,  # Berlin
        expected_tier="uncommon",
        month=6,
    ),
    # ===== Africa Additional =====
    SpeciesTestCase(
        name="African Fish Eagle in Kenya (common)",
        scientific_name="Icthyophaga vocifer",  # Note: genus changed from Haliaeetus
        lat=-0.09,
        lon=34.76,  # Lake Victoria
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Lilac-breasted Roller in Tanzania (common)",
        scientific_name="Coracias caudatus",
        lat=-3.37,
        lon=36.68,  # Serengeti area
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Shoebill in Uganda (common at hotspot)",
        scientific_name="Balaeniceps rex",
        lat=1.37,
        lon=32.29,  # Murchison Falls area - birding hotspot!
        expected_tier="common",  # Common at this specific birding destination
        notes="Globally rare but common at eBird hotspots where birders go specifically to see it",
    ),
    # ===== Asia Additional =====
    SpeciesTestCase(
        name="Indian Peafowl in India (common)",
        scientific_name="Pavo cristatus",
        lat=28.61,
        lon=77.21,  # Delhi
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Japanese Bush Warbler in Japan (common)",
        scientific_name="Horornis diphone",
        lat=35.68,
        lon=139.76,  # Tokyo
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Red-crowned Crane in Hokkaido (common at wintering grounds)",
        scientific_name="Grus japonensis",
        lat=43.06,
        lon=144.41,  # Hokkaido - this IS the wintering ground
        expected_tier="common",  # Common at this specific location where they concentrate
        month=1,
        notes="Globally endangered but common at eBird hotspots where wintering population concentrates",
    ),
    # ===== Oceania Additional =====
    SpeciesTestCase(
        name="Tui in New Zealand (common)",
        scientific_name="Prosthemadera novaeseelandiae",
        lat=-41.29,
        lon=174.78,  # Wellington
        expected_tier="common",
    ),
    SpeciesTestCase(
        name="Kiwi in New Zealand (rare, nocturnal)",
        scientific_name="Apteryx mantelli",
        lat=-38.14,
        lon=176.24,  # Rotorua area
        expected_tier="rare",
        notes="Nocturnal, rarely seen",
    ),
    SpeciesTestCase(
        name="Superb Fairywren in Australia (common)",
        scientific_name="Malurus cyaneus",
        lat=-33.87,
        lon=151.21,  # Sydney
        expected_tier="common",
    ),
    # ===== Pelagic/Remote =====
    SpeciesTestCase(
        name="Wandering Albatross in Southern Ocean (uncommon)",
        scientific_name="Diomedea exulans",
        lat=-54.00,
        lon=-38.00,  # South Georgia area
        expected_tier="uncommon",
    ),
    SpeciesTestCase(
        name="King Penguin at South Georgia (common breeder)",
        scientific_name="Aptenodytes patagonicus",  # King Penguin, not Emperor
        lat=-54.00,
        lon=-38.00,  # South Georgia
        expected_tier="common",
        notes="Large breeding colonies at South Georgia",
    ),
]


# ===== Confidence Boost Test Cases =====
@dataclass
class BoostTestCase:
    """Test case for confidence boost validation."""

    name: str
    scientific_name: str
    lat: float
    lon: float
    expected_boost_direction: str  # "positive" (>1), "negative" (<1), "neutral" (~1)
    notes: str = ""


BOOST_TEST_CASES = [
    # Common species should have positive boost (>1)
    BoostTestCase(
        name="American Robin boost in NYC",
        scientific_name="Turdus migratorius",
        lat=40.78,
        lon=-73.97,
        expected_boost_direction="positive",
        notes="Common species should boost detection confidence",
    ),
    BoostTestCase(
        name="House Sparrow boost in London",
        scientific_name="Passer domesticus",
        lat=51.51,
        lon=-0.13,
        expected_boost_direction="positive",
    ),
    BoostTestCase(
        name="Australian Magpie boost in Sydney",
        scientific_name="Gymnorhina tibicen",
        lat=-33.87,
        lon=151.21,
        expected_boost_direction="positive",
    ),
    # Rare/vagrant species should have negative boost (<1)
    BoostTestCase(
        name="Snowy Owl boost in NYC",
        scientific_name="Bubo scandiacus",
        lat=40.78,
        lon=-73.97,
        expected_boost_direction="negative",
        notes="Rare species should reduce detection confidence",
    ),
    BoostTestCase(
        name="European Robin boost in NYC (vagrant)",
        scientific_name="Erithacus rubecula",
        lat=40.78,
        lon=-73.97,
        expected_boost_direction="negative",
        notes="Vagrant species should significantly reduce confidence",
    ),
    # Uncommon species should have neutral or slight boost
    BoostTestCase(
        name="Ruby-throated Hummingbird boost in NYC (summer)",
        scientific_name="Archilochus colubris",
        lat=40.78,
        lon=-73.97,
        expected_boost_direction="neutral",
        notes="Uncommon species - slight adjustment either way",
    ),
]


def find_pack_for_location(lat: float, lon: float) -> Path | None:
    """Find the pack file that covers a given location."""
    # Get H3 cell at boundary resolution (4)
    h3_cell = h3.latlng_to_cell(lat, lon, 4)

    # Search all packs for this cell
    for pack_path in PACKS_DIR.glob("*.db"):
        if pack_path.name.startswith("."):
            continue
        try:
            conn = sqlite3.connect(pack_path)
            cursor = conn.execute(
                "SELECT COUNT(*) FROM grid_species WHERE h3_cell = ?",
                (int(h3_cell, 16),)
            )
            count = cursor.fetchone()[0]
            conn.close()
            if count > 0:
                return pack_path
        except Exception:
            continue
    return None


def get_species_data(
    pack_path: Path,
    scientific_name: str,
    lat: float,
    lon: float,
    month: int | None = None,
) -> dict | None:
    """Query pack for species data at a location."""
    h3_cell = h3.latlng_to_cell(lat, lon, 4)
    h3_int = int(h3_cell, 16)

    conn = sqlite3.connect(pack_path)
    conn.row_factory = sqlite3.Row

    # First get avibase_id for the species
    cursor = conn.execute(
        "SELECT avibase_id FROM species_lookup WHERE scientific_name = ?",
        (scientific_name,)
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    avibase_id = row["avibase_id"]

    # Get species data at this cell
    # Try resolution 4 first, then fall back to coarser resolutions
    for res in [4, 2]:
        if res == 4:
            cell_int = h3_int
        else:
            parent = h3.cell_to_parent(h3_cell, res)
            cell_int = int(parent, 16)

        cursor = conn.execute(
            """
            SELECT confidence_tier, confidence_boost, yearly_frequency, quality_score
            FROM grid_species
            WHERE h3_cell = ? AND resolution = ? AND avibase_id = ?
            """,
            (cell_int, res, avibase_id)
        )
        row = cursor.fetchone()
        if row:
            result = dict(row)
            result["resolution"] = res

            # Get monthly data if requested
            if month is not None:
                cursor = conn.execute(
                    """
                    SELECT frequency, checklist_count
                    FROM grid_species_monthly
                    WHERE h3_cell = ? AND resolution = ? AND avibase_id = ? AND month = ?
                    """,
                    (cell_int, res, avibase_id, month)
                )
                monthly = cursor.fetchone()
                if monthly:
                    result["monthly_frequency"] = monthly["frequency"]
                    result["monthly_checklist_count"] = monthly["checklist_count"]

            conn.close()
            return result

    conn.close()
    return None


class TestPackValidation:
    """Test suite for pack species frequency validation."""

    @pytest.fixture(scope="class")
    def pack_availability(self):
        """Check which packs are available."""
        available = list(PACKS_DIR.glob("*.db"))
        return [p for p in available if not p.name.startswith(".")]

    def test_packs_exist(self, pack_availability):
        """Verify at least some packs have been built."""
        assert len(pack_availability) > 0, "No packs found in packs directory"
        print(f"Found {len(pack_availability)} pack files")

    @pytest.mark.parametrize("test_case", TEST_CASES, ids=lambda tc: tc.name)
    def test_species_occurrence(self, test_case: SpeciesTestCase):
        """Test species occurrence matches expected tier."""
        pack_path = find_pack_for_location(test_case.lat, test_case.lon)

        if pack_path is None:
            pytest.skip(f"No pack available for location ({test_case.lat}, {test_case.lon})")

        species_data = get_species_data(
            pack_path,
            test_case.scientific_name,
            test_case.lat,
            test_case.lon,
            test_case.month,
        )

        if test_case.expected_tier == "absent":
            # Species should not be in the database for this location
            assert species_data is None, (
                f"Expected {test_case.scientific_name} to be absent at "
                f"({test_case.lat}, {test_case.lon}), but found: {species_data}"
            )
        elif test_case.expected_tier == "seasonal_absent":
            # Species may exist in database but should have no/low monthly frequency
            if species_data is None:
                pass  # OK - not in database at all
            else:
                monthly_freq = species_data.get("monthly_frequency", 0)
                assert monthly_freq < 0.001, (
                    f"Expected {test_case.scientific_name} to be seasonally absent "
                    f"in month {test_case.month} at ({test_case.lat}, {test_case.lon}), "
                    f"but found monthly_frequency={monthly_freq}"
                )
        else:
            # Species should be present with correct tier
            assert species_data is not None, (
                f"Expected {test_case.scientific_name} to be {test_case.expected_tier} at "
                f"({test_case.lat}, {test_case.lon}), but species not found in pack"
            )

            actual_tier = species_data["confidence_tier"]

            # Allow some flexibility in tier matching
            tier_order = ["common", "uncommon", "rare", "vagrant"]
            expected_idx = tier_order.index(test_case.expected_tier)
            actual_idx = tier_order.index(actual_tier)

            # Allow +/- 1 tier difference (e.g., expected uncommon, got common or rare)
            tier_diff = abs(expected_idx - actual_idx)

            assert tier_diff <= 1, (
                f"Tier mismatch for {test_case.scientific_name} at "
                f"({test_case.lat}, {test_case.lon}): "
                f"expected {test_case.expected_tier}, got {actual_tier}"
            )

            if tier_diff == 1:
                print(
                    f"WARNING: Minor tier difference for {test_case.name}: "
                    f"expected {test_case.expected_tier}, got {actual_tier}"
                )

    @pytest.mark.parametrize("test_case", BOOST_TEST_CASES, ids=lambda tc: tc.name)
    def test_confidence_boost(self, test_case: BoostTestCase):
        """Test that confidence boost values are appropriate for species rarity."""
        pack_path = find_pack_for_location(test_case.lat, test_case.lon)

        if pack_path is None:
            pytest.skip(f"No pack available for location ({test_case.lat}, {test_case.lon})")

        species_data = get_species_data(
            pack_path,
            test_case.scientific_name,
            test_case.lat,
            test_case.lon,
        )

        if species_data is None:
            pytest.skip(f"Species {test_case.scientific_name} not found in pack")

        boost = species_data["confidence_boost"]

        if test_case.expected_boost_direction == "positive":
            assert boost >= 1.0, (
                f"Expected positive boost (>=1.0) for {test_case.scientific_name}, "
                f"got {boost:.3f}"
            )
        elif test_case.expected_boost_direction == "negative":
            assert boost < 1.0, (
                f"Expected negative boost (<1.0) for {test_case.scientific_name}, "
                f"got {boost:.3f}"
            )
        else:  # neutral
            assert 0.7 <= boost <= 1.3, (
                f"Expected neutral boost (0.7-1.3) for {test_case.scientific_name}, "
                f"got {boost:.3f}"
            )


def run_validation_report():
    """Generate a detailed validation report."""
    print("=" * 70)
    print("PACK VALIDATION REPORT")
    print("=" * 70)

    results = {"pass": 0, "fail": 0, "skip": 0, "warn": 0}

    for tc in TEST_CASES:
        pack_path = find_pack_for_location(tc.lat, tc.lon)

        if pack_path is None:
            print(f"SKIP: {tc.name}")
            print(f"      No pack for ({tc.lat}, {tc.lon})")
            results["skip"] += 1
            continue

        species_data = get_species_data(
            pack_path, tc.scientific_name, tc.lat, tc.lon, tc.month
        )

        if tc.expected_tier == "absent":
            if species_data is None:
                print(f"PASS: {tc.name}")
                results["pass"] += 1
            else:
                print(f"FAIL: {tc.name}")
                print(f"      Expected absent, found: {species_data['confidence_tier']}")
                results["fail"] += 1
        elif tc.expected_tier == "seasonal_absent":
            if species_data is None:
                print(f"PASS: {tc.name}")
                results["pass"] += 1
            else:
                monthly_freq = species_data.get("monthly_frequency", 0)
                if monthly_freq < 0.001:
                    print(f"PASS: {tc.name}")
                    print(f"      Monthly frequency: {monthly_freq:.6f} (correctly low/absent)")
                    results["pass"] += 1
                else:
                    print(f"FAIL: {tc.name}")
                    print(f"      Expected seasonally absent, monthly_frequency={monthly_freq:.4f}")
                    results["fail"] += 1
        else:
            if species_data is None:
                print(f"FAIL: {tc.name}")
                print(f"      Expected {tc.expected_tier}, but species not found")
                results["fail"] += 1
            else:
                tier_order = ["common", "uncommon", "rare", "vagrant"]
                expected_idx = tier_order.index(tc.expected_tier)
                actual_idx = tier_order.index(species_data["confidence_tier"])
                tier_diff = abs(expected_idx - actual_idx)

                if tier_diff == 0:
                    print(f"PASS: {tc.name}")
                    results["pass"] += 1
                elif tier_diff == 1:
                    print(f"WARN: {tc.name}")
                    print(f"      Expected {tc.expected_tier}, got {species_data['confidence_tier']}")
                    results["warn"] += 1
                else:
                    print(f"FAIL: {tc.name}")
                    print(f"      Expected {tc.expected_tier}, got {species_data['confidence_tier']}")
                    results["fail"] += 1

    print()
    print("=" * 70)
    print(f"TIER TESTS: {results['pass']} pass, {results['warn']} warn, "
          f"{results['fail']} fail, {results['skip']} skip")
    print("=" * 70)

    # Run boost tests
    print()
    print("=" * 70)
    print("CONFIDENCE BOOST VALIDATION")
    print("=" * 70)

    boost_results = {"pass": 0, "fail": 0, "skip": 0}

    for tc in BOOST_TEST_CASES:
        pack_path = find_pack_for_location(tc.lat, tc.lon)

        if pack_path is None:
            print(f"SKIP: {tc.name}")
            print(f"      No pack for ({tc.lat}, {tc.lon})")
            boost_results["skip"] += 1
            continue

        species_data = get_species_data(pack_path, tc.scientific_name, tc.lat, tc.lon)

        if species_data is None:
            print(f"SKIP: {tc.name}")
            print(f"      Species not found in pack")
            boost_results["skip"] += 1
            continue

        boost = species_data["confidence_boost"]
        tier = species_data["confidence_tier"]

        if tc.expected_boost_direction == "positive":
            if boost >= 1.0:
                print(f"PASS: {tc.name}")
                print(f"      tier={tier}, boost={boost:.3f} (expected >=1.0)")
                boost_results["pass"] += 1
            else:
                print(f"FAIL: {tc.name}")
                print(f"      tier={tier}, boost={boost:.3f} (expected >=1.0)")
                boost_results["fail"] += 1
        elif tc.expected_boost_direction == "negative":
            if boost < 1.0:
                print(f"PASS: {tc.name}")
                print(f"      tier={tier}, boost={boost:.3f} (expected <1.0)")
                boost_results["pass"] += 1
            else:
                print(f"FAIL: {tc.name}")
                print(f"      tier={tier}, boost={boost:.3f} (expected <1.0)")
                boost_results["fail"] += 1
        else:  # neutral
            if 0.7 <= boost <= 1.3:
                print(f"PASS: {tc.name}")
                print(f"      tier={tier}, boost={boost:.3f} (expected 0.7-1.3)")
                boost_results["pass"] += 1
            else:
                print(f"FAIL: {tc.name}")
                print(f"      tier={tier}, boost={boost:.3f} (expected 0.7-1.3)")
                boost_results["fail"] += 1

    print()
    print("=" * 70)
    print(f"BOOST TESTS: {boost_results['pass']} pass, "
          f"{boost_results['fail']} fail, {boost_results['skip']} skip")
    print("=" * 70)

    # Combined summary
    total_pass = results["pass"] + boost_results["pass"]
    total_fail = results["fail"] + boost_results["fail"]
    total_skip = results["skip"] + boost_results["skip"]
    total_warn = results["warn"]

    print()
    print("=" * 70)
    print(f"OVERALL: {total_pass} pass, {total_warn} warn, {total_fail} fail, {total_skip} skip")
    print("=" * 70)

    return {"tier": results, "boost": boost_results}


if __name__ == "__main__":
    run_validation_report()
