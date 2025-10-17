r"""IOC database builder CLI.

This script builds IOC World Bird Names SQLite database from pandas DataFrames or XML/XLSX files.

Usage:
    process-ioc-data build \
        --species-csv species.csv \
        --translations-csv translations.csv \
        --avilistr-csv avilistr.csv \
        --db-file ioc_database.db
"""

import sys
from pathlib import Path

import click
import pandas as pd
import requests

from ioc_reference_builder.ioc_database_builder import IOCDatabaseBuilder


@click.group()
def cli() -> None:
    """IOC World Bird Names database builder."""
    pass


@cli.command()
@click.option(
    "--species-csv",
    type=click.Path(exists=True, path_type=Path),
    help="Path to IOC species CSV file",
)
@click.option(
    "--translations-csv",
    type=click.Path(exists=True, path_type=Path),
    help="Path to IOC multilingual translations CSV file",
)
@click.option(
    "--avilistr-csv",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to Avilistr CSV file with Avibase ID mappings",
)
@click.option(
    "--db-file",
    type=click.Path(path_type=Path),
    required=True,
    help="Path to output SQLite database file",
)
def build(
    species_csv: Path | None,
    translations_csv: Path | None,
    avilistr_csv: Path,
    db_file: Path,
) -> None:
    """Build IOC database from CSV files."""
    click.echo("Building IOC database...")
    click.echo(f"Avilistr mapping: {avilistr_csv}")
    if species_csv:
        click.echo(f"Species CSV: {species_csv}")
    if translations_csv:
        click.echo(f"Translations CSV: {translations_csv}")
    click.echo(f"Database: {db_file}")
    click.echo()

    try:
        # Create database builder
        builder = IOCDatabaseBuilder(db_path=db_file)

        # Load Avilistr data
        click.echo("Loading Avilistr data...")
        avilistr_data = pd.read_csv(avilistr_csv)

        # Process species if provided
        if species_csv:
            click.echo("Processing species data...")
            species_df = pd.read_csv(species_csv)
            species_list = builder._parse_species_data(species_df)
            mapped_species = builder._map_avibase_ids(species_list, avilistr_data)
            builder._insert_species(mapped_species)
            click.echo(f"  Inserted {len(mapped_species)} species")

        # Process translations if provided
        if translations_csv:
            click.echo("Processing translations...")
            translations_df = pd.read_csv(translations_csv)
            translations = builder._parse_multilingual_data(translations_df)
            builder._insert_translations(translations, avilistr_data)
            click.echo(f"  Inserted {len(translations)} translations")

        # Show statistics
        stats = builder.get_statistics()
        click.echo()
        click.echo("Database statistics:")
        click.echo(f"  Species: {stats['species_count']}")
        click.echo(f"  Translations: {stats['translation_count']}")
        click.echo(f"  Languages: {stats['language_count']}")

        click.echo(click.style("\n✓ Database built successfully", fg="green"))

    except FileNotFoundError as e:
        click.echo(click.style(f"✗ File not found: {e}", fg="red"), err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(click.style(f"✗ Error building database: {e}", fg="red"), err=True)
        sys.exit(1)


def download_ioc_files(version: str, output_dir: Path, quiet: bool = False) -> bool:
    """Download IOC World Bird Names files from worldbirdnames.org.

    Args:
        version: IOC version to download (e.g., "15.1")
        output_dir: Directory to save downloaded files
        quiet: If True, suppress informational output

    Returns:
        True if all files downloaded successfully, False otherwise
    """
    if not quiet:
        click.echo(f"Downloading IOC World Bird Names v{version}...")
        click.echo(f"Output directory: {output_dir}")
        click.echo()

    # Create output directory
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Define file URLs
    base_url = "https://www.worldbirdnames.org"
    files = {
        "ioc_names_plus_red.xlsx": f"{base_url}/IOC_Names_File_Plus-{version}_red.xlsx",
        "ioc_names_plus.xlsx": f"{base_url}/IOC_Names_File_Plus-{version}.xlsx",
        "multilingual.xlsx": f"{base_url}/Multiling%20IOC%20{version}_c.xlsx",
        "master_xml.xml": f"{base_url}/master_ioc-names_xml.{version}.xml",
    }

    downloaded_files = []
    failed_files = []

    # Set headers to avoid 403 Forbidden errors
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    for filename, url in files.items():
        output_path = output_dir / filename
        if not quiet:
            click.echo(f"Downloading {filename}...")

        try:
            response = requests.get(url, headers=headers, timeout=60)
            response.raise_for_status()

            with open(output_path, "wb") as f:
                f.write(response.content)

            size_mb = len(response.content) / (1024 * 1024)
            if not quiet:
                click.echo(click.style(f"  ✓ Downloaded {filename} ({size_mb:.2f} MB)", fg="green"))
            downloaded_files.append(filename)

        except requests.exceptions.RequestException as e:
            if not quiet:
                click.echo(
                    click.style(f"  ✗ Failed to download {filename}: {e}", fg="red"),
                    err=True,
                )
            failed_files.append(filename)

    if not quiet:
        click.echo()
        click.echo("Download summary:")
        click.echo(f"  Downloaded: {len(downloaded_files)}/{len(files)} files")

        if downloaded_files:
            click.echo("\nSuccessfully downloaded:")
            for filename in downloaded_files:
                click.echo(f"  • {output_dir / filename}")

        if failed_files:
            click.echo(click.style("\nFailed downloads:", fg="red"))
            for filename in failed_files:
                click.echo(f"  • {filename}")
        else:
            click.echo(click.style("\n✓ All files downloaded successfully", fg="green"))

    return len(failed_files) == 0


@cli.command()
@click.option(
    "--version",
    default="15.1",
    help="IOC version to download (e.g., 15.1)",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default="data/ioc",
    help="Directory to save downloaded files",
)
def download(version: str, output_dir: Path) -> None:
    """Download IOC World Bird Names files from worldbirdnames.org."""
    success = download_ioc_files(version, output_dir, quiet=False)
    if not success:
        sys.exit(1)


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
