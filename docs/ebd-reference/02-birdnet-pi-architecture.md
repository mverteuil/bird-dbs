# BirdNET-Pi Architecture

## Overview

BirdNET-Pi is a real-time acoustic bird monitoring system for single-board computers (Raspberry Pi, etc.). It continuously captures audio, analyzes it with BirdNET's TensorFlow Lite models, and stores detections in a database with a web UI for exploration.

**Repository**: https://github.com/mcguirepr89/BirdNET-Pi (rewrite in progress)

## System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Audio Capture Daemon                       │
│  (birdnetpi/daemons/audio_capture_daemon.py)                 │
│  - Captures from microphone (48kHz mono)                     │
│  - Writes to FIFO: birdnet_audio_analysis.fifo               │
└───────────────────────────┬──────────────────────────────────┘
                            │ Raw audio bytes
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                  Audio Analysis Daemon                        │
│  (birdnetpi/daemons/audio_analysis_daemon.py)                │
│  - Reads from FIFO                                           │
│  - Buffers 3-second chunks                                   │
│  - Calls BirdDetectionService                                │
└───────────────────────────┬──────────────────────────────────┘
                            │ Detections
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                  BirdDetectionService                         │
│  (birdnetpi/detections/birdnet.py)                           │
│  - Loads TFLite model                                        │
│  - Runs inference on audio chunks                            │
│  - Applies location/time filtering (metadata model)          │
│  - Returns species + confidence                              │
└───────────────────────────┬──────────────────────────────────┘
                            │ Species detections
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                    FastAPI Application                        │
│  (birdnetpi/web/)                                            │
│  - Receives detection events via HTTP POST                   │
│  - Stores in SQLite database                                 │
│  - Serves web UI                                             │
│  - Handles notifications                                     │
└──────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. BirdDetectionService (`detections/birdnet.py`)

**Purpose**: TensorFlow Lite inference for bird species identification

**Models**:
- `BirdNET_GLOBAL_6K_V2.4_Model_FP16.tflite` - Main detection model (6,000 species)
- `BirdNET_GLOBAL_6K_V2.4_MData_Model_FP16.tflite` - Metadata/location filter model

**Key Methods**:

```python
class BirdDetectionService:
    def __init__(self, config: BirdNETConfig):
        # Loads TFLite interpreter
        # Loads species labels from text file

    def get_analysis_results(
        audio_chunk: np.ndarray,
        latitude: float,
        longitude: float,
        week: int,           # Week 1-48
        sensitivity: float   # 0.5-1.5 typical
    ) -> list[tuple[str, float]]:
        """
        Returns: [(species_name, confidence), ...]

        species_name format: "Scientific_name_Common Name"
        e.g., "Larus occidentalis_Western Gull"
        """
```

**Current Location Filtering** (line 236-273):

```python
def get_filtered_species_list(
    latitude: float,
    longitude: float,
    week: int
) -> list[str]:
    """Uses metadata model to predict species occurrence.

    Returns species with occurrence probability > threshold.
    This is ML-generated, NOT based on real observations.
    """
    if self.config.model == "BirdNET_GLOBAL_6K_V2.4_Model_FP16":
        location_filter = self._predict_filter_raw(lat, lon, week)
        threshold = self.species_frequency_threshold or 0.03
        filtered = np.where(location_filter >= threshold, location_filter, 0)
        return [species for species, prob in zip(self.classes, filtered) if prob > 0]
```

**🎯 This is where we integrate eBird filtering!**

### 2. Species Parser (`species/parser.py`)

**Purpose**: Parse BirdNET tensor output into structured components

**Tensor Format**: `"Scientific_name_Common Name"`
**Example**: `"Setophaga petechia_Yellow Warbler"`

```python
class SpeciesParser:
    @staticmethod
    async def parse_tensor_species(tensor_output: str) -> SpeciesComponents:
        """Splits on underscore, validates format.

        Returns:
            SpeciesComponents(
                scientific_name="Setophaga petechia",
                common_name="Yellow Warbler",
                full_species="Yellow Warbler (Setophaga petechia)"
            )
        """
```

**Taxonomy Handling**:
- BirdNET uses its own taxonomy (may differ from eBird/IOC)
- Scientific name is the crosswalk key
- Currently uses BirdNET common names as source of truth
- Has IOC database integration for multilingual names

### 3. Species Database Service (`database/species.py`)

**Purpose**: Multilingual bird name lookups

**Databases** (SQLite, attached via ATTACH DATABASE):
1. **IOC World Bird List** - Authoritative taxonomy
2. **PatLevin BirdNET labels** - BirdNET-specific translations
3. **Avibase** - Extensive multilingual coverage

**Priority**: IOC → PatLevin → Avibase

```python
class SpeciesDatabaseService:
    async def get_best_common_name(
        session: AsyncSession,
        scientific_name: str,
        language_code: str = "en"
    ) -> dict[str, Any]:
        """Lookup common name by scientific name.

        Returns: {"common_name": str, "source": str}
        """
```

### 4. Configuration (`config/models.py`)

**Relevant settings for eBird integration**:

```python
class BirdNETConfig(BaseModel):
    # Location
    latitude: float = 0.0
    longitude: float = 0.0

    # Model settings
    model: str = "BirdNET_GLOBAL_6K_V2.4_Model_FP16"
    metadata_model: str = "BirdNET_GLOBAL_6K_V2.4_MData_Model_FP16"
    species_confidence_threshold: float = 0.03  # Min confidence
    sensitivity_setting: float = 1.25
    privacy_threshold: float = 10.0  # % for human detection cutoff

    # Notification filters (already supports taxonomic filtering!)
    notification_rules: list[dict] = []
    # Each rule has:
    #   - include_taxa: {"orders": [], "families": [], "genera": [], "species": []}
    #   - exclude_taxa: {"orders": [], "families": [], "genera": [], "species": []}
```

**Notification system already has species filtering!** We can learn from this.

## Audio Processing Flow

### Buffer Management (3-second windows)

```python
# audio/analysis.py:167
async def process_audio_chunk(audio_data_bytes: bytes):
    """Accumulates audio until 3 seconds, then analyzes."""

    audio_data = np.frombuffer(audio_data_bytes, dtype=np.int16)
    self.audio_buffer = np.concatenate([self.audio_buffer, audio_data])

    if len(self.audio_buffer) >= self.buffer_size_samples:  # 144000 samples
        analysis_chunk = self.audio_buffer[:self.buffer_size_samples]

        # Overlap handling (default 0.5 seconds)
        overlap_samples = int(self.config.analysis_overlap * 48000)
        self.audio_buffer = self.audio_buffer[self.buffer_size_samples - overlap_samples:]

        # Normalize and analyze
        audio_float = analysis_chunk.astype(np.float32) / 32768.0
        await self._analyze_audio_chunk(audio_float)
```

### Analysis Pipeline

```python
# audio/analysis.py:213
async def _analyze_audio_chunk(audio_chunk: np.ndarray):
    # Get current week (1-53, but BirdNET uses 1-48)
    current_week = datetime.datetime.now(UTC).isocalendar()[1]

    # BirdNET analysis
    results = self.analysis_client.get_analysis_results(
        audio_chunk=audio_chunk,
        latitude=self.config.latitude,
        longitude=self.config.longitude,
        week=current_week,
        sensitivity=self.config.sensitivity_setting
    )

    # Filter by confidence threshold
    for species_tensor, confidence in results:
        if confidence >= self.config.species_confidence_threshold:
            # Parse species name
            species_components = await SpeciesParser.parse_tensor_species(species_tensor)

            # Send detection event
            await self._send_detection_event(species_components, confidence, audio_bytes)
```

## Detection Storage

**Database**: SQLite (via SQLAlchemy async)

**Key tables** (inferred from code):
- `detections` - Individual bird detections
- `species` - Species metadata
- Likely has timestamps, audio file paths, confidence scores

**Detection endpoint**: `http://127.0.0.1:8888/api/detections/` (configurable)

## Integration Points for eBird Region Packs

### Option 1: Replace Metadata Model Filter (Recommended)

**Location**: `birdnetpi/detections/birdnet.py:236`

```python
def get_filtered_species_list(self, lat, lon, week):
    # BEFORE: Use TensorFlow metadata model
    # AFTER: Load eBird region pack, return species list

    if self.ebird_filter:
        return self.ebird_filter.get_species_for_week(week)
    else:
        # Fallback to metadata model
        return self._use_metadata_model(lat, lon, week)
```

### Option 2: Post-Filter Detections

**Location**: `birdnetpi/detections/birdnet.py:404`

```python
def get_analysis_results(self, audio_chunk, lat, lon, week, sensitivity):
    raw_predictions = self.get_raw_prediction(...)

    # Apply eBird filter
    if self.ebird_filter:
        filtered = [
            (species, conf)
            for species, conf in raw_predictions
            if self.ebird_filter.is_species_expected(species, week)
        ]
        return filtered

    return raw_predictions
```

### Option 3: Confidence Boosting

**Location**: `birdnetpi/detections/birdnet.py:447`

```python
filtered_results = []
for species, confidence in raw_predictions:
    if confidence >= threshold:
        # Boost confidence for frequently-observed species
        if self.ebird_filter:
            boost = self.ebird_filter.get_confidence_boost(species, week)
            confidence = min(1.0, confidence * boost)

        filtered_results.append((species, confidence))
```

## Configuration Extension Proposal

**Add to `config/models.py`**:

```python
class BirdNETConfig(BaseModel):
    # ... existing fields ...

    # eBird Region Pack Settings
    enable_ebird_filtering: bool = False
    ebird_region_pack: str = ""  # Path to region pack JSON
    ebird_filter_mode: str = "supplement"  # "supplement", "replace", "strict"
    ebird_min_frequency: float = 0.01  # Minimum yearly frequency threshold
    ebird_seasonal_filtering: bool = True  # Use monthly frequency data
    ebird_confidence_boost: bool = True  # Boost confidence for common species
    ebird_boost_multiplier: float = 1.2  # Max boost (1.0-2.0)
```

**Filter modes**:
- `supplement`: Add eBird data to metadata model (union)
- `replace`: Use eBird data instead of metadata model
- `strict`: Only allow species in eBird pack (may miss rare vagrants)

## Deployment Considerations

### Python Environment
- Python 3.10+
- FastAPI, SQLAlchemy async
- TensorFlow Lite (custom builds for ARM)
- Already has JSON loading infrastructure

### File Locations (PathResolver)
```python
# src/birdnetpi/system/path_resolver.py
models_dir/          # TFLite models
  ├── BirdNET_*.tflite
  └── labels_*.txt

databases/           # SQLite databases
  ├── ioc.db
  ├── avibase.db
  └── patlevin.db

config/              # Configuration
  └── birdnet.yaml

# Proposed:
region_packs/        # eBird region packs
  ├── us-ca.json.gz
  ├── us-ny.json.gz
  └── custom-sf-bay.json.gz
```

### Performance Requirements
- Real-time processing (3-second chunks, ~0.3 analyses/sec)
- Low memory footprint (runs on Pi 3B+)
- Fast startup (< 10 seconds)
- Region pack load: must be < 100ms

### Resource Constraints
- **CPU**: ARM Cortex-A72 (Pi 4) or similar
- **RAM**: 1-4GB typical
- **Storage**: SD card (minimize writes)
- **Network**: Optional (offline operation supported)

## Testing Strategy

### Unit Tests
- Mock BirdDetectionService with eBird filter
- Test species filtering logic
- Verify confidence boosting calculations

### Integration Tests
- Load real region pack
- Run sample audio through pipeline
- Compare detections with/without eBird filter

### Validation Metrics
- **False positive rate**: Detections of species not in region
- **False negative rate**: Missed detections of expected species
- **Confidence distribution**: Should shift higher for common species
- **Processing latency**: Must stay < 3 seconds per chunk

## Related Files to Study

```
birdnetpi/
├── audio/
│   └── analysis.py              # Main analysis orchestration
├── config/
│   └── models.py                # Configuration schema
├── daemons/
│   └── audio_analysis_daemon.py # Daemon startup
├── database/
│   ├── species.py               # Multilingual species lookup
│   └── ioc.py                   # IOC database schema
├── detections/
│   ├── birdnet.py               # 🎯 BirdNET inference (main integration point)
│   └── constants.py             # Model mappings, non-bird labels
├── species/
│   └── parser.py                # Species name parsing
└── system/
    └── path_resolver.py         # File path management
```

## Key Takeaways

1. **Modular architecture** makes eBird integration clean
2. **Already has taxonomic filtering** in notification system
3. **Scientific name is the crosswalk** between BirdNET and eBird
4. **Week-based temporal filtering** (1-48) maps to monthly patterns
5. **Performance-critical** - must not slow down real-time processing
6. **Python JSON loading** is well-supported and fast enough
