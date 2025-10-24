# Pack Manifest Visualizer

A static site generator that creates an interactive map visualization of H3 hexagon pack manifests.

## Features

- **Interactive World Map**: Pan and zoom to explore H3 hexagons globally
- **Region Selection**: Browse and select from all regions in the manifest
- **Multi-Resolution Layers**: Toggle different H3 resolution layers on/off
- **Resilient Schema**: Only looks for relevant fields, handles manifest changes gracefully
- **Standalone HTML**: Generates a single HTML file that works offline

## Installation

```bash
cd pack-manifest-visualizer
npm install
npm run build
```

## Usage

```bash
node dist/index.js <manifest.json> <output-dir>
```

### Example

```bash
node dist/index.js /path/to/pack_manifest.json ./output
```

This will generate `./output/index.html` which you can open in any browser.

## How It Works

1. **Reads Manifest**: Parses the pack manifest JSON file
2. **Extracts H3 Cells**: Groups cells by region and resolution
3. **Generates Static HTML**: Creates a single-file web application with:
   - Leaflet.js for interactive mapping
   - h3-js for H3 hexagon rendering
   - Region sidebar with search/filter
   - Resolution layer controls

## Manifest Schema Support

The visualizer is resilient to schema changes and looks for these optional fields:

### Region Level
- `region_id`: Region identifier (fallback: "unknown")
- `h3_cells[]`: Array of H3 cell indices
- `center.lat`, `center.lon`: Region center coordinates
- `packs[]`: Array of pack objects

### Pack Level
- `boundary_cell`: H3 cell index
- `boundary_resolution`: H3 resolution number
- `data_resolution`: H3 resolution number

If fields are missing, they're safely ignored.

## Technologies

- TypeScript
- Leaflet.js (OpenStreetMap)
- h3-js (Uber's H3 library)
- Node.js

## License

MIT
