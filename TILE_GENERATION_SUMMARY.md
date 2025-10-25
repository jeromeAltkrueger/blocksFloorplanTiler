# Tile Generation Summary

## Overview
The system generates image tiles from PDF floorplans using Simple CRS (pixel coordinates), compatible with Leaflet's `L.CRS.Simple`.

## Process

### 1. PDF to Image Conversion
- PDF rendered at **2160 DPI** (scale factor 30.0)
- Output: Ultra-high quality image (e.g., 25257×4457 pixels)
- Format: RGBA for transparency support

### 2. Tile Generation (SimpleFloorplanTiler)

For each zoom level (2-5):

**Calculate scale:**
```
scale = 2^(zoom - max_zoom)
```
- Zoom 5 (max): scale = 1.0 (full resolution)
- Zoom 4: scale = 0.5
- Zoom 3: scale = 0.25
- Zoom 2 (min): scale = 0.125

**Resize image:**
```
scaled_width = full_width × scale
scaled_height = full_height × scale
```

**Calculate tile grid:**
```
tiles_x = ceil(scaled_width / 512)
tiles_y = ceil(scaled_height / 512)
```

**Generate tiles:**
- For each tile position (tx, ty):
  - Crop 512×512 region from scaled image
  - Edge tiles padded with transparency if needed
  - Save as `{zoom}/{x}/{y}.png` or `.webp`

### 3. Storage Structure
```
/
├── metadata.json (width, height, zoom levels, tile_size)
├── preview.png (low-res preview)
└── tiles/
    ├── 2/
    │   ├── 0/
    │   │   ├── 0.png
    │   │   └── 1.png
    │   ├── 1/...
    ├── 3/...
    ├── 4/...
    └── 5/...
```

### 4. Coordinate System
- **Origin:** Top-left (0, 0)
- **X-axis:** Increases rightward
- **Y-axis:** Increases downward
- **Bounds:** [[0, 0], [height, width]]

## Example (25257×4457 image)

| Zoom | Scale | Scaled Size | Tile Grid | Total Tiles |
|------|-------|-------------|-----------|-------------|
| 2    | 0.125 | 3157×557    | 7×2       | 14          |
| 3    | 0.25  | 6314×1114   | 13×3      | 39          |
| 4    | 0.5   | 12628×2228  | 25×5      | 125         |
| 5    | 1.0   | 25257×4457  | 50×9      | 450         |

**Total: 628 tiles**

## Key Features
- WebP compression (60-80% smaller than PNG)
- PNG fallback for compatibility
- Transparency preserved for edge tiles
- No geographic projection (pixel coordinates only)
