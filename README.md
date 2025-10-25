# Blocks Floorplan Tiler Service

🗺️ High-performance PDF floorplan to tile pyramid converter for Leaflet/MapTiler display.

**Now running on Azure Container Apps!** ✨

## ✨ What's New - Container Apps Migration

✅ **Unlimited execution time** - No more 10-minute Azure Functions timeout!  
✅ **Up to 8GB RAM** - Support for ultra-high quality (PDF_SCALE=40, 2880 DPI)  
✅ **Up to 4 CPU cores** - Faster tile generation  
✅ **Auto-scaling** - From 0 to 10 replicas based on load  
✅ **Scale to zero** - No costs when idle  

## 🚀 Quick Start

### Local Development

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Set environment variable**:
   ```cmd
   set AZURE_STORAGE_CONNECTION_STRING=your_connection_string
   ```

3. **Run locally**:
   ```bash
   python -m uvicorn app:app --reload --port 8000
   ```

4. **Test**: Visit http://localhost:8000

### Docker Testing

```bash
# Build image
docker build -t floorplan-tiler:latest .

# Run container
docker run -p 8000:8000 \
  -e AZURE_STORAGE_CONNECTION_STRING="your_connection_string" \
  floorplan-tiler:latest
```

## ☁️ Azure Deployment

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for complete deployment guide including:
- Azure Container Apps setup
- CI/CD with GitHub Actions
- Monitoring and scaling configuration
- Troubleshooting tips

### Quick Deploy

```bash
# 1. Build and push to ACR
az acr build --registry YOUR_ACR --image floorplan-tiler:latest .

# 2. Deploy infrastructure
az deployment group create \
  --resource-group rg-floorplan-tiler \
  --template-file infra/main.bicep \
  --parameters infra/main.parameters.json
```

## 📡 API Reference

### POST `/api/process-floorplan`

Convert a PDF floorplan into a tiled pyramid for Leaflet display.

**Request Body**:
```json
{
  "file_url": "https://blocksplayground.blob.core.windows.net/floor-plans/myplan.pdf",
  "floorplan_name": "myplan.pdf"
}
```

**Response**:
```json
{
  "success": true,
  "floorplan_id": "myplan",
  "dimensions": {
    "width": 25257,
    "height": 4457
  },
  "quality": {
    "dpi": 1080,
    "base_image_size_mb": 12.5,
    "format": "WEBP"
  },
  "tiles": {
    "total": 1234,
    "zoom_levels": 11,
    "min_zoom": 0,
    "max_zoom": 10,
    "tile_size": 512
  },
  "urls": {
    "metadata": "https://.../metadata.json",
    "preview": "https://.../preview.jpg",
    "tiles": "https://.../tiles/{z}/{x}/{y}.png"
  }
}
```

### GET `/health`

Health check endpoint for Container Apps probes.

## 🎨 Quality Settings

Configure in `app.py`:

```python
# Current settings (safe for 4GB RAM)
PDF_SCALE = 15.0         # 1080 DPI
MAX_DIMENSION = 30000    # 30K pixels max
FORCED_MAX_Z_ENV = 10    # Zoom levels 0-10

# Ultra-high quality (requires 8GB RAM)
PDF_SCALE = 40.0         # 2880 DPI
MAX_DIMENSION = 50000    # 50K pixels max
FORCED_MAX_Z_ENV = 12    # Zoom levels 0-12
```

## 📂 Project Structure

```
blocksFloorplanTiler/
├── app.py                      # FastAPI application (replaces function_app.py)
├── Dockerfile                  # Multi-stage container build
├── requirements.txt            # Python dependencies
├── .dockerignore              # Docker build exclusions
├── infra/                     # Infrastructure as Code
│   ├── main.bicep            # Azure Container Apps deployment
│   └── main.parameters.json  # Deployment parameters
├── DEPLOYMENT.md             # Comprehensive deployment guide
└── README.md                 # This file
```

## 🔧 Configuration

### Environment Variables

- `AZURE_STORAGE_CONNECTION_STRING`: Required - Azure Storage connection string
- `PORT`: Optional - HTTP port (default: 8000)
- `PYTHONUNBUFFERED`: Optional - Python logging (default: 1)

### Scaling Configuration

Edit `infra/main.bicep`:

```bicep
minReplicas: 1        // Minimum instances (0 = scale to zero)
maxReplicas: 10       // Maximum instances
cpuCores: '2'         // CPU cores per instance (0.25-4)
memorySize: '4'       // Memory in GB (0.5-8)
```

## 📊 Monitoring

```bash
# View live logs
az containerapp logs show \
  --name blocks-floorplan-tiler \
  --resource-group rg-floorplan-tiler \
  --follow

# View metrics in Azure Portal
# Resource Group → Container App → Monitoring → Metrics
```

## 🆚 Azure Functions vs Container Apps

| Feature | Azure Functions | Container Apps |
|---------|----------------|----------------|
| **Timeout** | 10 min (Premium) | ⭐ Unlimited |
| **Memory** | 1.5-14GB | ⭐ 0.5-8GB (2:1 with CPU) |
| **CPU** | Shared/1 core | ⭐ 0.25-4 cores |
| **Scale to Zero** | ✅ Yes | ✅ Yes |
| **Cold Start** | ~1-5s | ~3-10s |
| **Cost (idle)** | $0 | $0 |
| **Cost (active)** | $$ | $ (cheaper) |

Container Apps is **better for this workload** due to unlimited timeout and higher resource limits.

## 🐛 Troubleshooting

**Image won't build?**
- Ensure Docker Desktop is running
- Check Dockerfile syntax
- Verify system dependencies

**Container crashes on startup?**
- Check logs: `az containerapp logs show ...`
- Verify storage connection string is valid
- Ensure memory allocation is sufficient (4GB+ recommended)

**Processing times out?**
- Container Apps has **unlimited timeout** ✅
- Check PDF is accessible from the URL
- Monitor memory usage (may need more RAM)

**Tiles not generating?**
- Verify storage container `floor-plans` exists
- Check write permissions on storage account
- Review logs for specific errors

## 📚 Related Documentation

- [DEPLOYMENT.md](DEPLOYMENT.md) - Complete deployment guide
- [Azure Container Apps Docs](https://learn.microsoft.com/azure/container-apps/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Leaflet CRS.Simple Guide](https://leafletjs.com/examples/crs-simple/crs-simple.html)

## 📄 License

Copyright © 2025 Blocks Floorplan Tiler Service

---

**Ready to deploy?** Check out [DEPLOYMENT.md](DEPLOYMENT.md) for step-by-step instructions! 🚀
