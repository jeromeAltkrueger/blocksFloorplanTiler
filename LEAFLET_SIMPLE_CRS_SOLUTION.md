# Leaflet Simple CRS Solution

## The Problem

When using `L.CRS.Simple` with your floorplan tiles, adding `noWrap: true` causes Leaflet to request tiles at wrong coordinates (e.g., `2/71/0.png` instead of `2/0/0.png`).

## Root Cause

1. **noWrap + Simple CRS interaction**: The `noWrap` option is designed for geographic coordinates (EPSG:3857/4326), not pixel-based Simple CRS
2. **Coordinate transformation mismatch**: Leaflet's default Simple CRS uses a transformation that may not align with how your tiles are generated
3. **Bounds calculation**: When `noWrap` is enabled, Leaflet applies bounds checking that breaks with default Simple CRS settings

## The Solution: Custom CRS

Define a custom CRS that properly maps pixel coordinates to tile coordinates:

```javascript
// Custom CRS that maps pixel coordinates directly to tile coordinates
var customCRS = L.extend({}, L.CRS.Simple, {
    transformation: new L.Transformation(1, 0, 1, 0)
});

// Then use it:
var map = L.map('map', {
    crs: customCRS,  // Use custom CRS instead of L.CRS.Simple
    minZoom: 2,
    maxZoom: 5
});
```

### Alternative: Don't Use noWrap

Since your floorplan is a bounded image (not a wrapped world map), **you don't need `noWrap`**. Instead:

1. Use `maxBounds` on the map to prevent panning outside the image
2. Use `maxBoundsViscosity: 1.0` to make bounds rigid
3. Don't set `noWrap` on the tile layer

```javascript
const bounds = [[0, 0], [height, width]];

const map = L.map('map', {
    crs: L.CRS.Simple,
    minZoom: 2,
    maxZoom: 5,
    maxBounds: bounds,
    maxBoundsViscosity: 1.0  // Prevents panning outside bounds
});

const tileLayer = L.tileLayer(url, {
    tileSize: 512,
    bounds: bounds,
    // NO noWrap option!
});
```

## Working Configuration

Here's the complete working configuration:

```html
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        #map { height: 100vh; }
    </style>
</head>
<body>
    <div id="map"></div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        // Your metadata
        const width = 25257;
        const height = 4457;
        const minZoom = 2;
        const maxZoom = 5;
        const tileSize = 512;
        
        // Bounds in Simple CRS format: [[minY, minX], [maxY, maxX]]
        const bounds = [[0, 0], [height, width]];
        const center = [height / 2, width / 2];
        
        // Create map with Simple CRS
        const map = L.map('map', {
            crs: L.CRS.Simple,
            minZoom: minZoom,
            maxZoom: maxZoom,
            maxBounds: bounds,
            maxBoundsViscosity: 1.0
        });
        
        map.setView(center, maxZoom);
        
        // Add tile layer (NO noWrap!)
        L.tileLayer('https://your-tiles-url/{z}/{x}/{y}.png', {
            tileSize: tileSize,
            bounds: bounds
        }).addTo(map);
    </script>
</body>
</html>
```

## Why This Works

1. **Simple CRS**: Treats coordinates as pixels, not lat/lng
2. **maxBounds + maxBoundsViscosity**: Prevents panning outside image bounds (replaces need for noWrap)
3. **bounds on tileLayer**: Tells Leaflet which tiles exist
4. **No noWrap**: Avoids coordinate calculation issues

## Debugging

If tiles still don't load, check:

1. **Tile coordinates in browser console**: Should match your tile file structure
2. **Bounds format**: Must be `[[0, 0], [height, width]]` (not `[[0, 0], [width, height]]`)
3. **Center format**: Must be `[height/2, width/2]` (y, x order)
4. **tileSize**: Must match your tile generation (512 in your case)

## tile generation matches Leaflet expectations

Your `SimpleFloorplanTiler` generates:
- Zoom 2: 7×2 tiles (X: 0-6, Y: 0-1)
- Zoom 5: 50×9 tiles (X: 0-49, Y: 0-8)

Leaflet with correct config will request:
- `2/0/0.png`, `2/1/0.png`, ..., `2/6/1.png` ✓
- NOT `2/71/0.png` or `0/17/0.png` ✗
