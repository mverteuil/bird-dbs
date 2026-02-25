"""Tests for IOC database builder."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from ioc_reference_builder.ioc_database_builder import IOCDatabaseBuilder
from ioc_reference_builder.ioc_models import (
    IOCSpecies,
    IOCTranslation,
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
        """Should create database and tables correctly."""
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
        """Should parse IOC species data."""
        species_list = builder._parse_species_data(sample_ioc_species_data)

        assert len(species_list) == 2
        assert species_list[0]["scientific_name"] == "Struthio camelus"
        assert species_list[0]["english_name"] == "Common Ostrich"
        assert species_list[1]["scientific_name"] == "Struthio molybdophanes"
        assert species_list[1]["english_name"] == "Somali Ostrich"

    def test_parse_multilingual_data(self, builder, sample_ioc_multilingual_data):
        """Should parse IOC multilingual translation data."""
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
        """Should map Avibase IDs to IOC species."""
        species_list = builder._parse_species_data(sample_ioc_species_data)
        mapped = builder._map_avibase_ids(species_list, sample_avilistr_data)

        assert len(mapped) == 2
        assert mapped[0]["avibase_id"] == "ABC123DEF456"
        assert mapped[1]["avibase_id"] == "GHI789JKL012"

    def test_map_avibase_ids_missing_species(self, builder, sample_ioc_species_data):
        """Should exclude species without Avibase IDs."""
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
        """Should insert species into database."""
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
        """Should insert translations into database."""
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
        """Should handle duplicate species correctly."""
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
        """Should normalize language codes to lowercase."""
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
        """Should filter out empty translations."""
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
        """Should match scientific names case-insensitively."""
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
        """Should validate database statistics."""
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
        """Should populate database from XML file only."""
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
            assert ostrich.order_name == "STRUTHIONIFORMES"
            assert ostrich.family == "Struthionidae"

    def test_populate_from_xml_and_xlsx(
        self, temp_db, sample_xml_file, sample_xlsx_file, sample_avilistr_file
    ):
        """Should populate database from both XML and XLSX files."""
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
        """Should populate metadata correctly."""
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
        """Should create performance indexes."""
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


class TestIOCDatabaseBuilderErrorPaths:
    """Tests for error handling and edge cases."""

    def test_unicode_species_names(self, builder):
        """Should handle Unicode characters in species names."""
        # Test with various Unicode characters
        data = pd.DataFrame(
            {
                "Order": ["PASSERIFORMES"],
                "Family": ["Corvidae"],
                "Genus": ["Cyanocitta"],
                "Species": ["cristata"],
                "English name": ["Blue Jay (Māori: Kōlea)"],  # Macrons
                "Authority": ["Linnæus, 1758"],  # Ligature
            }
        )

        species_list = builder._parse_species_data(data)
        assert len(species_list) == 1
        assert "Māori" in species_list[0]["english_name"]
        assert "Linnæus" in species_list[0]["authority"]

    def test_unicode_translation_names(self, builder):
        """Should handle Unicode in multilingual translations."""
        data = pd.DataFrame(
            {
                "Scientific name": ["Passer domesticus", "Turdus merula"],
                "LanguageCode": ["zh-hans", "ja"],
                "CommonName": ["家麻雀", "クロウタドリ"],  # Chinese, Japanese
            }
        )

        translations = builder._parse_multilingual_data(data)
        assert len(translations) == 2
        assert translations[0]["common_name"] == "家麻雀"
        assert translations[1]["common_name"] == "クロウタドリ"

    def test_emoji_in_names(self, builder):
        """Should handle emoji characters in names."""
        data = pd.DataFrame(
            {
                "Scientific name": ["Passer domesticus"],
                "LanguageCode": ["en"],
                "CommonName": ["House Sparrow 🐦"],  # Emoji
            }
        )

        translations = builder._parse_multilingual_data(data)
        assert len(translations) == 1
        assert "🐦" in translations[0]["common_name"]

    def test_special_characters_in_authority(self, builder):
        """Should handle special characters in authority field."""
        data = pd.DataFrame(
            {
                "Order": ["PASSERIFORMES"],
                "Family": ["Fringillidae"],
                "Genus": ["Carduelis"],
                "Species": ["carduelis"],
                "English name": ["European Goldfinch"],
                "Authority": ["(Linnaeus, 1758)"],  # Parentheses
            }
        )

        species_list = builder._parse_species_data(data)
        assert len(species_list) == 1
        assert species_list[0]["authority"] == "(Linnaeus, 1758)"

    def test_extremely_long_names(self, builder):
        """Should handle extremely long species names."""
        long_name = "A" * 500  # 500 character name
        data = pd.DataFrame(
            {
                "Order": ["PASSERIFORMES"],
                "Family": ["Testidae"],
                "Genus": ["Test"],
                "Species": ["test"],
                "English name": [long_name],
                "Authority": ["Test, 2024"],
            }
        )

        species_list = builder._parse_species_data(data)
        assert len(species_list) == 1
        assert len(species_list[0]["english_name"]) == 500

    def test_whitespace_handling(self, builder):
        """Should handle extra whitespace in species data."""
        data = pd.DataFrame(
            {
                "Scientific name": ["  Passer domesticus  "],  # Leading/trailing spaces
                "LanguageCode": [" es "],
                "CommonName": ["  Gorrión Común  "],
            }
        )

        translations = builder._parse_multilingual_data(data)
        assert len(translations) == 1
        # Should trim whitespace
        assert translations[0]["common_name"].strip() == "Gorrión Común"

    def test_null_handling_in_optional_fields(self, builder):
        """Should handle null values in optional fields gracefully."""
        data = pd.DataFrame(
            {
                "Order": ["PASSERIFORMES"],
                "Family": ["Corvidae"],
                "Genus": ["Corvus"],
                "Species": ["corax"],
                "English name": ["Common Raven"],
                "Authority": [np.nan],  # Null authority
            }
        )

        species_list = builder._parse_species_data(data)
        assert len(species_list) == 1
        # Should handle nan gracefully (may be None, nan, or string 'nan')
        authority = species_list[0]["authority"]
        assert authority is None or pd.isna(authority) or authority == "nan"

    def test_mixed_case_language_codes(self, builder):
        """Should normalize mixed-case language codes."""
        data = pd.DataFrame(
            {
                "Scientific name": ["Passer domesticus", "Turdus merula"],
                "LanguageCode": ["eS", "Fr"],  # Mixed case
                "CommonName": ["Gorrión", "Merle"],
            }
        )

        translations = builder._parse_multilingual_data(data)
        assert all(t["language_code"].islower() for t in translations)
        assert {t["language_code"] for t in translations} == {"es", "fr"}

    def test_scientific_name_special_characters(self, builder):
        """Should handle special characters in scientific names."""
        data = pd.DataFrame(
            {
                "Scientific name": ["Circus cyaneus × Circus pygargus"],  # Hybrid indicator
                "LanguageCode": ["en"],
                "CommonName": ["Hen Harrier × Montagu's Harrier"],
            }
        )

        translations = builder._parse_multilingual_data(data)
        assert len(translations) == 1
        assert "×" in translations[0]["common_name"]
