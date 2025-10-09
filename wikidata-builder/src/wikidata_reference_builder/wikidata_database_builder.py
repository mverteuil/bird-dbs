"""Wikidata bird species database builder.

This utility queries Wikidata via SPARQL and builds a SQLite database
with multilingual bird common names linked via Avibase IDs.

The utility handles:
1. Querying Wikidata SPARQL endpoint for birds with Avibase IDs (P2026)
2. Extracting multilingual labels in 100+ languages
3. Creating optimized SQLite databases with indexes
4. Providing coverage statistics
"""

import contextlib
from collections import defaultdict
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session, sessionmaker
from sqlmodel import SQLModel

from wikidata_reference_builder.wikidata_models import (
    WikidataLanguage,
    WikidataMetadata,
    WikidataSpecies,
    WikidataTranslation,
)


class WikidataDatabaseBuilder:
    """Builder for Wikidata bird species multilingual SQLite databases."""

    # Target languages (most common + BirdNET-Pi supported)
    TARGET_LANGUAGES = [
        "en",
        "es",
        "fr",
        "de",
        "it",
        "pt",
        "nl",
        "sv",
        "nb",  # Norwegian Bokmål (primary Norwegian variant)
        "nn",  # Norwegian Nynorsk
        "da",
        "fi",
        "pl",
        "cs",
        "sk",
        "ru",
        "uk",
        "hr",
        "sr",
        "lt",
        "zh",  # Chinese (generic)
        "zh-hans",  # Simplified Chinese
        "zh-hant",  # Traditional Chinese
        "yue",  # Cantonese
        "ja",
        "ko",
        "ar",
        "he",
        "tr",
        "ca",
        "eu",
        "gl",
        "ro",
        "hu",
        "bg",
        "el",
        "th",
        "vi",
        "id",
        "ms",
        "tl",
        "hi",
        "bn",
        "ta",
        "te",
        "ml",
        "kn",
        "mr",
        "gu",
        "pa",
        "ur",
        "fa",
        # Additional languages from PatLevin
        "et",  # Estonian
        "lv",  # Latvian
        "sl",  # Slovenian
        "is",  # Icelandic
        "af",  # Afrikaans
    ]

    # Wikidata SPARQL endpoint
    SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"

    def __init__(self, db_path: Path | str):
        """Initialize Wikidata database builder.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create database connection
        self.engine = create_engine(f"sqlite:///{self.db_path}")
        SQLModel.metadata.create_all(self.engine)
        self.session_local = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    @contextlib.contextmanager
    def get_db(self) -> Generator[Session, Any, None]:
        """Provide a database session for dependency injection."""
        db = self.session_local()
        try:
            yield db
        finally:
            db.close()

    def populate_from_wikidata(
        self,
        limit: int | None = None,
        sample_mode: bool = False,
    ) -> tuple[int, int]:
        """Populate database from Wikidata SPARQL endpoint.

        Args:
            limit: Optional limit on number of species to fetch (for POC/testing)
            sample_mode: If True, fetch random sample; if False, fetch all

        Returns:
            Tuple of (species_count, translation_count)
        """
        print("Starting Wikidata bird species extraction...")
        print(f"Target languages: {len(self.TARGET_LANGUAGES)}")
        if limit:
            print(f"Limit: {limit} species (sample mode: {sample_mode})")

        # Clear existing data
        with self.get_db() as session:
            session.execute(delete(WikidataTranslation))
            session.execute(delete(WikidataSpecies))
            session.execute(delete(WikidataLanguage))
            session.execute(delete(WikidataMetadata))
            session.commit()

        # Fetch bird species with Avibase IDs
        print("\nQuerying Wikidata for bird species with Avibase IDs (P2026)...")
        species_data = self._query_species_data(limit=limit, sample_mode=sample_mode)

        print(f"Found {len(species_data)} bird species")

        # Fetch multilingual labels
        print("\nFetching multilingual labels...")
        translation_data, language_counts = self._query_multilingual_labels(species_data)

        print(f"Collected {sum(language_counts.values())} translations")
        print(f"Languages with data: {len(language_counts)}")

        # Insert into database
        print("\nInserting data into database...")
        self._insert_species(species_data)
        self._insert_translations(translation_data)
        self._insert_language_metadata(language_counts)
        self._store_metadata(len(species_data), sum(language_counts.values()), language_counts)

        # Create indexes
        self._create_performance_indexes()

        print("\n✓ Database population complete!")
        return len(species_data), sum(language_counts.values())

    def _build_species_query(self, limit: int | None = None) -> str:
        """Build SPARQL query for bird species with Avibase IDs.

        Args:
            limit: Optional limit on number of results

        Returns:
            SPARQL query string
        """
        query = """
        SELECT DISTINCT ?species ?speciesLabel ?scientificName ?avibaseID
        WHERE {
          ?species wdt:P2026 ?avibaseID .           # Has Avibase ID (P2026)
          ?species wdt:P105 wd:Q7432 .              # Filter for species rank only (Q7432)
          OPTIONAL { ?species wdt:P225 ?scientificName . }  # Scientific name (P225)

          # Exclude extinct species
          FILTER NOT EXISTS { ?species wdt:P141 wd:Q237350 . }     # Not extinct (EX)
          FILTER NOT EXISTS { ?species wdt:P141 wd:Q123509 . }     # Not extinct in wild (EW)
          FILTER NOT EXISTS { ?species wdt:P582 ?endTime . }       # No extinction date
          FILTER NOT EXISTS { ?species wdt:P31 wd:Q23038290 . }   # Not fossil taxon

          SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
        }
        """

        if limit:
            query += f"\nLIMIT {limit}"

        return query

    def _query_species_data(
        self, limit: int | None = None, sample_mode: bool = False
    ) -> list[dict[str, str]]:
        """Query Wikidata for bird species with Avibase IDs.

        Args:
            limit: Optional limit on number of results
            sample_mode: If True, use SAMPLE for random subset (currently unused)

        Returns:
            List of species dicts with wikidata_id, scientific_name, avibase_id, etc.
        """
        query = self._build_species_query(limit=limit)
        results = self._execute_sparql_query(query)

        species_data = []
        seen_ids = set()
        duplicates = []

        for binding in results.get("results", {}).get("bindings", []):
            species_id = binding.get("species", {}).get("value", "").split("/")[-1]
            scientific_name = binding.get("scientificName", {}).get("value", "")
            avibase_id = binding.get("avibaseID", {}).get("value", "")
            english_label = binding.get("speciesLabel", {}).get("value", "")

            if species_id and avibase_id:
                if species_id in seen_ids:
                    duplicates.append(species_id)
                else:
                    seen_ids.add(species_id)
                    species_data.append(
                        {
                            "wikidata_id": species_id,
                            "scientific_name": scientific_name or english_label,
                            "avibase_id": avibase_id,
                            "taxon_rank": "Q7432",  # All results are species-level (filtered in query)
                            "english_name": english_label,
                        }
                    )

        if duplicates:
            print(f"  WARNING: Found {len(duplicates)} duplicate Wikidata IDs: {duplicates[:10]}")

        return species_data

    def _build_labels_query(
        self, species_ids: list[str], languages: list[str] | None = None
    ) -> str:
        """Build SPARQL query for multilingual labels.

        Args:
            species_ids: List of Wikidata IDs (e.g., ["Q123", "Q456"])
            languages: Optional list of language codes (defaults to TARGET_LANGUAGES)

        Returns:
            SPARQL query string
        """
        if languages is None:
            languages = self.TARGET_LANGUAGES

        values_clause = " ".join([f"wd:{species_id}" for species_id in species_ids])

        query = f"""
        SELECT ?species ?label (LANG(?label) AS ?lang)
        WHERE {{
          VALUES ?species {{ {values_clause} }}
          ?species rdfs:label ?label .
          FILTER(LANG(?label) IN ({",".join([f'"{lang}"' for lang in languages])}))
        }}
        """

        return query

    def _query_multilingual_labels(
        self, species_data: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], dict[str, int]]:
        """Query multilingual labels for bird species, excluding scientific name fallbacks.

        Args:
            species_data: List of species dicts from previous query

        Returns:
            Tuple of (translation_data, language_counts)
        """
        translation_data = []
        language_counts = defaultdict(int)

        # Create mappings for filtering and foreign key
        species_names = {sp["wikidata_id"]: sp["scientific_name"] for sp in species_data}
        wikidata_to_avibase = {sp["wikidata_id"]: sp["avibase_id"] for sp in species_data}
        filtered_count = 0

        # Batch species by 50 to avoid query timeout
        batch_size = 50
        total_batches = (len(species_data) + batch_size - 1) // batch_size

        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(species_data))
            batch = species_data[start_idx:end_idx]

            print(f"  Processing batch {batch_num + 1}/{total_batches} ({len(batch)} species)...")

            # Build query for this batch
            batch_ids = [sp["wikidata_id"] for sp in batch]
            query = self._build_labels_query(batch_ids)

            results = self._execute_sparql_query(query)

            for binding in results.get("results", {}).get("bindings", []):
                species_id = binding.get("species", {}).get("value", "").split("/")[-1]
                label = binding.get("label", {}).get("value", "")
                lang = binding.get("lang", {}).get("value", "")

                if species_id and label and lang:
                    # FILTER: Only add if label is NOT the scientific name
                    scientific_name = species_names.get(species_id)
                    avibase_id = wikidata_to_avibase.get(species_id)
                    if label != scientific_name and avibase_id:
                        translation_data.append(
                            {"avibase_id": avibase_id, "language_code": lang, "common_name": label}
                        )
                        language_counts[lang] += 1
                    else:
                        filtered_count += 1

        print(f"  Filtered out {filtered_count} scientific name fallbacks")
        return translation_data, dict(language_counts)

    def _execute_sparql_query(self, query: str) -> dict[str, Any]:
        """Execute SPARQL query against Wikidata endpoint.

        Args:
            query: SPARQL query string

        Returns:
            JSON response from Wikidata
        """
        headers = {
            "User-Agent": "BirdNET-Pi/Avibase-Builder POC (https://github.com/mcguirepr89/BirdNET-Pi)",
            "Accept": "application/sparql-results+json",
        }

        try:
            response = requests.get(
                self.SPARQL_ENDPOINT,
                params={"query": query, "format": "json"},
                headers=headers,
                timeout=300,  # 5 minute timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"ERROR: SPARQL query failed: {e}")
            return {}

    def _insert_species(self, species_data: list[dict[str, str]]) -> None:
        """Insert species data in batch, ignoring duplicates.

        Args:
            species_data: List of species dicts
        """
        with self.get_db() as session:
            self._set_bulk_insert_pragmas(session)

            # Use INSERT OR IGNORE to handle duplicate wikidata_id gracefully
            for species in species_data:
                # Prepare parameters with NULL for missing optional fields
                params = {
                    "wikidata_id": species["wikidata_id"],
                    "scientific_name": species["scientific_name"],
                    "avibase_id": species.get("avibase_id"),
                    "taxon_rank": species.get("taxon_rank"),
                    "english_name": species.get("english_name"),
                }
                session.execute(
                    text("""
                        INSERT OR IGNORE INTO species (wikidata_id, scientific_name, avibase_id, taxon_rank, english_name)
                        VALUES (:wikidata_id, :scientific_name, :avibase_id, :taxon_rank, :english_name)
                    """),
                    params,
                )

            session.commit()
            self._restore_normal_pragmas(session)

    def _insert_translations(self, translation_data: list[dict[str, str]]) -> None:
        """Insert translation data in batches, handling duplicates.

        Args:
            translation_data: List of translation dicts
        """
        with self.get_db() as session:
            self._set_bulk_insert_pragmas(session)

            batch_size = 1000
            for i in range(0, len(translation_data), batch_size):
                batch = translation_data[i : i + batch_size]

                # Use INSERT OR IGNORE to skip duplicates (keeps first occurrence)
                for trans in batch:
                    session.execute(
                        text("""
                            INSERT OR IGNORE INTO translations (avibase_id, language_code, common_name)
                            VALUES (:avibase_id, :language_code, :common_name)
                        """),
                        trans,
                    )

                session.commit()
                if (i + batch_size) % 10000 == 0:
                    print(f"  Inserted {i + batch_size} translations...")

            self._restore_normal_pragmas(session)

    def _insert_language_metadata(self, language_counts: dict[str, int]) -> None:
        """Insert language metadata into database.

        Args:
            language_counts: Dict of language_code -> count
        """
        with self.get_db() as session:
            language_names = self._get_language_names()
            for language_code, count in language_counts.items():
                language_name = language_names.get(language_code, language_code.upper())
                db_language = WikidataLanguage(
                    language_code=language_code,
                    language_name=language_name,
                    translation_count=count,
                )
                session.add(db_language)
            session.commit()

    def _store_metadata(
        self, species_count: int, translation_count: int, language_counts: dict[str, int]
    ) -> None:
        """Store metadata about the database.

        Args:
            species_count: Number of species in database
            translation_count: Number of translations in database
            language_counts: Dict of language_code -> count
        """
        with self.get_db() as session:
            metadata_entries = [
                WikidataMetadata(
                    key="wikidata_dump_date", value=datetime.utcnow().strftime("%Y-%m-%d")
                ),
                WikidataMetadata(key="created_at", value=datetime.utcnow().isoformat()),
                WikidataMetadata(key="species_count", value=str(species_count)),
                WikidataMetadata(key="translation_count", value=str(translation_count)),
                WikidataMetadata(
                    key="languages_available", value=",".join(sorted(language_counts.keys()))
                ),
                WikidataMetadata(key="extraction_method", value="SPARQL"),
            ]

            for metadata in metadata_entries:
                session.add(metadata)
            session.commit()

    def _create_performance_indexes(self) -> None:
        """Create database indexes for optimal performance."""
        with self.get_db() as session:
            print("Creating performance indexes...")

            # NOTE: avibase_id is PK, automatically indexed
            # NOTE: scientific_name has index=True in model, automatically indexed
            # NOTE: wikidata_id has unique=True in model, automatically indexed
            # NOTE: translations composite PK (avibase_id, language_code) automatically indexed

            # Index on language + common name for reverse lookups
            session.execute(
                text("""
                CREATE INDEX IF NOT EXISTS idx_translations_lang_name
                ON translations(language_code, common_name)
            """)
            )

            session.commit()

    def _set_bulk_insert_pragmas(self, session: Session) -> None:
        """Set SQLite pragmas for optimized bulk insert."""
        session.execute(text("PRAGMA journal_mode = OFF"))
        session.execute(text("PRAGMA synchronous = OFF"))
        session.execute(text("PRAGMA temp_store = MEMORY"))
        session.execute(text("PRAGMA mmap_size = 268435456"))  # 256MB

    def _restore_normal_pragmas(self, session: Session) -> None:
        """Restore normal SQLite pragmas after bulk insert."""
        session.execute(text("PRAGMA journal_mode = WAL"))
        session.execute(text("PRAGMA synchronous = NORMAL"))

    def _get_language_names(self) -> dict[str, str]:
        """Get mapping of language codes to display names."""
        return {
            "en": "English",
            "es": "Spanish",
            "fr": "French",
            "de": "German",
            "it": "Italian",
            "pt": "Portuguese",
            "nl": "Dutch",
            "sv": "Swedish",
            "nb": "Norwegian Bokmål",
            "nn": "Norwegian Nynorsk",
            "da": "Danish",
            "fi": "Finnish",
            "pl": "Polish",
            "cs": "Czech",
            "sk": "Slovak",
            "ru": "Russian",
            "uk": "Ukrainian",
            "hr": "Croatian",
            "sr": "Serbian",
            "lt": "Lithuanian",
            "zh": "Chinese",
            "zh-hans": "Chinese (Simplified)",
            "zh-hant": "Chinese (Traditional)",
            "yue": "Cantonese",
            "ja": "Japanese",
            "ko": "Korean",
            "ar": "Arabic",
            "he": "Hebrew",
            "tr": "Turkish",
            "ca": "Catalan",
            "eu": "Basque",
            "gl": "Galician",
            "ro": "Romanian",
            "hu": "Hungarian",
            "bg": "Bulgarian",
            "el": "Greek",
            "th": "Thai",
            "vi": "Vietnamese",
            "id": "Indonesian",
            "ms": "Malay",
            "tl": "Tagalog",
            "hi": "Hindi",
            "bn": "Bengali",
            "ta": "Tamil",
            "te": "Telugu",
            "ml": "Malayalam",
            "kn": "Kannada",
            "mr": "Marathi",
            "gu": "Gujarati",
            "pa": "Punjabi",
            "ur": "Urdu",
            "fa": "Persian",
            "et": "Estonian",
            "lv": "Latvian",
            "sl": "Slovenian",
            "is": "Icelandic",
            "af": "Afrikaans",
        }

    def get_statistics(self) -> dict[str, int]:
        """Get database statistics matching ioc-builder interface.

        Returns:
            Dictionary with species_count, translation_count, and language_count
        """
        with self.get_db() as session:
            species_count = session.query(WikidataSpecies).count()
            translation_count = session.query(WikidataTranslation).count()
            language_count = session.query(WikidataLanguage).count()

        return {
            "species_count": species_count,
            "translation_count": translation_count,
            "language_count": language_count,
        }

    def generate_coverage_report(self) -> dict[str, Any]:
        """Generate coverage statistics report.

        Returns:
            Dict with coverage statistics
        """
        with self.get_db() as session:
            # Get basic counts
            species_count = session.query(WikidataSpecies).count()
            translation_count = session.query(WikidataTranslation).count()

            # Get language counts
            lang_results = session.query(WikidataLanguage).all()
            language_stats = {
                lang.language_code: {"name": lang.language_name, "count": lang.translation_count}
                for lang in lang_results
            }

            # Get average translations per species
            avg_translations = translation_count / species_count if species_count > 0 else 0

            # Get top 20 languages by coverage
            top_languages = sorted(
                language_stats.items(), key=lambda x: x[1]["count"], reverse=True
            )[:20]

            return {
                "species_count": species_count,
                "translation_count": translation_count,
                "language_count": len(language_stats),
                "avg_translations_per_species": round(avg_translations, 2),
                "top_languages": top_languages,
                "all_languages": language_stats,
            }
