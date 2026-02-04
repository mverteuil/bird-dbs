"""Bundle region packs into GitHub releases with size constraints."""

from dataclasses import dataclass
from pathlib import Path

from .manifest import PackRegistry


@dataclass
class RegionFile:
    """Information about a region's .db.gz file."""

    region_id: str
    release_name: str
    file_path: Path
    size_bytes: int

    @property
    def size_mb(self) -> float:
        """Size in MB."""
        return self.size_bytes / 1024 / 1024


@dataclass
class ReleaseBundle:
    """A bundle of regions grouped into a single GitHub release."""

    bundle_id: int
    release_name: str
    regions: list[RegionFile]
    total_size_bytes: int

    @property
    def total_size_mb(self) -> float:
        """Total size in MB."""
        return self.total_size_bytes / 1024 / 1024


def collect_region_files(registry: PackRegistry, db_dir: Path) -> list[RegionFile]:
    """Collect all region .db.gz files with their sizes.

    Args:
        registry: Pack registry
        db_dir: Directory containing .db.gz files

    Returns:
        List of RegionFile objects sorted by size (largest first)
    """
    region_files = []

    for region in registry.regions:
        db_file = db_dir / f"{region.release_name}.db.gz"

        if not db_file.exists():
            print(f"  ⚠ Warning: {db_file.name} not found, skipping")
            continue

        size_bytes = db_file.stat().st_size
        region_files.append(
            RegionFile(
                region_id=region.region_id,
                release_name=region.release_name,
                file_path=db_file,
                size_bytes=size_bytes,
            )
        )

    # Sort by size descending (largest first for better bin packing)
    region_files.sort(key=lambda r: r.size_bytes, reverse=True)

    return region_files


def create_bundles(
    region_files: list[RegionFile],
    max_bundle_mb: int = 1950,
    version: str = "2025.08",
) -> list[ReleaseBundle]:
    """Group region files into bundles using first-fit-decreasing bin packing.

    Args:
        region_files: List of region files (should be sorted by size descending)
        max_bundle_mb: Maximum bundle size in MB
        version: Version string for release names

    Returns:
        List of ReleaseBundle objects
    """
    max_bundle_bytes = max_bundle_mb * 1024 * 1024
    bundles: list[ReleaseBundle] = []

    for region_file in region_files:
        # Try to fit into existing bundle
        placed = False
        for bundle in bundles:
            if bundle.total_size_bytes + region_file.size_bytes <= max_bundle_bytes:
                bundle.regions.append(region_file)
                bundle.total_size_bytes += region_file.size_bytes
                placed = True
                break

        # Create new bundle if needed
        if not placed:
            bundle_id = len(bundles) + 1
            bundles.append(
                ReleaseBundle(
                    bundle_id=bundle_id,
                    release_name=f"pack-bundle-{bundle_id:03d}-{version}",
                    regions=[region_file],
                    total_size_bytes=region_file.size_bytes,
                )
            )

    return bundles


def build_release_bundles(
    registry: PackRegistry, db_dir: Path, max_bundle_mb: int = 1950, version: str = "2025.08"
) -> tuple[list[ReleaseBundle], dict[str, str]]:
    """Build release bundles from registry and .db.gz files.

    Args:
        registry: Pack registry
        db_dir: Directory containing .db.gz files
        max_bundle_mb: Maximum bundle size in MB
        version: Version string for release names

    Returns:
        Tuple of (bundles, region_to_release_map)
        - bundles: List of ReleaseBundle objects
        - region_to_release_map: Dict mapping region_id to release_name
    """
    # Collect all region files
    region_files = collect_region_files(registry, db_dir)

    print(f"\n📦 Collected {len(region_files)} region files")
    total_size_mb = sum(r.size_mb for r in region_files)
    print(f"  Total size: {total_size_mb:.1f} MB")

    # Create bundles
    bundles = create_bundles(region_files, max_bundle_mb, version)

    print(f"\n📊 Created {len(bundles)} release bundles:")
    for bundle in bundles:
        print(
            f"  {bundle.release_name}: {len(bundle.regions)} regions, {bundle.total_size_mb:.1f} MB"
        )

    # Build region-to-release map
    region_to_release: dict[str, str] = {}
    for bundle in bundles:
        for region_file in bundle.regions:
            region_to_release[region_file.region_id] = bundle.release_name

    return bundles, region_to_release
