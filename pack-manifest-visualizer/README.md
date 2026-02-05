# Pack Manifest Visualizer

A static site generator that creates an interactive map visualization of H3 hexagon pack manifests.

## Features

### Core Visualization
- **Interactive World Map**: Pan and zoom to explore H3 hexagons globally
- **Region Selection**: Browse and select from all regions in the manifest
- **Multi-Resolution Layers**: Toggle different H3 resolution layers on/off
- **Statistics Panel**: View counts for regions, hexagons, resolutions, and boundary cells
- **Standalone HTML**: Generates a single HTML file that works offline

### User Interface
- **Dark/Light Theme**: Toggle between themes with system preference detection
- **Search & Filter**: Debounced search to quickly find regions by name
- **Card-Based Layout**: Modern region cards with size and pack count badges
- **Toast Notifications**: Animated feedback for user actions
- **Responsive Design**: Mobile-friendly layout with adaptive breakpoints

### Accessibility
- **Keyboard Navigation**: Ctrl+F for search, Ctrl+D for theme, arrow keys for region list
- **ARIA Labels**: Screen reader support throughout the interface
- **Focus Management**: Visible focus indicators and logical tab order
- **Reduced Motion**: Respects `prefers-reduced-motion` system preference

### Export
- **GeoJSON Export**: Download region boundaries as GeoJSON for use in GIS tools

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
   - Theme system with CSS custom properties

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+F` | Focus search input |
| `Ctrl+D` | Toggle dark/light theme |
| `Arrow Up/Down` | Navigate region list |
| `Enter` | Select focused region |
| `Escape` | Clear search |

## Manifest Schema Support

The visualizer is resilient to schema changes and looks for these optional fields:

### Region Level
- `region_id`: Region identifier (fallback: "unknown")
- `h3_cells[]`: Array of H3 cell indices
- `center.lat`, `center.lon`: Region center coordinates
- `packs[]`: Array of pack objects
- `size_mb`: Region size in megabytes
- `pack_count`: Number of packs in region

### Pack Level
- `boundary_cell`: H3 cell index
- `boundary_resolution`: H3 resolution number
- `data_resolution`: H3 resolution number

If fields are missing, they're safely ignored.

## Technologies

- TypeScript
- Leaflet.js (OpenStreetMap / CARTO tiles)
- h3-js (Uber's H3 library)
- CSS Custom Properties (design tokens)
- Node.js

## License

MIT
