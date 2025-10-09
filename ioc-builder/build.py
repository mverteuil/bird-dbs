"""Build IOC reference database from source files."""

from pathlib import Path

import click

from ioc_reference_builder.ioc_database_builder import IOCDatabaseBuilder


@click.command()
@click.option(
    "--xml",
    "xml_file",
    type=click.Path(exists=True, path_type=Path),
    default=Path("data/ioc/master_xml.xml"),
    help="Path to IOC XML file (master_xml.xml)",
    show_default=True,
)
@click.option(
    "--multilingual",
    "multilingual_file",
    type=click.Path(exists=True, path_type=Path),
    default=Path("data/ioc/multilingual.xlsx"),
    help="Path to IOC multilingual XLSX file",
    show_default=True,
)
@click.option(
    "--avilistr",
    "avilistr_csv",
    type=click.Path(exists=True, path_type=Path),
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
def build(
    xml_file: Path,
    multilingual_file: Path,
    avilistr_csv: Path,
    output_db: Path,
) -> None:
    """Build IOC reference database from source files.

    This tool creates a SQLite database containing:
    - IOC World Bird List taxonomy (species, families, orders)
    - Stable Avibase ID mappings
    - Multilingual translations (24 languages)
    """
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
