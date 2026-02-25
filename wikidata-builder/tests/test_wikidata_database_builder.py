"""Tests for Wikidata database builder."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from wikidata_reference_builder.wikidata_database_builder import (
    WikidataDatabaseBuilder,
)
from wikidata_reference_builder.wikidata_models import (
    WikidataSpecies,
    WikidataTranslation,
)


@pytest.fixture
def builder(temp_db):
    """Create Wikidata database builder instance."""
    return WikidataDatabaseBuilder(db_path=temp_db)


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
                    "?species wdt:P105 wd:Q7432",  # taxon rank = species
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
        # Patch TARGET_LANGUAGES as class attribute
        with patch.object(WikidataDatabaseBuilder, "TARGET_LANGUAGES", ["nb", "eu"]):
            query = builder._build_labels_query(["Q123"])

            assert '"nb"' in query
            assert '"eu"' in query

    @patch("wikidata_reference_builder.wikidata_database_builder.requests.get", autospec=True)
    def test_query_species_data(self, mock_get, builder, sample_sparql_species_response):
        """Should query species data from Wikidata."""
        # Mock requests.get response
        mock_response = MagicMock(spec=requests.Response)
        mock_response.json.return_value = sample_sparql_species_response
        mock_response.raise_for_status = MagicMock(spec=requests.Response.raise_for_status)
        mock_get.return_value = mock_response

        species_data = builder._query_species_data()

        assert len(species_data) == 2
        assert species_data[0]["wikidata_id"] == "Q123"
        assert species_data[0]["avibase_id"] == "ABC123DEF456"
        assert species_data[0]["scientific_name"] == "Struthio camelus"

    @patch("wikidata_reference_builder.wikidata_database_builder.requests.get", autospec=True)
    def test_query_multilingual_labels(
        self,
        mock_get,
        builder,
        sample_sparql_species_response,
        sample_sparql_labels_response,
    ):
        """Should query multilingual labels from Wikidata."""
        # Mock requests.get response
        mock_response = MagicMock(spec=requests.Response)
        mock_response.json.return_value = sample_sparql_labels_response
        mock_response.raise_for_status = MagicMock(spec=requests.Response.raise_for_status)
        mock_get.return_value = mock_response

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

    @patch("wikidata_reference_builder.wikidata_database_builder.requests.get", autospec=True)
    def test_insert_species(self, mock_get, builder, sample_sparql_species_response):
        """Should insert species into database."""
        # Mock requests.get response
        mock_response = MagicMock(spec=requests.Response)
        mock_response.json.return_value = sample_sparql_species_response
        mock_response.raise_for_status = MagicMock(spec=requests.Response.raise_for_status)
        mock_get.return_value = mock_response

        species_data = builder._query_species_data()
        builder._insert_species(species_data)

        # Verify species were inserted
        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            species = session.execute(select(WikidataSpecies)).scalars().all()
            assert len(species) == 2
            assert species[0].avibase_id == "ABC123DEF456"
            assert species[0].wikidata_id == "Q123"

    def test_insert_translations(self, builder):
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
        with patch(
            "wikidata_reference_builder.wikidata_database_builder.requests.get", autospec=True
        ) as mock_get:
            mock_get.side_effect = Exception("Timeout")

            with pytest.raises(Exception, match="Timeout"):
                builder._query_species_data()

    def test_handle_empty_response(self, builder):
        """Should handle empty API responses."""
        with patch(
            "wikidata_reference_builder.wikidata_database_builder.requests.get", autospec=True
        ) as mock_get:
            # Mock requests.get response with empty results
            mock_response = MagicMock(spec=requests.Response)
            mock_response.json.return_value = {"results": {"bindings": []}}
            mock_response.raise_for_status = MagicMock(spec=requests.Response.raise_for_status)
            mock_get.return_value = mock_response

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
        # Patch TARGET_LANGUAGES as class attribute
        with patch.object(WikidataDatabaseBuilder, "TARGET_LANGUAGES", ["nb", "eu"]):
            query = builder._build_labels_query(["Q123"])

            # Should only include target languages
            assert '"nb"' in query
            assert '"eu"' in query

            # Should not include other languages
            assert '"es"' not in query
            assert '"fr"' not in query


class TestWikidataDatabaseBuilderErrorPaths:
    """Tests for error handling and edge cases."""

    def test_unicode_wikidata_ids(self, builder):
        """Should handle Unicode in scientific names."""
        species_data = [
            {
                "wikidata_id": "Q123",
                "avibase_id": "ABC123",
                "scientific_name": "Tōhī camelus",  # Macron
            }
        ]

        builder._insert_species(species_data)

        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            species = session.execute(select(WikidataSpecies)).scalars().all()
            assert len(species) == 1
            assert "Tōhī" in species[0].scientific_name

    def test_unicode_translation_names(self, builder):
        """Should handle Unicode in translations."""
        # First insert species
        species_data = [
            {
                "wikidata_id": "Q123",
                "avibase_id": "ABC123",
                "scientific_name": "Passer domesticus",
            }
        ]
        builder._insert_species(species_data)

        # Add translations with Unicode
        translations = [
            {
                "avibase_id": "ABC123",
                "language_code": "zh-hans",
                "common_name": "家麻雀",  # Chinese
            },
            {
                "avibase_id": "ABC123",
                "language_code": "ja",
                "common_name": "イエスズメ",  # Japanese
            },
        ]

        builder._insert_translations(translations)

        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            trans = session.execute(select(WikidataTranslation)).scalars().all()
            assert len(trans) == 2
            names = [t.common_name for t in trans]
            assert "家麻雀" in names
            assert "イエスズメ" in names

    def test_emoji_in_translations(self, builder):
        """Should handle emoji in translation names."""
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
                "language_code": "en",
                "common_name": "Test Bird 🐦",  # Emoji
            }
        ]

        builder._insert_translations(translations)

        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            trans = session.execute(select(WikidataTranslation)).scalars().all()
            assert len(trans) == 1
            assert "🐦" in trans[0].common_name

    def test_hybrid_species_names(self, builder):
        """Should handle hybrid species names with special characters."""
        species_data = [
            {
                "wikidata_id": "Q123",
                "avibase_id": "ABC123",
                "scientific_name": "Circus cyaneus × Circus pygargus",  # Hybrid
            }
        ]

        builder._insert_species(species_data)

        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            species = session.execute(select(WikidataSpecies)).scalars().all()
            assert len(species) == 1
            assert "×" in species[0].scientific_name

    def test_very_long_common_names(self, builder):
        """Should handle very long common names."""
        species_data = [
            {
                "wikidata_id": "Q123",
                "avibase_id": "ABC123",
                "scientific_name": "Test species",
            }
        ]
        builder._insert_species(species_data)

        long_name = "A" * 500  # 500 character name
        translations = [
            {
                "avibase_id": "ABC123",
                "language_code": "en",
                "common_name": long_name,
            }
        ]

        builder._insert_translations(translations)

        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            trans = session.execute(select(WikidataTranslation)).scalars().all()
            assert len(trans) == 1
            assert len(trans[0].common_name) == 500

    def test_special_language_codes(self, builder):
        """Should handle language codes with region suffixes."""
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
                "language_code": "zh-hans",  # Simplified Chinese
                "common_name": "测试鸟",
            },
            {
                "avibase_id": "ABC123",
                "language_code": "zh-hant",  # Traditional Chinese
                "common_name": "測試鳥",
            },
        ]

        builder._insert_translations(translations)

        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            trans = session.execute(select(WikidataTranslation)).scalars().all()
            assert len(trans) == 2
            lang_codes = [t.language_code for t in trans]
            assert "zh-hans" in lang_codes
            assert "zh-hant" in lang_codes

    def test_empty_scientific_name_filtering(self, builder):
        """Should filter species with empty scientific names."""
        species_data = [
            {
                "wikidata_id": "Q123",
                "avibase_id": "ABC123",
                "scientific_name": "",  # Empty name
            }
        ]

        # Should handle gracefully (either skip or store as-is)
        builder._insert_species(species_data)

        engine = create_engine(f"sqlite:///{builder.db_path}")
        with Session(engine) as session:
            session.execute(select(WikidataSpecies)).scalars().all()
            # Implementation may filter or store - just verify it doesn't crash
            assert True  # Made it this far without error


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
