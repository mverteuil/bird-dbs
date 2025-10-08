# Critical: Wikidata Data Quality Issue

**Date:** 2025-10-08
**Status:** 🚨 MAJOR ISSUE DISCOVERED
**Impact:** Wikidata POC database has terrible translation quality

---

## Problem Summary

**Wikidata stores the scientific name in the `common_name` field when no translation exists**, making most "translations" completely useless.

### Example

```sql
SELECT scientific_name, language_code, common_name
FROM translations WHERE scientific_name = 'Thalassarche eremita';

-- Results:
Thalassarche eremita | es | Thalassarche eremita  ❌ NOT A TRANSLATION
Thalassarche eremita | it | Thalassarche eremita  ❌ NOT A TRANSLATION
Thalassarche eremita | ro | Thalassarche eremita  ❌ NOT A TRANSLATION
Thalassarche eremita | de | Chatham-Albatros      ✅ Real German name
Thalassarche eremita | en | Chatham Albatross     ✅ Real English name
```

**The scientific name is already language-independent!** Storing it as a "translation" provides ZERO value.

---

## Data Quality Breakdown

| Language | Total | Real Translations | Scientific Name Fallbacks | Useless % |
|----------|-------|-------------------|---------------------------|-----------|
| **Romanian (ro)** | 495 | **9** | 486 | **98%** |
| **Italian (it)** | 499 | **29** | 470 | **94%** |
| **Ukrainian (uk)** | 495 | **42** | 453 | **91%** |
| **Vietnamese (vi)** | 495 | **61** | 434 | **88%** |
| **Spanish (es)** | 499 | **85** | 414 | **83%** |
| **Basque (eu)** | 481 | **88** | 393 | **82%** |
| **Bulgarian (bg)** | 495 | **132** | 363 | **73%** |
| **Russian (ru)** | 495 | **178** | 317 | **64%** |
| German (de) | 499 | 235 | 264 | 53% |
| Portuguese (pt) | 499 | 237 | 262 | 52% |
| Catalan (ca) | 489 | 325 | 164 | 34% |
| French (fr) | 499 | 403 | 96 | 19% |
| Hungarian (hu) | 436 | 340 | 96 | 22% |
| Galician (gl) | 83 | 10 | 73 | 88% |
| Finnish (fi) | 495 | 448 | 47 | 9% |
| Polish (pl) | 499 | 452 | 47 | 9% |
| English (en) | 499 | 458 | 41 | 8% |
| Dutch (nl) | 499 | 465 | 34 | 7% |

### Summary

- **Total Wikidata translations:** 13,484
- **Real translations:** ~5,500 (41%)
- **Scientific name fallbacks:** ~8,000 (59%)
- **Useless data:** 59%!

---

## Why This Happened

**Wikidata extraction logic (SPARQL query):**

```sparql
SELECT ?species ?label (LANG(?label) AS ?lang)
WHERE {
  ?species wdt:P2026 ?avibaseID .
  ?species rdfs:label ?label .
  FILTER(LANG(?label) IN ("es", "fr", "de", ...))
}
```

**The problem:** `rdfs:label` in Wikidata includes:
1. Actual common names (e.g., "Chatham Albatross" in English)
2. **Scientific names as fallback labels** (e.g., "Thalassarche eremita" in Spanish)

Wikidata uses the scientific name as the label in languages where no common name has been added yet.

---

## Impact on Our Analysis

### Previous (WRONG) Analysis

I previously reported:
- ❌ "Spanish has only 5.8% match with IOC - different translation conventions!"
- ❌ "Italian has only 3.3% match - regional variations!"
- ❌ "Keep both databases for alternative translations!"

### Actual Truth

- ✅ Spanish: IOC has 11,059 real translations, Wikidata has only **85** (0.7%!)
- ✅ Italian: IOC has 10,189 real translations, Wikidata has only **29** (0.3%!)
- ✅ Romanian: Wikidata has only **9 real translations** out of 495!

**Wikidata POC is NOT providing alternative translations - it's mostly garbage.**

---

## Corrected Recommendations

### ❌ DO NOT Use Wikidata for These Languages

**Terrible quality (<50% real translations):**
- Romanian (ro): 98% useless
- Italian (it): 94% useless
- Ukrainian (uk): 91% useless
- Vietnamese (vi): 88% useless
- Galician (gl): 88% useless
- Spanish (es): 83% useless
- Basque (eu): 82% useless
- Bulgarian (bg): 73% useless
- Russian (ru): 64% useless
- German (de): 53% useless
- Portuguese (pt): 52% useless

**IOC already has excellent coverage for all these languages - Wikidata adds NOTHING.**

### ✅ Only Use Wikidata for Unique Languages

**Good quality (>80% real translations):**
- English (en): 92% real ✓ (but IOC has this in species table)
- Dutch (nl): 93% real ✓ (but IOC has 11,250 vs 465)
- Polish (pl): 91% real ✓ (but IOC has 11,185 vs 452)
- Finnish (fi): 91% real ✓ (but IOC has 10,182 vs 448)

**Actually unique languages (not in IOC):**
- Norwegian Bokmål (nb): Need to check quality
- Norwegian Nynorsk (nn): Need to check quality
- Chinese Simplified (zh-hans): Need to check quality
- Chinese Traditional (zh-hant): Need to check quality
- Cantonese (yue): Need to check quality
- Bengali (bn), Gujarati (gu), Hindi (hi), Kannada (kn), Marathi (mr), Malay (ms), Punjabi (pa), Tamil (ta), Telugu (te), Tagalog (tl), Urdu (ur)

---

## Solution: Filter Out Scientific Name Fallbacks

### Update Wikidata Extraction

```python
def _query_multilingual_labels(self, species_data):
    """Query multilingual labels, excluding scientific name fallbacks."""

    # ... existing code ...

    for binding in results.get("results", {}).get("bindings", []):
        species_id = binding.get("species", {}).get("value", "").split("/")[-1]
        label = binding.get("label", {}).get("value", "")
        lang = binding.get("lang", {}).get("value", "")

        # Get scientific name for this species
        scientific_name = next(
            (sp["scientific_name"] for sp in species_data if sp["wikidata_id"] == species_id),
            None
        )

        # FILTER: Only add if label is NOT the scientific name
        if species_id and label and lang and label != scientific_name:
            translation_data.append({
                "wikidata_id": species_id,
                "language_code": lang,
                "common_name": label
            })
            language_counts[lang] += 1
```

### Re-run Analysis

After filtering, we expect:
- **Wikidata translations:** ~5,500 (down from 13,484)
- **Database size:** ~13-15 MB (down from 26 MB)
- **Languages with >100 translations:** ~15-20 (down from 57)

---

## Revised Database Strategy

### Option 1: Drop Wikidata Entirely (RECOMMENDED)

**Rationale:**
- IOC has 44 languages with excellent coverage
- Wikidata POC adds only ~10-15 truly unique languages
- Most Wikidata data is garbage (scientific name fallbacks)
- Not worth 13-15 MB for 10-15 languages with low coverage

**Result:**
- Keep: IOC (51 MB, 44 languages, 297K translations)
- Drop: Wikidata (useless)
- Total: 51 MB

### Option 2: Keep Only High-Quality Wikidata Languages

**Filter to languages with:**
- >80% real translations
- Not already in IOC with better coverage

**Likely candidates:**
- Norwegian Bokmål (nb)
- Norwegian Nynorsk (nn)
- Chinese variants (zh-hans, zh-hant, yue)
- Indic languages (bn, gu, hi, kn, mr, pa, ta, te)
- Malay (ms), Tagalog (tl), Urdu (ur)

**Result:**
- Wikidata: ~2,000-3,000 real translations (~10-15 languages)
- Size: ~5-8 MB
- Total: 51 MB (IOC) + 5-8 MB (Wikidata) = 56-59 MB

---

## Action Items

1. ✅ Identify data quality issue
2. ⏳ Update extraction to filter scientific name fallbacks
3. ⏳ Re-run POC with 100 species to verify fix
4. ⏳ Re-run overlap analysis with cleaned data
5. ⏳ Decide: Drop Wikidata entirely OR keep only high-quality languages
6. ⏳ Update documentation with corrected recommendations

---

## Conclusion

**My previous analysis was wrong.** I thought Wikidata provided "alternative translations" but it's actually just **copying scientific names** when real translations don't exist.

**Corrected recommendation:**
- IOC is excellent (44 languages, 297K real translations)
- Wikidata POC is mostly garbage (59% scientific name fallbacks)
- **Drop Wikidata OR filter aggressively to only high-quality unique languages**

---

**Status:** 🚨 CRITICAL ISSUE - Requires re-analysis
**Impact:** Changes entire database strategy
**Next Step:** Filter scientific name fallbacks and re-evaluate
