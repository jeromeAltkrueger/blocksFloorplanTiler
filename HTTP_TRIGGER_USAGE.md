# HTTP Trigger Usage

## Overview
The floorplan tiler now accepts HTTP POST requests with a PDF file URL instead of blob storage triggers.

## Endpoint
```
POST https://<your-function-app>.azurewebsites.net/api/process-floorplan
```

## Request Format

### Headers
```
Content-Type: application/json
```

### Body
```json
{
  "file_url": "https://example.com/path/to/floorplan.pdf",
  "floorplan_name": "my-floorplan.pdf"  // Optional, extracted from URL if not provided
}
```

### Example with cURL
```bash
curl -X POST https://<your-function-app>.azurewebsites.net/api/process-floorplan \
  -H "Content-Type: application/json" \
  -d '{
    "file_url": "https://example.com/floorplan.pdf",
    "floorplan_name": "office-floor-1.pdf"
  }'
```

### Example with JavaScript
```javascript
const response = await fetch('https://<your-function-app>.azurewebsites.net/api/process-floorplan', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    file_url: 'https://example.com/floorplan.pdf',
    floorplan_name: 'office-floor-1.pdf'
  })
});

const result = await response.json();
console.log(result);
```

### Example with Python
```python
import requests

response = requests.post(
    'https://<your-function-app>.azurewebsites.net/api/process-floorplan',
    json={
        'file_url': 'https://example.com/floorplan.pdf',
        'floorplan_name': 'office-floor-1.pdf'
    }
)

result = response.json()
print(result)
```

## Response Format

### Success (200 OK)
```json
{
  "success": true,
  "floorplan_id": "office-floor-1",
  "dimensions": {
    "width": 25257,
    "height": 4457
  },
  "quality": {
    "dpi": 2160,
    "base_image_size_mb": 15.43,
    "format": "WEBP"
  },
  "tiles": {
    "total": 628,
    "zoom_levels": 4,
    "min_zoom": 2,
    "max_zoom": 5,
    "tile_size": 512
  },
  "urls": {
    "metadata": "https://blocksplayground.blob.core.windows.net/floor-plans/office-floor-1/metadata.json",
    "preview": "https://blocksplayground.blob.core.windows.net/floor-plans/office-floor-1/preview.png",
    "tiles": "https://blocksplayground.blob.core.windows.net/floor-plans/office-floor-1/tiles/{z}/{x}/{y}.png"
  }
}
```

### Error Responses

#### Missing file_url (400 Bad Request)
```json
{
  "error": "Missing 'file_url' in request body"
}
```

#### Invalid PDF (400 Bad Request)
```json
{
  "error": "File must be a PDF"
}
```

#### Download failed (400 Bad Request)
```json
{
  "error": "Failed to download file: <error details>"
}
```

#### Processing failed (500 Internal Server Error)
```json
{
  "error": "Processing failed: <error details>"
}
```

## Processing Details

The function will:
1. Download the PDF from the provided URL
2. Convert PDF to ultra-high quality image (2160 DPI)
3. Generate tile pyramid (zoom levels 2-5)
4. Upload tiles, metadata, and preview to blob storage
5. Return processing results with URLs

**Processing time:** Typically 30-60 seconds depending on PDF size and complexity.

## Notes

- The PDF must be publicly accessible at the provided URL
- Maximum PDF size depends on Azure Function timeout settings (default: 5 minutes)
- Tiles are stored in: `floor-plans/{floorplan_id}/tiles/{z}/{x}/{y}.png`
- Uses Simple CRS (L.CRS.Simple) coordinate system
- WebP compression for optimal file sizes
