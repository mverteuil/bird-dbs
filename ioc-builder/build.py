"""Build IOC reference database from source files."""

import sys
from pathlib import Path

import click

from ioc_reference_builder.ioc_database_builder import IOCDatabaseBuilder
from ioc_reference_builder.process_ioc_data import download_ioc_files


@click.command()
@click.option(
    "--xml",
    "xml_file",
    type=click.Path(path_type=Path),
    default=Path("data/ioc/master_xml.xml"),
    help="Path to IOC XML file (master_xml.xml)",
    show_default=True,
)
@click.option(
    "--multilingual",
    "multilingual_file",
    type=click.Path(path_type=Path),
    default=Path("data/ioc/multilingual.xlsx"),
    help="Path to IOC multilingual XLSX file",
    show_default=True,
)
@click.option(
    "--avilistr",
    "avilistr_csv",
    type=click.Path(path_type=Path),
    default=Path("../shared/avilistr/avilistr_mapping.csv"),
    help="Path to Avibase mapping CSV (AviList 2025 format)",
    show_default=True,
)
@click.option(
    "--output",
    "output_db",
    type=click.Path(path_type=Path),
    default=Path("output/ioc_reference.db"),
    help="Path to output SQLite database",
    show_default=True,
)
@click.option(
    "--download/--no-download",
    default=False,
    help="Download IOC data files if missing",
    show_default=True,
)
@click.option(
    "--ioc-version",
    default="15.1",
    help="IOC version to download if --download is used",
    show_default=True,
)
def build(
    xml_file: Path,
    multilingual_file: Path,
    avilistr_csv: Path,
    output_db: Path,
    download: bool,
    ioc_version: str,
) -> None:
    """Build IOC reference database from source files.

    This tool creates a SQLite database containing:
    - IOC World Bird List taxonomy (species, families, orders)
    - Stable Avibase ID mappings
    - Multilingual translations (24 languages)

    If --download is specified, missing IOC data files will be automatically
    downloaded from worldbirdnames.org before building the database.
    """
    # Check if required files exist
    missing_files = []
    if not xml_file.exists():
        missing_files.append(("XML", xml_file))
    if not multilingual_file.exists():
        missing_files.append(("Multilingual", multilingual_file))
    if not avilistr_csv.exists():
        missing_files.append(("Avilistr", avilistr_csv))

    # Download missing IOC files if requested
    if missing_files and download:
        ioc_missing = [f for label, f in missing_files if label in ("XML", "Multilingual")]
        if ioc_missing:
            click.echo(click.style("Missing IOC data files - downloading...", fg="yellow"))
            click.echo()
            success = download_ioc_files(ioc_version, Path("data/ioc"), quiet=False)
            if not success:
                click.echo(click.style("✗ Download failed. Cannot proceed.", fg="red"), err=True)
                sys.exit(1)
            click.echo()

    # Check again after potential download
    if not xml_file.exists():
        click.echo(click.style(f"✗ XML file not found: {xml_file}", fg="red"), err=True)
        click.echo("\nRun with --download to automatically download IOC files:", err=True)
        click.echo(f"  uv run build.py --download --ioc-version {ioc_version}", err=True)
        sys.exit(1)

    if not multilingual_file.exists():
        click.echo(
            click.style(f"✗ Multilingual file not found: {multilingual_file}", fg="red"), err=True
        )
        click.echo("\nRun with --download to automatically download IOC files:", err=True)
        click.echo(f"  uv run build.py --download --ioc-version {ioc_version}", err=True)
        sys.exit(1)

    if not avilistr_csv.exists():
        click.echo(click.style(f"✗ Avilistr file not found: {avilistr_csv}", fg="red"), err=True)
        click.echo(
            "\nThe Avilistr mapping file must be downloaded separately. See README.md", err=True
        )
        sys.exit(1)

    # Create output directory
    output_db.parent.mkdir(parents=True, exist_ok=True)

    # Build database
    click.echo(click.style("Building IOC Reference Database", fg="cyan", bold=True))
    click.echo(f"  XML: {xml_file}")
    click.echo(f"  Multilingual: {multilingual_file}")
    click.echo(f"  Avilistr: {avilistr_csv}")
    click.echo(f"  Output: {output_db}")
    click.echo()

    builder = IOCDatabaseBuilder(output_db)
    builder.populate_from_files(xml_file, avilistr_csv, multilingual_file)

    # Show statistics
    stats = builder.get_statistics()
    click.echo()
    click.echo(click.style("Database Statistics:", fg="green", bold=True))
    click.echo(f"  Species: {stats['species_count']:,}")
    click.echo(f"  Translations: {stats['translation_count']:,}")
    click.echo(f"  Languages: {stats['language_count']}")
    click.echo()
    click.echo(click.style("✓ Database build complete!", fg="green"))


if __name__ == "__main__":
    build()
