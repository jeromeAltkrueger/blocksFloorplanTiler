# Step-by-step commands to run NOW

# Step 1: Login to Azure
az login

# Step 2: Set your variables (copy and paste these together)
$resourceGroup = "rg-floorplan-tiler"
$location = "eastus"
$appName = "blocks-floorplan-tiler"
$storageConnStr = "DefaultEndpointsProtocol=https;AccountName=blocksplayground;AccountKey=kkEgPRG9ve1s/1mv/xNXdMwpd4Yp7tQVnweFnQvbWCK45khrlyJJnhLVKKZXB8BS/fzhRIPkYtEO+AStKbWzrw==;EndpointSuffix=core.windows.net"

# Step 3: Create resource group
az group create --name $resourceGroup --location $location

# Step 4: Create Container Apps environment (takes ~2 minutes)
az containerapp env create --name "$appName-env" --resource-group $resourceGroup --location $location

# Step 5: Deploy from source code (takes ~5-10 minutes)
az containerapp up --name $appName --resource-group $resourceGroup --location $location --environment "$appName-env" --source . --ingress external --target-port 8000 --env-vars AZURE_STORAGE_CONNECTION_STRING="$storageConnStr" PORT=8000 PDF_SCALE=15.0 FORCED_MAX_Z=10

# Step 6: Get your app URL
az containerapp show --name $appName --resource-group $resourceGroup --query properties.configuration.ingress.fqdn --output tsv

# Step 7: Test it
$appUrl = az containerapp show --name $appName --resource-group $resourceGroup --query properties.configuration.ingress.fqdn --output tsv
Invoke-WebRequest -Uri "https://$appUrl/health"
