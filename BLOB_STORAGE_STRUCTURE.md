# Azure Blob Storage Structure

## Complete Folder Structure Definition

This document defines the exact folder structure created in Azure Blob Storage for the floor plan tiling system.

---

## Container: `floor-plans/` (INPUT & OUTPUT)

This is the single container that holds everything - both the uploaded PDFs and their generated tiles.

### Before Processing
```
floor-plans/
├── {floorplan-name-1}.pdf       # Original PDF (will be moved into folder after processing)
├── {floorplan-name-2}.pdf
└── {floorplan-name-3}.pdf
```

### After Processing
```
floor-plans/
├── {floorplan-id-1}/            # Processed floor plan folder
│   ├── {floorplan-id-1}.pdf     # Original PDF (moved here)
│   ├── metadata.json
│   ├── preview.jpg
│   └── tiles/
│       └── {z}/{x}/{y}.png
├── {floorplan-id-2}/
│   └── ...
└── {floorplan-name-3}.pdf       # Unprocessed PDF (still in root)
```

**Example:**
```
floor-plans/
├── Building_A_Floor_1.pdf       # Waiting to be processed
├── KÖP_000_5_ZOO_GR_XX_U1_0000_J (1)/  # Already processed
│   ├── KÖP_000_5_ZOO_GR_XX_U1_0000_J (1).pdf
│   ├── metadata.json
│   ├── preview.jpg
│   └── tiles/
│       ├── 0/0/0.png
│       ├── 1/...
│       └── 5/...
└── Warehouse_Layout/            # Already processed
    ├── Warehouse_Layout.pdf
    ├── metadata.json
    ├── preview.jpg
    └── tiles/
```

---

## Container: `floor-plan-tiles/` ~~(OUTPUT)~~ ❌ NO LONGER USED

~~This container is no longer used. Everything is now in `floor-plans/`.~~

---

## Complete Folder Structure (NEW)

## Complete Folder Structure (NEW)

```
floor-plans/
└── {floorplan-id}/                      # Folder per floor plan (same name as PDF without .pdf)
    ├── {floorplan-id}.pdf               # Original PDF file (moved here after processing)
    ├── metadata.json                    # Floor plan metadata & configuration
    ├── preview.jpg                      # Low-res preview image (800px wide)
    └── tiles/                           # All tiles organized by zoom level
        ├── 0/                               # Zoom level 0 (most zoomed out, 1 tile)
        │   └── 0/                           # X coordinate folder
        │       └── 0.png                    # Y coordinate tile (256×256px)
        │
        ├── 1/                               # Zoom level 1 (4 tiles total)
        │   ├── 0/                           # X = 0
        │   │   ├── 0.png                    # Tile at (0,0)
        │   │   └── 1.png                    # Tile at (0,1)
        │   └── 1/                           # X = 1
        │       ├── 0.png                    # Tile at (1,0)
        │       └── 1.png                    # Tile at (1,1)
        │
        ├── 2/                               # Zoom level 2 (16 tiles total)
        │   ├── 0/
        │   │   ├── 0.png
        │   │   ├── 1.png
        │   │   ├── 2.png
        │   │   └── 3.png
        │   ├── 1/
        │   │   ├── 0.png
        │   │   ├── 1.png
        │   │   ├── 2.png
        │   │   └── 3.png
        │   ├── 2/
        │   │   ├── 0.png
        │   │   ├── 1.png
        │   │   ├── 2.png
        │   │   └── 3.png
        │   └── 3/
        │       ├── 0.png
        │       ├── 1.png
        │       ├── 2.png
        │       └── 3.png
        │
        ├── 3/                               # Zoom level 3
        │   └── ...
        │
        ├── 4/                               # Zoom level 4
        │   └── ...
        │
        └── {max_zoom}/                      # Maximum zoom level (highest detail)
            ├── 0/
            │   ├── 0.png
            │   ├── 1.png
            │   └── ...
            ├── 1/
            │   └── ...
            └── {max_x}/
                └── {max_y}.png
```

---

## Real Example with Actual Floor Plan

### Input
```
floor-plans/
└── KÖP_000_5_ZOO_GR_XX_U1_0000_J (1).pdf     # Original PDF (2.8 MB)
```

### Output (After Processing)
```
floor-plans/
└── KÖP_000_5_ZOO_GR_XX_U1_0000_J (1)/    # Folder named after PDF
    ├── KÖP_000_5_ZOO_GR_XX_U1_0000_J (1).pdf  # Original PDF (moved here)
    ├── metadata.json                          # 450 bytes
    ├── preview.jpg                            # 85 KB
    └── tiles/
        ├── 0/                                 # 1 tile (256×256)
        │   └── 0/
        │       └── 0.png                      # 45 KB
        │
        ├── 1/                                 # 4 tiles (2×2 grid)
        │   ├── 0/
        │   │   ├── 0.png                      # 48 KB
        │   │   └── 1.png                      # 42 KB
        │   └── 1/
        │       ├── 0.png                      # 51 KB
        │       └── 1.png                      # 39 KB
        │
        ├── 2/                                 # 12 tiles (4×3 grid)
        │   ├── 0/
        │   │   ├── 0.png
        │   │   ├── 1.png
        │   │   └── 2.png
        │   ├── 1/
        │   │   ├── 0.png
        │   │   ├── 1.png
        │   │   └── 2.png
        │   ├── 2/
        │   │   ├── 0.png
        │   │   ├── 1.png
        │   │   └── 2.png
        │   └── 3/
        │       ├── 0.png
        │       ├── 1.png
        │       └── 2.png
        │
        ├── 3/                                 # 48 tiles (8×6 grid)
        │   ├── 0/ ... 7/
        │   │   ├── 0.png ... 5.png
        │
        ├── 4/                                 # 192 tiles (16×12 grid)
        │   ├── 0/
        │   │   ├── 0.png
        │   │   ├── 1.png
        │   │   ├── 2.png
        │   │   ├── 3.png
        │   │   ├── 4.png
        │   │   ├── 5.png
        │   │   ├── 6.png
        │   │   ├── 7.png
        │   │   ├── 8.png
        │   │   ├── 9.png
        │   │   ├── 10.png
        │   │   └── 11.png
        │   ├── 1/ ... 15/
        │   │   └── 0.png ... 11.png
        │
        └── 5/                                 # 768 tiles (32×24 grid) - MAX ZOOM
            ├── 0/
            │   ├── 0.png
            │   ├── 1.png
            │   └── ... (24 tiles in Y direction)
            ├── 1/
            │   └── ...
            ├── 2/
            │   └── ...
            └── 31/                            # Last X coordinate
                ├── 0.png
                ├── 1.png
                └── 23.png                     # Last Y coordinate
```

**Total for this example:**
- Zoom levels: 6 (0-5)
- Total tiles: 1,025 tiles
- Total storage: ~75 MB

---

## Tile Naming Convention

### Format
```
{floorplan-id}/{floorplan-id}.pdf           # Original PDF
{floorplan-id}/metadata.json                 # Metadata
{floorplan-id}/preview.jpg                   # Preview
{floorplan-id}/tiles/{z}/{x}/{y}.png        # Tiles
```

### Parameters
- **{floorplan-id}**: Unique identifier (PDF filename without extension)
- **{z}**: Zoom level (0 = most zoomed out, higher = more zoomed in)
- **{x}**: Tile X coordinate (column, starts at 0)
- **{y}**: Tile Y coordinate (row, starts at 0)

### Examples
```
KÖP_000_5_ZOO_GR_XX_U1_0000_J (1)/KÖP_000_5_ZOO_GR_XX_U1_0000_J (1).pdf  # Original PDF
KÖP_000_5_ZOO_GR_XX_U1_0000_J (1)/metadata.json                           # Metadata
KÖP_000_5_ZOO_GR_XX_U1_0000_J (1)/preview.jpg                             # Preview
KÖP_000_5_ZOO_GR_XX_U1_0000_J (1)/tiles/0/0/0.png      # Zoom 0, position (0,0)
KÖP_000_5_ZOO_GR_XX_U1_0000_J (1)/tiles/3/7/5.png      # Zoom 3, position (7,5)
KÖP_000_5_ZOO_GR_XX_U1_0000_J (1)/tiles/5/31/23.png    # Zoom 5, position (31,23)
```

---

## Metadata File Structure

### File: `{floorplan-id}/metadata.json`

```json
{
  "floorplan_id": "KÖP_000_5_ZOO_GR_XX_U1_0000_J (1)",
  "width": 19800,
  "height": 10524,
  "tile_size": 256,
  "max_zoom": 5,
  "min_zoom": 0,
  "bounds": [
    [0, 0],
    [10524, 19800]
  ],
  "created_at": "2025-10-23T14:32:15.123456",
  "format": "png"
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `floorplan_id` | string | Unique identifier (PDF filename without extension) |
| `width` | integer | Original rendered image width in pixels |
| `height` | integer | Original rendered image height in pixels |
| `tile_size` | integer | Size of each tile (always 256×256 pixels) |
| `max_zoom` | integer | Maximum zoom level available (highest detail) |
| `min_zoom` | integer | Minimum zoom level available (always 0) |
| `bounds` | array | Leaflet CRS.Simple bounds [[y_min, x_min], [y_max, x_max]] |
| `created_at` | string | ISO 8601 timestamp when tiles were generated |
| `format` | string | Tile image format (always "png") |

---

## URL Patterns

### Accessing Files via HTTP

All files are accessible via standard HTTP(S) URLs:

```
https://{storage-account}.blob.core.windows.net/{container}/{blob-path}
```

### Examples

**Metadata:**
```
https://blocksplayground.blob.core.windows.net/floor-plans/KÖP_000_5_ZOO_GR_XX_U1_0000_J%20%281%29/metadata.json
```

**Preview:**
```
https://blocksplayground.blob.core.windows.net/floor-plans/KÖP_000_5_ZOO_GR_XX_U1_0000_J%20%281%29/preview.jpg
```

**Original PDF:**
```
https://blocksplayground.blob.core.windows.net/floor-plans/KÖP_000_5_ZOO_GR_XX_U1_0000_J%20%281%29/KÖP_000_5_ZOO_GR_XX_U1_0000_J%20%281%29.pdf
```

**Tiles:**
```
https://blocksplayground.blob.core.windows.net/floor-plans/KÖP_000_5_ZOO_GR_XX_U1_0000_J%20%281%29/tiles/0/0/0.png
https://blocksplayground.blob.core.windows.net/floor-plans/KÖP_000_5_ZOO_GR_XX_U1_0000_J%20%281%29/tiles/5/31/23.png
```

**Note:** Special characters in floor plan IDs must be URL-encoded:
- Space ` ` → `%20`
- Parentheses `()` → `%28%29`
- Umlaut `Ö` → `%C3%96`

---

## Tile Grid Calculations

### How Many Tiles Per Zoom Level?

For an image of dimensions `W × H` pixels:

```
Zoom Level Z:
  - Scale Factor = 2^(max_zoom - Z)
  - Scaled Width = W / Scale Factor
  - Scaled Height = H / Scale Factor
  - Tiles X = ceil(Scaled Width / 256)
  - Tiles Y = ceil(Scaled Height / 256)
  - Total Tiles at Z = Tiles X × Tiles Y
```

### Example Calculation

Original image: 19,800 × 10,524 pixels, max_zoom = 5

| Zoom | Scale | Scaled Size | Tiles (X×Y) | Total Tiles |
|------|-------|-------------|-------------|-------------|
| 0 | 1/32 | 619×329 | 3×2 | 6 |
| 1 | 1/16 | 1,238×658 | 5×3 | 15 |
| 2 | 1/8 | 2,475×1,316 | 10×6 | 60 |
| 3 | 1/4 | 4,950×2,631 | 20×11 | 220 |
| 4 | 1/2 | 9,900×5,262 | 39×21 | 819 |
| 5 | 1/1 | 19,800×10,524 | 78×42 | 3,276 |

**Total tiles:** 4,396 tiles across all zoom levels

---

## Storage Size Estimates

### Per-Tile Size
- Average PNG tile (256×256): **30-60 KB**
- Preview JPEG (800px wide): **80-120 KB**
- Metadata JSON: **400-500 bytes**

### Total Storage by Image Size

| PDF Size | Rendered Size | Max Zoom | Total Tiles | Storage |
|----------|---------------|----------|-------------|---------|
| A4 | 4,000×2,800 | 4 | ~400 | ~20 MB |
| A3 | 5,600×4,000 | 5 | ~900 | ~45 MB |
| A1 | 14,000×10,000 | 6 | ~4,000 | ~180 MB |
| A0 | 19,800×14,000 | 7 | ~16,000 | ~700 MB |

---

## Folder Properties

### Blob Properties Set by Azure Function

Each uploaded blob has these properties:

**Tiles (PNG):**
- Content-Type: `image/png`
- Content-Encoding: (none)
- Cache-Control: (default)

**Preview (JPEG):**
- Content-Type: `image/jpeg`
- Content-Encoding: (none)

**Metadata (JSON):**
- Content-Type: `application/json`
- Content-Encoding: (none)

---

## Leaflet URL Template

Leaflet.js loads tiles using this URL template:

```javascript
const tileUrl = `https://blocksplayground.blob.core.windows.net/floor-plan-tiles/${encodeURIComponent(floorplanId)}/tiles/{z}/{x}/{y}.png`;
```

Leaflet replaces:
- `{z}` with zoom level
- `{x}` with tile X coordinate
- `{y}` with tile Y coordinate

---

## Workflow Summary

```
1. UPLOAD PDF
   floor-plans/MyFloorPlan.pdf
   ↓
2. AZURE FUNCTION TRIGGERS
   - Reads PDF from root of container
   - Renders at high resolution
   - Generates tile pyramid
   ↓
3. OUTPUT CREATED IN SAME CONTAINER
   floor-plans/MyFloorPlan/
   ├── MyFloorPlan.pdf        ← Original PDF (moved here)
   ├── metadata.json          ← Configuration
   ├── preview.jpg            ← Quick preview
   └── tiles/
       ├── 0/0/0.png          ← Zoom level 0
       ├── 1/0/0.png          ← Zoom level 1
       ├── ...
       └── 5/31/23.png        ← Zoom level 5 (max detail)
   ↓
4. ORIGINAL PDF REMOVED FROM ROOT (OPTIONAL)
   The original PDF at floor-plans/MyFloorPlan.pdf can be deleted
   since it's now at floor-plans/MyFloorPlan/MyFloorPlan.pdf
   ↓
5. LEAFLET LOADS TILES
   Browser requests tiles as user pans/zooms
```

---

## Advanced: Custom Folder Structures

If you want to customize the folder structure, modify these functions in `function_app.py`:

### 1. Change Container Name
```python
container="your-custom-container-name"
```

### 2. Change Folder Structure
```python
# Current: {floorplan-id}/tiles/{z}/{x}/{y}.png
blob_path = f"{floorplan_id}/tiles/{zoom}/{x}/{y}.png"

# Example: Flat structure
blob_path = f"{floorplan_id}/{zoom}_{x}_{y}.png"

# Example: Year/Month folders
blob_path = f"{year}/{month}/{floorplan_id}/tiles/{zoom}/{x}/{y}.png"
```

### 3. Change Metadata Location
```python
# Current: {floorplan-id}/metadata.json
metadata_blob = f"{floorplan_id}/metadata.json"

# Example: Central metadata folder
metadata_blob = f"metadata/{floorplan_id}.json"
```

---

## File Counts by Zoom Level

Quick reference for expected file counts:

| Max Zoom | Approx. Tiles | Files Created |
|----------|--------------|---------------|
| 3 | 50-200 | ~200 |
| 4 | 200-800 | ~800 |
| 5 | 800-3,000 | ~3,000 |
| 6 | 3,000-12,000 | ~12,000 |
| 7 | 12,000-50,000 | ~50,000 |
| 8 | 50,000-200,000 | ~200,000 |

**Note:** Plus 2 additional files (metadata.json and preview.jpg) per floor plan.
