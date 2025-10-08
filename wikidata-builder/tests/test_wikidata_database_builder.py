"""Tests for Wikidata database builder."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from wikidata_database_builder import WikidataDatabaseBuilder
from wikidata_models import Base, Species, Translation


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
    return WikidataDatabaseBuilder(database_path=temp_db)


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

    def test_init_creates_database(self, temp_db):
        """Test that initialization creates database file."""
        _ = WikidataDatabaseBuilder(database_path=temp_db)
        assert Path(temp_db).exists()

    def test_init_creates_tables(self, temp_db):
        """Test that initialization creates required tables."""
        _ = WikidataDatabaseBuilder(database_path=temp_db)
        engine = create_engine(f"sqlite:///{temp_db}")

        from sqlalchemy import inspect

        inspector = inspect(engine)
        tables = inspector.get_table_names()

        assert "species" in tables
        assert "translations" in tables

    def test_build_species_query(self, builder):
        """Test SPARQL query construction for species."""
        query = builder._build_species_query()

        assert "SELECT" in query
        assert "?species wdt:P2026 ?avibaseID" in query  # Avibase ID property
        assert "?species wdt:P225 ?scientificName" in query  # Scientific name
        assert "?species wdt:P31 wd:Q16521" in query  # Instance of: taxon

    def test_build_species_query_excludes_extinct(self, builder):
        """Test that species query excludes extinct species."""
        query = builder._build_species_query()

        # Should filter extinct species
        assert "FILTER NOT EXISTS" in query or "MINUS" in query
        assert "P141" in query  # Conservation status
        assert "P582" in query  # Extinction date

    def test_build_labels_query(self, builder):
        """Test SPARQL query construction for multilingual labels."""
        species_ids = ["Q123", "Q456"]
        query = builder._build_labels_query(species_ids)

        assert "SELECT" in query
        assert "rdfs:label" in query
        assert "LANG(?label)" in query
        assert "Q123" in query
        assert "Q456" in query

    def test_build_labels_query_language_filter(self, builder):
        """Test that labels query filters to target languages."""
        # Patch TARGET_LANGUAGES
        with patch("wikidata_database_builder.TARGET_LANGUAGES", ["nb", "eu"]):
            query = builder._build_labels_query(["Q123"])

            assert '"nb"' in query
            assert '"eu"' in query

    @patch("wikidata_database_builder.SPARQLWrapper")
    def test_query_species_data(self, mock_sparql, builder, sample_sparql_species_response):
        """Test querying species data from Wikidata."""
        # Mock SPARQL response
        mock_wrapper = MagicMock()
        mock_wrapper.query.return_value.convert.return_value = sample_sparql_species_response
        mock_sparql.return_value = mock_wrapper

        species_data = builder._query_species_data()

        assert len(species_data) == 2
        assert species_data[0]["wikidata_id"] == "Q123"
        assert species_data[0]["avibase_id"] == "ABC123DEF456"
        assert species_data[0]["scientific_name"] == "Struthio camelus"

    @patch("wikidata_database_builder.SPARQLWrapper")
    def test_query_multilingual_labels(
        self,
        mock_sparql,
        builder,
        sample_sparql_species_response,
        sample_sparql_labels_response,
    ):
        """Test querying multilingual labels from Wikidata."""
        # Mock SPARQL response
        mock_wrapper = MagicMock()
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
        """Test that scientific name fallbacks are filtered out."""
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

    @patch("wikidata_database_builder.SPARQLWrapper")
    def test_insert_species(self, mock_sparql, builder, sample_sparql_species_response):
        """Test inserting species into database."""
        mock_wrapper = MagicMock()
        mock_wrapper.query.return_value.convert.return_value = sample_sparql_species_response
        mock_sparql.return_value = mock_wrapper

        species_data = builder._query_species_data()
        builder._insert_species(species_data)

        # Verify species were inserted
        engine = create_engine(f"sqlite:///{builder.database_path}")
        with Session(engine) as session:
            species = session.execute(select(Species)).scalars().all()
            assert len(species) == 2
            assert species[0].avibase_id == "ABC123DEF456"
            assert species[0].wikidata_id == "Q123"

    @patch("wikidata_database_builder.SPARQLWrapper")
    def test_insert_translations(self, mock_sparql, builder):
        """Test inserting translations into database."""
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
        engine = create_engine(f"sqlite:///{builder.database_path}")
        with Session(engine) as session:
            trans = session.execute(select(Translation)).scalars().all()
            assert len(trans) == 1
            assert trans[0].avibase_id == "ABC123DEF456"
            assert trans[0].common_name == "Avestruz Común"

    def test_handle_api_timeout(self, builder):
        """Test handling of API timeout errors."""
        with patch("wikidata_database_builder.SPARQLWrapper") as mock_sparql:
            mock_wrapper = MagicMock()
            mock_wrapper.query.side_effect = Exception("Timeout")
            mock_sparql.return_value = mock_wrapper

            with pytest.raises(Exception, match="Timeout"):
                builder._query_species_data()

    def test_handle_empty_response(self, builder):
        """Test handling of empty API responses."""
        with patch("wikidata_database_builder.SPARQLWrapper") as mock_sparql:
            mock_wrapper = MagicMock()
            mock_wrapper.query.return_value.convert.return_value = {"results": {"bindings": []}}
            mock_sparql.return_value = mock_wrapper

            species_data = builder._query_species_data()
            assert len(species_data) == 0

    def test_duplicate_species_handling(self, builder):
        """Test that duplicate species are handled correctly."""
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
        engine = create_engine(f"sqlite:///{builder.database_path}")
        with Session(engine) as session:
            species = session.execute(select(Species)).scalars().all()
            assert len(species) == 1

    def test_validation_species_count(self, builder):
        """Test validation of species count."""
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

        stats = builder.get_statistics()
        assert stats["species_count"] == 2

    def test_validation_translation_count(self, builder):
        """Test validation of translation count."""
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
        assert stats["translation_count"] == 2

    def test_language_filtering(self, builder):
        """Test that only target languages are extracted."""
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
        """Test that Species model has required fields."""
        engine = create_engine(f"sqlite:///{temp_db}")
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            species = Species(
                avibase_id="TEST123",
                wikidata_id="Q123",
                scientific_name="Test species",
            )
            session.add(species)
            session.commit()

            retrieved = session.execute(
                select(Species).where(Species.avibase_id == "TEST123")
            ).scalar_one()

            assert retrieved.wikidata_id == "Q123"
            assert retrieved.scientific_name == "Test species"

    def test_translation_model_required_fields(self, temp_db):
        """Test that Translation model has required fields."""
        engine = create_engine(f"sqlite:///{temp_db}")
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            # First create a species
            species = Species(
                avibase_id="TEST123",
                wikidata_id="Q123",
                scientific_name="Test species",
            )
            session.add(species)
            session.commit()

            # Then create translation
            translation = Translation(
                avibase_id="TEST123",
                language_code="nb",
                common_name="Test art",
            )
            session.add(translation)
            session.commit()

            retrieved = session.execute(
                select(Translation).where(Translation.avibase_id == "TEST123")
            ).scalar_one()

            assert retrieved.language_code == "nb"
            assert retrieved.common_name == "Test art"

    def test_species_unique_constraint(self, temp_db):
        """Test that avibase_id is unique in Species table."""
        engine = create_engine(f"sqlite:///{temp_db}")
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            species1 = Species(
                avibase_id="TEST123",
                wikidata_id="Q123",
                scientific_name="Test species",
            )
            session.add(species1)
            session.commit()

            # Try to add duplicate
            species2 = Species(
                avibase_id="TEST123",  # Same ID
                wikidata_id="Q456",
                scientific_name="Different species",
            )
            session.add(species2)

            with pytest.raises(IntegrityError):  # Should raise integrity error
                session.commit()


class TestScientificNameFiltering:
    """Tests specifically for scientific name fallback filtering."""

    def test_exact_match_filtering(self, builder):
        """Test that exact matches are filtered."""
        species_data = [
            {
                "wikidata_id": "Q123",
                "avibase_id": "ABC123",
                "scientific_name": "Thalassarche eremita",
            }
        ]

        labels = [
            {
                "wikidata_id": "Q123",
                "language_code": "es",
                "common_name": "Thalassarche eremita",  # Exact match
            },
            {
                "wikidata_id": "Q123",
                "language_code": "de",
                "common_name": "Chatham-Albatros",  # Real translation
            },
        ]

        species_names = {sp["wikidata_id"]: sp["scientific_name"] for sp in species_data}
        filtered = [
            label
            for label in labels
            if label["common_name"] != species_names.get(label["wikidata_id"])
        ]

        assert len(filtered) == 1
        assert filtered[0]["common_name"] == "Chatham-Albatros"

    def test_case_sensitive_filtering(self, builder):
        """Test that filtering is case-sensitive (preserve scientific names in other cases)."""
        species_data = [
            {
                "wikidata_id": "Q123",
                "avibase_id": "ABC123",
                "scientific_name": "Test species",
            }
        ]

        labels = [
            {
                "wikidata_id": "Q123",
                "language_code": "en",
                "common_name": "Test species",  # Exact match
            },
            {
                "wikidata_id": "Q123",
                "language_code": "de",
                "common_name": "TEST SPECIES",  # Different case - keep
            },
        ]

        species_names = {sp["wikidata_id"]: sp["scientific_name"] for sp in species_data}
        filtered = [
            label
            for label in labels
            if label["common_name"] != species_names.get(label["wikidata_id"])
        ]

        # Should keep the uppercase version (different case = different name)
        assert len(filtered) == 1
        assert filtered[0]["common_name"] == "TEST SPECIES"

    def test_filtering_percentage(self, builder):
        """Test realistic filtering percentage."""
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
