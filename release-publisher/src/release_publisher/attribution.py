"""eBird data attribution and citation generation."""

from dataclasses import dataclass


@dataclass
class EBirdAttribution:
    """eBird Basic Dataset attribution information."""

    version: str = "EBD_relAug-2025"
    institution: str = "Cornell Lab of Ornithology"
    location: str = "Ithaca, New York"
    month_year: str = "Aug 2025"

    @property
    def citation(self) -> str:
        """Get formatted citation string."""
        return (
            f"eBird Basic Dataset. Version: {self.version}.\n"
            f"eBird Sampling Dataset. Version: {self.version}.\n"
            f"{self.institution}, {self.location}. {self.month_year}."
        )

    @property
    def terms_url(self) -> str:
        """Get eBird Terms of Use URL."""
        return "https://www.birds.cornell.edu/home/ebird-data-access-terms-of-use/"

    @property
    def ebird_url(self) -> str:
        """Get eBird website URL."""
        return "https://ebird.org"

    def release_description(self, region_name: str) -> str:
        """Generate GitHub release description with attribution.

        Args:
            region_name: Human-readable region name

        Returns:
            Formatted release description with citation
        """
        return f"""{region_name} eBird Species Pack

Data derived from:
{self.citation}

See ATTRIBUTION.txt for complete citation and terms.

Terms of Use: {self.terms_url}
"""

    def attribution_file_content(self) -> str:
        """Generate ATTRIBUTION.txt file content.

        Returns:
            Complete attribution file content
        """
        return f"""eBird Basic Dataset Citation
=============================

This dataset is derived from:
{self.citation}

Terms of Use: {self.terms_url}
eBird Website: {self.ebird_url}

Processing Information
======================
Aggregated using H3 hexagonal spatial indexing (resolution 5-7)
Filtered for approved observations from complete checklists
Native species only, 2020-2025 date range

About This Data
===============
eBird is a real-time, online bird checklist program. Launched in 2002 by the
Cornell Lab of Ornithology and National Audubon Society, eBird gathers
observations from bird watchers worldwide.

This regional pack contains aggregated species occurrence data processed from
the eBird Basic Dataset to reduce false positives in bird detection systems.

License and Terms
=================
Use of this data is subject to the eBird Terms of Use:
{self.terms_url}

Please cite the eBird Basic Dataset when using this data:
{self.citation}
"""

    def readme_attribution_section(self) -> str:
        """Generate README attribution section.

        Returns:
            Markdown section for repository README
        """
        return f"""## Data Attribution

All species packs in this repository are derived from:

**{self.citation}**

### Terms of Use

Use of this data is subject to the [eBird Terms of Use]({self.terms_url}).

Please cite the eBird Basic Dataset when using these regional packs.

### About eBird

[eBird]({self.ebird_url}) is a real-time, online bird checklist program launched in 2002
by the Cornell Lab of Ornithology and National Audubon Society. eBird gathers observations
from bird watchers worldwide and is one of the largest biodiversity-related science projects
in the world.

### Processing

These regional packs aggregate raw eBird observations using:
- H3 hexagonal spatial indexing (resolution 5-7)
- Filtering for approved observations from complete checklists
- Native species only, 2020-2025 date range
- Minimum thresholds for observations and checklists per species
"""


def get_default_attribution() -> EBirdAttribution:
    """Get default eBird attribution for Aug 2025 release.

    Returns:
        EBirdAttribution configured for current release
    """
    return EBirdAttribution()
