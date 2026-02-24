#!/usr/bin/env node

import { readFileSync, writeFileSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { cellToBoundary, cellToChildren, cellToParent } from 'h3-js';

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
      total_checklists?: number;
    }>;
    center?: {
      lat?: number;
      lon?: number;
    };
    size_mb?: number;
    pack_count?: number;
  }>;
}

function generateHtml(manifestPath: string): string {
  const manifest: PackManifest = JSON.parse(readFileSync(manifestPath, 'utf-8'));

  // Extract regions with resilient schema handling
  // Show coverage at standard tiers: res 2 (regional), res 4 (metro), res 5 (hyperlocal)
  const TARGET_RESOLUTIONS = [2, 4, 5];

  // Pack info type for tracking membership
  interface PackInfo {
    packId: string;
    regionId: string;
    boundaryCell: string;
  }

  const regions = (manifest.regions || []).map(region => {
    const packs = region.packs || [];
    const regionId = region.region_id || 'unknown';

    // Track cells, checklist counts, and pack membership at each resolution
    const resolutionLayers = new Map<number, Map<string, number>>();
    const cellPacks = new Map<number, Map<string, PackInfo[]>>();
    TARGET_RESOLUTIONS.forEach(r => {
      resolutionLayers.set(r, new Map());
      cellPacks.set(r, new Map());
    });

    packs.forEach(pack => {
      const cell = pack.boundary_cell;
      const boundaryRes = pack.boundary_resolution;
      const checklists = pack.total_checklists || 0;
      const packInfo: PackInfo = {
        packId: pack.pack_id || cell || 'unknown',
        regionId,
        boundaryCell: cell || ''
      };

      if (cell && boundaryRes !== undefined) {
        TARGET_RESOLUTIONS.forEach(targetRes => {
          try {
            const layerMap = resolutionLayers.get(targetRes)!;
            const packsMap = cellPacks.get(targetRes)!;

            if (targetRes === boundaryRes) {
              // Exact match - use the cell directly
              layerMap.set(cell, (layerMap.get(cell) || 0) + checklists);
              if (!packsMap.has(cell)) packsMap.set(cell, []);
              packsMap.get(cell)!.push(packInfo);
            } else if (targetRes < boundaryRes) {
              // Target is coarser - get parent, aggregate checklists
              const parent = cellToParent(cell, targetRes);
              if (parent) {
                layerMap.set(parent, (layerMap.get(parent) || 0) + checklists);
                if (!packsMap.has(parent)) packsMap.set(parent, []);
                packsMap.get(parent)!.push(packInfo);
              }
            } else {
              // Target is finer - get children, distribute checklists equally
              const children = cellToChildren(cell, targetRes);
              const perChild = children.length > 0 ? Math.round(checklists / children.length) : 0;
              children.forEach(child => {
                layerMap.set(child, (layerMap.get(child) || 0) + perChild);
                if (!packsMap.has(child)) packsMap.set(child, []);
                packsMap.get(child)!.push(packInfo);
              });
            }
          } catch (e) {
            // Some conversions may fail for edge cases
          }
        });
      }
    });

    return {
      id: regionId,
      center: region.center || { lat: 0, lon: 0 },
      sizeMb: region.size_mb,
      packCount: region.pack_count || packs.length,
      resolutions: Array.from(resolutionLayers.entries())
        .map(([res, cellMap]) => ({
          resolution: res,
          cells: Array.from(cellMap.keys()),
          checklists: Object.fromEntries(cellMap),
          packs: Object.fromEntries(cellPacks.get(res)!)
        }))
        .filter(layer => layer.cells.length > 0)
        .sort((a, b) => a.resolution - b.resolution)
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
    /* ===== Design Tokens ===== */
    :root {
      /* Color Palette - Light Theme */
      --color-primary-50: #eff6ff;
      --color-primary-100: #dbeafe;
      --color-primary-200: #bfdbfe;
      --color-primary-300: #93c5fd;
      --color-primary-400: #60a5fa;
      --color-primary-500: #3b82f6;
      --color-primary-600: #2563eb;
      --color-primary-700: #1d4ed8;

      --color-neutral-50: #fafafa;
      --color-neutral-100: #f4f4f5;
      --color-neutral-200: #e4e4e7;
      --color-neutral-300: #d4d4d8;
      --color-neutral-400: #a1a1aa;
      --color-neutral-500: #71717a;
      --color-neutral-600: #52525b;
      --color-neutral-700: #3f3f46;
      --color-neutral-800: #27272a;
      --color-neutral-900: #18181b;

      --color-success-500: #22c55e;
      --color-warning-500: #f59e0b;
      --color-error-500: #ef4444;

      /* Semantic Colors */
      --bg-primary: var(--color-neutral-50);
      --bg-secondary: #ffffff;
      --bg-tertiary: var(--color-neutral-100);
      --text-primary: var(--color-neutral-900);
      --text-secondary: var(--color-neutral-600);
      --text-tertiary: var(--color-neutral-400);
      --border-default: var(--color-neutral-200);
      --border-hover: var(--color-primary-400);
      --accent: var(--color-primary-500);
      --accent-hover: var(--color-primary-600);

      /* Typography */
      --font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      --font-mono: 'SF Mono', Monaco, 'Cascadia Code', monospace;
      --text-xs: 0.75rem;
      --text-sm: 0.875rem;
      --text-base: 1rem;
      --text-lg: 1.125rem;
      --text-xl: 1.25rem;

      /* Spacing */
      --space-1: 0.25rem;
      --space-2: 0.5rem;
      --space-3: 0.75rem;
      --space-4: 1rem;
      --space-5: 1.25rem;
      --space-6: 1.5rem;
      --space-8: 2rem;

      /* Border Radius */
      --radius-sm: 0.25rem;
      --radius-md: 0.375rem;
      --radius-lg: 0.5rem;
      --radius-xl: 0.75rem;
      --radius-full: 9999px;

      /* Shadows */
      --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
      --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
      --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1);
      --shadow-focus: 0 0 0 3px var(--color-primary-200);

      /* Transitions */
      --transition-fast: 100ms ease-out;
      --transition-base: 150ms ease-out;
      --transition-smooth: 300ms cubic-bezier(0.4, 0, 0.2, 1);

      /* Layout */
      --sidebar-width: 340px;
    }

    /* Dark Theme */
    [data-theme="dark"] {
      --bg-primary: var(--color-neutral-900);
      --bg-secondary: var(--color-neutral-800);
      --bg-tertiary: var(--color-neutral-700);
      --text-primary: var(--color-neutral-50);
      --text-secondary: var(--color-neutral-400);
      --text-tertiary: var(--color-neutral-500);
      --border-default: var(--color-neutral-700);
      --border-hover: var(--color-primary-500);
      --shadow-focus: 0 0 0 3px var(--color-primary-700);
    }

    /* Reduced Motion */
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
      }
    }

    /* ===== Base Reset ===== */
    *, *::before, *::after {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      font-family: var(--font-family);
      background: var(--bg-primary);
      color: var(--text-primary);
    }

    /* ===== App Container ===== */
    .app-container {
      display: flex;
      height: 100vh;
      overflow: hidden;
    }

    /* ===== Sidebar ===== */
    .sidebar {
      width: var(--sidebar-width);
      background: var(--bg-secondary);
      border-right: 1px solid var(--border-default);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      transition: width var(--transition-smooth);
    }

    /* Sidebar Header */
    .sidebar-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--space-4);
      background: var(--bg-secondary);
      border-bottom: 1px solid var(--border-default);
    }

    .brand {
      display: flex;
      align-items: center;
      gap: var(--space-3);
    }

    .brand-icon {
      width: 32px;
      height: 32px;
      color: var(--accent);
      flex-shrink: 0;
    }

    .brand-text {
      display: flex;
      flex-direction: column;
    }

    .brand-title {
      font-size: var(--text-lg);
      font-weight: 700;
      color: var(--text-primary);
      line-height: 1.25;
    }

    .brand-subtitle {
      font-size: var(--text-xs);
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: var(--space-2);
    }

    /* Icon Buttons */
    .icon-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      border: none;
      border-radius: var(--radius-md);
      background: transparent;
      color: var(--text-secondary);
      cursor: pointer;
      transition: background var(--transition-fast), color var(--transition-fast), transform var(--transition-fast);
    }

    .icon-btn:hover {
      background: var(--bg-tertiary);
      color: var(--text-primary);
    }

    .icon-btn:focus-visible {
      outline: none;
      box-shadow: var(--shadow-focus);
    }

    .icon-btn:active {
      transform: scale(0.95);
    }

    .icon-btn svg {
      width: 20px;
      height: 20px;
    }

    /* Theme Toggle */
    #themeToggle .icon-moon { display: none; }
    [data-theme="dark"] #themeToggle .icon-sun { display: none; }
    [data-theme="dark"] #themeToggle .icon-moon { display: block; }

    /* ===== Statistics Panel ===== */
    .stats-panel {
      padding: var(--space-4);
      background: var(--bg-tertiary);
      border-bottom: 1px solid var(--border-default);
    }

    .stats-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: var(--space-3);
    }

    .stat-card {
      display: flex;
      flex-direction: column;
      padding: var(--space-3);
      background: var(--bg-secondary);
      border-radius: var(--radius-lg);
      border: 1px solid var(--border-default);
      transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
    }

    .stat-card:hover {
      border-color: var(--border-hover);
      box-shadow: var(--shadow-sm);
    }

    .stat-value {
      font-size: var(--text-xl);
      font-weight: 700;
      color: var(--text-primary);
      font-variant-numeric: tabular-nums;
      line-height: 1;
    }

    .stat-label {
      font-size: var(--text-xs);
      color: var(--text-secondary);
      margin-top: var(--space-1);
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }

    /* ===== Search ===== */
    .search-container {
      padding: var(--space-3) var(--space-4);
      border-bottom: 1px solid var(--border-default);
    }

    .search-input-wrapper {
      position: relative;
      display: flex;
      align-items: center;
    }

    .search-icon {
      position: absolute;
      left: var(--space-3);
      width: 16px;
      height: 16px;
      color: var(--text-tertiary);
      pointer-events: none;
    }

    .search-input {
      width: 100%;
      height: 40px;
      padding: var(--space-2) var(--space-4);
      padding-left: 40px;
      padding-right: 40px;
      font-size: var(--text-sm);
      font-family: var(--font-family);
      color: var(--text-primary);
      background: var(--bg-primary);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-lg);
      transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
    }

    .search-input::placeholder {
      color: var(--text-tertiary);
    }

    .search-input:hover {
      border-color: var(--border-hover);
    }

    .search-input:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: var(--shadow-focus);
    }

    .clear-search-btn {
      position: absolute;
      right: var(--space-2);
      display: flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      border: none;
      border-radius: var(--radius-full);
      background: var(--bg-tertiary);
      color: var(--text-secondary);
      cursor: pointer;
      transition: background var(--transition-fast), color var(--transition-fast);
    }

    .clear-search-btn:hover {
      background: var(--color-neutral-300);
      color: var(--text-primary);
    }

    .clear-search-btn[hidden] {
      display: none;
    }

    .search-meta {
      margin-top: var(--space-2);
      font-size: var(--text-xs);
      color: var(--text-tertiary);
      min-height: 1em;
    }

    /* ===== Region List ===== */
    .region-list-container {
      flex: 1;
      overflow-y: auto;
      overflow-x: hidden;
      scrollbar-width: thin;
      scrollbar-color: var(--color-neutral-300) transparent;
    }

    .region-list-container::-webkit-scrollbar {
      width: 8px;
    }

    .region-list-container::-webkit-scrollbar-track {
      background: transparent;
    }

    .region-list-container::-webkit-scrollbar-thumb {
      background: var(--color-neutral-300);
      border-radius: var(--radius-full);
    }

    .region-list {
      padding: var(--space-3);
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
    }

    /* Region Card */
    .region-card {
      display: flex;
      flex-direction: column;
      padding: var(--space-3) var(--space-4);
      background: var(--bg-primary);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-lg);
      cursor: pointer;
      transition: border-color var(--transition-fast), box-shadow var(--transition-fast), transform var(--transition-fast), background var(--transition-fast);
      user-select: none;
    }

    .region-card:hover {
      border-color: var(--border-hover);
      box-shadow: var(--shadow-md);
      transform: translateY(-1px);
    }

    .region-card:focus-visible {
      outline: none;
      box-shadow: var(--shadow-focus);
    }

    .region-card:active {
      transform: translateY(0);
    }

    .region-card.active {
      background: var(--color-primary-50);
      border-color: var(--accent);
      box-shadow: 0 0 0 1px var(--accent);
    }

    [data-theme="dark"] .region-card.active {
      background: color-mix(in srgb, var(--accent) 15%, var(--bg-secondary));
    }

    .region-card.show-all {
      background: linear-gradient(135deg, var(--color-primary-50), var(--bg-secondary));
      border-width: 2px;
      border-color: var(--accent);
    }

    [data-theme="dark"] .region-card.show-all {
      background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 20%, var(--bg-secondary)), var(--bg-secondary));
    }

    .region-card[hidden] {
      display: none;
    }

    .region-card-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--space-2);
    }

    .region-icon {
      width: 20px;
      height: 20px;
      color: var(--accent);
      flex-shrink: 0;
      margin-top: 2px;
    }

    .region-name {
      flex: 1;
      font-size: var(--text-sm);
      font-weight: 600;
      color: var(--text-primary);
      line-height: 1.25;
      word-break: break-word;
    }

    .region-badge {
      display: inline-flex;
      align-items: center;
      padding: var(--space-1) var(--space-2);
      font-size: 10px;
      font-weight: 500;
      color: var(--accent);
      background: var(--color-primary-100);
      border-radius: var(--radius-full);
      white-space: nowrap;
    }

    [data-theme="dark"] .region-badge {
      background: color-mix(in srgb, var(--accent) 20%, transparent);
    }

    .region-meta {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      margin-top: var(--space-2);
    }

    .region-stat {
      display: flex;
      align-items: center;
      gap: var(--space-1);
      font-size: var(--text-xs);
      color: var(--text-secondary);
    }

    .region-stat svg {
      width: 12px;
      height: 12px;
      color: var(--text-tertiary);
    }

    /* ===== Resolution Controls ===== */
    .resolution-controls {
      border-top: 1px solid var(--border-default);
      background: var(--bg-secondary);
      max-height: 280px;
      display: flex;
      flex-direction: column;
    }

    .controls-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--space-3) var(--space-4);
      border-bottom: 1px solid var(--border-default);
      background: var(--bg-tertiary);
    }

    .controls-title {
      font-size: var(--text-sm);
      font-weight: 600;
      color: var(--text-primary);
    }

    .controls-actions {
      display: flex;
      gap: var(--space-2);
    }

    .text-btn {
      padding: var(--space-1) var(--space-2);
      font-size: var(--text-xs);
      font-weight: 500;
      color: var(--accent);
      background: transparent;
      border: none;
      border-radius: var(--radius-sm);
      cursor: pointer;
      transition: background var(--transition-fast);
    }

    .text-btn:hover {
      background: var(--color-primary-50);
    }

    [data-theme="dark"] .text-btn:hover {
      background: color-mix(in srgb, var(--accent) 15%, transparent);
    }

    .text-btn:focus-visible {
      outline: none;
      box-shadow: var(--shadow-focus);
    }

    .layer-toggles {
      flex: 1;
      overflow-y: auto;
      padding: var(--space-2);
    }

    .no-selection {
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100%;
      min-height: 80px;
      font-size: var(--text-sm);
      color: var(--text-tertiary);
      text-align: center;
    }

    .layer-toggle {
      display: flex;
      align-items: center;
      gap: var(--space-3);
      padding: var(--space-2) var(--space-3);
      border-radius: var(--radius-md);
      transition: background var(--transition-fast);
    }

    .layer-toggle:hover {
      background: var(--bg-tertiary);
    }

    .layer-checkbox {
      position: relative;
      width: 18px;
      height: 18px;
      appearance: none;
      background: var(--bg-primary);
      border: 2px solid var(--border-default);
      border-radius: var(--radius-sm);
      cursor: pointer;
      transition: border-color var(--transition-fast), background var(--transition-fast);
    }

    .layer-checkbox:checked {
      background: var(--accent);
      border-color: var(--accent);
    }

    .layer-checkbox:checked::after {
      content: '';
      position: absolute;
      left: 5px;
      top: 2px;
      width: 4px;
      height: 8px;
      border: solid white;
      border-width: 0 2px 2px 0;
      transform: rotate(45deg);
    }

    .layer-checkbox:focus-visible {
      outline: none;
      box-shadow: var(--shadow-focus);
    }

    .layer-color {
      width: 24px;
      height: 24px;
      border-radius: var(--radius-md);
      border: 1px solid rgba(0, 0, 0, 0.1);
      flex-shrink: 0;
    }

    .layer-info {
      flex: 1;
      min-width: 0;
    }

    .layer-name {
      font-size: var(--text-sm);
      font-weight: 500;
      color: var(--text-primary);
    }

    .layer-count {
      font-size: var(--text-xs);
      color: var(--text-secondary);
      font-variant-numeric: tabular-nums;
    }

    /* ===== Export Actions ===== */
    .sidebar-footer {
      padding: var(--space-3) var(--space-4);
      border-top: 1px solid var(--border-default);
      background: var(--bg-tertiary);
    }

    .export-actions {
      display: flex;
      gap: var(--space-2);
    }

    .action-btn {
      flex: 1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: var(--space-2);
      padding: var(--space-2) var(--space-3);
      font-size: var(--text-sm);
      font-weight: 500;
      font-family: var(--font-family);
      color: var(--text-primary);
      background: var(--bg-secondary);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      cursor: pointer;
      transition: border-color var(--transition-fast), background var(--transition-fast), transform var(--transition-fast);
    }

    .action-btn:hover {
      border-color: var(--border-hover);
      background: var(--bg-primary);
    }

    .action-btn:focus-visible {
      outline: none;
      box-shadow: var(--shadow-focus);
    }

    .action-btn:active {
      transform: scale(0.98);
    }

    .action-btn svg {
      width: 16px;
      height: 16px;
      color: var(--text-secondary);
    }

    /* ===== Main Content ===== */
    .main-content {
      flex: 1;
      position: relative;
      display: flex;
      flex-direction: column;
    }

    .map-container {
      flex: 1;
    }

    .leaflet-container {
      background: #a5bfdd;
    }

    [data-theme="dark"] .leaflet-container {
      background: #1a1a2e;
    }

    /* Map Controls Overlay */
    .map-controls-overlay {
      position: absolute;
      top: var(--space-4);
      right: var(--space-4);
      z-index: 1000;
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
    }

    .zoom-display {
      padding: var(--space-2) var(--space-3);
      background: var(--bg-secondary);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      font-size: var(--text-xs);
      font-weight: 500;
      color: var(--text-secondary);
      box-shadow: var(--shadow-md);
    }

    .zoom-lock-btn {
      padding: var(--space-2) var(--space-3);
      background: var(--bg-secondary);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      font-size: var(--text-xs);
      font-weight: 500;
      color: var(--text-secondary);
      box-shadow: var(--shadow-md);
      cursor: pointer;
      transition: all 0.15s ease;
    }

    .zoom-lock-btn:hover {
      background: var(--bg-tertiary);
    }

    .zoom-lock-btn.locked {
      background: var(--color-primary-100);
      border-color: var(--color-primary-300);
      color: var(--color-primary-700);
    }

    /* Loading Overlay */
    .loading-overlay {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: var(--space-4);
      background: color-mix(in srgb, var(--bg-primary) 90%, transparent);
      backdrop-filter: blur(4px);
      z-index: 1001;
      transition: opacity var(--transition-smooth);
    }

    .loading-overlay[hidden] {
      display: none;
    }

    .loading-spinner {
      width: 48px;
      height: 48px;
      border: 3px solid var(--border-default);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
    }

    .loading-text {
      font-size: var(--text-sm);
      color: var(--text-secondary);
    }

    .loading-progress {
      width: 200px;
      height: 4px;
      background: var(--bg-tertiary);
      border-radius: var(--radius-full);
      overflow: hidden;
    }

    .progress-bar {
      height: 100%;
      background: var(--accent);
      border-radius: var(--radius-full);
      width: 0%;
      transition: width var(--transition-fast);
    }

    /* ===== Toast Notifications ===== */
    .toast-container {
      position: fixed;
      bottom: var(--space-6);
      right: var(--space-6);
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
      z-index: 2000;
      pointer-events: none;
    }

    .toast {
      display: flex;
      align-items: center;
      gap: var(--space-3);
      min-width: 280px;
      max-width: 400px;
      padding: var(--space-3) var(--space-4);
      background: var(--bg-secondary);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow-lg);
      pointer-events: auto;
      animation: toast-in 300ms cubic-bezier(0.34, 1.56, 0.64, 1);
    }

    .toast.dismissing {
      animation: toast-out 200ms ease-in forwards;
    }

    @keyframes toast-in {
      from { opacity: 0; transform: translateX(100%); }
      to { opacity: 1; transform: translateX(0); }
    }

    @keyframes toast-out {
      from { opacity: 1; transform: translateX(0); }
      to { opacity: 0; transform: translateX(100%); }
    }

    .toast-icon {
      width: 20px;
      height: 20px;
      flex-shrink: 0;
    }

    .toast-icon.success { color: var(--color-success-500); }
    .toast-icon.info { color: var(--accent); }

    .toast-content { flex: 1; }

    .toast-title {
      font-size: var(--text-sm);
      font-weight: 600;
      color: var(--text-primary);
    }

    .toast-message {
      font-size: var(--text-xs);
      color: var(--text-secondary);
      margin-top: var(--space-1);
    }

    .toast-dismiss {
      width: 24px;
      height: 24px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--text-tertiary);
      background: transparent;
      border: none;
      border-radius: var(--radius-sm);
      cursor: pointer;
      transition: color var(--transition-fast), background var(--transition-fast);
    }

    .toast-dismiss:hover {
      color: var(--text-primary);
      background: var(--bg-tertiary);
    }

    /* ===== Custom Popups ===== */
    .custom-popup .leaflet-popup-content-wrapper {
      background: var(--bg-secondary);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow-lg);
      padding: 0;
      overflow: hidden;
    }

    .custom-popup .leaflet-popup-content {
      margin: 0;
    }

    .custom-popup .leaflet-popup-tip {
      background: var(--bg-secondary);
    }

    .hex-popup {
      min-width: 200px;
    }

    .hex-popup-header {
      padding: var(--space-3);
      background: var(--bg-tertiary);
      border-bottom: 1px solid var(--border-default);
    }

    .hex-popup-res {
      display: inline-block;
      padding: var(--space-1) var(--space-2);
      font-size: var(--text-xs);
      font-weight: 600;
      color: white;
      border-radius: var(--radius-sm);
    }

    .hex-popup-body {
      padding: var(--space-3);
    }

    .hex-popup-row {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
      margin-bottom: var(--space-3);
    }

    .hex-popup-label {
      font-size: var(--text-xs);
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }

    .hex-popup-value {
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      color: var(--text-primary);
      background: var(--bg-tertiary);
      padding: var(--space-1) var(--space-2);
      border-radius: var(--radius-sm);
      word-break: break-all;
    }

    .hex-popup-copy {
      width: 100%;
      padding: var(--space-2);
      font-size: var(--text-xs);
      font-weight: 500;
      color: var(--accent);
      background: var(--color-primary-50);
      border: none;
      border-radius: var(--radius-md);
      cursor: pointer;
      transition: background var(--transition-fast);
    }

    .hex-popup-copy:hover {
      background: var(--color-primary-100);
    }

    /* ===== Screen Reader ===== */
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }

    /* ===== Responsive ===== */
    @media (max-width: 768px) {
      .app-container {
        flex-direction: column;
      }

      .sidebar {
        width: 100%;
        height: auto;
        max-height: 50vh;
        border-right: none;
        border-bottom: 1px solid var(--border-default);
      }

      .main-content {
        flex: 1;
        min-height: 50vh;
      }

      .stats-grid {
        grid-template-columns: repeat(4, 1fr);
      }

      .stat-card {
        padding: var(--space-2);
      }

      .stat-value {
        font-size: var(--text-base);
      }

      .toast-container {
        bottom: var(--space-4);
        right: var(--space-4);
        left: var(--space-4);
      }

      .toast {
        min-width: auto;
        max-width: none;
      }
    }

    @media (pointer: coarse) {
      .icon-btn {
        min-width: 44px;
        min-height: 44px;
      }

      .region-card {
        min-height: 60px;
      }

      .layer-toggle {
        min-height: 48px;
      }

      .action-btn {
        min-height: 44px;
      }
    }
  </style>
</head>
<body>
  <div id="app" class="app-container">
    <!-- Sidebar -->
    <aside class="sidebar" role="complementary" aria-label="Region navigation">
      <!-- Header -->
      <header class="sidebar-header">
        <div class="brand">
          <svg class="brand-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path d="M12 2l9 5v10l-9 5-9-5V7l9-5z"/>
          </svg>
          <div class="brand-text">
            <h1 class="brand-title">Pack Manifest</h1>
            <span class="brand-subtitle">Visualizer</span>
          </div>
        </div>
        <div class="header-actions">
          <button id="themeToggle" class="icon-btn" aria-label="Toggle dark mode" title="Toggle theme (Ctrl+D)">
            <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <circle cx="12" cy="12" r="5"/>
              <path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
            </svg>
            <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>
            </svg>
          </button>
        </div>
      </header>

      <!-- Statistics Panel -->
      <section class="stats-panel" aria-label="Coverage statistics">
        <div class="stats-grid">
          <div class="stat-card">
            <span class="stat-value" id="totalRegions">--</span>
            <span class="stat-label">Regions</span>
          </div>
          <div class="stat-card">
            <span class="stat-value" id="totalHexagons">--</span>
            <span class="stat-label">Hexagons</span>
          </div>
          <div class="stat-card">
            <span class="stat-value" id="totalResolutions">--</span>
            <span class="stat-label">Res. Levels</span>
          </div>
          <div class="stat-card">
            <span class="stat-value" id="coverageArea">--</span>
            <span class="stat-label">Boundary Cells</span>
          </div>
        </div>
      </section>

      <!-- Search -->
      <div class="search-container">
        <div class="search-input-wrapper">
          <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="11" cy="11" r="8"/>
            <path d="M21 21l-4.35-4.35"/>
          </svg>
          <input type="search" id="regionSearch" class="search-input" placeholder="Search regions... (Ctrl+F)" aria-label="Search regions" autocomplete="off">
          <button id="clearSearch" class="clear-search-btn" aria-label="Clear search" hidden>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>
        <div class="search-meta" id="searchMeta" aria-live="polite"></div>
      </div>

      <!-- Region List -->
      <div class="region-list-container">
        <nav id="regionList" class="region-list" role="listbox" aria-label="Region list" tabindex="0"></nav>
      </div>

      <!-- Resolution Controls -->
      <section class="resolution-controls" aria-label="Resolution layer controls">
        <div class="controls-header">
          <h2 class="controls-title">H3 Resolution Layers</h2>
          <div class="controls-actions">
            <button id="showAllLayers" class="text-btn" aria-label="Show all layers">All</button>
            <button id="hideAllLayers" class="text-btn" aria-label="Hide all layers">None</button>
          </div>
        </div>
        <div id="layerToggles" class="layer-toggles">
          <div class="no-selection" role="status">Select a region to view layers</div>
        </div>
      </section>

      <!-- Export Footer -->
      <footer class="sidebar-footer">
        <div class="export-actions">
          <button id="exportGeoJSON" class="action-btn" aria-label="Export as GeoJSON">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4m4-5l5 5 5-5m-5 5V3"/>
            </svg>
            <span>Export GeoJSON</span>
          </button>
        </div>
      </footer>
    </aside>

    <!-- Main Map Area -->
    <main class="main-content">
      <div id="map" class="map-container" role="application" aria-label="Interactive map"></div>

      <!-- Loading Overlay -->
      <div id="loadingOverlay" class="loading-overlay" role="status" aria-live="polite" hidden>
        <div class="loading-spinner"></div>
        <span class="loading-text">Loading hexagons...</span>
        <div class="loading-progress">
          <div class="progress-bar" id="loadingProgress"></div>
        </div>
      </div>

      <!-- Map Controls Overlay -->
      <div class="map-controls-overlay">
        <div class="zoom-display" id="zoomDisplay" aria-live="polite">Zoom: 2</div>
        <button id="zoomLockBtn" class="zoom-lock-btn" title="Lock zoom when switching regions">🔓 Unlocked</button>
      </div>
    </main>
  </div>

  <!-- Toast Container -->
  <div id="toastContainer" class="toast-container" role="alert" aria-live="assertive"></div>

  <!-- Screen Reader Announcer -->
  <div id="srAnnouncer" role="status" aria-live="polite" aria-atomic="true" class="sr-only"></div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/h3-js@4.1.0/dist/h3-js.umd.js"></script>
  <script>
    // ===== Data =====
    const REGIONS = ${JSON.stringify(regions, null, 2)};

    const RESOLUTION_COLORS = {
      0: { fill: '#dc2626', stroke: '#991b1b', label: 'Continental' },
      1: { fill: '#ea580c', stroke: '#c2410c', label: 'Sub-continental' },
      2: { fill: '#d97706', stroke: '#b45309', label: 'Country' },
      3: { fill: '#ca8a04', stroke: '#a16207', label: 'State' },
      4: { fill: '#65a30d', stroke: '#4d7c0f', label: 'Metro' },
      5: { fill: '#16a34a', stroke: '#15803d', label: 'City' },
      6: { fill: '#0d9488', stroke: '#0f766e', label: 'District' },
      7: { fill: '#0891b2', stroke: '#0e7490', label: 'Neighborhood' },
      8: { fill: '#2563eb', stroke: '#1d4ed8', label: 'Block' },
      9: { fill: '#7c3aed', stroke: '#6d28d9', label: 'Street' },
      10: { fill: '#c026d3', stroke: '#a21caf', label: 'Building' }
    };

    // ===== State =====
    let map;
    let currentTileLayer;
    let currentLayers = [];
    let selectedRegion = null;
    let allRegionsCombined = null;
    let zoomLocked = false;

    // ===== Toast System =====
    const Toast = {
      container: document.getElementById('toastContainer'),

      show(options) {
        const { type = 'info', title, message, duration = 4000 } = options;
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.setAttribute('role', 'alert');

        const icons = {
          success: '<path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>',
          info: '<path d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>'
        };

        const iconSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        iconSvg.setAttribute('class', 'toast-icon ' + type);
        iconSvg.setAttribute('viewBox', '0 0 24 24');
        iconSvg.setAttribute('fill', 'none');
        iconSvg.setAttribute('stroke', 'currentColor');
        iconSvg.setAttribute('stroke-width', '2');
        iconSvg.setAttribute('stroke-linecap', 'round');
        iconSvg.setAttribute('stroke-linejoin', 'round');
        const iconPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        iconPath.setAttribute('d', type === 'success' ? 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z' : 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z');
        iconSvg.appendChild(iconPath);
        toast.appendChild(iconSvg);

        const content = document.createElement('div');
        content.className = 'toast-content';
        const titleEl = document.createElement('div');
        titleEl.className = 'toast-title';
        titleEl.textContent = title;
        content.appendChild(titleEl);
        if (message) {
          const msgEl = document.createElement('div');
          msgEl.className = 'toast-message';
          msgEl.textContent = message;
          content.appendChild(msgEl);
        }
        toast.appendChild(content);

        const dismissBtn = document.createElement('button');
        dismissBtn.className = 'toast-dismiss';
        dismissBtn.setAttribute('aria-label', 'Dismiss');
        const dismissSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        dismissSvg.setAttribute('viewBox', '0 0 24 24');
        dismissSvg.setAttribute('width', '16');
        dismissSvg.setAttribute('height', '16');
        dismissSvg.setAttribute('fill', 'none');
        dismissSvg.setAttribute('stroke', 'currentColor');
        dismissSvg.setAttribute('stroke-width', '2');
        const dismissPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        dismissPath.setAttribute('d', 'M6 18L18 6M6 6l12 12');
        dismissSvg.appendChild(dismissPath);
        dismissBtn.appendChild(dismissSvg);
        toast.appendChild(dismissBtn);

        const dismiss = () => {
          toast.classList.add('dismissing');
          setTimeout(() => toast.remove(), 200);
        };

        dismissBtn.addEventListener('click', dismiss);
        this.container.appendChild(toast);

        if (duration > 0) setTimeout(dismiss, duration);
        return { dismiss };
      },

      success(title, message) { return this.show({ type: 'success', title, message }); },
      info(title, message) { return this.show({ type: 'info', title, message }); }
    };

    // ===== Theme Management =====
    const ThemeManager = {
      storageKey: 'pmv-theme',

      init() {
        const saved = localStorage.getItem(this.storageKey);
        const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        this.setTheme(saved || (systemDark ? 'dark' : 'light'));

        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
          if (!localStorage.getItem(this.storageKey)) {
            this.setTheme(e.matches ? 'dark' : 'light');
          }
        });

        document.getElementById('themeToggle').addEventListener('click', () => this.toggle());
      },

      setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        this.updateMapTheme(theme);
      },

      toggle() {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        this.setTheme(next);
        localStorage.setItem(this.storageKey, next);
        Toast.info((next === 'dark' ? 'Dark' : 'Light') + ' mode enabled');
      },

      updateMapTheme(theme) {
        if (!map || !currentTileLayer) return;

        const tileUrl = theme === 'dark'
          ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
          : 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
        const attr = theme === 'dark' ? '© CARTO' : '© OpenStreetMap';

        map.removeLayer(currentTileLayer);
        currentTileLayer = L.tileLayer(tileUrl, { attribution: attr, maxZoom: 18 }).addTo(map);
      }
    };

    // ===== Search Manager =====
    const SearchManager = {
      init() {
        const input = document.getElementById('regionSearch');
        const clearBtn = document.getElementById('clearSearch');
        const meta = document.getElementById('searchMeta');
        let debounce = null;

        input.addEventListener('input', () => {
          clearTimeout(debounce);
          debounce = setTimeout(() => this.search(input.value), 150);
        });

        clearBtn.addEventListener('click', () => {
          input.value = '';
          clearBtn.hidden = true;
          meta.textContent = '';
          this.showAll();
          input.focus();
        });
      },

      search(query) {
        const q = query.trim().toLowerCase();
        const clearBtn = document.getElementById('clearSearch');
        const meta = document.getElementById('searchMeta');

        clearBtn.hidden = !q;

        if (!q) {
          meta.textContent = '';
          this.showAll();
          return;
        }

        const cards = document.querySelectorAll('.region-card:not(.show-all)');
        let visible = 0;

        cards.forEach(card => {
          const id = card.dataset.regionId || '';
          const match = id.toLowerCase().includes(q);
          card.hidden = !match;
          if (match) visible++;
        });

        document.querySelector('.region-card.show-all').hidden = visible === 0;

        meta.textContent = visible === 0
          ? 'No regions found for "' + query + '"'
          : 'Showing ' + visible + ' of ' + REGIONS.length + ' regions';

        announce(visible + ' regions found');
      },

      showAll() {
        document.querySelectorAll('.region-card').forEach(c => c.hidden = false);
      }
    };

    // ===== Export Manager =====
    const ExportManager = {
      init() {
        document.getElementById('exportGeoJSON').addEventListener('click', () => this.exportGeoJSON());
      },

      exportGeoJSON() {
        if (!selectedRegion) {
          Toast.info('No region selected', 'Select a region to export');
          return;
        }

        const features = [];

        selectedRegion.resolutions.forEach(resLayer => {
          resLayer.cells.forEach(cell => {
            try {
              const boundary = h3.cellToBoundary(cell);
              features.push({
                type: 'Feature',
                properties: { h3_index: cell, resolution: resLayer.resolution, region_id: selectedRegion.id },
                geometry: { type: 'Polygon', coordinates: [boundary.map(c => [c[1], c[0]])] }
              });
            } catch (e) { console.warn('Export failed for cell:', cell); }
          });
        });

        const geojson = {
          type: 'FeatureCollection',
          properties: { region_id: selectedRegion.id, exported_at: new Date().toISOString() },
          features: features
        };

        const blob = new Blob([JSON.stringify(geojson, null, 2)], { type: 'application/json' });
        const link = document.createElement('a');
        link.download = selectedRegion.id.replace(/[^a-z0-9]/gi, '_') + '.geojson';
        link.href = URL.createObjectURL(blob);
        link.click();
        URL.revokeObjectURL(link.href);

        Toast.success('GeoJSON exported', features.length + ' features saved');
      }
    };

    // ===== Keyboard Navigation =====
    const KeyboardNav = {
      init() {
        const regionList = document.getElementById('regionList');
        const searchInput = document.getElementById('regionSearch');

        regionList.addEventListener('keydown', (e) => {
          const items = Array.from(regionList.querySelectorAll('.region-card:not([hidden])'));
          const idx = items.findIndex(i => i === document.activeElement);

          switch(e.key) {
            case 'ArrowDown':
              e.preventDefault();
              if (idx < items.length - 1) items[idx + 1].focus();
              break;
            case 'ArrowUp':
              e.preventDefault();
              if (idx > 0) items[idx - 1].focus();
              else searchInput.focus();
              break;
            case 'Enter':
            case ' ':
              e.preventDefault();
              if (document.activeElement.classList.contains('region-card')) {
                document.activeElement.click();
              }
              break;
          }
        });

        searchInput.addEventListener('keydown', (e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            const first = regionList.querySelector('.region-card:not([hidden])');
            if (first) first.focus();
          }
        });

        document.addEventListener('keydown', (e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
            e.preventDefault();
            searchInput.focus();
            searchInput.select();
          }
          if ((e.metaKey || e.ctrlKey) && e.key === 'd') {
            e.preventDefault();
            ThemeManager.toggle();
          }
          if (e.key === 'Escape') {
            if (searchInput.value) {
              document.getElementById('clearSearch').click();
            }
          }
        });
      }
    };

    // ===== Announce to Screen Reader =====
    function announce(message) {
      document.getElementById('srAnnouncer').textContent = message;
    }

    // ===== Copy to Clipboard =====
    function copyToClipboard(text) {
      navigator.clipboard.writeText(text).then(() => {
        Toast.success('Copied!', text);
      });
    }

    // ===== Initialize Map =====
    function initMap() {
      map = L.map('map', { zoomControl: true }).setView([20, 0], 2);

      const theme = document.documentElement.getAttribute('data-theme');
      const tileUrl = theme === 'dark'
        ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
        : 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
      const attr = theme === 'dark' ? '© CARTO' : '© OpenStreetMap';

      currentTileLayer = L.tileLayer(tileUrl, { attribution: attr, maxZoom: 18 }).addTo(map);

      map.on('zoomend', () => {
        document.getElementById('zoomDisplay').textContent = 'Zoom: ' + map.getZoom();
      });
    }

    // ===== Render Statistics =====
    function renderStats() {
      const totalHex = REGIONS.reduce((sum, r) =>
        sum + r.resolutions.reduce((s, res) => s + res.cells.length, 0), 0);

      const uniqueRes = new Set();
      REGIONS.forEach(r => r.resolutions.forEach(res => uniqueRes.add(res.resolution)));

      const boundaryCells = REGIONS.reduce((sum, r) => {
        const res4 = r.resolutions.find(res => res.resolution === 4);
        return sum + (res4 ? res4.cells.length : 0);
      }, 0);

      document.getElementById('totalRegions').textContent = REGIONS.length.toLocaleString();
      document.getElementById('totalHexagons').textContent = totalHex.toLocaleString();
      document.getElementById('totalResolutions').textContent = uniqueRes.size;
      document.getElementById('coverageArea').textContent = boundaryCells.toLocaleString();
    }

    // ===== Create Combined Region =====
    function createCombinedRegion() {
      const combined = new Map();
      const combinedChecklists = new Map();
      const combinedPacks = new Map();
      REGIONS.forEach(region => {
        region.resolutions.forEach(resLayer => {
          if (!combined.has(resLayer.resolution)) {
            combined.set(resLayer.resolution, new Set());
            combinedChecklists.set(resLayer.resolution, {});
            combinedPacks.set(resLayer.resolution, {});
          }
          resLayer.cells.forEach(cell => {
            combined.get(resLayer.resolution).add(cell);
            // Aggregate checklists
            const checklists = combinedChecklists.get(resLayer.resolution);
            const count = resLayer.checklists && resLayer.checklists[cell] ? resLayer.checklists[cell] : 0;
            checklists[cell] = (checklists[cell] || 0) + count;
            // Aggregate packs
            const packs = combinedPacks.get(resLayer.resolution);
            const cellPacks = resLayer.packs && resLayer.packs[cell] ? resLayer.packs[cell] : [];
            if (!packs[cell]) packs[cell] = [];
            packs[cell] = packs[cell].concat(cellPacks);
          });
        });
      });

      return {
        id: 'ALL REGIONS',
        center: { lat: 20, lon: 0 },
        resolutions: Array.from(combined.entries()).map(function(entry) {
          return {
            resolution: entry[0],
            cells: Array.from(entry[1]),
            checklists: combinedChecklists.get(entry[0]),
            packs: combinedPacks.get(entry[0])
          };
        })
      };
    }

    // ===== Render Region List =====
    function renderRegionList() {
      const regionList = document.getElementById('regionList');
      allRegionsCombined = createCombinedRegion();

      const totalHex = REGIONS.reduce((sum, r) =>
        sum + r.resolutions.reduce((s, res) => s + res.cells.length, 0), 0);

      // Show All card
      const showAllCard = createRegionCard(allRegionsCombined, true, REGIONS.length, totalHex);
      regionList.appendChild(showAllCard);

      // Separator
      const sep = document.createElement('div');
      sep.style.cssText = 'border-top: 2px solid var(--border-default); margin: var(--space-2) 0;';
      regionList.appendChild(sep);

      // Individual regions
      REGIONS.forEach(region => {
        const card = createRegionCard(region, false);
        regionList.appendChild(card);
      });
    }

    function createRegionCard(region, isShowAll, regionCount, hexCount) {
      const card = document.createElement('div');
      card.className = 'region-card' + (isShowAll ? ' show-all' : '');
      card.setAttribute('role', 'option');
      card.setAttribute('aria-selected', 'false');
      card.setAttribute('tabindex', '0');
      card.dataset.regionId = region.id;

      const hexagons = region.resolutions.reduce((sum, r) => sum + r.cells.length, 0);
      const layers = region.resolutions.length;

      // Build card content using DOM methods for security
      const header = document.createElement('div');
      header.className = 'region-card-header';

      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      icon.setAttribute('class', 'region-icon');
      icon.setAttribute('viewBox', '0 0 24 24');
      icon.setAttribute('fill', 'none');
      icon.setAttribute('stroke', 'currentColor');
      icon.setAttribute('stroke-width', '2');
      icon.setAttribute('aria-hidden', 'true');
      const iconPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      if (isShowAll) {
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', '12');
        circle.setAttribute('cy', '12');
        circle.setAttribute('r', '10');
        icon.appendChild(circle);
        iconPath.setAttribute('d', 'M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z');
      } else {
        iconPath.setAttribute('d', 'M12 2l9 5v10l-9 5-9-5V7l9-5z');
      }
      icon.appendChild(iconPath);
      header.appendChild(icon);

      const nameSpan = document.createElement('span');
      nameSpan.className = 'region-name';
      nameSpan.textContent = isShowAll ? '🌍 SHOW ALL COVERAGE' : region.id;
      header.appendChild(nameSpan);

      if (layers > 0) {
        const badge = document.createElement('span');
        badge.className = 'region-badge';
        badge.textContent = layers + ' layers';
        header.appendChild(badge);
      }

      card.appendChild(header);

      const meta = document.createElement('div');
      meta.className = 'region-meta';

      const stat = document.createElement('span');
      stat.className = 'region-stat';
      const statIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      statIcon.setAttribute('viewBox', '0 0 24 24');
      statIcon.setAttribute('fill', 'none');
      statIcon.setAttribute('stroke', 'currentColor');
      statIcon.setAttribute('stroke-width', '2');
      statIcon.setAttribute('aria-hidden', 'true');
      const statIconPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      statIconPath.setAttribute('d', 'M12 2l9 5v10l-9 5-9-5V7l9-5z');
      statIcon.appendChild(statIconPath);
      stat.appendChild(statIcon);
      const statText = document.createTextNode((isShowAll ? hexCount : hexagons).toLocaleString() + ' hexagons');
      stat.appendChild(statText);
      meta.appendChild(stat);

      if (isShowAll) {
        const regionStat = document.createElement('span');
        regionStat.className = 'region-stat';
        regionStat.textContent = regionCount + ' regions';
        meta.appendChild(regionStat);
      }

      card.appendChild(meta);
      card.onclick = () => selectRegion(region, card);

      return card;
    }

    // ===== Select Region =====
    function selectRegion(region, element) {
      document.querySelectorAll('.region-card').forEach(el => {
        el.classList.remove('active');
        el.setAttribute('aria-selected', 'false');
      });
      element.classList.add('active');
      element.setAttribute('aria-selected', 'true');
      selectedRegion = region;

      // Clear existing layers
      currentLayers.forEach(layer => map.removeLayer(layer));
      currentLayers = [];

      // Zoom to region (unless zoom is locked)
      if (!zoomLocked) {
        map.setView([region.center.lat, region.center.lon], region.id === 'ALL REGIONS' ? 2 : 5);
      }

      // Render controls
      renderResolutionControls(region);

      announce('Selected ' + region.id);
    }

    // ===== Render Resolution Controls =====
    function renderResolutionControls(region) {
      const container = document.getElementById('layerToggles');
      container.textContent = '';

      region.resolutions.sort((a, b) => a.resolution - b.resolution).forEach(resLayer => {
        const colorConfig = RESOLUTION_COLORS[resLayer.resolution] || { fill: '#999', stroke: '#666', label: 'Unknown' };

        const item = document.createElement('div');
        item.className = 'layer-toggle';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'layer-checkbox';
        checkbox.id = 'layer-' + resLayer.resolution;
        checkbox.checked = true;
        checkbox.onchange = () => toggleResolution(resLayer, checkbox.checked);
        item.appendChild(checkbox);

        const colorDiv = document.createElement('div');
        colorDiv.className = 'layer-color';
        colorDiv.style.background = colorConfig.fill;
        item.appendChild(colorDiv);

        const info = document.createElement('div');
        info.className = 'layer-info';
        const name = document.createElement('div');
        name.className = 'layer-name';
        name.textContent = 'Resolution ' + resLayer.resolution;
        info.appendChild(name);
        const count = document.createElement('div');
        count.className = 'layer-count';
        count.textContent = resLayer.cells.length.toLocaleString() + ' hexagons • ' + colorConfig.label;
        info.appendChild(count);
        item.appendChild(info);

        container.appendChild(item);

        // Show layer initially
        showResolution(resLayer);
      });

      // Wire up All/None buttons
      document.getElementById('showAllLayers').onclick = () => {
        container.querySelectorAll('.layer-checkbox').forEach(cb => {
          if (!cb.checked) { cb.checked = true; cb.onchange(); }
        });
      };

      document.getElementById('hideAllLayers').onclick = () => {
        container.querySelectorAll('.layer-checkbox').forEach(cb => {
          if (cb.checked) { cb.checked = false; cb.onchange(); }
        });
      };
    }

    // ===== Toggle Resolution Layer =====
    function toggleResolution(resLayer, show) {
      if (show) showResolution(resLayer);
      else hideResolution(resLayer);
    }

    // ===== Show Resolution Layer =====
    function showResolution(resLayer) {
      const colorConfig = RESOLUTION_COLORS[resLayer.resolution] || { fill: '#999', stroke: '#666' };
      const totalCells = resLayer.cells.length;

      // Show loading for large datasets
      if (totalCells > 500) {
        document.getElementById('loadingOverlay').hidden = false;
        document.querySelector('.loading-text').textContent = 'Loading ' + totalCells.toLocaleString() + ' hexagons...';
      }

      let rendered = 0;

      resLayer.cells.forEach((cell, idx) => {
        try {
          const boundary = h3.cellToBoundary(cell);

          // Check for antimeridian crossing
          const lons = boundary.map(c => c[1]);
          if (Math.max.apply(null, lons) - Math.min.apply(null, lons) > 180) {
            console.warn('Cell ' + cell + ' crosses antimeridian, skipping');
            return;
          }

          // Skip cells with no checklists (e.g., from rounding when distributing to children)
          const checklistCount = resLayer.checklists && resLayer.checklists[cell] ? resLayer.checklists[cell] : 0;
          if (checklistCount === 0) {
            return;
          }

          const polygon = L.polygon(
            boundary.map(c => [c[0], c[1]]),
            {
              color: colorConfig.stroke,
              weight: 1,
              opacity: 0.8,
              fillColor: colorConfig.fill,
              fillOpacity: 0.2
            }
          );

          // Enhanced popup using DOM methods
          const popupContent = document.createElement('div');
          popupContent.className = 'hex-popup';

          const popupHeader = document.createElement('div');
          popupHeader.className = 'hex-popup-header';
          const resSpan = document.createElement('span');
          resSpan.className = 'hex-popup-res';
          resSpan.style.background = colorConfig.fill;
          resSpan.textContent = 'Res ' + resLayer.resolution;
          popupHeader.appendChild(resSpan);
          popupContent.appendChild(popupHeader);

          const popupBody = document.createElement('div');
          popupBody.className = 'hex-popup-body';

          // Cell Index row
          const cellRow = document.createElement('div');
          cellRow.className = 'hex-popup-row';
          const cellLabel = document.createElement('span');
          cellLabel.className = 'hex-popup-label';
          cellLabel.textContent = 'Cell Index';
          cellRow.appendChild(cellLabel);
          const cellValue = document.createElement('code');
          cellValue.className = 'hex-popup-value';
          cellValue.textContent = cell;
          cellRow.appendChild(cellValue);
          popupBody.appendChild(cellRow);

          // Checklists row (checklistCount already defined above)
          const checklistRow = document.createElement('div');
          checklistRow.className = 'hex-popup-row';
          const checklistLabel = document.createElement('span');
          checklistLabel.className = 'hex-popup-label';
          checklistLabel.textContent = 'Checklists';
          checklistRow.appendChild(checklistLabel);
          const checklistValue = document.createElement('span');
          checklistValue.className = 'hex-popup-value';
          checklistValue.textContent = checklistCount.toLocaleString();
          checklistRow.appendChild(checklistValue);
          popupBody.appendChild(checklistRow);

          // Regions row - show which region packs this cell belongs to
          const cellPacks = resLayer.packs && resLayer.packs[cell] ? resLayer.packs[cell] : [];
          if (cellPacks.length > 0) {
            // Get unique regions
            const regionSet = new Set();
            cellPacks.forEach(function(pack) {
              regionSet.add(pack.regionId);
            });
            const regions = Array.from(regionSet).sort();

            const regionsRow = document.createElement('div');
            regionsRow.className = 'hex-popup-row';
            regionsRow.style.flexDirection = 'column';
            regionsRow.style.alignItems = 'flex-start';
            const regionsLabel = document.createElement('span');
            regionsLabel.className = 'hex-popup-label';
            regionsLabel.textContent = regions.length === 1 ? 'Region' : 'Regions (' + regions.length + ')';
            regionsRow.appendChild(regionsLabel);

            const regionsList = document.createElement('div');
            regionsList.style.cssText = 'max-height: 120px; overflow-y: auto; width: 100%; margin-top: 4px;';

            regions.forEach(function(regionId) {
              const regionItem = document.createElement('div');
              regionItem.style.cssText = 'font-size: 12px; padding: 2px 0;';
              regionItem.textContent = regionId;
              regionsList.appendChild(regionItem);
            });
            regionsRow.appendChild(regionsList);
            popupBody.appendChild(regionsRow);
          }

          const copyBtn = document.createElement('button');
          copyBtn.className = 'hex-popup-copy';
          copyBtn.textContent = 'Copy Index';
          copyBtn.onclick = () => copyToClipboard(cell);
          popupBody.appendChild(copyBtn);
          popupContent.appendChild(popupBody);

          polygon.bindPopup(popupContent, { className: 'custom-popup' });

          // Hover effect
          polygon.on('mouseover', function() {
            this.setStyle({ weight: 2, fillOpacity: 0.4 });
            this.bringToFront();
          });
          polygon.on('mouseout', function() {
            this.setStyle({ weight: 1, fillOpacity: 0.2 });
          });

          polygon.addTo(map);
          polygon._resolutionId = resLayer.resolution;
          currentLayers.push(polygon);

          rendered++;

          // Update progress
          if (totalCells > 500 && rendered % 100 === 0) {
            document.getElementById('loadingProgress').style.width = ((rendered / totalCells) * 100) + '%';
          }
        } catch (e) {
          console.warn('Failed to render cell ' + cell + ':', e);
        }
      });

      document.getElementById('loadingOverlay').hidden = true;
    }

    // ===== Hide Resolution Layer =====
    function hideResolution(resLayer) {
      currentLayers = currentLayers.filter(layer => {
        if (layer._resolutionId === resLayer.resolution) {
          map.removeLayer(layer);
          return false;
        }
        return true;
      });
    }

    // ===== Initialize App =====
    function init() {
      ThemeManager.init();
      initMap();
      renderStats();
      renderRegionList();
      SearchManager.init();
      KeyboardNav.init();
      ExportManager.init();

      // Zoom lock button
      const zoomLockBtn = document.getElementById('zoomLockBtn');
      zoomLockBtn.addEventListener('click', () => {
        zoomLocked = !zoomLocked;
        zoomLockBtn.textContent = zoomLocked ? '🔒 Locked' : '🔓 Unlocked';
        zoomLockBtn.classList.toggle('locked', zoomLocked);
        Toast.info(zoomLocked ? 'Zoom locked' : 'Zoom unlocked', 'Switching regions will ' + (zoomLocked ? 'keep' : 'change') + ' the current view');
      });

      console.log('Pack Manifest Visualizer initialized');
    }

    document.addEventListener('DOMContentLoaded', init);
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
