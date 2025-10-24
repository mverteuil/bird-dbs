"""Region naming logic for geographic identification."""

import logging

logger = logging.getLogger(__name__)


class RegionNamer:
    """Generate human-readable region names from H3 cells."""

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

    def name_region(self, region: dict, region_counter: dict[str, int]) -> str:
        """
        Generate region name from custom region tag (no sequential numbering).

        Args:
            region: Region dict with m49_region tag and center lat/lon
            region_counter: Counter dict (unused, kept for API compatibility)

        Returns:
            Region slug (e.g., "northern-america-west", "middle-east")
        """
        # Use m49_region tag directly (one region pack per boundary)
        if "m49_region" in region:
            slug = region["m49_region"]

            logger.debug(
                "Named region at (%.2f, %.2f) as: %s",
                region["center"]["lat"],
                region["center"]["lon"],
                slug,
            )
            return slug

        # Fallback to old logic for regions without M49 tag
        lat = region["center"]["lat"]
        lon = region["center"]["lon"]

        # Check special regions first (islands, oceanic areas)
        special = self._get_special_region(lat, lon)
        if special:
            logger.debug("Named region at (%.2f, %.2f) as: %s", lat, lon, special)
            return special

        # Determine continent
        continent = self._get_continent(lat, lon)

        # Determine subregion
        subregion = self._get_subregion(continent, lat, lon)

        # Create slug with counter
        if continent not in region_counter:
            region_counter[continent] = 0
        region_counter[continent] += 1

        if subregion:
            slug = f"{continent}-{subregion}-{region_counter[continent]:02d}"
        else:
            slug = f"{continent}-{region_counter[continent]:02d}"

        logger.debug("Named region at (%.2f, %.2f) as: %s", lat, lon, slug)

        return slug

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

        # Default fallback
        return "unknown"

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
