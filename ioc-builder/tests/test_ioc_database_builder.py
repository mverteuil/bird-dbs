"""Tests for IOC database builder."""

import tempfile
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from ioc_reference_builder.ioc_database_builder import IOCDatabaseBuilder
from ioc_reference_builder.ioc_models import (
    IOCSpecies,
    IOCTranslation,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def sample_ioc_species_data():
    """Sample IOC species data."""
    return pd.DataFrame(
        {
            "Order": ["STRUTHIONIFORMES", "STRUTHIONIFORMES"],
            "Family": ["Struthionidae", "Struthionidae"],
            "Genus": ["Struthio", "Struthio"],
            "Species": ["camelus", "molybdophanes"],
            "English name": ["Common Ostrich", "Somali Ostrich"],
            "Authority": ["Linnaeus, 1758", "Reichenow, 1883"],
        }
    )


@pytest.fixture
def sample_ioc_multilingual_data():
    """Sample IOC multilingual translation data."""
    return pd.DataFrame(
        {
            "Scientific name": [
                "Struthio camelus",
                "Struthio camelus",
                "Struthio molybdophanes",
                "Struthio molybdophanes",
            ],
            "LanguageCode": ["es", "fr", "es", "fr"],
            "CommonName": [
                "Avestruz Común",
                "Autruche d'Afrique",
                "Avestruz Somalí",
                "Autruche de Somalie",
            ],
        }
    )


@pytest.fixture
def sample_avilistr_data():
    """Sample Avilistr data with Avibase ID mappings."""
    return pd.DataFrame(
        {
            "scientific_name": ["Struthio camelus", "Struthio molybdophanes"],
            "avibase_id": ["ABC123DEF456", "GHI789JKL012"],
            "ioc_scientific_name": ["Struthio camelus", "Struthio molybdophanes"],
            "clements_scientific_name": ["Struthio camelus", "Struthio molybdophanes"],
        }
    )


@pytest.fixture
def builder(temp_db):
    """Create IOC database builder instance."""
    return IOCDatabaseBuilder(db_path=temp_db)


class TestIOCDatabaseBuilder:
    """Tests for IOC database builder."""

    @pytest.mark.parametrize(
        "check_type,expected_result",
        [
            pytest.param("database_file", True, id="creates-database-file"),
            pytest.param("tables", ["species", "translations"], id="creates-required-tables"),
        ],
    )
    def test_initialization(self, temp_db, check_type, expected_result):
        """Test that initialization creates database and tables correctly."""
        _ = IOCDatabaseBuilder(db_path=temp_db)

        if check_type == "database_file":
            assert Path(temp_db).exists() == expected_result
        elif check_type == "tables":
            engine = create_engine(f"sqlite:///{temp_db}")
            from sqlalchemy import inspect

            inspector = inspect(engine)
            tables = inspector.get_table_names()

            for table_name in expected_result:
                assert table_name in tables

    def test_parse_species_data(self, builder, sample_ioc_species_data):
        """Test parsing IOC species data."""
        species_list = builder._parse_species_data(sample_ioc_species_data)

        assert len(species_list) == 2
        assert species_list[0]["scientific_name"] == "Struthio camelus"
        assert species_list[0]["english_name"] == "Common Ostrich"
        assert species_list[1]["scientific_name"] == "Struthio molybdophanes"
        assert species_list[1]["english_name"] == "Somali Ostrich"

    def test_parse_multilingual_data(self, builder, sample_ioc_multilingual_data):
        """Test parsing IOC multilingual translation data."""
        translations = builder._parse_multilingual_data(sample_ioc_multilingual_data)

        assert len(translations) == 4

        # Check Spanish translations
        spanish = [t for t in translations if t["language_code"] == "es"]
        assert len(spanish) == 2
        assert any(t["common_name"] == "Avestruz Común" for t in spanish)

        # Check French translations
        french = [t for t in translations if t["language_code"] == "fr"]
        assert len(french) == 2
        assert any(t["common_name"] == "Autruche d'Afrique" for t in french)

    def test_map_avibase_ids(self, builder, sample_ioc_species_data, sample_avilistr_data):
        """Test mapping Avibase IDs to IOC species."""
        species_list = builder._parse_species_data(sample_ioc_species_data)
        mapped = builder._map_avibase_ids(species_list, sample_avilistr_data)

        assert len(mapped) == 2
        assert mapped[0]["avibase_id"] == "ABC123DEF456"
        assert mapped[1]["avibase_id"] == "GHI789JKL012"

    def test_map_avibase_ids_missing_species(self, builder, sample_ioc_species_data):
        """Test that species without Avibase IDs are excluded."""
        species_list = builder._parse_species_data(sample_ioc_species_data)

        # Empty Avilistr data
        empty_avilistr = pd.DataFrame(
            {
                "scientific_name": [],
                "avibase_id": [],
                "ioc_scientific_name": [],
            }
        )

        mapped = builder._map_avibase_ids(species_list, empty_avilistr)
        assert len(mapped) == 0

    def test_insert_species(self, builder, sample_ioc_species_data, sample_avilistr_data):
        """Test inserting species into database."""
        species_list = builder._parse_species_data(sample_ioc_species_data)
        mapped = builder._map_avibase_ids(species_list, sample_avilistr_data)

        builder._insert_species(mapped)

        # Verify species were inserted
        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            species = session.execute(select(IOCSpecies)).scalars().all()
            assert len(species) == 2
            assert species[0].avibase_id == "ABC123DEF456"
            assert species[0].scientific_name == "Struthio camelus"
            assert species[1].avibase_id == "GHI789JKL012"

    def test_insert_translations(
        self,
        builder,
        sample_ioc_species_data,
        sample_ioc_multilingual_data,
        sample_avilistr_data,
    ):
        """Test inserting translations into database."""
        # First insert species
        species_list = builder._parse_species_data(sample_ioc_species_data)
        mapped = builder._map_avibase_ids(species_list, sample_avilistr_data)
        builder._insert_species(mapped)

        # Then insert translations
        translations = builder._parse_multilingual_data(sample_ioc_multilingual_data)
        builder._insert_translations(translations, sample_avilistr_data)

        # Verify translations were inserted
        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            trans = session.execute(select(IOCTranslation)).scalars().all()
            assert len(trans) == 4

            # Check avibase_id mapping worked
            avibase_ids = {t.avibase_id for t in trans}
            assert "ABC123DEF456" in avibase_ids
            assert "GHI789JKL012" in avibase_ids

    def test_duplicate_species_handling(
        self, builder, sample_ioc_species_data, sample_avilistr_data
    ):
        """Test that duplicate species are handled correctly."""
        species_list = builder._parse_species_data(sample_ioc_species_data)
        mapped = builder._map_avibase_ids(species_list, sample_avilistr_data)

        # Insert twice
        builder._insert_species(mapped)
        builder._insert_species(mapped)

        # Should only have 2 species (no duplicates)
        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            species = session.execute(select(IOCSpecies)).scalars().all()
            assert len(species) == 2

    def test_language_code_normalization(self, builder):
        """Test that language codes are normalized to lowercase."""
        data = pd.DataFrame(
            {
                "Scientific name": ["Struthio camelus"],
                "LanguageCode": ["ES"],  # Uppercase
                "CommonName": ["Avestruz"],
            }
        )

        translations = builder._parse_multilingual_data(data)
        assert translations[0]["language_code"] == "es"  # Should be lowercase

    def test_empty_translation_filtering(self, builder):
        """Test that empty translations are filtered out."""
        data = pd.DataFrame(
            {
                "Scientific name": ["Struthio camelus", "Struthio molybdophanes"],
                "LanguageCode": ["es", "fr"],
                "CommonName": ["Avestruz", ""],  # Empty translation
            }
        )

        translations = builder._parse_multilingual_data(data)
        assert len(translations) == 1
        assert translations[0]["common_name"] == "Avestruz"

    def test_scientific_name_matching_case_insensitive(self, builder, sample_avilistr_data):
        """Test that scientific name matching is case-insensitive."""
        species_data = pd.DataFrame(
            {
                "Order": ["STRUTHIONIFORMES"],
                "Family": ["Struthionidae"],
                "Genus": ["Struthio"],
                "Species": ["camelus"],
                "English name": ["Common Ostrich"],
                "Authority": ["Linnaeus, 1758"],
            }
        )

        # Use uppercase in Avilistr
        avilistr = sample_avilistr_data.copy()
        avilistr.loc[0, "ioc_scientific_name"] = "STRUTHIO CAMELUS"

        species_list = builder._parse_species_data(species_data)
        mapped = builder._map_avibase_ids(species_list, avilistr)

        assert len(mapped) == 1
        assert mapped[0]["avibase_id"] == "ABC123DEF456"

    @pytest.mark.parametrize(
        "stat_key,expected_value,needs_translations",
        [
            pytest.param("species_count", 2, False, id="species-count"),
            pytest.param("translation_count", 4, True, id="translation-count"),
            pytest.param("language_count", 2, True, id="language-count-spanish-french"),
        ],
    )
    def test_validation_statistics(
        self,
        builder,
        sample_ioc_species_data,
        sample_ioc_multilingual_data,
        sample_avilistr_data,
        stat_key,
        expected_value,
        needs_translations,
    ):
        """Test validation of database statistics."""
        # Always insert species
        species_list = builder._parse_species_data(sample_ioc_species_data)
        mapped = builder._map_avibase_ids(species_list, sample_avilistr_data)
        builder._insert_species(mapped)

        # Conditionally insert translations based on test requirements
        if needs_translations:
            translations = builder._parse_multilingual_data(sample_ioc_multilingual_data)
            builder._insert_translations(translations, sample_avilistr_data)

        stats = builder.get_statistics()
        assert stats[stat_key] == expected_value


class TestIOCModels:
    """Tests for IOC database models."""

    def test_species_model_required_fields(self, temp_db):
        """Test that Species model has required fields."""
        engine = create_engine(f"sqlite:///{temp_db}")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            species = IOCSpecies(
                avibase_id="TEST123",
                scientific_name="Test species",
                english_name="Test Species",
                order="TESTORDER",
                family="Testidae",
                genus="Test",
                species="species",
            )
            session.add(species)
            session.commit()

            retrieved = session.execute(
                select(IOCSpecies).where(IOCSpecies.avibase_id == "TEST123")
            ).scalar_one()

            assert retrieved.scientific_name == "Test species"
            assert retrieved.english_name == "Test Species"

    def test_translation_model_required_fields(self, temp_db):
        """Test that Translation model has required fields."""
        engine = create_engine(f"sqlite:///{temp_db}")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            # First create a species
            species = IOCSpecies(
                avibase_id="TEST123",
                scientific_name="Test species",
                english_name="Test Species",
                order="TESTORDER",
                family="Testidae",
                genus="Test",
                species="species",
            )
            session.add(species)
            session.commit()

            # Then create translation
            translation = IOCTranslation(
                avibase_id="TEST123",
                language_code="es",
                common_name="Especie de Prueba",
            )
            session.add(translation)
            session.commit()

            retrieved = session.execute(
                select(IOCTranslation).where(IOCTranslation.avibase_id == "TEST123")
            ).scalar_one()

            assert retrieved.language_code == "es"
            assert retrieved.common_name == "Especie de Prueba"

    def test_species_unique_constraint(self, temp_db):
        """Test that avibase_id is unique in Species table."""
        engine = create_engine(f"sqlite:///{temp_db}")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            species1 = IOCSpecies(
                avibase_id="TEST123",
                scientific_name="Test species",
                english_name="Test Species",
                order="TESTORDER",
                family="Testidae",
                genus="Test",
                species="species",
            )
            session.add(species1)
            session.commit()

            # Try to add duplicate
            species2 = IOCSpecies(
                avibase_id="TEST123",  # Same ID
                scientific_name="Different species",
                english_name="Different Species",
                order="TESTORDER",
                family="Testidae",
                genus="Different",
                species="species",
            )
            session.add(species2)

            with pytest.raises(IntegrityError):  # Should raise integrity error
                session.commit()


class TestIOCDatabaseBuilderIntegration:
    """Integration tests for XML/XLSX file processing."""

    @pytest.fixture
    def sample_xml_file(self):
        """Path to sample IOC XML file."""
        return Path(__file__).parent / "fixtures" / "sample_ioc.xml"

    @pytest.fixture
    def sample_xlsx_file(self):
        """Path to sample IOC XLSX file."""
        return Path(__file__).parent / "fixtures" / "sample_ioc_multilingual.xlsx"

    @pytest.fixture
    def sample_avilistr_file(self):
        """Path to sample Avibase mapping CSV file."""
        return Path(__file__).parent / "fixtures" / "sample_avilistr.csv"

    def test_populate_from_xml_only(self, temp_db, sample_xml_file, sample_avilistr_file):
        """Test populating database from XML file only."""
        builder = IOCDatabaseBuilder(db_path=temp_db)
        builder.populate_from_files(xml_file=sample_xml_file, avilistr_csv=sample_avilistr_file)

        # Verify species were inserted
        engine = create_engine(f"sqlite:///{temp_db}")
        with Session(engine) as session:
            species = session.execute(select(IOCSpecies)).scalars().all()
            assert len(species) == 3  # Struthio camelus, S. molybdophanes, Anas platyrhynchos

            # Check specific species
            scientific_names = [s.scientific_name for s in species]
            assert "Struthio camelus" in scientific_names
            assert "Struthio molybdophanes" in scientific_names
            assert "Anas platyrhynchos" in scientific_names

            # Check English names
            ostrich = [s for s in species if s.scientific_name == "Struthio camelus"][0]
            assert ostrich.english_name == "Common Ostrich"
            assert ostrich.order == "STRUTHIONIFORMES"
            assert ostrich.family == "Struthionidae"

    def test_populate_from_xml_and_xlsx(
        self, temp_db, sample_xml_file, sample_xlsx_file, sample_avilistr_file
    ):
        """Test populating database from both XML and XLSX files."""
        builder = IOCDatabaseBuilder(db_path=temp_db)
        builder.populate_from_files(
            xml_file=sample_xml_file,
            avilistr_csv=sample_avilistr_file,
            xlsx_file=sample_xlsx_file,
        )

        engine = create_engine(f"sqlite:///{temp_db}")
        with Session(engine) as session:
            # Verify species
            species = session.execute(select(IOCSpecies)).scalars().all()
            assert len(species) == 3

            # Verify translations
            translations = session.execute(select(IOCTranslation)).scalars().all()
            assert len(translations) == 9  # 3 species × 3 languages (Spanish, French, German)

            # Check specific translations
            spanish = [t for t in translations if t.language_code == "es"]
            assert len(spanish) == 3
            assert any(t.common_name == "Avestruz Común" for t in spanish)

            french = [t for t in translations if t.language_code == "fr"]
            assert len(french) == 3
            assert any(t.common_name == "Autruche d'Afrique" for t in french)

            german = [t for t in translations if t.language_code == "de"]
            assert len(german) == 3
            assert any(t.common_name == "Afrikanischer Strauß" for t in german)

    def test_populate_metadata(self, temp_db, sample_xml_file, sample_avilistr_file):
        """Test that metadata is populated correctly."""
        builder = IOCDatabaseBuilder(db_path=temp_db)
        builder.populate_from_files(xml_file=sample_xml_file, avilistr_csv=sample_avilistr_file)

        # Check metadata was stored
        engine = create_engine(f"sqlite:///{temp_db}")
        with Session(engine) as session:
            # Get IOC version from metadata
            version = session.execute(
                text("SELECT value FROM metadata WHERE key = 'ioc_version'")
            ).scalar()
            assert version == "15.1"

            # Get species count
            species_count = session.execute(
                text("SELECT value FROM metadata WHERE key = 'species_count'")
            ).scalar()
            assert species_count == "3"

    def test_populate_creates_indexes(self, temp_db, sample_xml_file, sample_avilistr_file):
        """Test that performance indexes are created."""
        builder = IOCDatabaseBuilder(db_path=temp_db)
        builder.populate_from_files(xml_file=sample_xml_file, avilistr_csv=sample_avilistr_file)

        engine = create_engine(f"sqlite:///{temp_db}")
        with Session(engine) as session:
            # Query for indexes
            indexes = session.execute(
                text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='species'")
            ).fetchall()

            index_names = [idx[0] for idx in indexes]
            assert "idx_species_family" in index_names
            assert "idx_species_genus" in index_names
            assert "idx_species_english_name" in index_names
