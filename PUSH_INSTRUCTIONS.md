# GitHub Push - Secret Detected

GitHub detected Azure Storage secrets in the first commit. Here's how to proceed:

## Option 1: Allow the Secret (Quick, Recommended)

1. Go to this URL (click "Allow secret" button):
   https://github.com/jeromeAltkrueger/blocksFloorplanTiler/security/secret-scanning/unblock-secret/34ZJurfFMwsdZM1DtCgF0ZiHjsI

2. GitHub will ask you to confirm

3. After allowing, run in PowerShell:
   ```powershell
   git push -u origin main --force
   ```

4. Done! Your code will be pushed.

**Note**: The secrets are already REMOVED from the current files. GitHub just sees them in the Git history.

## Option 2: Regenerate Storage Key (More Secure)

If you want to be extra secure since the key was in Git history:

1. Go to Azure Portal
2. Navigate to Storage Account: `blocksplayground`
3. Settings → Access Keys
4. Click "Rotate key" for key1 or key2
5. Copy the new connection string
6. Update it in Azure Portal when deploying Container App
7. Then allow the secret (Option 1) and push

---

## After Successful Push

Your repo will be at:
https://github.com/jeromeAltkrueger/blocksFloorplanTiler

Then return to Azure Portal and continue with Container App setup!
