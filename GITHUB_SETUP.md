# 🚀 GitHub Setup Commands - Run These Step by Step

# ============================================
# STEP 1: Create GitHub Repository
# ============================================
# Go to: https://github.com/new
# - Repository name: blocksFloorplanTiler
# - Description: High-performance PDF floorplan tiler for Azure Container Apps
# - Visibility: Private (recommended) or Public
# - DO NOT check "Add a README" (you already have one)
# - Click "Create repository"
# 
# After creating, come back here and continue with Step 2


# ============================================
# STEP 2: Initialize Git & Commit Your Code
# ============================================

# Check if git is initialized
git status

# If not initialized, run:
git init

# Add all files
git add .

# Check what will be committed (review the list)
git status

# Commit everything
git commit -m "Initial commit - Azure Container Apps ready deployment"


# ============================================
# STEP 3: Connect to GitHub & Push
# ============================================

# Add GitHub as remote (REPLACE jeromeAltkrueger if different)
git remote add origin https://github.com/jeromeAltkrueger/blocksFloorplanTiler.git

# Rename branch to 'main' (GitHub default)
git branch -M main

# Push to GitHub
git push -u origin main

# ============================================
# AUTHENTICATION
# ============================================
# When prompted for credentials:
# - Username: jeromeAltkrueger
# - Password: USE YOUR PERSONAL ACCESS TOKEN (NOT your GitHub password!)
#
# Get token from: https://github.com/settings/tokens/new
# - Note: "Container Apps Deployment"
# - Expiration: 90 days (or your choice)
# - Select scopes: ✓ repo (all), ✓ workflow
# - Click "Generate token"
# - COPY THE TOKEN (you won't see it again!)


# ============================================
# STEP 4: Verify Upload
# ============================================
# Visit: https://github.com/jeromeAltkrueger/blocksFloorplanTiler
# You should see all your files!


# ============================================
# STEP 5: Return to Azure Portal
# ============================================
# Now go back to Azure Portal and:
# 1. Refresh the page
# 2. Organization: jeromeAltkrueger
# 3. Repository: blocksFloorplanTiler (should show up now!)
# 4. Branch: main
# 5. Continue with deployment settings


# ============================================
# TROUBLESHOOTING
# ============================================

# If you get "remote already exists" error:
git remote remove origin
git remote add origin https://github.com/jeromeAltkrueger/blocksFloorplanTiler.git

# If you get authentication errors:
# Use Personal Access Token, not password!
# Get it from: https://github.com/settings/tokens

# If you want to see what files will be pushed:
git ls-files

# If you want to undo and start over:
git rm -rf .git
# Then start from Step 2 again
