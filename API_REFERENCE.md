# 🚀 Blocks Floorplan Tiler API Reference

Complete API reference for calling the floorplan tiling service, including authentication, endpoints, request/response formats, and examples.

---

## 🔐 API Credentials & Authentication

### Base URL
```
https://blockstilingservice.blackpond-228bbd7d.germanywestcentral.azurecontainerapps.io
```

### Authentication
All API endpoints (except health checks) require API key authentication via header:

```http
X-API-Key: 2oq4mH-_nubgyizh8AXwIcRMUJTIKTgNUKxtigOGEVs
```

### Storage Account
- **Account**: `blocksplayground`
- **Container**: `blocks` (PRIVATE)
- **Output Location**: `blocks/floorplans/{file_id}/`

---

## 📋 API Endpoints

### 1. Health Check (No Auth Required)

```http
GET /health
```

**Response:**
```json
{
  "status": "healthy"
}
```

**Example:**
```bash
curl https://blockstilingservice.blackpond-228bbd7d.germanywestcentral.azurecontainerapps.io/health
```

---

### 2. Submit Floorplan for Processing (Async)

```http
POST /api/process-floorplan
```

**Headers:**
```http
Content-Type: application/json
X-API-Key: 2oq4mH-_nubgyizh8AXwIcRMUJTIKTgNUKxtigOGEVs
```

**Request Body:**
```json
{
  "file_url": "https://blocksplayground.blob.core.windows.net/floor-plans/my-floorplan.pdf",
  "file_id": 12345
}
```

**Request Schema:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file_url` | string | ✅ Yes | Full URL to PDF file in Azure Blob Storage |
| `file_id` | integer | ✅ Yes | Unique numeric identifier for this floorplan |

**Success Response (202 Accepted):**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "queued",
  "message": "Job queued for processing",
  "status_url": "/api/status/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**Response Schema:**
| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | UUID to track job progress |
| `status` | string | Current status: `queued`, `processing`, `completed`, `failed` |
| `message` | string | Human-readable status message |
| `status_url` | string | Relative URL to check job status |

**Example - PowerShell:**
```powershell
$headers = @{
    "Content-Type" = "application/json"
    "X-API-Key" = "2oq4mH-_nubgyizh8AXwIcRMUJTIKTgNUKxtigOGEVs"
}

$body = @{
    file_url = "https://blocksplayground.blob.core.windows.net/floor-plans/plan-123.pdf"
    file_id = 12345
} | ConvertTo-Json

$response = Invoke-RestMethod -Uri "https://blockstilingservice.blackpond-228bbd7d.germanywestcentral.azurecontainerapps.io/api/process-floorplan" -Method POST -Headers $headers -Body $body

Write-Host "Job ID: $($response.job_id)"
```

**Example - cURL:**
```bash
curl -X POST \
  https://blockstilingservice.blackpond-228bbd7d.germanywestcentral.azurecontainerapps.io/api/process-floorplan \
  -H "Content-Type: application/json" \
  -H "X-API-Key: 2oq4mH-_nubgyizh8AXwIcRMUJTIKTgNUKxtigOGEVs" \
  -d '{
    "file_url": "https://blocksplayground.blob.core.windows.net/floor-plans/plan-123.pdf",
    "file_id": 12345
  }'
```

**Example - JavaScript/Fetch:**
```javascript
const response = await fetch('https://blockstilingservice.blackpond-228bbd7d.germanywestcentral.azurecontainerapps.io/api/process-floorplan', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': '2oq4mH-_nubgyizh8AXwIcRMUJTIKTgNUKxtigOGEVs'
  },
  body: JSON.stringify({
    file_url: 'https://blocksplayground.blob.core.windows.net/floor-plans/plan-123.pdf',
    file_id: 12345
  })
});

const result = await response.json();
console.log('Job ID:', result.job_id);
```

---

### 3. Check Job Status

```http
GET /api/status/{job_id}
```

**Headers:**
```http
X-API-Key: 2oq4mH-_nubgyizh8AXwIcRMUJTIKTgNUKxtigOGEVs
```

**URL Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | string | UUID returned from process-floorplan endpoint |

**Response - Processing:**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "processing",
  "progress": 45,
  "message": "Generating 8 zoom levels of tiles...",
  "created_at": "2025-10-28T10:30:00.123456",
  "updated_at": "2025-10-28T10:30:15.789012",
  "result": null
}
```

**Response - Completed:**
```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "completed",
  "progress": 100,
  "message": "Processing completed successfully",
  "created_at": "2025-10-28T10:30:00.123456",
  "updated_at": "2025-10-28T10:31:45.234567",
  "result": {
    "success": true,
    "floorplan_id": "12345",
    "dimensions": {
      "width": 15360,
      "height": 11520
    },
    "quality": {
      "dpi": 2520
    },
    "tiles": {
      "total": 1234,
      "zoom_levels": 9,
      "min_zoom": 0,
      "max_zoom": 8,
      "tile_size": 512
    },
    "urls": {
      "metadata": "https://blocksplayground.blob.core.windows.net/blocks/floorplans/12345/metadata.json",
      "preview": "https://blocksplayground.blob.core.windows.net/blocks/floorplans/12345/preview.png",
      "tiles": "https://blocksplayground.blob.core.windows.net/blocks/floorplans/12345/tiles/{z}/{x}/{y}.png"
    }
  }
}
```

**Response Schema:**
| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | Job UUID |
| `status` | string | `queued`, `processing`, `completed`, or `failed` |
| `progress` | integer | 0-100 percentage |
| `message` | string | Current operation message |
| `created_at` | string | ISO 8601 timestamp when job was created |
| `updated_at` | string | ISO 8601 timestamp of last update |
| `result` | object/null | Processing result (only when completed) |

**Example - PowerShell (with polling):**
```powershell
$headers = @{
    "X-API-Key" = "2oq4mH-_nubgyizh8AXwIcRMUJTIKTgNUKxtigOGEVs"
}

$jobId = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

do {
    $status = Invoke-RestMethod -Uri "https://blockstilingservice.blackpond-228bbd7d.germanywestcentral.azurecontainerapps.io/api/status/$jobId" -Headers $headers
    
    Write-Host "Status: $($status.status) - Progress: $($status.progress)% - $($status.message)"
    
    if ($status.status -eq "completed" -or $status.status -eq "failed") {
        break
    }
    
    Start-Sleep -Seconds 5
} while ($true)

if ($status.status -eq "completed") {
    Write-Host "✅ Success! Floorplan ID: $($status.result.floorplan_id)"
    Write-Host "Tile URL: $($status.result.urls.tiles)"
}
```

---

### 4. Delete Floorplan

```http
DELETE /api/delete-floorplan/{file_id}
```

**Headers:**
```http
X-API-Key: 2oq4mH-_nubgyizh8AXwIcRMUJTIKTgNUKxtigOGEVs
```

**URL Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `file_id` | integer | File ID to delete (matches file_id from process request) |

**Success Response:**
```json
{
  "success": true,
  "message": "All floorplans deleted successfully",
  "file_id": 12345,
  "deleted_count": 1245
}
```

**Example - PowerShell:**
```powershell
$headers = @{
    "X-API-Key" = "2oq4mH-_nubgyizh8AXwIcRMUJTIKTgNUKxtigOGEVs"
}

$fileId = 12345

Invoke-RestMethod -Uri "https://blockstilingservice.blackpond-228bbd7d.germanywestcentral.azurecontainerapps.io/api/delete-floorplan/$fileId" -Method DELETE -Headers $headers
```

---

### 5. Mass Delete Floorplans

```http
DELETE /api/mass-delete-floorplan
```

**Headers:**
```http
Content-Type: application/json
X-API-Key: 2oq4mH-_nubgyizh8AXwIcRMUJTIKTgNUKxtigOGEVs
```

**Request Body:**
```json
{
  "file_ids": [12345, 12346, 12347, 12348]
}
```

**Success Response:**
```json
{
  "success": true,
  "message": "Mass deletion completed: 4 successful, 0 failed",
  "total_items": 4,
  "successful_items": 4,
  "failed_items": 0,
  "total_blobs_deleted": 4980,
  "results": [
    {
      "file_id": 12345,
      "success": true,
      "deleted_count": 1245,
      "message": "All floorplans deleted successfully"
    },
    {
      "file_id": 12346,
      "success": true,
      "deleted_count": 1245,
      "message": "All floorplans deleted successfully"
    }
  ]
}
```

**Example - PowerShell:**
```powershell
$headers = @{
    "Content-Type" = "application/json"
    "X-API-Key" = "2oq4mH-_nubgyizh8AXwIcRMUJTIKTgNUKxtigOGEVs"
}

$body = @{
    file_ids = @(12345, 12346, 12347, 12348)
} | ConvertTo-Json

Invoke-RestMethod -Uri "https://blockstilingservice.blackpond-228bbd7d.germanywestcentral.azurecontainerapps.io/api/mass-delete-floorplan" -Method DELETE -Headers $headers -Body $body
```

---

## 🎯 Processing Logic & Behavior

### Smart Scaling System

The API automatically determines optimal quality based on PDF characteristics:

**Analysis Factors:**
1. **Physical Size**: PDF dimensions in inches (72 points = 1 inch)
2. **Content Type**: Scanned (raster) vs vector (CAD) detection
3. **File Complexity**: File size >500KB indicates detailed plans

**Scale Selection:**
| PDF Size | Content Type | File Size | Scale | DPI | Use Case |
|----------|--------------|-----------|-------|-----|----------|
| 36"+ | Any | Any | 40x | 2880 | Large architectural plans |
| 24-36" | Any | Any | 30x | 2160 | Medium architectural plans |
| 17-24" | Vector | >500KB | 40x | 2880 | Complex large-format plans |
| 17-24" | Scanned | Any | 15x | 1080 | Scanned large-format |
| 11-17" (A4) | Vector | >500KB | **35x** | **2520** | Complex standard plans |
| 11-17" (A4) | Vector | <500KB | 15x | 1080 | Simple documents |
| 11-17" (A4) | Scanned | Any | 12x | 864 | Scanned documents |
| <11" | Any | Any | 10x | 720 | Small documents |

**Memory Safety:**
- Maximum pixels: 300,000,000 (~17,000 × 17,000)
- Automatically reduces scale if would exceed limit

### Zoom Level Calculation

**Formula:**
```
optimal_zoom = ceil(log2(max_dimension / tile_size))
max_zoom = min(optimal_zoom + ZOOM_BOOST, 12)
```

**Configuration (via environment variables):**
- `ZOOM_BOOST`: 4 (adds 4 extra zoom levels for deep zoom with upscaling)
- `TILE_SIZE`: 512px
- `MAX_ZOOM_LIMIT`: 12

**Example:**
- A4 complex plan (2.7MB): 35x scale → 15,360 × 11,520 pixels → zoom 0-8 (9 levels)
- Large plan (36"): 40x scale → 28,800 × 21,600 pixels → zoom 0-10 (11 levels)

### Duplicate Detection

If a floorplan with the same `file_id` already exists:
- **Processing is skipped** (no re-processing)
- Returns existing floorplan URLs immediately
- Status: `completed` with existing data

---

## 📦 Output Structure

After successful processing, the following structure is created in Azure Blob Storage:

```
blocks/floorplans/{file_id}/
├── metadata.json          # Floorplan metadata & configuration
├── preview.jpg            # Low-res preview (800px max width)
├── {file_id}.pdf         # Original PDF (archived)
└── tiles/                 # Tile pyramid
    ├── 0/                 # Zoom level 0 (most zoomed out)
    │   └── 0/
    │       └── 0.png
    ├── 1/                 # Zoom level 1
    │   ├── 0/
    │   │   ├── 0.png
    │   │   └── 1.png
    │   └── 1/
    │       ├── 0.png
    │       └── 1.png
    └── 8/                 # Zoom level 8 (most zoomed in)
        └── ...
```

### Metadata JSON Structure

```json
{
  "floorplan_id": "12345",
  "file_id": 12345,
  "source_image": {
    "width": 15360,
    "height": 11520,
    "format": "RGBA"
  },
  "tile_size": 512,
  "max_zoom": 8,
  "min_zoom": 0,
  "zoom_levels": [0, 1, 2, 3, 4, 5, 6, 7, 8],
  "bounds": [[0, 0], [11520, 15360]],
  "coordinate_system": "Simple CRS (L.CRS.Simple) - pixel coordinates, compatible with MapTiler",
  "center": [5760, 7680],
  "created_at": "2025-10-28T10:31:45.234567",
  "tile_format": "png",
  "total_tiles": 1234,
  "quality_settings": {
    "pdf_scale": 35.0,
    "max_dimension": 30000,
    "dpi": 2520
  },
  "usage_notes": {
    "leaflet_crs": "Use L.CRS.Simple for flat floorplan display",
    "tile_url_template": "{baseUrl}/{z}/{x}/{y}.png",
    "bounds_format": "Geographic coordinates (lat/lon)"
  }
}
```

---

## 🗺️ Using the Tiles in Leaflet

```javascript
// Load metadata first
const metadata = await fetch('https://blocksplayground.blob.core.windows.net/blocks/floorplans/12345/metadata.json')
  .then(r => r.json());

// Initialize Leaflet map with Simple CRS
const map = L.map('map', {
  crs: L.CRS.Simple,
  minZoom: metadata.min_zoom,
  maxZoom: metadata.max_zoom
});

// Add tile layer
L.tileLayer('https://blocksplayground.blob.core.windows.net/blocks/floorplans/12345/tiles/{z}/{x}/{y}.png', {
  attribution: 'Blocks Floorplan',
  tileSize: metadata.tile_size,
  noWrap: true
}).addTo(map);

// Set view to center
map.fitBounds(metadata.bounds);
```

---

## ⚠️ Error Responses

### 401 Unauthorized
```json
{
  "detail": "API key is required. Please provide X-API-Key header."
}
```

### 403 Forbidden
```json
{
  "detail": "Invalid API key"
}
```

### 404 Not Found (Job Status)
```json
{
  "detail": "Job not found"
}
```

### 400 Bad Request
```json
{
  "detail": "File must be a PDF"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Storage connection string not configured"
}
```

---

## 📊 Performance Characteristics

| Metric | Value |
|--------|-------|
| **Processing Time** | 30 seconds - 5 minutes (depends on PDF size/complexity) |
| **Max PDF Size** | 100 MB (recommended) |
| **Max Image Dimensions** | 30,000 × 30,000 pixels |
| **Tile Size** | 512 × 512 pixels |
| **Output Format** | PNG with compression level 6 |
| **Quality Range** | 720 DPI - 2880 DPI (auto-selected) |
| **Container Resources** | 4 CPU cores, 8GB RAM |
| **Concurrent Jobs** | Up to 10 (auto-scaling) |

---

## 🔄 Complete Workflow Example

```powershell
# Step 1: Submit job
$headers = @{
    "Content-Type" = "application/json"
    "X-API-Key" = "2oq4mH-_nubgyizh8AXwIcRMUJTIKTgNUKxtigOGEVs"
}

$body = @{
    file_url = "https://blocksplayground.blob.core.windows.net/floor-plans/complex-plan.pdf"
    file_id = 98765
} | ConvertTo-Json

$job = Invoke-RestMethod -Uri "https://blockstilingservice.blackpond-228bbd7d.germanywestcentral.azurecontainerapps.io/api/process-floorplan" -Method POST -Headers $headers -Body $body

Write-Host "Job submitted: $($job.job_id)"

# Step 2: Poll for completion
do {
    Start-Sleep -Seconds 5
    $status = Invoke-RestMethod -Uri "https://blockstilingservice.blackpond-228bbd7d.germanywestcentral.azurecontainerapps.io/api/status/$($job.job_id)" -Headers $headers
    Write-Host "[$($status.status)] $($status.progress)% - $($status.message)"
} while ($status.status -ne "completed" -and $status.status -ne "failed")

# Step 3: Use the result
if ($status.status -eq "completed") {
    Write-Host "✅ Success!"
    Write-Host "Floorplan ID: $($status.result.floorplan_id)"
    Write-Host "Total tiles: $($status.result.tiles.total)"
    Write-Host "Quality: $($status.result.quality.dpi) DPI"
    Write-Host "Tile URL: $($status.result.urls.tiles)"
    
    # Step 4: Display in browser (example)
    $htmlUrl = "viewer.html?floorplan_id=$($status.result.floorplan_id)"
    Start-Process $htmlUrl
} else {
    Write-Host "❌ Processing failed: $($status.message)"
}
```

---

## 📞 Support

For issues or questions:
- Check logs in Azure Portal: Container Apps → blockstilingservice → Monitoring
- Verify API key is correct
- Ensure PDF is accessible from the provided URL
- Check PDF meets requirements (single page, <100MB, valid format)

---

**Last Updated**: October 28, 2025  
**API Version**: 2.0.0  
**Service**: Azure Container Apps (Germany West Central)
