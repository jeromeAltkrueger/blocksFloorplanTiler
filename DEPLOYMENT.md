# Blocks Floorplan Tiler Service - Azure Container Apps Deployment

Complete guide for deploying the floorplan PDF tiling service to Azure Container Apps.

## 🏗️ Architecture Overview

This service converts PDF floorplans into tiled pyramids optimized for Leaflet/MapTiler display. Deployed as a containerized application on Azure Container Apps for:

- ✅ **Unlimited execution time** (no 10-minute timeout!)
- ✅ **Up to 8GB RAM** (supports PDF_SCALE=40 for 2880 DPI)
- ✅ **Up to 4 CPU cores** (fast tile generation)
- ✅ **Auto-scaling** (0 to 10 replicas based on load)
- ✅ **Scale to zero** (no costs when idle)

## 📋 Prerequisites

1. **Azure Subscription** with permissions to create resources
2. **Azure CLI** installed: https://aka.ms/azure-cli
3. **Docker Desktop** installed: https://www.docker.com/products/docker-desktop
4. **Azure Container Registry** (or Docker Hub for testing)
5. **Azure Storage Account** with `floor-plans` container

## 🚀 Quick Start - Local Testing

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Environment Variables

Windows (cmd):
```cmd
set AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=blocksplayground;AccountKey=YOUR_KEY;EndpointSuffix=core.windows.net
```

Windows (PowerShell):
```powershell
$env:AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=blocksplayground;AccountKey=YOUR_KEY;EndpointSuffix=core.windows.net"
```

### 3. Run Locally

```bash
python -m uvicorn app:app --reload --port 8000
```

Visit: http://localhost:8000 (health check)

### 4. Test the API

```powershell
# PowerShell example
$body = @{
    file_url = "https://blocksplayground.blob.core.windows.net/floor-plans/your-floorplan.pdf"
    floorplan_name = "test-plan.pdf"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/process-floorplan" -Method POST -Body $body -ContentType "application/json"
```

## 🐳 Docker Build & Test

### 1. Build Docker Image

```bash
docker build -t floorplan-tiler:latest .
```

### 2. Run Container Locally

```bash
docker run -p 8000:8000 \
  -e AZURE_STORAGE_CONNECTION_STRING="YOUR_CONNECTION_STRING" \
  floorplan-tiler:latest
```

Visit: http://localhost:8000/health

## ☁️ Azure Deployment

### Option A: Using Azure Container Registry (Recommended)

#### 1. Create Azure Container Registry

```bash
# Login to Azure
az login

# Create resource group (if needed)
az group create --name rg-floorplan-tiler --location eastus

# Create container registry
az acr create \
  --resource-group rg-floorplan-tiler \
  --name blocksacr \
  --sku Basic \
  --admin-enabled true
```

#### 2. Build & Push Image to ACR

```bash
# Login to ACR
az acr login --name blocksacr

# Build and push (ACR task - recommended)
az acr build \
  --registry blocksacr \
  --image floorplan-tiler:latest \
  --file Dockerfile \
  .

# OR: Tag and push locally built image
docker tag floorplan-tiler:latest blocksacr.azurecr.io/floorplan-tiler:latest
docker push blocksacr.azurecr.io/floorplan-tiler:latest
```

#### 3. Update Parameters File

Edit `infra/main.parameters.json`:

```json
{
  "containerImage": {
    "value": "blocksacr.azurecr.io/floorplan-tiler:latest"
  },
  "storageConnectionString": {
    "value": "DefaultEndpointsProtocol=https;AccountName=blocksplayground;AccountKey=YOUR_KEY;EndpointSuffix=core.windows.net"
  }
}
```

#### 4. Deploy Infrastructure

```bash
# Preview deployment (what-if)
az deployment group what-if \
  --resource-group rg-floorplan-tiler \
  --template-file infra/main.bicep \
  --parameters infra/main.parameters.json

# Deploy
az deployment group create \
  --resource-group rg-floorplan-tiler \
  --template-file infra/main.bicep \
  --parameters infra/main.parameters.json \
  --name floorplan-tiler-deployment
```

#### 5. Get App URL

```bash
az deployment group show \
  --resource-group rg-floorplan-tiler \
  --name floorplan-tiler-deployment \
  --query properties.outputs.containerAppUrl.value \
  --output tsv
```

### Option B: Using Azure CLI (Quick Deploy)

```bash
# Create Container App directly
az containerapp create \
  --name blocks-floorplan-tiler \
  --resource-group rg-floorplan-tiler \
  --image blocksacr.azurecr.io/floorplan-tiler:latest \
  --environment blocks-env \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 10 \
  --cpu 2 \
  --memory 4Gi \
  --secrets storage-conn-str="YOUR_CONNECTION_STRING" \
  --env-vars AZURE_STORAGE_CONNECTION_STRING=secretref:storage-conn-str PORT=8000
```

## 🔧 Configuration

### Scaling Configuration

Adjust in `infra/main.bicep`:

- `minReplicas`: 0-1 (0 = scale to zero when idle)
- `maxReplicas`: 1-30 (max concurrent instances)
- `cpuCores`: 0.25-4 (CPU per instance)
- `memorySize`: 0.5-8GB (must maintain 2:1 ratio with CPU)

### Performance Tuning

For **PDF_SCALE=40** (2880 DPI, ultra-high quality):

```bicep
cpuCores: '4'      // 4 cores for faster processing
memorySize: '8'    // 8GB RAM for large images
```

For **PDF_SCALE=15** (1080 DPI, balanced):

```bicep
cpuCores: '2'      // 2 cores sufficient
memorySize: '4'    // 4GB RAM enough
```

## 📊 Monitoring & Logs

### View Live Logs

```bash
az containerapp logs show \
  --name blocks-floorplan-tiler \
  --resource-group rg-floorplan-tiler \
  --follow
```

### View Metrics in Portal

1. Navigate to: https://portal.azure.com
2. Go to Resource Group → `rg-floorplan-tiler`
3. Open Container App → **Monitoring** → **Metrics**

### Log Analytics Queries

```kusto
// Recent errors
ContainerAppConsoleLogs_CL
| where Log_s contains "ERROR"
| order by TimeGenerated desc
| take 50

// Processing times
ContainerAppConsoleLogs_CL
| where Log_s contains "Successfully created"
| project TimeGenerated, Log_s
```

## 🔄 CI/CD Integration

### GitHub Actions Example

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Azure Container Apps

on:
  push:
    branches: [main]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Azure Login
        uses: azure/login@v1
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}
      
      - name: Build and Push to ACR
        run: |
          az acr build \
            --registry blocksacr \
            --image floorplan-tiler:${{ github.sha }} \
            --image floorplan-tiler:latest \
            --file Dockerfile \
            .
      
      - name: Deploy to Container Apps
        run: |
          az containerapp update \
            --name blocks-floorplan-tiler \
            --resource-group rg-floorplan-tiler \
            --image blocksacr.azurecr.io/floorplan-tiler:${{ github.sha }}
```

## 🧪 Testing Deployment

```bash
# Get the app URL
APP_URL=$(az containerapp show \
  --name blocks-floorplan-tiler \
  --resource-group rg-floorplan-tiler \
  --query properties.configuration.ingress.fqdn \
  --output tsv)

# Test health endpoint
curl https://$APP_URL/health

# Test processing endpoint
curl -X POST https://$APP_URL/api/process-floorplan \
  -H "Content-Type: application/json" \
  -d '{
    "file_url": "https://blocksplayground.blob.core.windows.net/floor-plans/test.pdf",
    "floorplan_name": "test-plan.pdf"
  }'
```

## 💰 Cost Optimization

- **Scale to Zero**: Set `minReplicas: 0` to pay nothing when idle
- **Right-size Resources**: Start with 2 cores/4GB, adjust based on metrics
- **Auto-scaling**: Max replicas based on expected load
- **Consumption Plan**: Container Apps Consumption is cheaper than dedicated

Estimated costs (eastus):
- 2 cores + 4GB: ~$0.10/hour when running
- Scale to zero: $0/hour when idle
- 100 hours/month: ~$10/month

## 🆘 Troubleshooting

### Container Won't Start

```bash
# Check container logs
az containerapp logs show \
  --name blocks-floorplan-tiler \
  --resource-group rg-floorplan-tiler \
  --tail 100

# Check revision status
az containerapp revision list \
  --name blocks-floorplan-tiler \
  --resource-group rg-floorplan-tiler
```

### Memory Issues

Increase memory in deployment:

```bash
az containerapp update \
  --name blocks-floorplan-tiler \
  --resource-group rg-floorplan-tiler \
  --cpu 4 \
  --memory 8Gi
```

### Timeout Issues

Container Apps has **unlimited timeout** - if processing is still timing out, check:
1. Storage connection is valid
2. PDF file is accessible
3. Memory is sufficient for PDF_SCALE setting

## 📚 Additional Resources

- [Azure Container Apps Documentation](https://learn.microsoft.com/azure/container-apps/)
- [Bicep Documentation](https://learn.microsoft.com/azure/azure-resource-manager/bicep/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)

## 🔐 Security Best Practices

1. **Store secrets in Azure Key Vault** (not in parameters file)
2. **Use Managed Identity** for ACR access
3. **Enable HTTPS only** (ingress.allowInsecure: false)
4. **Regular image updates** (patch vulnerabilities)
5. **Network isolation** (consider VNET integration)

---

**Need Help?** Check the [Azure Container Apps limits](https://learn.microsoft.com/azure/container-apps/quotas) or review logs for errors.
