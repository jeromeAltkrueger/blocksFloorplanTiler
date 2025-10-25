# Leaflet.js Floor Plan Viewer Guide

## Your Azure Blob Storage Configuration

**Storage Account**: `blocksplayground`  
**Container**: `floor-plan-tiles`  
**Base URL**: `https://blocksplayground.blob.core.windows.net/floor-plan-tiles/`

---

## Step 1: Enable Public Access (Required)

Before you can load tiles in a browser, you need to enable public read access:

### Option A: Azure Portal
1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to Storage Account: `blocksplayground`
3. Go to **Containers** → **floor-plan-tiles**
4. Click **Change access level**
5. Set to **Blob (anonymous read access for blobs only)**
6. Click **OK**

### Option B: Azure CLI
```bash
az storage container set-permission \
  --name floor-plan-tiles \
  --account-name blocksplayground \
  --public-access blob
```

---

## Step 2: HTML + Leaflet.js Implementation

Create an `index.html` file with this code:

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Floor Plan Viewer</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <!-- Leaflet CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    
    <style>
        body {
            margin: 0;
            padding: 0;
            font-family: Arial, sans-serif;
        }
        #map {
            width: 100vw;
            height: 100vh;
        }
        #controls {
            position: absolute;
            top: 10px;
            right: 10px;
            z-index: 1000;
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }
        #controls input {
            width: 100%;
            padding: 8px;
            margin-bottom: 10px;
            border: 1px solid #ccc;
            border-radius: 4px;
        }
        #controls button {
            width: 100%;
            padding: 10px;
            background: #007bff;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        #controls button:hover {
            background: #0056b3;
        }
        #info {
            margin-top: 10px;
            font-size: 12px;
            color: #666;
        }
    </style>
</head>
<body>
    <div id="controls">
        <h3>Floor Plan Viewer</h3>
        <input 
            type="text" 
            id="floorplanId" 
            placeholder="Enter floor plan ID"
            value="KÖP_000_5_ZOO_GR_XX_U1_0000_J (1)"
        />
        <button onclick="loadFloorPlan()">Load Floor Plan</button>
        <div id="info"></div>
    </div>
    
    <div id="map"></div>

    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    
    <script>
        // Azure Blob Storage configuration
        const STORAGE_ACCOUNT = 'blocksplayground';
        const CONTAINER = 'floor-plan-tiles';
        const BASE_URL = `https://${STORAGE_ACCOUNT}.blob.core.windows.net/${CONTAINER}`;
        
        let map = null;
        let currentLayer = null;

        async function loadFloorPlan() {
            const floorplanId = document.getElementById('floorplanId').value.trim();
            
            if (!floorplanId) {
                alert('Please enter a floor plan ID');
                return;
            }

            try {
                // Fetch metadata
                const metadataUrl = `${BASE_URL}/${encodeURIComponent(floorplanId)}/metadata.json`;
                console.log('Fetching metadata from:', metadataUrl);
                
                const response = await fetch(metadataUrl);
                if (!response.ok) {
                    throw new Error(`Metadata not found (${response.status})`);
                }
                
                const metadata = await response.json();
                console.log('Metadata loaded:', metadata);
                
                // Update info display
                document.getElementById('info').innerHTML = `
                    <strong>Loaded:</strong> ${metadata.floorplan_id}<br>
                    <strong>Size:</strong> ${metadata.width}×${metadata.height}px<br>
                    <strong>Zoom:</strong> ${metadata.min_zoom}-${metadata.max_zoom}
                `;
                
                // Initialize or update map
                if (!map) {
                    // Create new map with CRS.Simple for non-geographic images
                    map = L.map('map', {
                        crs: L.CRS.Simple,
                        minZoom: metadata.min_zoom,
                        maxZoom: metadata.max_zoom,
                        zoomSnap: 1,
                        zoomDelta: 1
                    });
                } else {
                    // Remove existing layer
                    if (currentLayer) {
                        map.removeLayer(currentLayer);
                    }
                    map.setMinZoom(metadata.min_zoom);
                    map.setMaxZoom(metadata.max_zoom);
                }
                
                // Create tile layer URL template
                // Note: {s} is removed since Azure Blob Storage doesn't use subdomains
                const tileUrl = `${BASE_URL}/${encodeURIComponent(floorplanId)}/tiles/{z}/{x}/{y}.png`;
                
                // Add tile layer
                currentLayer = L.tileLayer(tileUrl, {
                    minZoom: metadata.min_zoom,
                    maxZoom: metadata.max_zoom,
                    tileSize: metadata.tile_size,
                    noWrap: true,
                    tms: false,  // Not using TMS tile scheme
                    attribution: 'Floor Plan Tiles'
                }).addTo(map);
                
                // Set bounds and fit map
                const bounds = L.latLngBounds(metadata.bounds);
                map.setMaxBounds(bounds.pad(0.1));
                map.fitBounds(bounds);
                
                console.log('Floor plan loaded successfully');
                
            } catch (error) {
                console.error('Error loading floor plan:', error);
                alert(`Error: ${error.message}\n\nMake sure:\n1. The floor plan exists\n2. Container has public blob access enabled`);
            }
        }

        // Load default floor plan on page load
        window.addEventListener('load', () => {
            loadFloorPlan();
        });
    </script>
</body>
</html>
```

---

## Step 3: Usage Examples

### Example 1: Direct Tile URL Pattern
```javascript
const floorplanId = "KÖP_000_5_ZOO_GR_XX_U1_0000_J (1)";
const tileUrl = `https://blocksplayground.blob.core.windows.net/floor-plan-tiles/${encodeURIComponent(floorplanId)}/tiles/{z}/{x}/{y}.png`;

const layer = L.tileLayer(tileUrl, {
    minZoom: 0,
    maxZoom: 5,
    tileSize: 256
});
```

### Example 2: With Metadata Loading
```javascript
async function loadFloorPlanWithMetadata(floorplanId) {
    // 1. Fetch metadata
    const metadataUrl = `https://blocksplayground.blob.core.windows.net/floor-plan-tiles/${encodeURIComponent(floorplanId)}/metadata.json`;
    const metadata = await fetch(metadataUrl).then(r => r.json());
    
    // 2. Create map
    const map = L.map('map', {
        crs: L.CRS.Simple,
        minZoom: metadata.min_zoom,
        maxZoom: metadata.max_zoom
    });
    
    // 3. Add tiles
    const tileUrl = `https://blocksplayground.blob.core.windows.net/floor-plan-tiles/${encodeURIComponent(floorplanId)}/tiles/{z}/{x}/{y}.png`;
    L.tileLayer(tileUrl, {
        minZoom: metadata.min_zoom,
        maxZoom: metadata.max_zoom,
        tileSize: 256
    }).addTo(map);
    
    // 4. Fit bounds
    map.fitBounds(metadata.bounds);
}
```

### Example 3: React Component
```jsx
import { useEffect, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

function FloorPlanViewer({ floorplanId }) {
    const [map, setMap] = useState(null);
    
    useEffect(() => {
        async function loadFloorPlan() {
            const BASE_URL = 'https://blocksplayground.blob.core.windows.net/floor-plan-tiles';
            
            // Fetch metadata
            const metadataUrl = `${BASE_URL}/${encodeURIComponent(floorplanId)}/metadata.json`;
            const metadata = await fetch(metadataUrl).then(r => r.json());
            
            // Initialize map
            const leafletMap = L.map('map', {
                crs: L.CRS.Simple,
                minZoom: metadata.min_zoom,
                maxZoom: metadata.max_zoom
            });
            
            // Add tiles
            const tileUrl = `${BASE_URL}/${encodeURIComponent(floorplanId)}/tiles/{z}/{x}/{y}.png`;
            L.tileLayer(tileUrl, {
                minZoom: metadata.min_zoom,
                maxZoom: metadata.max_zoom,
                tileSize: 256
            }).addTo(leafletMap);
            
            // Fit bounds
            leafletMap.fitBounds(metadata.bounds);
            
            setMap(leafletMap);
        }
        
        loadFloorPlan();
        
        return () => {
            if (map) map.remove();
        };
    }, [floorplanId]);
    
    return <div id="map" style={{ width: '100%', height: '600px' }} />;
}
```

---

## Step 4: Testing

### Quick Test URLs

**Metadata URL** (check if public):
```
https://blocksplayground.blob.core.windows.net/floor-plan-tiles/KÖP_000_5_ZOO_GR_XX_U1_0000_J%20%281%29/metadata.json
```

**Sample Tile URL** (zoom 0, tile 0,0):
```
https://blocksplayground.blob.core.windows.net/floor-plan-tiles/KÖP_000_5_ZOO_GR_XX_U1_0000_J%20%281%29/tiles/0/0/0.png
```

**Preview Image**:
```
https://blocksplayground.blob.core.windows.net/floor-plan-tiles/KÖP_000_5_ZOO_GR_XX_U1_0000_J%20%281%29/preview.jpg
```

Open these URLs in your browser - if you get "Public access is not permitted", follow Step 1 to enable public access.

---

## Important Notes

### CORS Configuration (if needed)
If you're loading from a different domain, configure CORS:

```json
{
  "cors": [
    {
      "allowedOrigins": ["*"],
      "allowedMethods": ["GET", "HEAD"],
      "allowedHeaders": ["*"],
      "exposedHeaders": ["*"],
      "maxAgeInSeconds": 3600
    }
  ]
}
```

Apply via Azure CLI:
```bash
az storage cors add \
  --account-name blocksplayground \
  --services b \
  --methods GET HEAD \
  --origins '*' \
  --allowed-headers '*' \
  --exposed-headers '*' \
  --max-age 3600
```

### URL Encoding
Always use `encodeURIComponent()` for floor plan IDs with special characters:
```javascript
const floorplanId = "KÖP_000_5_ZOO_GR_XX_U1_0000_J (1)";
const encoded = encodeURIComponent(floorplanId);
// Result: "K%C3%96P_000_5_ZOO_GR_XX_U1_0000_J%20%281%29"
```

### Security Options
1. **Public Access** (simplest): Anyone can view tiles
2. **SAS Token**: Time-limited secure URLs
   ```javascript
   const sasToken = "?sv=2021-06-08&ss=b&srt=sco&sp=r&se=...";
   const tileUrl = `${BASE_URL}/${floorplanId}/tiles/{z}/{x}/{y}.png${sasToken}`;
   ```
3. **Azure AD Authentication**: Enterprise-grade security (requires backend)

---

## Need Help?

- **Tiles not loading?** Check browser console (F12) for error messages
- **404 errors?** Verify the floor plan was processed (check Azure Portal → Containers)
- **Grey tiles at specific zoom level?** This usually means:
  1. **Leaflet is requesting tiles that don't exist** - Check console for 404 errors
  2. **Max zoom calculation is off** - The function now supports up to zoom level 12
  3. **Tile coordinates mismatch** - Verify tile paths in browser DevTools Network tab
  4. **Solution**: Re-upload your PDF to trigger re-processing with updated zoom calculations
- **CORS errors?** Apply CORS configuration above
- **Access denied?** Enable public blob access (Step 1)

### Debugging Grey Tiles

Open browser console (F12) and check:

```javascript
// 1. Check what zoom level shows grey tiles
console.log('Current zoom:', map.getZoom());

// 2. Check which tiles are being requested
// Look in Network tab for 404 errors on tile URLs like:
// /tiles/5/12/8.png (404) <- This tile doesn't exist

// 3. Verify metadata max_zoom matches available tiles
fetch('https://blocksplayground.blob.core.windows.net/floor-plan-tiles/YOUR_ID/metadata.json')
  .then(r => r.json())
  .then(m => console.log('Max zoom in metadata:', m.max_zoom));

// 4. Manually check if tile exists
// Try accessing a tile URL directly:
// https://blocksplayground.blob.core.windows.net/floor-plan-tiles/YOUR_ID/tiles/5/0/0.png
```

**Fix**: Re-upload your PDF to the `floor-plans/` container. The updated Azure Function will:
- Generate more zoom levels (up to level 12 instead of 6)
- Use higher resolution at max zoom (432 DPI)
- Support up to 20,000 pixel dimensions
- Create all necessary tiles to prevent grey squares

### Zoom Level Capabilities

The system now supports:
- **Up to 12 zoom levels** (0-11)
- **Up to 4,096 tiles** in each dimension at max zoom
- **PDF rendering at 432 DPI** (scale=6.0)
- **Max dimension: 20,000 pixels** before auto-scaling
- **Total tiles**: Can handle millions of tiles for very large floor plans

---

## File Structure Reference

```
floor-plan-tiles/
└── {floorplan-id}/
    ├── metadata.json          // Floor plan dimensions & config
    ├── preview.jpg            // 800px wide preview
    └── tiles/
        ├── 0/                 // Zoom level 0 (most zoomed out)
        │   └── 0/
        │       └── 0.png
        ├── 1/                 // Zoom level 1
        │   ├── 0/
        │   │   ├── 0.png
        │   │   └── 1.png
        │   └── 1/
        │       ├── 0.png
        │       └── 1.png
        └── 5/                 // Zoom level 5 (most zoomed in)
            └── ...            // Many tiles at highest detail
```
