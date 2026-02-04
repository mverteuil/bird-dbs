#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "polars>=1.0.0",
# ]
# ///
"""
Convert eBird sampling event data from TSV to Parquet format.

Streams data directly from tarball without extracting to disk.
The sampling file contains checklist metadata (33 columns) without species data.

Usage:
    uv run convert_sampling_to_parquet.py \
        --input /Volumes/backup/ebird/ebd_sampling_relAug-2025.tar \
        --output-dir /Volumes/Lightroom/ebird_sampling
"""

import argparse
import csv
import gzip
import tarfile
import time
from pathlib import Path

import polars as pl


def get_sampling_schema():
    """
    Define the eBird sampling event schema.

    33 columns containing checklist metadata without species-specific data.
    """
    return {
        "LAST EDITED DATE": pl.Utf8,
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
        "OBSERVER ORCID ID": pl.Utf8,
        "SAMPLING EVENT IDENTIFIER": pl.Utf8,
        "OBSERVATION TYPE": pl.Utf8,
        "PROTOCOL NAME": pl.Utf8,
        "PROTOCOL CODE": pl.Utf8,
        "PROJECT NAMES": pl.Utf8,
        "PROJECT IDENTIFIERS": pl.Utf8,
        "DURATION MINUTES": pl.Float64,
        "EFFORT DISTANCE KM": pl.Float64,
        "EFFORT AREA HA": pl.Float64,
        "NUMBER OBSERVERS": pl.Int64,
        "ALL SPECIES REPORTED": pl.Int64,
        "GROUP IDENTIFIER": pl.Utf8,
        "CHECKLIST COMMENTS": pl.Utf8,
    }


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def convert_tarball_to_parquet(
    tarball_path: Path,
    output_dir: Path,
    chunk_size: int = 1_000_000,
):
    """
    Stream eBird sampling tarball directly to Parquet format.

    Args:
        tarball_path: Path to the .tar file containing ebd_sampling_*.txt.gz
        output_dir: Directory to write Parquet files
        chunk_size: Number of rows per chunk
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Input tarball: {tarball_path}")
    print(f"Output directory: {output_dir}")
    print(f"Chunk size: {chunk_size:,} rows")
    print()

    start_time = time.time()

    with tarfile.open(tarball_path, "r") as tar:
        # Find the .txt.gz file
        members = tar.getmembers()
        txt_gz_members = [m for m in members if m.name.endswith(".txt.gz")]

        if not txt_gz_members:
            raise ValueError("No .txt.gz file found in tarball")

        if len(txt_gz_members) > 1:
            print(f"Warning: Multiple .txt.gz files found, using: {txt_gz_members[0].name}")

        member = txt_gz_members[0]
        compressed_size_gb = member.size / (1024**3)
        print(f"Processing: {member.name} ({compressed_size_gb:.2f} GB compressed)")
        print("Streaming: tar -> gzip -> TSV -> Parquet (no disk extraction)")
        print()

        # Get file-like object (streaming, not extracting!)
        compressed_stream = tar.extractfile(member)
        if compressed_stream is None:
            raise ValueError(f"Could not get stream for {member.name}")

        chunk_num = 0
        total_rows = 0

        with gzip.open(compressed_stream, "rt", encoding="utf-8") as text_stream:
            # Read header
            csv_reader = csv.DictReader(text_stream, delimiter="\t")

            # Verify column count
            if csv_reader.fieldnames:
                print(f"Columns found: {len(csv_reader.fieldnames)}")
                print()

            chunk_rows = []
            for row in csv_reader:
                chunk_rows.append(row)

                if len(chunk_rows) >= chunk_size:
                    chunk_num += 1
                    total_rows += len(chunk_rows)

                    elapsed = time.time() - start_time
                    rate = total_rows / elapsed if elapsed > 0 else 0
                    print(
                        f"Chunk {chunk_num}: {len(chunk_rows):,} rows "
                        f"(total: {total_rows:,}, {rate:,.0f} rows/sec)",
                        end="",
                    )

                    # Convert to DataFrame
                    df = pl.DataFrame(chunk_rows)

                    # Write chunk to Parquet
                    output_file = output_dir / f"sampling_{chunk_num:04d}.parquet"
                    df.write_parquet(
                        output_file,
                        compression="zstd",
                        compression_level=3,
                    )

                    file_size_mb = output_file.stat().st_size / (1024**2)
                    print(f" -> {file_size_mb:.1f} MB")

                    chunk_rows = []

            # Write final chunk if any rows remain
            if chunk_rows:
                chunk_num += 1
                total_rows += len(chunk_rows)

                print(
                    f"Chunk {chunk_num}: {len(chunk_rows):,} rows (total: {total_rows:,})",
                    end="",
                )

                df = pl.DataFrame(chunk_rows)

                output_file = output_dir / f"sampling_{chunk_num:04d}.parquet"
                df.write_parquet(
                    output_file,
                    compression="zstd",
                    compression_level=3,
                )

                file_size_mb = output_file.stat().st_size / (1024**2)
                print(f" -> {file_size_mb:.1f} MB")

    # Calculate totals
    duration = time.time() - start_time
    output_files = list(output_dir.glob("*.parquet"))
    total_size_gb = sum(f.stat().st_size for f in output_files) / (1024**3)

    print()
    print("=" * 60)
    print("✓ Conversion complete!")
    print(f"  Total rows: {total_rows:,}")
    print(f"  Total chunks: {chunk_num}")
    print(f"  Total size: {total_size_gb:.2f} GB")
    print(f"  Duration: {format_duration(duration)}")
    print(f"  Output directory: {output_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert eBird sampling tarball to Parquet (streaming, no extraction)"
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input tarball (.tar)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for Parquet files",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1_000_000,
        help="Number of rows per chunk (default: 1,000,000)",
    )

    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}")
        return 1

    if not args.input.suffix == ".tar":
        print(f"Error: Input must be a .tar file, got: {args.input}")
        return 1

    convert_tarball_to_parquet(
        args.input,
        args.output_dir,
        args.chunk_size,
    )

    return 0


if __name__ == "__main__":
    exit(main())
