"""Region naming logic for geographic identification."""

import logging

logger = logging.getLogger(__name__)


class RegionNamer:
    """Generate human-readable region names from H3 cells."""

    def __init__(self):
        """Initialize with tracking for unique names."""
        self._name_counts = {}

    # Special regions (islands, oceanic areas) - checked first
    SPECIAL_REGIONS = {
        "oceania-galapagos": {"lon": (-92, -89), "lat": (-2, 1)},  # Galápagos Islands
        "atlantic-azores": {"lon": (-32, -24), "lat": (36, 40)},  # Azores
        "atlantic-canary": {"lon": (-19, -13), "lat": (27, 30)},  # Canary Islands
        "na-aleutian": {"lon": (-180, -165), "lat": (50, 56)},  # Aleutian Islands
        "pacific-hawaii": {"lon": (-161, -154), "lat": (18, 23)},  # Hawaiian Islands
        "pacific-mid": {"lon": (-180, -175), "lat": (25, 35)},  # Mid-Pacific
        "asia-arabian-gulf": {"lon": (50, 60), "lat": (15, 27)},  # UAE/Arabian Gulf/Arabian Sea
        "africa-west-coast": {"lon": (-20, 5), "lat": (0, 18)},  # West Africa coast
        "europe-arctic": {"lon": (15, 70), "lat": (68, 75)},  # Arctic Europe/Russia
        "atlantic-south": {"lon": (-40, 20), "lat": (-60, -30)},  # South Atlantic
        "pacific-western": {"lon": (120, 180), "lat": (-30, 30)},  # Western Pacific
        "pacific-eastern": {"lon": (-180, -120), "lat": (-30, 30)},  # Eastern Pacific
        "indian-ocean": {"lon": (40, 120), "lat": (-60, 30)},  # Indian Ocean
        "southern-ocean": {"lon": (-180, 180), "lat": (-90, -60)},  # Southern Ocean/Antarctica
        "arctic-ocean": {"lon": (-180, 180), "lat": (70, 90)},  # Arctic Ocean
        # Additional oceanic regions for better coverage
        "pacific-marshall": {"lon": (160, 175), "lat": (5, 25)},  # Marshall Islands area
        "pacific-line": {"lon": (-165, -150), "lat": (-5, 10)},  # Line Islands
        "pacific-kiribati": {"lon": (-180, -170), "lat": (-5, 5)},  # Kiribati
        "indian-chagos": {"lon": (65, 80), "lat": (-15, -5)},  # Chagos Archipelago
        "bering-sea": {"lon": (160, 180), "lat": (52, 70)},  # Bering Sea
    }

    # Predefined geographic mappings
    CONTINENT_BOUNDS = {
        "na": {"lon": (-170, -50), "lat": (15, 75)},  # North America
        "sa": {"lon": (-85, -30), "lat": (-60, 15)},  # South America
        "europe": {"lon": (-20, 50), "lat": (35, 70)},  # Europe
        "africa": {"lon": (10, 55), "lat": (-35, 35)},  # Africa
        "asia": {"lon": (60, 150), "lat": (-10, 55)},  # Asia
        "oceania": {"lon": (110, 180), "lat": (-50, -10)},  # Oceania/Australia
    }

    SUBREGION_MAPPINGS = {
        "na": {
            "west-coast": {"lon": (-125, -115), "lat": (32, 49)},
            "east-coast": {"lon": (-80, -70), "lat": (35, 45)},
            "midwest": {"lon": (-95, -80), "lat": (38, 48)},
            "southwest": {"lon": (-115, -100), "lat": (28, 37)},
            "southeast": {"lon": (-95, -75), "lat": (25, 38)},
            "northwest": {"lon": (-125, -105), "lat": (42, 60)},
            "northeast": {"lon": (-80, -65), "lat": (40, 50)},
            "central": {"lon": (-105, -90), "lat": (35, 50)},
        },
        "europe": {
            "western": {"lon": (-10, 10), "lat": (40, 60)},
            "central": {"lon": (5, 20), "lat": (45, 55)},
            "eastern": {"lon": (20, 50), "lat": (45, 60)},
            "northern": {"lon": (10, 30), "lat": (55, 70)},
            "southern": {"lon": (-10, 25), "lat": (35, 45)},
        },
        "asia": {
            "southeast": {"lon": (95, 120), "lat": (-10, 20)},
            "east": {"lon": (110, 145), "lat": (20, 50)},
            "south": {"lon": (60, 95), "lat": (5, 35)},
            "central": {"lon": (50, 85), "lat": (35, 50)},
        },
        "sa": {
            "north": {"lon": (-80, -50), "lat": (-5, 15)},
            "central": {"lon": (-85, -45), "lat": (-20, -5)},
            "south": {"lon": (-75, -45), "lat": (-55, -20)},
        },
        "africa": {
            "north": {"lon": (-10, 40), "lat": (15, 35)},
            "west": {"lon": (-20, 20), "lat": (-5, 20)},
            "east": {"lon": (20, 50), "lat": (-10, 15)},
            "south": {"lon": (15, 35), "lat": (-35, -15)},
        },
        "oceania": {
            "australia": {"lon": (110, 155), "lat": (-45, -10)},
            "pacific": {"lon": (155, 180), "lat": (-25, 10)},
        },
    }

    def name_region(self, region: dict) -> str:
        """
        Generate region name from geographic center with H3 cell ID for uniqueness.

        Args:
            region: Region dict with center lat/lon and h3_cells list

        Returns:
            Unique region slug (e.g., "na-west-coast-8244b", "europe-central-824cd")
        """
        lat = region["center"]["lat"]
        lon = region["center"]["lon"]

        # Check special regions first (islands, oceanic areas)
        special = self._get_special_region(lat, lon)
        if special:
            base_name = special
        else:
            # Determine continent
            continent = self._get_continent(lat, lon)

            # Determine subregion
            subregion = self._get_subregion(continent, lat, lon)

            # Create base slug
            if subregion:
                base_name = f"{continent}-{subregion}"
            else:
                base_name = continent

        # Get primary H3 cell for this region (first cell in the list)
        # Use first 5 characters of the H3 cell ID for brevity
        h3_cells = region.get("h3_cells", [])
        if h3_cells:
            h3_suffix = h3_cells[0][:5]  # First 5 chars of H3 cell ID
            unique_name = f"{base_name}-{h3_suffix}"
        else:
            # Fallback to numeric suffix if no H3 cells (shouldn't happen)
            if base_name in self._name_counts:
                self._name_counts[base_name] += 1
                unique_name = f"{base_name}-{self._name_counts[base_name]}"
            else:
                self._name_counts[base_name] = 1
                unique_name = base_name

        logger.debug("Named region at (%.2f, %.2f) as: %s", lat, lon, unique_name)

        return unique_name

    def _get_special_region(self, lat: float, lon: float) -> str | None:
        """Check if coordinates fall in a special region (islands, oceanic areas)."""
        for region_name, bounds in self.SPECIAL_REGIONS.items():
            lon_min, lon_max = bounds["lon"]
            lat_min, lat_max = bounds["lat"]

            if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
                return region_name

        return None

    def _get_continent(self, lat: float, lon: float) -> str:
        """Determine continent from coordinates."""
        for continent, bounds in self.CONTINENT_BOUNDS.items():
            lon_min, lon_max = bounds["lon"]
            lat_min, lat_max = bounds["lat"]

            if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
                return continent

        # Fallback to ocean-based naming for non-continental areas
        return self._get_ocean_region(lat, lon)

    def _get_ocean_region(self, lat: float, lon: float) -> str:
        """Determine ocean-based region for non-continental coordinates."""
        # Check latitude bands first
        if lat >= 60:
            return "arctic"
        elif lat <= -60:
            return "antarctic"

        # Determine ocean by longitude for tropical/temperate regions
        if -180 <= lon < -20:
            if lat > 0:
                return "pacific-north"
            else:
                return "pacific-south"
        elif -20 <= lon < 40:
            if lat > 0:
                return "atlantic-north"
            else:
                return "atlantic-south"
        elif 40 <= lon < 120:
            if lat > 0:
                return "indian-north"
            else:
                return "indian-south"
        else:  # 120 <= lon <= 180
            if lat > 0:
                return "pacific-west-north"
            else:
                return "pacific-west-south"

    def _get_subregion(self, continent: str, lat: float, lon: float) -> str | None:
        """Determine subregion within continent."""
        if continent not in self.SUBREGION_MAPPINGS:
            return None

        for subregion, bounds in self.SUBREGION_MAPPINGS[continent].items():
            lon_min, lon_max = bounds["lon"]
            lat_min, lat_max = bounds["lat"]

            if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
                return subregion

        # If no specific subregion matches, use generic
        return "main"
