# 🚀 Quick Deploy - Source Code to Azure Container Apps

Deploy directly from source code - **No Docker or ACR required!**

## Prerequisites

- ✅ Azure CLI installed
- ✅ Azure subscription
- ✅ Storage account connection string ready

## Step-by-Step Deployment

### 1. Login to Azure

```powershell
az login
```

### 2. Set Variables (PowerShell)

```powershell
# Configuration
$resourceGroup = "rg-floorplan-tiler"
$location = "eastus"
$appName = "blocks-floorplan-tiler"
$storageConnStr = "YOUR_STORAGE_CONNECTION_STRING_HERE"
```

### 3. Create Resource Group

```powershell
az group create --name $resourceGroup --location $location
```

### 4. Create Container Apps Environment

```powershell
az containerapp env create `
  --name "$appName-env" `
  --resource-group $resourceGroup `
  --location $location
```

### 5. Deploy from Source Code

```powershell
az containerapp up `
  --name $appName `
  --resource-group $resourceGroup `
  --location $location `
  --environment "$appName-env" `
  --source . `
  --ingress external `
  --target-port 8000 `
  --env-vars `
    AZURE_STORAGE_CONNECTION_STRING="$storageConnStr" `
    PORT=8000 `
    PDF_SCALE=15.0 `
    FORCED_MAX_Z=10
```

This command will:
- ✅ Build your Docker image in Azure
- ✅ Create the container app
- ✅ Set environment variables
- ✅ Configure ingress (public endpoint)
- ✅ Deploy and start the app

**Wait 5-10 minutes** for Azure to build and deploy.

### 6. Get Your App URL

```powershell
az containerapp show `
  --name $appName `
  --resource-group $resourceGroup `
  --query properties.configuration.ingress.fqdn `
  --output tsv
```

### 7. Test the Deployment

```powershell
# Save the URL
$appUrl = az containerapp show --name $appName --resource-group $resourceGroup --query properties.configuration.ingress.fqdn --output tsv

# Test health endpoint
Invoke-WebRequest -Uri "https://$appUrl/health"

# Test main endpoint
Invoke-WebRequest -Uri "https://$appUrl/"
```

### 8. Test Processing Endpoint

```powershell
$body = @{
    file_url = "https://blocksplayground.blob.core.windows.net/floor-plans/your-test.pdf"
    floorplan_name = "test-plan.pdf"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "https://$appUrl/api/process-floorplan" `
  -Method POST `
  -Body $body `
  -ContentType "application/json"
```

---

## 🎨 Optional: Enable Ultra-High Quality (PDF_SCALE=40)

After initial deployment, update to use 8GB RAM:

```powershell
az containerapp update `
  --name $appName `
  --resource-group $resourceGroup `
  --set-env-vars `
    PDF_SCALE=40.0 `
    FORCED_MAX_Z=12 `
    MAX_DIMENSION=50000 `
  --cpu 4 `
  --memory 8Gi
```

---

## 📊 View Logs

```powershell
az containerapp logs show `
  --name $appName `
  --resource-group $resourceGroup `
  --follow
```

---

## 🔄 Update Deployment (After Code Changes)

When you make changes to your code:

```powershell
az containerapp up `
  --name $appName `
  --resource-group $resourceGroup `
  --source .
```

Azure will rebuild and redeploy automatically!

---

## 🆘 Troubleshooting

**Deployment fails?**
```powershell
# Check deployment logs
az containerapp logs show --name $appName --resource-group $resourceGroup --tail 100
```

**App not responding?**
```powershell
# Check app status
az containerapp show --name $appName --resource-group $resourceGroup --query properties.runningStatus
```

**Need to delete and start over?**
```powershell
az group delete --name $resourceGroup --yes --no-wait
```

---

## ✅ Success Checklist

- [ ] Azure CLI logged in
- [ ] Resource group created
- [ ] Container Apps environment created
- [ ] App deployed from source code
- [ ] Health endpoint returns 200
- [ ] API endpoint tested successfully
- [ ] Tiles uploaded to blob storage

---

**That's it!** Your app is now running on Azure Container Apps! 🎉

**App URL**: `https://blocks-floorplan-tiler.REGION.azurecontainerapps.io`
