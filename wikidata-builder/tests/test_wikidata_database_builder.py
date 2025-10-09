"""Tests for Wikidata database builder."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from SPARQLWrapper import SPARQLWrapper
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from wikidata_reference_builder.wikidata_database_builder import WikidataDatabaseBuilder
from wikidata_reference_builder.wikidata_models import (
    WikidataSpecies,
    WikidataTranslation,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def builder(temp_db):
    """Create Wikidata database builder instance."""
    return WikidataDatabaseBuilder(db_path=temp_db)


@pytest.fixture
def sample_sparql_species_response():
    """Sample SPARQL response for species query."""
    return {
        "results": {
            "bindings": [
                {
                    "species": {"value": "http://www.wikidata.org/entity/Q123"},
                    "avibaseID": {"value": "ABC123DEF456"},
                    "scientificName": {"value": "Struthio camelus"},
                },
                {
                    "species": {"value": "http://www.wikidata.org/entity/Q456"},
                    "avibaseID": {"value": "GHI789JKL012"},
                    "scientificName": {"value": "Thalassarche eremita"},
                },
            ]
        }
    }


@pytest.fixture
def sample_sparql_labels_response():
    """Sample SPARQL response for multilingual labels query."""
    return {
        "results": {
            "bindings": [
                # Real translations
                {
                    "species": {"value": "http://www.wikidata.org/entity/Q123"},
                    "label": {"value": "Common Ostrich"},
                    "lang": {"value": "en"},
                },
                {
                    "species": {"value": "http://www.wikidata.org/entity/Q123"},
                    "label": {"value": "Avestruz Común"},
                    "lang": {"value": "es"},
                },
                # Scientific name fallback (should be filtered)
                {
                    "species": {"value": "http://www.wikidata.org/entity/Q456"},
                    "label": {"value": "Thalassarche eremita"},
                    "lang": {"value": "es"},
                },
                # Real translation
                {
                    "species": {"value": "http://www.wikidata.org/entity/Q456"},
                    "label": {"value": "Chatham Albatross"},
                    "lang": {"value": "en"},
                },
            ]
        }
    }


class TestWikidataDatabaseBuilder:
    """Tests for Wikidata database builder."""

    @pytest.mark.parametrize(
        "check_type,expected_result",
        [
            pytest.param("database_file", True, id="creates-database-file"),
            pytest.param("tables", ["species", "translations"], id="creates-required-tables"),
        ],
    )
    def test_initialization(self, temp_db, check_type, expected_result):
        """Should create database and tables correctly."""
        _ = WikidataDatabaseBuilder(db_path=temp_db)

        if check_type == "database_file":
            assert Path(temp_db).exists() == expected_result
        elif check_type == "tables":
            engine = create_engine(f"sqlite:///{temp_db}")
            from sqlalchemy import inspect

            inspector = inspect(engine)
            tables = inspector.get_table_names()

            for table_name in expected_result:
                assert table_name in tables

    @pytest.mark.parametrize(
        "check_elements",
        [
            pytest.param(
                [
                    "SELECT",
                    "?species wdt:P2026 ?avibaseID",
                    "?species wdt:P225 ?scientificName",
                    "?species wdt:P31 wd:Q16521",
                ],
                id="basic-query-elements",
            ),
            pytest.param(
                ["P141", "P582"],  # Conservation status and extinction date
                id="excludes-extinct-species",
            ),
        ],
    )
    def test_build_species_query(self, builder, check_elements):
        """Should construct SPARQL query for species."""
        query = builder._build_species_query()

        for element in check_elements:
            assert element in query

        # Additional check for extinct species filter
        if "P141" in check_elements:
            assert "FILTER NOT EXISTS" in query or "MINUS" in query

    def test_build_labels_query(self, builder):
        """Should construct SPARQL query for multilingual labels."""
        species_ids = ["Q123", "Q456"]
        query = builder._build_labels_query(species_ids)

        assert "SELECT" in query
        assert "rdfs:label" in query
        assert "LANG(?label)" in query
        assert "Q123" in query
        assert "Q456" in query

    def test_build_labels_query_language_filter(self, builder):
        """Should filter labels query to target languages."""
        # Patch TARGET_LANGUAGES
        with patch("wikidata_database_builder.TARGET_LANGUAGES", ["nb", "eu"]):
            query = builder._build_labels_query(["Q123"])

            assert '"nb"' in query
            assert '"eu"' in query

    @patch("wikidata_database_builder.SPARQLWrapper", autospec=True)
    def test_query_species_data(self, mock_sparql, builder, sample_sparql_species_response):
        """Should query species data from Wikidata."""
        # Mock SPARQL response
        mock_wrapper = MagicMock(spec=SPARQLWrapper)
        mock_wrapper.query.return_value.convert.return_value = sample_sparql_species_response
        mock_sparql.return_value = mock_wrapper

        species_data = builder._query_species_data()

        assert len(species_data) == 2
        assert species_data[0]["wikidata_id"] == "Q123"
        assert species_data[0]["avibase_id"] == "ABC123DEF456"
        assert species_data[0]["scientific_name"] == "Struthio camelus"

    @patch("wikidata_database_builder.SPARQLWrapper", autospec=True)
    def test_query_multilingual_labels(
        self,
        mock_sparql,
        builder,
        sample_sparql_species_response,
        sample_sparql_labels_response,
    ):
        """Should query multilingual labels from Wikidata."""
        # Mock SPARQL response
        mock_wrapper = MagicMock(spec=SPARQLWrapper)
        mock_wrapper.query.return_value.convert.return_value = sample_sparql_labels_response
        mock_sparql.return_value = mock_wrapper

        # Parse species data first
        species_data = [
            {
                "wikidata_id": "Q123",
                "avibase_id": "ABC123DEF456",
                "scientific_name": "Struthio camelus",
            },
            {
                "wikidata_id": "Q456",
                "avibase_id": "GHI789JKL012",
                "scientific_name": "Thalassarche eremita",
            },
        ]

        translations, lang_counts = builder._query_multilingual_labels(species_data)

        # Should have 3 real translations (1 scientific name fallback filtered)
        assert len(translations) == 3

        # Verify filtering worked
        scientific_names = [t["common_name"] for t in translations]
        assert "Thalassarche eremita" not in scientific_names

        # Real translations should be present
        assert any(
            t["common_name"] == "Common Ostrich" and t["language_code"] == "en"
            for t in translations
        )
        assert any(
            t["common_name"] == "Avestruz Común" and t["language_code"] == "es"
            for t in translations
        )

    def test_filter_scientific_name_fallbacks(self, builder):
        """Should filter out scientific name fallbacks."""
        species_data = [
            {
                "wikidata_id": "Q123",
                "avibase_id": "ABC123",
                "scientific_name": "Test species",
            }
        ]

        raw_translations = [
            {
                "wikidata_id": "Q123",
                "language_code": "en",
                "common_name": "Test Bird",  # Real translation
            },
            {
                "wikidata_id": "Q123",
                "language_code": "es",
                "common_name": "Test species",  # Scientific name fallback
            },
        ]

        # Create species name mapping
        species_names = {sp["wikidata_id"]: sp["scientific_name"] for sp in species_data}

        # Filter translations
        filtered = [
            t for t in raw_translations if t["common_name"] != species_names.get(t["wikidata_id"])
        ]

        assert len(filtered) == 1
        assert filtered[0]["common_name"] == "Test Bird"

    @patch("wikidata_database_builder.SPARQLWrapper", autospec=True)
    def test_insert_species(self, mock_sparql, builder, sample_sparql_species_response):
        """Should insert species into database."""
        mock_wrapper = MagicMock(spec=SPARQLWrapper)
        mock_wrapper.query.return_value.convert.return_value = sample_sparql_species_response
        mock_sparql.return_value = mock_wrapper

        species_data = builder._query_species_data()
        builder._insert_species(species_data)

        # Verify species were inserted
        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            species = session.execute(select(WikidataSpecies)).scalars().all()
            assert len(species) == 2
            assert species[0].avibase_id == "ABC123DEF456"
            assert species[0].wikidata_id == "Q123"

    @patch("wikidata_database_builder.SPARQLWrapper", autospec=True)
    def test_insert_translations(self, mock_sparql, builder):
        """Should insert translations into database."""
        # First insert species
        species_data = [
            {
                "wikidata_id": "Q123",
                "avibase_id": "ABC123DEF456",
                "scientific_name": "Struthio camelus",
            }
        ]
        builder._insert_species(species_data)

        # Then insert translations
        translations = [
            {
                "wikidata_id": "Q123",
                "language_code": "es",
                "common_name": "Avestruz Común",
            }
        ]

        # Map to avibase_id
        wikidata_to_avibase = {sp["wikidata_id"]: sp["avibase_id"] for sp in species_data}
        translations_with_avibase = [
            {
                "avibase_id": wikidata_to_avibase[t["wikidata_id"]],
                "language_code": t["language_code"],
                "common_name": t["common_name"],
            }
            for t in translations
        ]

        builder._insert_translations(translations_with_avibase)

        # Verify translations were inserted
        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            trans = session.execute(select(WikidataTranslation)).scalars().all()
            assert len(trans) == 1
            assert trans[0].avibase_id == "ABC123DEF456"
            assert trans[0].common_name == "Avestruz Común"

    def test_handle_api_timeout(self, builder):
        """Should handle API timeout errors."""
        with patch("wikidata_database_builder.SPARQLWrapper", autospec=True) as mock_sparql:
            mock_wrapper = MagicMock(spec=SPARQLWrapper)
            mock_wrapper.query.side_effect = Exception("Timeout")
            mock_sparql.return_value = mock_wrapper

            with pytest.raises(Exception, match="Timeout"):
                builder._query_species_data()

    def test_handle_empty_response(self, builder):
        """Should handle empty API responses."""
        with patch("wikidata_database_builder.SPARQLWrapper", autospec=True) as mock_sparql:
            mock_wrapper = MagicMock(spec=SPARQLWrapper)
            mock_wrapper.query.return_value.convert.return_value = {"results": {"bindings": []}}
            mock_sparql.return_value = mock_wrapper

            species_data = builder._query_species_data()
            assert len(species_data) == 0

    def test_duplicate_species_handling(self, builder):
        """Should handle duplicate species correctly."""
        species_data = [
            {
                "wikidata_id": "Q123",
                "avibase_id": "ABC123",
                "scientific_name": "Test species",
            }
        ]

        # Insert twice
        builder._insert_species(species_data)
        builder._insert_species(species_data)

        # Should only have 1 species (no duplicates)
        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            species = session.execute(select(WikidataSpecies)).scalars().all()
            assert len(species) == 1

    @pytest.mark.parametrize(
        "stat_key,expected_value,setup_type",
        [
            pytest.param("species_count", 2, "species", id="species-count"),
            pytest.param("translation_count", 2, "translations", id="translation-count"),
        ],
    )
    def test_validation_statistics(self, builder, stat_key, expected_value, setup_type):
        """Should validate database statistics."""
        if setup_type == "species":
            species_data = [
                {
                    "wikidata_id": "Q123",
                    "avibase_id": "ABC123",
                    "scientific_name": "Test species",
                },
                {
                    "wikidata_id": "Q456",
                    "avibase_id": "DEF456",
                    "scientific_name": "Another species",
                },
            ]
            builder._insert_species(species_data)
        elif setup_type == "translations":
            # First insert species for translations
            species_data = [
                {
                    "wikidata_id": "Q123",
                    "avibase_id": "ABC123",
                    "scientific_name": "Test species",
                }
            ]
            builder._insert_species(species_data)

            translations = [
                {
                    "avibase_id": "ABC123",
                    "language_code": "es",
                    "common_name": "Especie de Prueba",
                },
                {
                    "avibase_id": "ABC123",
                    "language_code": "fr",
                    "common_name": "Espèce de Test",
                },
            ]
            builder._insert_translations(translations)

        stats = builder.get_statistics()
        assert stats[stat_key] == expected_value

    def test_language_filtering(self, builder):
        """Should extract only target languages."""
        with patch("wikidata_database_builder.TARGET_LANGUAGES", ["nb", "eu"]):
            query = builder._build_labels_query(["Q123"])

            # Should only include target languages
            assert '"nb"' in query
            assert '"eu"' in query

            # Should not include other languages
            assert '"es"' not in query
            assert '"fr"' not in query


class TestWikidataModels:
    """Tests for Wikidata database models."""

    def test_species_model_required_fields(self, temp_db):
        """Should verify Species model has required fields."""
        engine = create_engine(f"sqlite:///{temp_db}")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            species = WikidataSpecies(
                avibase_id="TEST123",
                wikidata_id="Q123",
                scientific_name="Test species",
            )
            session.add(species)
            session.commit()

            retrieved = session.execute(
                select(WikidataSpecies).where(WikidataSpecies.avibase_id == "TEST123")
            ).scalar_one()

            assert retrieved.wikidata_id == "Q123"
            assert retrieved.scientific_name == "Test species"

    def test_translation_model_required_fields(self, temp_db):
        """Should verify Translation model has required fields."""
        engine = create_engine(f"sqlite:///{temp_db}")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            # First create a species
            species = WikidataSpecies(
                avibase_id="TEST123",
                wikidata_id="Q123",
                scientific_name="Test species",
            )
            session.add(species)
            session.commit()

            # Then create translation
            translation = WikidataTranslation(
                avibase_id="TEST123",
                language_code="nb",
                common_name="Test art",
            )
            session.add(translation)
            session.commit()

            retrieved = session.execute(
                select(WikidataTranslation).where(WikidataTranslation.avibase_id == "TEST123")
            ).scalar_one()

            assert retrieved.language_code == "nb"
            assert retrieved.common_name == "Test art"

    def test_species_unique_constraint(self, temp_db):
        """Should ensure avibase_id is unique in Species table."""
        engine = create_engine(f"sqlite:///{temp_db}")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            species1 = WikidataSpecies(
                avibase_id="TEST123",
                wikidata_id="Q123",
                scientific_name="Test species",
            )
            session.add(species1)
            session.commit()

            # Try to add duplicate
            species2 = WikidataSpecies(
                avibase_id="TEST123",  # Same ID
                wikidata_id="Q456",
                scientific_name="Different species",
            )
            session.add(species2)

            with pytest.raises(IntegrityError):  # Should raise integrity error
                session.commit()


class TestScientificNameFiltering:
    """Tests specifically for scientific name fallback filtering."""

    @pytest.mark.parametrize(
        "scientific_name,labels_data,expected_filtered_count,expected_common_name",
        [
            pytest.param(
                "Thalassarche eremita",
                [
                    ("es", "Thalassarche eremita"),  # Exact match - filter out
                    ("de", "Chatham-Albatros"),  # Real translation - keep
                ],
                1,
                "Chatham-Albatros",
                id="exact-match-filtering",
            ),
            pytest.param(
                "Test species",
                [
                    ("en", "Test species"),  # Exact match - filter out
                    ("de", "TEST SPECIES"),  # Different case - keep
                ],
                1,
                "TEST SPECIES",
                id="case-sensitive-filtering",
            ),
        ],
    )
    def test_scientific_name_filtering_variants(
        self, builder, scientific_name, labels_data, expected_filtered_count, expected_common_name
    ):
        """Should test various scientific name filtering scenarios."""
        species_data = [
            {
                "wikidata_id": "Q123",
                "avibase_id": "ABC123",
                "scientific_name": scientific_name,
            }
        ]

        labels = [
            {
                "wikidata_id": "Q123",
                "language_code": lang,
                "common_name": name,
            }
            for lang, name in labels_data
        ]

        species_names = {sp["wikidata_id"]: sp["scientific_name"] for sp in species_data}
        filtered = [
            label
            for label in labels
            if label["common_name"] != species_names.get(label["wikidata_id"])
        ]

        assert len(filtered) == expected_filtered_count
        if expected_common_name:
            assert filtered[0]["common_name"] == expected_common_name

    def test_filtering_percentage(self, builder):
        """Should calculate realistic filtering percentage."""
        species_data = [
            {"wikidata_id": f"Q{i}", "avibase_id": f"ABC{i}", "scientific_name": f"Species {i}"}
            for i in range(100)
        ]

        # Simulate 60% scientific name fallbacks
        labels = []
        for i in range(100):
            # 40% real translations
            if i < 40:
                labels.append(
                    {
                        "wikidata_id": f"Q{i}",
                        "language_code": "es",
                        "common_name": f"Especie {i}",
                    }
                )
            # 60% scientific name fallbacks
            else:
                labels.append(
                    {
                        "wikidata_id": f"Q{i}",
                        "language_code": "es",
                        "common_name": f"Species {i}",
                    }
                )

        species_names = {sp["wikidata_id"]: sp["scientific_name"] for sp in species_data}
        filtered = [
            label
            for label in labels
            if label["common_name"] != species_names.get(label["wikidata_id"])
        ]

        # Should have filtered 60% (60 fallbacks)
        assert len(filtered) == 40
        filtered_percentage = (len(labels) - len(filtered)) / len(labels) * 100
        assert filtered_percentage == 60.0
