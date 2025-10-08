"""SQLAlchemy models for Wikidata bird species multilingual database.

This module defines the database schema for Wikidata bird species data,
including Avibase ID mappings and multilingual common names.
"""

from __future__ import annotations

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel


class WikidataSpecies(SQLModel, table=True):
    """Wikidata bird species with Avibase ID linkage."""

    __tablename__: str = "species"  # type: ignore[assignment]

    wikidata_id: str = Field(sa_column=Column(String(20), primary_key=True))  # e.g., "Q1234567"
    scientific_name: str = Field(sa_column=Column(String(80)))  # e.g., "Passer domesticus"
    avibase_id_native: str | None = Field(
        default=None, sa_column=Column(String(20))
    )  # e.g., "240E33900CE34D44" (16-char)
    taxon_rank: str | None = Field(default=None, sa_column=Column(String(30)))  # e.g., "species"
    # Common name in English as reference
    english_name: str | None = Field(default=None, sa_column=Column(String(120)))


class WikidataTranslation(SQLModel, table=True):
    """Wikidata multilingual labels for bird species."""

    __tablename__: str = "translations"  # type: ignore[assignment]
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: int | None = Field(default=None, primary_key=True)
    wikidata_id: str = Field(foreign_key="species.wikidata_id")
    language_code: str = Field(sa_column=Column(String(10)))  # e.g., "es", "fr", "zh"
    common_name: str = Field(sa_column=Column(String(150)))  # e.g., "Gorrión común"


class WikidataMetadata(SQLModel, table=True):
    """Metadata about the Wikidata bird species database."""

    __tablename__: str = "metadata"  # type: ignore[assignment]

    key: str = Field(sa_column=Column(String(50), primary_key=True))
    value: str = Field(sa_column=Column(String(500)))

    # Common keys:
    # - 'wikidata_dump_date': '2025-10-08'
    # - 'created_at': '2025-10-08T10:30:00Z'
    # - 'species_count': '10245'
    # - 'translation_count': '487623'
    # - 'languages_available': 'en,es,fr,de,zh,ja,...'
    # - 'extraction_method': 'SPARQL' or 'JSON_dump'


class WikidataLanguage(SQLModel, table=True):
    """Available languages in the Wikidata bird species database."""

    __tablename__: str = "languages"  # type: ignore[assignment]

    language_code: str = Field(sa_column=Column(String(10), primary_key=True))  # e.g., "es"
    language_name: str = Field(sa_column=Column(String(50)))  # e.g., "Spanish"
    translation_count: int = Field(default=0)  # Number of translations available
