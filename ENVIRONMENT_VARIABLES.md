# ⚙️ Environment Variables Reference

## Required Variables

### `AZURE_STORAGE_CONNECTION_STRING` (Required)
Azure Storage account connection string for uploading tiles.

**Example**:
```
DefaultEndpointsProtocol=https;AccountName=blocksplayground;AccountKey=YOUR_KEY;EndpointSuffix=core.windows.net
```

**How to get**:
```bash
az storage account show-connection-string \
  --name blocksplayground \
  --resource-group rg-floorplan-tiler \
  --query connectionString \
  --output tsv
```

---

## Optional Variables - Quality Settings

### `PDF_SCALE` (Default: `15.0`)
Scale factor for PDF rendering. Higher = better quality but more memory.

**Values**:
- `15.0` = 1080 DPI (standard quality, 4GB RAM) ✅ Safe default
- `20.0` = 1440 DPI (high quality, 4-6GB RAM)
- `30.0` = 2160 DPI (very high quality, 6-8GB RAM)
- `40.0` = 2880 DPI (ultra-high quality, 8GB RAM) ⭐ Your target!

**Example**:
```bash
# Windows
set PDF_SCALE=40.0

# Docker
docker run -e PDF_SCALE=40.0 ...

# Azure Container Apps (Bicep)
{
  name: 'PDF_SCALE'
  value: '40.0'
}
```

---

### `MAX_DIMENSION` (Default: `30000`)
Maximum width or height in pixels before reducing scale.

**Values**:
- `20000` = 20K pixels (safer for low memory)
- `30000` = 30K pixels (default)
- `40000` = 40K pixels (high quality)
- `50000` = 50K pixels (ultra-high, requires more RAM)

**Example**:
```bash
set MAX_DIMENSION=50000
```

---

### `FORCED_MAX_Z` (Default: `10`)
Maximum zoom level for tile generation.

**Values**:
- `8` = Zoom levels 0-8 (fewer tiles)
- `10` = Zoom levels 0-10 (default)
- `12` = Zoom levels 0-12 (more zoom, upscaling)
- `15` = Zoom levels 0-15 (deep zoom, heavy upscaling)

**Note**: Higher zoom levels beyond native resolution will **upscale** the image.

**Example**:
```bash
set FORCED_MAX_Z=12
```

---

### `TILE_SIZE` (Default: `512`)
Size of each tile in pixels.

**Values**:
- `256` = Standard Leaflet tile size
- `512` = Default (better for high-res floorplans) ✅
- `1024` = Large tiles (fewer files, more memory per tile)

**Example**:
```bash
set TILE_SIZE=512
```

---

### `MIN_ZOOM` (Default: `0`)
Minimum zoom level to generate.

**Values**:
- `0` = Most zoomed out (default)
- `2` = Skip lowest zoom levels (fewer tiles)

**Example**:
```bash
set MIN_ZOOM=0
```

---

## Optional Variables - Application Settings

### `PORT` (Default: `8000`)
HTTP port for the application to listen on.

**Example**:
```bash
set PORT=8080
```

---

### `PYTHONUNBUFFERED` (Default: `1`)
Disable Python output buffering for real-time logs.

**Values**:
- `1` = Unbuffered (recommended) ✅
- `0` = Buffered

---

## 🎯 Recommended Configurations

### Standard Quality (4GB RAM, 2 cores)
```bash
AZURE_STORAGE_CONNECTION_STRING=...
PDF_SCALE=15.0
MAX_DIMENSION=30000
FORCED_MAX_Z=10
TILE_SIZE=512
MIN_ZOOM=0
```

**Use case**: Most floorplans, balanced quality/performance

---

### High Quality (6GB RAM, 2-4 cores)
```bash
AZURE_STORAGE_CONNECTION_STRING=...
PDF_SCALE=25.0
MAX_DIMENSION=40000
FORCED_MAX_Z=11
TILE_SIZE=512
MIN_ZOOM=0
```

**Use case**: Detailed architectural drawings

---

### Ultra-High Quality (8GB RAM, 4 cores) ⭐
```bash
AZURE_STORAGE_CONNECTION_STRING=...
PDF_SCALE=40.0
MAX_DIMENSION=50000
FORCED_MAX_Z=12
TILE_SIZE=512
MIN_ZOOM=0
```

**Use case**: Maximum detail, large format prints, your requirement!

---

## 🐳 Docker Examples

### Standard Quality
```bash
docker run -p 8000:8000 \
  -e AZURE_STORAGE_CONNECTION_STRING="..." \
  -e PDF_SCALE=15.0 \
  floorplan-tiler:latest
```

### Ultra-High Quality
```bash
docker run -p 8000:8000 \
  -e AZURE_STORAGE_CONNECTION_STRING="..." \
  -e PDF_SCALE=40.0 \
  -e MAX_DIMENSION=50000 \
  -e FORCED_MAX_Z=12 \
  floorplan-tiler:latest
```

---

## ☁️ Azure Container Apps Examples

### Update via CLI
```bash
az containerapp update \
  --name blocks-floorplan-tiler \
  --resource-group rg-floorplan-tiler \
  --set-env-vars \
    PDF_SCALE=40.0 \
    MAX_DIMENSION=50000 \
    FORCED_MAX_Z=12 \
  --cpu 4 \
  --memory 8Gi
```

### Update via Bicep
```bicep
env: [
  {
    name: 'AZURE_STORAGE_CONNECTION_STRING'
    secretRef: 'storage-connection-string'
  }
  {
    name: 'PDF_SCALE'
    value: '40.0'
  }
  {
    name: 'MAX_DIMENSION'
    value: '50000'
  }
  {
    name: 'FORCED_MAX_Z'
    value: '12'
  }
  {
    name: 'TILE_SIZE'
    value: '512'
  }
  {
    name: 'MIN_ZOOM'
    value: '0'
  }
  {
    name: 'PORT'
    value: '8000'
  }
]
```

---

## 📊 Memory Requirements by PDF_SCALE

| PDF_SCALE | DPI  | Typical Image Size | RAM Required | CPU Recommended |
|-----------|------|-------------------|--------------|----------------|
| 10.0      | 720  | ~10K x 2K         | 2GB          | 1-2 cores      |
| 15.0      | 1080 | ~15K x 3K         | 4GB          | 2 cores        |
| 20.0      | 1440 | ~20K x 4K         | 4-6GB        | 2-4 cores      |
| 30.0      | 2160 | ~30K x 6K         | 6-8GB        | 4 cores        |
| 40.0      | 2880 | ~40K x 8K         | 8GB          | 4 cores        |

---

## 🔍 How to Check Current Settings

### Local/Docker
```bash
# Check environment
python -c "import os; print(f'PDF_SCALE={os.environ.get(\"PDF_SCALE\", \"15.0\")}')"
```

### Azure Container Apps
```bash
# List environment variables
az containerapp show \
  --name blocks-floorplan-tiler \
  --resource-group rg-floorplan-tiler \
  --query properties.template.containers[0].env
```

---

## 💡 Tips

1. **Start with defaults** and increase gradually based on requirements
2. **Monitor memory usage** in Azure Portal metrics
3. **Test locally with Docker** before deploying to Azure
4. **Use PDF_SCALE=40** only when you need ultra-high quality
5. **Ensure RAM is sufficient** (8GB for PDF_SCALE=40)
6. **Consider processing time**: Higher scale = longer processing

---

## 🆘 Troubleshooting

**Out of Memory?**
- Reduce `PDF_SCALE`
- Reduce `MAX_DIMENSION`
- Increase container RAM allocation

**Processing too slow?**
- Increase CPU cores
- Reduce `FORCED_MAX_Z` (fewer zoom levels)
- Use smaller `TILE_SIZE` (256 instead of 512)

**Quality not sufficient?**
- Increase `PDF_SCALE` (up to 40.0)
- Increase `MAX_DIMENSION`
- Add more zoom levels with `FORCED_MAX_Z`

---

**See Also**: [DEPLOYMENT.md](DEPLOYMENT.md) for complete deployment guide
