"""Build Wikidata reference database from SPARQL queries."""

from pathlib import Path

import click

from wikidata_reference_builder.wikidata_database_builder import WikidataDatabaseBuilder


@click.command()
@click.option(
    "--output",
    "output_db",
    type=click.Path(path_type=Path),
    default=Path("output/wikidata_reference.db"),
    help="Path to output SQLite database",
    show_default=True,
)
@click.option(
    "--limit",
    "limit",
    type=int,
    default=None,
    help="Limit number of species to fetch (for testing/POC)",
    show_default=True,
)
@click.option(
    "--sample",
    "sample_mode",
    is_flag=True,
    default=False,
    help="Use random sampling when limiting results",
    show_default=True,
)
def build(
    output_db: Path,
    limit: int | None,
    sample_mode: bool,
) -> None:
    """Build Wikidata reference database from SPARQL queries.

    This tool creates a SQLite database containing:
    - Bird species with Avibase IDs from Wikidata (P2026 property)
    - Multilingual common names (50+ languages)
    - Excludes extinct species and scientific name fallbacks

    The database supplements IOC translations with additional languages
    and alternative common names from Wikidata's crowdsourced data.
    """
    # Create output directory
    output_db.parent.mkdir(parents=True, exist_ok=True)

    # Build database
    click.echo(click.style("Building Wikidata Reference Database", fg="cyan", bold=True))
    click.echo(f"  Output: {output_db}")
    if limit:
        click.echo(f"  Limit: {limit} species")
        click.echo(f"  Sample mode: {sample_mode}")
    click.echo()

    builder = WikidataDatabaseBuilder(output_db)
    species_count, translation_count = builder.populate_from_wikidata(
        limit=limit,
        sample_mode=sample_mode,
    )

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
