"""Package built packs for release.

Gzips .db files with release-compatible naming for the release-publisher tool.
"""

import gzip
import json
import shutil
from pathlib import Path

from ebd_pack_builder.utils.formatting import format_size


def package_packs(
    packs_dir: Path,
    registry_path: Path,
    compression_level: int = 6,
) -> dict:
    """Gzip all .db files with release-compatible naming.

    Args:
        packs_dir: Directory containing built .db pack files
        registry_path: Pack registry JSON (from build command)
        compression_level: Gzip compression level 1-9 (default: 6)

    Returns:
        Dict with packaging statistics
    """
    with open(registry_path) as f:
        registry = json.load(f)

    regions = registry.get("regions", [])

    print("=" * 60)
    print("Packaging Packs for Release")
    print("=" * 60)
    print(f"Packs directory: {packs_dir}")
    print(f"Registry: {registry_path}")
    print(f"Regions: {len(regions)}")
    print(f"Compression level: {compression_level}")
    print()

    packaged = 0
    skipped = 0
    total_uncompressed = 0
    total_compressed = 0

    for i, region in enumerate(regions, 1):
        region_id = region["region_id"]
        release_name = region["release_name"]

        db_file = packs_dir / f"{region_id}.db"
        gz_file = packs_dir / f"{release_name}.db.gz"

        if not db_file.exists():
            print(f"[{i}/{len(regions)}] {region_id}: SKIP (no .db file)")
            skipped += 1
            continue

        if gz_file.exists():
            print(f"[{i}/{len(regions)}] {region_id}: SKIP (already packaged)")
            skipped += 1
            total_compressed += gz_file.stat().st_size
            total_uncompressed += db_file.stat().st_size
            continue

        db_size = db_file.stat().st_size

        with open(db_file, "rb") as f_in:
            with gzip.open(gz_file, "wb", compresslevel=compression_level) as f_out:
                shutil.copyfileobj(f_in, f_out)

        gz_size = gz_file.stat().st_size
        ratio = gz_size / db_size * 100

        print(
            f"[{i}/{len(regions)}] {region_id}: "
            f"{format_size(db_size)} -> {format_size(gz_size)} ({ratio:.1f}%)"
        )

        packaged += 1
        total_uncompressed += db_size
        total_compressed += gz_size

    print()
    print("=" * 60)
    print("PACKAGING COMPLETE")
    print("=" * 60)
    print(f"  Packaged: {packaged}")
    print(f"  Skipped: {skipped}")
    print(f"  Uncompressed: {format_size(total_uncompressed)}")
    print(f"  Compressed: {format_size(total_compressed)}")
    if total_uncompressed > 0:
        print(f"  Ratio: {total_compressed / total_uncompressed * 100:.1f}%")

    return {
        "packaged": packaged,
        "skipped": skipped,
        "total_uncompressed_bytes": total_uncompressed,
        "total_compressed_bytes": total_compressed,
    }
