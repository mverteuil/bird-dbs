"""Convert eBird observation data from TSV tarball to Parquet format.

Streams data directly from tarball without extracting to disk.
"""

import csv
import gzip
import tarfile
from pathlib import Path

import polars as pl

from ebd_pack_builder.utils.formatting import format_size


def get_ebird_schema() -> dict:
    """Define the eBird observation schema."""
    return {
        "GLOBAL UNIQUE IDENTIFIER": pl.Utf8,
        "LAST EDITED DATE": pl.Utf8,
        "TAXONOMIC ORDER": pl.Float64,
        "CATEGORY": pl.Utf8,
        "TAXON CONCEPT ID": pl.Utf8,
        "COMMON NAME": pl.Utf8,
        "SCIENTIFIC NAME": pl.Utf8,
        "SUBSPECIES COMMON NAME": pl.Utf8,
        "SUBSPECIES SCIENTIFIC NAME": pl.Utf8,
        "EXOTIC CODE": pl.Utf8,
        "OBSERVATION COUNT": pl.Utf8,
        "BREEDING CODE": pl.Utf8,
        "BREEDING CATEGORY": pl.Utf8,
        "BEHAVIOR CODE": pl.Utf8,
        "AGE/SEX": pl.Utf8,
        "COUNTRY": pl.Utf8,
        "COUNTRY CODE": pl.Utf8,
        "STATE": pl.Utf8,
        "STATE CODE": pl.Utf8,
        "COUNTY": pl.Utf8,
        "COUNTY CODE": pl.Utf8,
        "IBA CODE": pl.Utf8,
        "BCR CODE": pl.Int64,
        "USFWS CODE": pl.Utf8,
        "ATLAS BLOCK": pl.Utf8,
        "LOCALITY": pl.Utf8,
        "LOCALITY ID": pl.Utf8,
        "LOCALITY TYPE": pl.Utf8,
        "LATITUDE": pl.Float64,
        "LONGITUDE": pl.Float64,
        "OBSERVATION DATE": pl.Utf8,
        "TIME OBSERVATIONS STARTED": pl.Utf8,
        "OBSERVER ID": pl.Utf8,
        "SAMPLING EVENT IDENTIFIER": pl.Utf8,
        "PROTOCOL TYPE": pl.Utf8,
        "PROTOCOL CODE": pl.Utf8,
        "PROJECT CODE": pl.Utf8,
        "DURATION MINUTES": pl.Float64,
        "EFFORT DISTANCE KM": pl.Float64,
        "EFFORT AREA HA": pl.Float64,
        "NUMBER OBSERVERS": pl.Int64,
        "ALL SPECIES REPORTED": pl.Int64,
        "GROUP IDENTIFIER": pl.Utf8,
        "HAS MEDIA": pl.Int64,
        "APPROVED": pl.Int64,
        "REVIEWED": pl.Int64,
        "REASON": pl.Utf8,
        "TRIP COMMENTS": pl.Utf8,
        "SPECIES COMMENTS": pl.Utf8,
    }


def convert_tarball_to_parquet(
    tarball_path: Path,
    output_dir: Path,
    chunk_size: int = 1_000_000,
) -> dict:
    """Stream eBird tarball directly to Parquet format (no extraction to disk).

    Args:
        tarball_path: Path to the .tar file containing ebd_*.txt.gz
        output_dir: Directory to write Parquet files
        chunk_size: Number of rows per chunk

    Returns:
        Dict with total_rows and chunk_count metrics
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Streaming from tarball: {tarball_path}")
    print(f"Output directory: {output_dir}")
    print(f"Chunk size: {chunk_size:,} rows\n")

    with tarfile.open(tarball_path, "r") as tar:
        # Find the .txt.gz file (skip macOS resource fork files starting with "._")
        members = tar.getmembers()
        txt_gz_members = [
            m for m in members
            if m.name.endswith(".txt.gz") and not m.name.startswith("._")
        ]

        if not txt_gz_members:
            raise ValueError("No .txt.gz file found in tarball")

        if len(txt_gz_members) > 1:
            print(f"Warning: Multiple .txt.gz files found, using: {txt_gz_members[0].name}")

        member = txt_gz_members[0]
        print(f"Processing: {member.name} ({member.size / 1e9:.1f} GB compressed)")
        print("Streaming: tar -> gzip -> TSV -> Parquet (no disk extraction)\n")

        # Get file-like object (streaming, not extracting!)
        compressed_stream = tar.extractfile(member)
        if compressed_stream is None:
            raise ValueError(f"Could not get stream for {member.name}")

        chunk_num = 0
        total_rows = 0

        with gzip.open(compressed_stream, "rt", encoding="utf-8") as text_stream:
            # Read header
            csv_reader = csv.DictReader(text_stream, delimiter="\t")

            chunk_rows: list[dict] = []
            for row in csv_reader:
                # Convert None values to empty strings and filter out None keys
                # (DictReader returns None for empty fields, and trailing tabs create None keys)
                clean_row = {
                    k: (v if v is not None else "")
                    for k, v in row.items()
                    if k is not None
                }
                chunk_rows.append(clean_row)

                if len(chunk_rows) >= chunk_size:
                    # Convert chunk to DataFrame
                    chunk_num += 1
                    total_rows += len(chunk_rows)

                    print(
                        f"Chunk {chunk_num}: {len(chunk_rows):,} rows (total: {total_rows:,})",
                        end="",
                    )

                    # Convert to DataFrame - use all strings to avoid schema issues
                    df = pl.DataFrame(chunk_rows)

                    # Write chunk to Parquet
                    output_file = output_dir / f"ebird_{chunk_num:04d}.parquet"
                    df.write_parquet(
                        output_file,
                        compression="zstd",
                        compression_level=3,
                    )

                    file_size_mb = output_file.stat().st_size / 1e6
                    print(f" -> {file_size_mb:.1f} MB")

                    # Clear chunk
                    chunk_rows = []

            # Write final chunk if any rows remain
            if chunk_rows:
                chunk_num += 1
                total_rows += len(chunk_rows)

                print(
                    f"Chunk {chunk_num}: {len(chunk_rows):,} rows (total: {total_rows:,})",
                    end="",
                )

                # Convert to DataFrame - use all strings to avoid schema issues
                df = pl.DataFrame(chunk_rows)

                output_file = output_dir / f"ebird_{chunk_num:04d}.parquet"
                df.write_parquet(
                    output_file,
                    compression="zstd",
                    compression_level=3,
                )

                file_size_mb = output_file.stat().st_size / 1e6
                print(f" -> {file_size_mb:.1f} MB")

        # Calculate total output size
        total_size = sum(f.stat().st_size for f in output_dir.glob("*.parquet"))

        print(f"\nConversion complete!")
        print(f"  Total rows: {total_rows:,}")
        print(f"  Total chunks: {chunk_num}")
        print(f"  Total size: {format_size(total_size)}")
        print(f"  Output directory: {output_dir}")

        return {
            "total_rows": total_rows,
            "chunk_count": chunk_num,
            "total_size_bytes": total_size,
        }
