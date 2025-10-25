# ✅ Deployment Checklist - Azure Container Apps

Use this checklist to ensure a successful deployment of your floorplan tiler service.

## 📋 Pre-Deployment Checklist

### Prerequisites
- [ ] Azure subscription with active credits/billing
- [ ] Azure CLI installed (`az --version`)
- [ ] Docker Desktop installed and running (`docker version`)
- [ ] Access to Azure Storage account `blocksplayground`
- [ ] `floor-plans` container exists in storage account

### Configuration
- [ ] Reviewed `app.py` configuration settings (PDF_SCALE, etc.)
- [ ] Updated `infra/main.parameters.json` with your values
- [ ] Decided on quality settings (standard 15.0 vs ultra 40.0)
- [ ] Determined resource allocation (CPU/Memory)

---

## 🧪 Local Testing Checklist

### Test 1: Local Python (No Docker)
- [ ] Installed dependencies: `pip install -r requirements.txt`
- [ ] Set `AZURE_STORAGE_CONNECTION_STRING` environment variable
- [ ] Started app: `python -m uvicorn app:app --reload --port 8000`
- [ ] Health check works: `curl http://localhost:8000/health`
- [ ] Tested POST endpoint with sample PDF
- [ ] Verified tiles uploaded to blob storage

**If any test fails**, check logs and fix before proceeding.

### Test 2: Docker Build & Run
- [ ] Built Docker image: `docker build -t floorplan-tiler:latest .`
- [ ] Build completed without errors
- [ ] Image size is reasonable (~500-800MB)
- [ ] Started container with env vars
- [ ] Health check works inside container
- [ ] Tested POST endpoint through container
- [ ] Verified tiles uploaded correctly

**If any test fails**, review Dockerfile and fix before Azure deployment.

---

## ☁️ Azure Deployment Checklist

### Step 1: Azure Login & Resource Group
- [ ] Logged in: `az login`
- [ ] Selected correct subscription
- [ ] Created resource group: `az group create --name rg-floorplan-tiler --location eastus`
- [ ] Verified resource group exists

### Step 2: Container Registry Setup
- [ ] Created ACR: `az acr create --name blocksacr --resource-group rg-floorplan-tiler --sku Basic`
- [ ] Enabled admin access (for testing): `az acr update --name blocksacr --admin-enabled true`
- [ ] Logged into ACR: `az acr login --name blocksacr`
- [ ] Verified login successful

### Step 3: Build & Push Image
- [ ] Built image in ACR: `az acr build --registry blocksacr --image floorplan-tiler:latest .`
- [ ] OR tagged local image: `docker tag floorplan-tiler:latest blocksacr.azurecr.io/floorplan-tiler:latest`
- [ ] OR pushed local image: `docker push blocksacr.azurecr.io/floorplan-tiler:latest`
- [ ] Verified image in ACR: `az acr repository list --name blocksacr`

### Step 4: Update Parameters
- [ ] Edited `infra/main.parameters.json`
- [ ] Set `containerImage` to your ACR URL (e.g., `blocksacr.azurecr.io/floorplan-tiler:latest`)
- [ ] Set `storageConnectionString` to your storage account connection string
- [ ] Configured `cpuCores` and `memorySize` based on quality settings
- [ ] Set `location` to your preferred region (e.g., `eastus`)

**Standard Quality (PDF_SCALE=15)**:
```json
"cpuCores": { "value": "2" },
"memorySize": { "value": "4" }
```

**Ultra Quality (PDF_SCALE=40)**:
```json
"cpuCores": { "value": "4" },
"memorySize": { "value": "8" }
```

### Step 5: Validate Deployment (What-If)
- [ ] Ran what-if: `az deployment group what-if --resource-group rg-floorplan-tiler --template-file infra/main.bicep --parameters infra/main.parameters.json`
- [ ] Reviewed resources to be created
- [ ] No errors or warnings in what-if output
- [ ] Confirmed resource names and configurations

### Step 6: Deploy Infrastructure
- [ ] Deployed: `az deployment group create --resource-group rg-floorplan-tiler --template-file infra/main.bicep --parameters infra/main.parameters.json --name floorplan-deployment`
- [ ] Deployment succeeded (no errors)
- [ ] Waited for deployment to complete (~5-10 minutes)

### Step 7: Get App URL
- [ ] Retrieved URL: `az deployment group show --resource-group rg-floorplan-tiler --name floorplan-deployment --query properties.outputs.containerAppUrl.value --output tsv`
- [ ] Saved URL for testing: `____________________________________`

---

## 🧪 Post-Deployment Testing

### Verify Container App
- [ ] Health endpoint works: `curl https://YOUR_APP_URL/health`
- [ ] Root endpoint works: `curl https://YOUR_APP_URL/`
- [ ] Container is running (check Azure Portal)
- [ ] No errors in container logs

### Test API Endpoint
- [ ] Prepared test PDF URL
- [ ] Sent POST request to `/api/process-floorplan`
- [ ] Request accepted (200 response)
- [ ] Processing completed successfully
- [ ] Tiles uploaded to blob storage
- [ ] Metadata.json accessible
- [ ] Preview.jpg accessible
- [ ] Tiles accessible at `/tiles/{z}/{x}/{y}.png`

**Sample test request**:
```bash
curl -X POST https://YOUR_APP_URL/api/process-floorplan \
  -H "Content-Type: application/json" \
  -d '{
    "file_url": "https://blocksplayground.blob.core.windows.net/floor-plans/test.pdf",
    "floorplan_name": "test-plan.pdf"
  }'
```

### Test Quality Settings (If using PDF_SCALE=40)
- [ ] Configured environment variables for ultra quality
- [ ] Processed a test PDF
- [ ] Verified higher resolution output
- [ ] Checked memory usage in Azure Portal
- [ ] No out-of-memory errors
- [ ] Processing time acceptable

---

## 📊 Monitoring Setup

### Configure Monitoring
- [ ] Opened Azure Portal
- [ ] Found Container App resource
- [ ] Reviewed **Metrics** tab
- [ ] Set up alerts (optional):
  - [ ] CPU usage > 80%
  - [ ] Memory usage > 90%
  - [ ] HTTP 5xx errors > 5
- [ ] Enabled Application Insights (optional)

### Review Logs
- [ ] Viewed live logs: `az containerapp logs show --name blocks-floorplan-tiler --resource-group rg-floorplan-tiler --follow`
- [ ] No critical errors in logs
- [ ] Application startup successful
- [ ] Health checks passing

---

## 🎯 Quality Configuration (Optional)

### If Using Standard Quality (PDF_SCALE=15) - DEFAULT
- [ ] No additional configuration needed
- [ ] Works with 2 cores + 4GB RAM
- [ ] Good for most floorplans

### If Using Ultra Quality (PDF_SCALE=40) - YOUR REQUEST
- [ ] Updated container app environment variables:
  ```bash
  az containerapp update \
    --name blocks-floorplan-tiler \
    --resource-group rg-floorplan-tiler \
    --set-env-vars PDF_SCALE=40.0 FORCED_MAX_Z=12 MAX_DIMENSION=50000 \
    --cpu 4 \
    --memory 8Gi
  ```
- [ ] Verified settings applied
- [ ] Tested with sample PDF
- [ ] Confirmed ultra-high quality output
- [ ] No memory errors

---

## 🔄 Optional: CI/CD Setup

### GitHub Actions (Optional)
- [ ] Created `.github/workflows/deploy.yml`
- [ ] Added Azure credentials as GitHub secret
- [ ] Configured ACR push
- [ ] Configured Container App update
- [ ] Tested workflow with commit
- [ ] Verified auto-deployment works

---

## 📝 Documentation

### Update Team Documentation
- [ ] Shared new API endpoint URL with team
- [ ] Updated any client applications with new URL
- [ ] Documented environment variable configuration
- [ ] Added monitoring dashboard links
- [ ] Noted any changes from Azure Functions version

---

## ✅ Final Verification

### Production Readiness
- [ ] All tests passed (local + Docker + Azure)
- [ ] Container App running in Azure
- [ ] API endpoint accessible publicly
- [ ] Health checks passing
- [ ] Logs show no errors
- [ ] Resource utilization acceptable
- [ ] Auto-scaling configured
- [ ] Monitoring/alerts set up
- [ ] Team informed of new endpoint

### Clean Up Old Resources (Optional)
- [ ] Archived old Azure Functions code
- [ ] Deleted old Azure Functions app (if no longer needed)
- [ ] Updated DNS/routing if applicable
- [ ] Removed unused resources

---

## 🎉 Deployment Complete!

Once all checkboxes are complete, your floorplan tiler service is successfully deployed to Azure Container Apps!

### Next Steps
1. **Monitor for 24 hours** to ensure stability
2. **Review metrics** and adjust resources if needed
3. **Test with production workloads** gradually
4. **Document any issues** and resolutions
5. **Set up PDF_SCALE=40** when ready for ultra quality

### Support Resources
- [DEPLOYMENT.md](DEPLOYMENT.md) - Full deployment guide
- [MIGRATION_SUMMARY.md](MIGRATION_SUMMARY.md) - Migration details
- [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) - Config reference
- [Azure Container Apps Docs](https://learn.microsoft.com/azure/container-apps/)

---

**Congratulations! 🚀 Your service is now running on Azure Container Apps with unlimited timeout and up to 8GB RAM for ultra-high quality processing!**
