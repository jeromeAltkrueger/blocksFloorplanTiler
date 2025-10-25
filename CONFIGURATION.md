# Floor Plan Tiler Configuration Guide

## Quality vs Performance Settings

You can adjust key parameters to balance quality and performance.

There are two ways to configure:

1) Code constants (quick local tweaks)
2) Recommended: Environment variables in the Azure Function App (no code change required)

### 1. PDF_SCALE (PDF Rendering Resolution)

Controls the DPI at which PDFs are rendered.

Environment variable: `PDF_SCALE` (float)

Code default (if env not set): `PDF_SCALE = 6.0`

| Value | DPI | Quality | Use Case | Processing Time |
|-------|-----|---------|----------|----------------|
| 2.0 | 144 DPI | Basic | Quick previews, simple diagrams | Fast ⚡ |
| 4.0 | 288 DPI | Good | Standard floor plans | Medium ⚡⚡ |
| **6.0** | **432 DPI** | **Very Good** | **Detailed floor plans** ← **CURRENT** | Slower ⚡⚡⚡ |
| 8.0 | 576 DPI | Extreme | Architectural drawings with fine text | Slow ⚡⚡⚡⚡ |

**Recommendation**: Start with 6.0, increase to 8.0 only if text/details are not sharp enough.

---

### 2. MAX_DIMENSION (Maximum Pixel Dimension)

Maximum width or height before auto-scaling kicks in to prevent timeouts.

Environment variable: `MAX_DIMENSION` (int)

Code default (if env not set): `MAX_DIMENSION = 20000`

| Value | Use Case | Memory Usage | Risk |
|-------|----------|-------------|------|
| 10000 | Small to medium PDFs | Low | Safe |
| 15000 | Medium to large PDFs | Medium | Generally safe |
| **20000** | **Large PDFs** ← **CURRENT** | **High** | **May timeout on huge files** |
| 25000 | Extremely large PDFs | Very High | High timeout risk |

**Recommendation**: Keep at 20000 unless you encounter timeout errors, then reduce to 15000.

---

### 3. MAX_ZOOM_LIMIT (Maximum Zoom Levels)

Maximum number of zoom levels to generate.

Environment variable: `MAX_ZOOM_LIMIT` (int)

Code default (if env not set): `MAX_ZOOM_LIMIT = 12`

Additionally, the highest generated zoom folder is controlled by:

- Environment variable: `FORCED_MAX_Z` (int)
- Code default (if env not set): `FORCED_MAX_Z = 12`

| Value | Max Tiles Per Dimension | Total Possible Tiles | Use Case | Storage |
|-------|------------------------|---------------------|----------|---------|
| 6 | 64 | ~4,000 | Simple diagrams | Minimal |
| 8 | 256 | ~65,000 | Standard floor plans | Low |
| 10 | 1,024 | ~1 million | Detailed floor plans | Medium |
| **12** | **4,096** | **~16 million** ← **CURRENT** | **Very detailed** | **High** |
| 15 | 32,768 | ~1 billion | Extreme detail | Very High |

**Note**: Actual tiles generated depend on image dimensions. The function automatically calculates the optimal zoom level up to this limit.

**Recommendation**: Keep at 12 for most use cases. Only increase to 15 for massive, extremely detailed floor plans.

---

### 4. TILE_SIZE (Tile image size in pixels)

Controls how large each tile image is. Larger tiles dramatically reduce the total number of tiles and HTTP requests.

Environment variable: `TILE_SIZE` (int; supported: 256, 512, 1024)

Code default (if env not set): `TILE_SIZE = 256`

| TILE_SIZE | Effect | Typical Use |
|-----------|--------|-------------|
| 256 | Leaflet default; most compatible | General use |
| 512 | ~4× fewer tiles vs 256 | Faster browsing, fewer requests |
| 1024 | ~16× fewer tiles vs 256 | Minimum tile count; heavier per-request payload |

Notes:
- The viewer reads `tile_size` from `metadata.json` and configures Leaflet accordingly.
- For best “highest zoom detail,” combine larger `TILE_SIZE` with higher `PDF_SCALE` and sufficient `MAX_DIMENSION`.

---

### 5. MIN_ZOOM (Optional lower bound)

Reduces the number of generated zoom levels by skipping very low zooms.

Environment variable: `MIN_ZOOM` (int, default 0)

Example: `MIN_ZOOM=3` with `FORCED_MAX_Z=12` generates only zooms 3..12 instead of 0..12.

Trade-offs:
- Fewer tiles and faster processing.
- Users can’t zoom out as far; initial extent starts more “zoomed in”.

---

## Example Configurations

### Fast & Lightweight (Small files, quick processing)
```python
PDF_SCALE = 4.0
MAX_DIMENSION = 10000
MAX_ZOOM_LIMIT = 8
```
- Best for: Simple floor plans, quick iteration
- Processing time: ~10-30 seconds
- Storage per floor plan: ~5-20 MB

### Balanced Quality (Good detail, reasonable processing) ← **CURRENT**
```python
PDF_SCALE = 6.0
MAX_DIMENSION = 20000
MAX_ZOOM_LIMIT = 12
```
- Best for: Most floor plans with good detail
- Processing time: ~30-60 seconds
- Storage per floor plan: ~20-100 MB

### Maximum Quality (Extreme detail, slow processing)
```python
PDF_SCALE = 8.0
MAX_DIMENSION = 25000
MAX_ZOOM_LIMIT = 15
```
- Best for: Architectural drawings, highly detailed plans
- Processing time: ~2-5 minutes
- Storage per floor plan: ~100-500 MB
- ⚠️ **Warning**: May timeout on Azure Functions (5-10 minute limit)

---

## How to Change Settings

Recommended (no code change):

1. In Azure Portal, go to Function App > Configuration > Application settings.
2. Add or update the following keys (as needed):
   - `PDF_SCALE` (e.g., 8.0)
   - `MAX_DIMENSION` (e.g., 25000)
   - `MAX_ZOOM_LIMIT` (e.g., 12 or 15)
   - `FORCED_MAX_Z` (e.g., 12)
   - `TILE_SIZE` (256, 512, or 1024)
   - `MIN_ZOOM` (e.g., 0–4)
3. Save and restart the Function App.
4. Upload a fresh, uniquely named PDF to trigger processing.

Alternative (code change):

1. Open `function_app.py` and adjust the defaults in the CONFIGURATION section.
2. Deploy the function and re-upload your PDF.

---

## Calculating Storage Requirements

Rough estimate for storage per floor plan:

```
Storage (MB) ≈ (Width × Height × PDF_SCALE²) / 50,000,000
```

Example:
- PDF dimensions: A1 size (594mm × 841mm ≈ 2339px × 3311px at 100 DPI)
- PDF_SCALE = 6.0
- Rendered size: 14,034px × 19,866px

```
Storage ≈ (14,034 × 19,866 × 6²) / 50,000,000
        ≈ 2,009 MB (~2 GB)
```

**Actual storage** will be lower due to PNG compression, typically 30-50% of this estimate.

---

## Performance Tips

1. **Start with defaults** (PDF_SCALE=6.0, MAX_DIMENSION=20000, MAX_ZOOM_LIMIT=12)
2. **Monitor processing time** in Azure Function logs
3. **Check tile quality** at max zoom in browser
4. **Adjust only if needed**:
   - Grey tiles? → Increase MAX_ZOOM_LIMIT
   - Blurry text? → Increase PDF_SCALE
   - Timeouts? → Decrease PDF_SCALE or MAX_DIMENSION
   - Too much storage? → Decrease PDF_SCALE or MAX_ZOOM_LIMIT

---

## Zoom Level Impact

Number of tiles grows exponentially:

| Zoom Level | Tiles for 4000×3000px Image | Approx Storage (PNG) |
|------------|----------------------------|---------------------|
| 0 | 1 | 60 KB |
| 1 | 2×2 = 4 | 240 KB |
| 2 | 4×4 = 16 | 960 KB |
| 3 | 8×6 = 48 | 2.8 MB |
| 4 | 16×12 = 192 | 11 MB |
| 5 | 32×24 = 768 | 46 MB |
| 6 | 64×48 = 3,072 | 180 MB |
| ... | ... | ... |

**Total storage** = sum of all zoom levels ≈ 1.33× storage of highest zoom level.

---

## Monitoring & Debugging

Check Azure Function logs for:
```
Configuration overrides → PDF_SCALE=6.0, MAX_DIMENSION=20000, MAX_ZOOM_LIMIT=12, FORCED_MAX_Z=12, TILE_SIZE=512, MIN_ZOOM=0
Max-zoom native tile grid: 55x78 (total 4290) at 14034x19866px
Calculated max zoom: 5 for 14034x19866 image
  → Full resolution needs 55x78 tiles = 4290 total tiles
  → Max dimension requires 78 tiles, which needs zoom level 7
```

This tells you:
- What configuration was used
- How many zoom levels were actually created
- How many tiles were generated
- If the zoom limit capped the result

---

## Azure Function Timeout Limits

| Plan | Timeout Limit |
|------|--------------|
| Consumption Plan | 5 minutes (default), 10 minutes (max) |
| Premium Plan | 30 minutes (default), unlimited (max) |
| Dedicated Plan | 30 minutes (default), unlimited (max) |

If you hit timeouts with high settings, consider:
1. Upgrading to Premium/Dedicated plan
2. Reducing PDF_SCALE
3. Reducing MAX_DIMENSION
4. Processing very large PDFs offline

---

## Current Configuration Summary

Your function is currently optimized for:
- ✅ **High quality** rendering (432 DPI)
- ✅ **Large PDFs** (up to 20,000px)
- ✅ **Deep zoom** (up to 12 levels)
- ⚠️ Processing time: 30-60 seconds per PDF
- ⚠️ Storage: 20-100 MB per floor plan

This is a good balance for most detailed floor plan use cases.
