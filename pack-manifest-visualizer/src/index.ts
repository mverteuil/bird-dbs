#!/usr/bin/env node

import { readFileSync, writeFileSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { cellToBoundary } from 'h3-js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

interface PackManifest {
  regions?: Array<{
    region_id?: string;
    h3_cells?: string[];
    packs?: Array<{
      boundary_cell?: string;
      boundary_resolution?: number;
      data_resolution?: number;
      pack_id?: string;
    }>;
    center?: {
      lat?: number;
      lon?: number;
    };
  }>;
}

function generateHtml(manifestPath: string): string {
  const manifest: PackManifest = JSON.parse(readFileSync(manifestPath, 'utf-8'));

  // Extract regions with resilient schema handling
  const regions = (manifest.regions || []).map(region => {
    const cells = region.h3_cells || [];
    const packs = region.packs || [];

    // Group by resolution
    const resolutionLayers = new Map<number, Set<string>>();

    cells.forEach(cell => {
      const resolution = cell.length === 15 ? parseInt(cell[1], 16) : 0;
      if (!resolutionLayers.has(resolution)) {
        resolutionLayers.set(resolution, new Set());
      }
      resolutionLayers.get(resolution)!.add(cell);
    });

    packs.forEach(pack => {
      if (pack.boundary_cell && pack.boundary_resolution !== undefined) {
        if (!resolutionLayers.has(pack.boundary_resolution)) {
          resolutionLayers.set(pack.boundary_resolution, new Set());
        }
        resolutionLayers.get(pack.boundary_resolution)!.add(pack.boundary_cell);
      }
      // Note: data_resolution cells are not included in manifest, only boundary cells
    });

    return {
      id: region.region_id || 'unknown',
      center: region.center || { lat: 0, lon: 0 },
      resolutions: Array.from(resolutionLayers.entries()).map(([res, cells]) => ({
        resolution: res,
        cells: Array.from(cells)
      }))
    };
  });

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pack Manifest Visualizer</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex;
      height: 100vh;
      overflow: hidden;
    }

    #sidebar {
      width: 300px;
      background: #f5f5f5;
      border-right: 1px solid #ddd;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    #map {
      flex: 1;
      height: 100vh;
    }

    .sidebar-header {
      padding: 20px;
      background: #fff;
      border-bottom: 1px solid #ddd;
    }

    .sidebar-header h1 {
      font-size: 18px;
      color: #333;
      margin-bottom: 5px;
    }

    .sidebar-header p {
      font-size: 12px;
      color: #666;
    }

    .region-list {
      flex: 1;
      overflow-y: auto;
      padding: 10px;
    }

    .region-item {
      background: white;
      border: 1px solid #ddd;
      border-radius: 4px;
      padding: 12px;
      margin-bottom: 8px;
      cursor: pointer;
      transition: all 0.2s;
    }

    .region-item:hover {
      border-color: #4a90e2;
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }

    .region-item.active {
      background: #e3f2fd;
      border-color: #4a90e2;
    }

    .region-name {
      font-weight: 600;
      color: #333;
      margin-bottom: 4px;
    }

    .region-stats {
      font-size: 11px;
      color: #666;
    }

    .resolution-controls {
      padding: 15px;
      background: white;
      border-top: 1px solid #ddd;
    }

    .resolution-controls h3 {
      font-size: 13px;
      color: #333;
      margin-bottom: 10px;
    }

    .resolution-item {
      display: flex;
      align-items: center;
      margin-bottom: 8px;
      padding: 6px;
      background: #f9f9f9;
      border-radius: 3px;
    }

    .resolution-item input[type="checkbox"] {
      margin-right: 8px;
    }

    .resolution-item label {
      flex: 1;
      font-size: 12px;
      color: #333;
      cursor: pointer;
    }

    .resolution-color {
      width: 20px;
      height: 20px;
      border-radius: 3px;
      margin-left: 8px;
      border: 1px solid rgba(0,0,0,0.2);
    }

    .leaflet-container {
      background: #a5bfdd;
    }

    .no-selection {
      padding: 20px;
      text-align: center;
      color: #999;
      font-size: 13px;
    }
  </style>
</head>
<body>
  <div id="sidebar">
    <div class="sidebar-header">
      <h1>Pack Manifest Visualizer</h1>
      <p>${regions.length} regions</p>
    </div>
    <div class="region-list" id="regionList"></div>
    <div class="resolution-controls" id="resolutionControls">
      <div class="no-selection">Select a region to view H3 layers</div>
    </div>
  </div>
  <div id="map"></div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/h3-js@4.1.0/dist/h3-js.umd.js"></script>
  <script>
    const REGIONS = ${JSON.stringify(regions, null, 2)};

    const RESOLUTION_COLORS = {
      0: '#e74c3c',
      1: '#e67e22',
      2: '#f39c12',
      3: '#f1c40f',
      4: '#2ecc71',
      5: '#1abc9c',
      6: '#3498db',
      7: '#9b59b6',
      8: '#e91e63',
      9: '#ff5722',
      10: '#795548',
      11: '#607d8b',
      12: '#9e9e9e',
      13: '#ff9800',
      14: '#00bcd4',
      15: '#4caf50'
    };

    // Initialize map
    const map = L.map('map').setView([20, 0], 2);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 18
    }).addTo(map);

    let currentLayers = [];
    let selectedRegion = null;

    // Render region list
    const regionList = document.getElementById('regionList');
    REGIONS.forEach((region, index) => {
      const item = document.createElement('div');
      item.className = 'region-item';
      item.innerHTML = \`
        <div class="region-name">\${region.id}</div>
        <div class="region-stats">
          \${region.resolutions.length} resolution layer(s) •
          \${region.resolutions.reduce((sum, r) => sum + r.cells.length, 0)} hexagons
        </div>
      \`;
      item.onclick = () => selectRegion(region, item);
      regionList.appendChild(item);
    });

    function selectRegion(region, element) {
      // Update UI
      document.querySelectorAll('.region-item').forEach(el => el.classList.remove('active'));
      element.classList.add('active');
      selectedRegion = region;

      // Clear existing layers
      currentLayers.forEach(layer => map.removeLayer(layer));
      currentLayers = [];

      // Zoom to region center
      map.setView([region.center.lat, region.center.lon], 5);

      // Render resolution controls
      renderResolutionControls(region);
    }

    function renderResolutionControls(region) {
      const controls = document.getElementById('resolutionControls');
      controls.innerHTML = '<h3>H3 Resolution Layers</h3>';

      region.resolutions.sort((a, b) => a.resolution - b.resolution).forEach(resLayer => {
        const color = RESOLUTION_COLORS[resLayer.resolution] || '#999';
        const item = document.createElement('div');
        item.className = 'resolution-item';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.id = \`res-\${resLayer.resolution}\`;
        checkbox.checked = true;
        checkbox.onchange = () => toggleResolution(resLayer, checkbox.checked);

        const label = document.createElement('label');
        label.htmlFor = \`res-\${resLayer.resolution}\`;
        label.textContent = \`Resolution \${resLayer.resolution} (\${resLayer.cells.length} hexagons)\`;

        const colorBox = document.createElement('div');
        colorBox.className = 'resolution-color';
        colorBox.style.backgroundColor = color;

        item.appendChild(checkbox);
        item.appendChild(label);
        item.appendChild(colorBox);
        controls.appendChild(item);

        // Initially show all layers
        showResolution(resLayer);
      });
    }

    function toggleResolution(resLayer, show) {
      if (show) {
        showResolution(resLayer);
      } else {
        hideResolution(resLayer);
      }
    }

    function showResolution(resLayer) {
      const color = RESOLUTION_COLORS[resLayer.resolution] || '#999';

      resLayer.cells.forEach(cell => {
        try {
          const boundary = h3.cellToBoundary(cell);

          // Check for antimeridian crossing
          const lons = boundary.map(coord => coord[1]);
          const lonRange = Math.max(...lons) - Math.min(...lons);

          // If longitude range > 180°, cell crosses antimeridian - skip rendering
          // These need special handling which we'll add later
          if (lonRange > 180) {
            console.warn(\`Cell \${cell} crosses antimeridian, skipping\`);
            return;
          }

          const polygon = L.polygon(
            boundary.map(coord => [coord[0], coord[1]]),
            {
              color: color,
              weight: 1,
              opacity: 0.8,
              fillColor: color,
              fillOpacity: 0.2
            }
          );

          polygon.bindPopup(\`
            <strong>H3 Cell</strong><br>
            Index: \${cell}<br>
            Resolution: \${resLayer.resolution}
          \`);

          polygon.addTo(map);
          polygon._resolutionId = resLayer.resolution;
          currentLayers.push(polygon);
        } catch (e) {
          console.warn(\`Failed to render cell \${cell}:\`, e);
        }
      });
    }

    function hideResolution(resLayer) {
      currentLayers = currentLayers.filter(layer => {
        if (layer._resolutionId === resLayer.resolution) {
          map.removeLayer(layer);
          return false;
        }
        return true;
      });
    }
  </script>
</body>
</html>`;
}

function main() {
  const args = process.argv.slice(2);

  if (args.length < 2) {
    console.error('Usage: pack-manifest-visualizer <manifest.json> <output-dir>');
    process.exit(1);
  }

  const [manifestPath, outputDir] = args;

  try {
    // Create output directory
    mkdirSync(outputDir, { recursive: true });

    // Generate HTML
    const html = generateHtml(manifestPath);

    // Write to output
    const outputPath = join(outputDir, 'index.html');
    writeFileSync(outputPath, html, 'utf-8');

    console.log(`✓ Generated visualization at: ${outputPath}`);
    console.log(`  Open in browser: file://${outputPath}`);
  } catch (error) {
    console.error('Error:', error instanceof Error ? error.message : error);
    process.exit(1);
  }
}

main();
