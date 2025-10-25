# Blocks Floorplan Tiler API

Base URL: `https://blockstilingservice.blackpond-228bbd7d.germanywestcentral.azurecontainerapps.io`

## Authentication

All endpoints require `X-API-Key` header:
```
X-API-Key: your-api-key-here
```

## Smart Duplicate Handling

Before processing a floorplan, the service checks if any floorplan with the same `file_id` already exists. If found, processing is skipped and the existing floorplan information is returned. This prevents redundant processing and storage costs.

---

## Endpoints

### 1. POST `/api/process-floorplan`

Process a PDF floorplan and convert it to a tile pyramid for Leaflet/MapTiler.

**Request Body:**
```json
{
  "file_url": "https://blocksplayground.blob.core.windows.net/blocks/myfloorplan.pdf",
  "file_id": 123
}
```

**Response (Success):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "message": "Job queued for processing",
  "status_url": "/api/status/550e8400-e29b-41d4-a716-446655440000"
}
```

**Response (Duplicate Found):**
```json
{
  "success": true,
  "message": "Floorplan already exists for this file_id",
  "floorplan_id": "123-myfloorplan",
  "urls": {
    "metadata": "https://blocksplayground.blob.core.windows.net/blocks/floorplans/123-myfloorplan/metadata.json",
    "preview": "https://blocksplayground.blob.core.windows.net/blocks/floorplans/123-myfloorplan/preview.jpg",
    "tiles": "https://blocksplayground.blob.core.windows.net/blocks/floorplans/123-myfloorplan/tiles/{z}/{x}/{y}.png"
  }
}
```

---

### 2. GET `/api/status/{job_id}`

Check the status of a processing job.

**Parameters:**
- `job_id` (path): Job ID returned from POST `/api/process-floorplan`

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "progress": 100,
  "message": "Processing completed successfully",
  "created_at": "2025-10-26T10:00:00.000000",
  "updated_at": "2025-10-26T10:05:30.000000",
  "result": {
    "success": true,
    "floorplan_id": "123-myfloorplan",
    "dimensions": {
      "width": 15360,
      "height": 8640
    },
    "quality": {
      "dpi": 2880
    },
    "tiles": {
      "total": 1234,
      "zoom_levels": 10,
      "min_zoom": 0,
      "max_zoom": 9,
      "tile_size": 512
    },
    "urls": {
      "metadata": "https://blocksplayground.blob.core.windows.net/blocks/floorplans/123-myfloorplan/metadata.json",
      "preview": "https://blocksplayground.blob.core.windows.net/blocks/floorplans/123-myfloorplan/preview.png",
      "tiles": "https://blocksplayground.blob.core.windows.net/blocks/floorplans/123-myfloorplan/tiles/{z}/{x}/{y}.png"
    }
  }
}
```

**Status Values:**
- `queued`: Job is waiting to be processed
- `processing`: Job is currently being processed
- `completed`: Job finished successfully
- `failed`: Job failed with an error

---

### 3. DELETE `/api/delete-floorplan/{file_id}`

Delete a single floorplan by file_id. Removes all tiles, metadata, and preview images.

**Parameters:**
- `file_id` (path): File ID of the floorplan to delete

**Example:** `DELETE /api/delete-floorplan/123`

**Response:**
```json
{
  "success": true,
  "message": "All floorplans deleted successfully",
  "file_id": 123,
  "deleted_count": 1234
}
```

---

### 4. DELETE `/api/mass-delete-floorplan`

Delete multiple floorplans in a single request.

**Request Body:**
```json
{
  "file_ids": [1, 2, 5, 123]
}
```

**Response:**
```json
{
  "success": true,
  "message": "Mass deletion completed: 4 successful, 0 failed",
  "total_items": 4,
  "successful_items": 4,
  "failed_items": 0,
  "total_blobs_deleted": 4936,
  "results": [
    {
      "file_id": 1,
      "success": true,
      "deleted_count": 1234,
      "message": "All floorplans deleted successfully"
    },
    {
      "file_id": 2,
      "success": true,
      "deleted_count": 1234,
      "message": "All floorplans deleted successfully"
    }
  ]
}
```

---

## Storage Structure

Floorplans are stored in Azure Blob Storage with the following structure:

```
blocks/floorplans/{file_id}-{filename}/
├── metadata.json          # Floorplan metadata and configuration
├── preview.jpg            # Low-resolution preview image
├── {file_id}-{filename}.pdf  # Original PDF file
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
    └── ...                # Higher zoom levels
```

**Example:** For `file_id=123` and filename `myfloorplan.pdf`:
- Folder: `floorplans/123-myfloorplan/`
- Metadata: `floorplans/123-myfloorplan/metadata.json`
- Tiles: `floorplans/123-myfloorplan/tiles/{z}/{x}/{y}.png`

---

## Quality Settings

The service is configured for extremely high quality output:

- **DPI**: 2880 (40x scale factor from 72 DPI)
- **Max Dimension**: 30,000 pixels
- **Tile Size**: 512x512 pixels
- **Zoom Boost**: +3 levels beyond native resolution
- **Coordinate System**: Simple CRS (L.CRS.Simple) - pixel coordinates compatible with Leaflet and MapTiler

---

## Error Handling

All endpoints return appropriate HTTP status codes:

- `200 OK`: Request successful
- `400 Bad Request`: Invalid input (e.g., missing required fields, invalid URL)
- `401 Unauthorized`: Missing API key
- `403 Forbidden`: Invalid API key
- `404 Not Found`: Resource not found (e.g., job_id doesn't exist)
- `500 Internal Server Error`: Server-side error during processing

**Error Response Format:**
```json
{
  "detail": "Error message describing what went wrong"
}
```
