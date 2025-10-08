# Test Fixtures for IOC Builder

This directory contains sample data files for testing the IOC database builder.

## Files

### `sample_avilistr.csv`
Sample Avilistr data with Avibase ID mappings for 3 species.

**Format:**
- `scientific_name`: Scientific name of the species
- `avibase_id`: Unique Avibase identifier
- `ioc_scientific_name`: Scientific name in IOC taxonomy
- `clements_scientific_name`: Scientific name in Clements taxonomy
- `english_name`: English common name

## Creating Test IOC Files

For testing with actual IOC Excel files, you'll need to download them manually from:
https://www.worldbirdnames.org/

**Required files:**
- IOC_Names_File_Plus-XX.X.xlsx
- IOC_Multiling_Names_File-XX.X.xlsx

**Note:** These files are NOT included in the repository due to licensing.
Place them in this directory when running integration tests.

## Usage

```python
import pandas as pd
from pathlib import Path

test_data_dir = Path(__file__).parent / "fixtures"
avilistr_df = pd.read_csv(test_data_dir / "sample_avilistr.csv")
```
