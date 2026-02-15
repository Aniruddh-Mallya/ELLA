###############################################################################
# deploy.ps1 — One-command deployment for RMS on Azure
#
# Usage:
#   .\deploy.ps1 setup       # First time: provision infra + deploy app
#   .\deploy.ps1 push        # After code changes: rebuild + redeploy
#   .\deploy.ps1 status      # Check what's running
#   .\deploy.ps1 logs        # Stream container logs
#   .\deploy.ps1 debug       # Open /debug endpoint in browser
#   .\deploy.ps1 destroy     # Delete everything from Azure
###############################################################################

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("setup", "push", "status", "logs", "debug", "destroy")]
    [string]$Command
)

$ErrorActionPreference = "Stop"

function Get-TfOutput($name) {
    return (terraform output -raw $name 2>$null)
}

function Invoke-Setup {
    Write-Host "`n Step 1: Logging into Azure..." -ForegroundColor Cyan
    az login

    Write-Host "`n Step 2: Running Terraform..." -ForegroundColor Cyan
    terraform init -upgrade
    terraform apply -auto-approve

    Write-Host "`n Step 3: Building and deploying container..." -ForegroundColor Cyan
    Invoke-Push

    Write-Host "`n====================================" -ForegroundColor Green
    Write-Host " YOUR APP IS LIVE!" -ForegroundColor Green
    Write-Host " $(Get-TfOutput 'app_url')" -ForegroundColor Green
    Write-Host "====================================" -ForegroundColor Green
    Write-Host ""
    Write-Host " Wait 2-3 minutes for container startup, then visit the URL above." -ForegroundColor Yellow
    Write-Host " Debug: $(Get-TfOutput 'app_url')/debug" -ForegroundColor Cyan
}

function Invoke-Push {
    $acrName   = Get-TfOutput "acr_name"
    $acrServer = Get-TfOutput "acr_login_server"
    $appName   = Get-TfOutput "app_name"
    $rgName    = Get-TfOutput "resource_group"

    # ── Step 1: Login to ACR ──
    Write-Host " Logging into ACR..." -ForegroundColor Yellow
    az acr login --name $acrName

    # ── Step 2: Build Docker image ──
    Write-Host " Building Docker image..." -ForegroundColor Yellow
    docker build -t "${acrServer}/rms-api:latest" ..

    # ── Step 3: Push to ACR ──
    Write-Host " Pushing image to Azure..." -ForegroundColor Yellow
    docker push "${acrServer}/rms-api:latest"

    # ── Step 4: Wire ACR credentials to App Service ──
    # This ensures App Service can always pull from ACR.
    # (Fixes the ImagePullFailure issue permanently)
    Write-Host " Configuring container credentials..." -ForegroundColor Yellow
    $acrPassword = az acr credential show --name $acrName --query "passwords[0].value" -o tsv

    az webapp config container set `
        --name $appName `
        --resource-group $rgName `
        --container-image-name "${acrServer}/rms-api:latest" `
        --container-registry-url "https://${acrServer}" `
        --container-registry-user $acrName `
        --container-registry-password $acrPassword `
        --output none

    # ── Step 5: Restart to pull new image ──
    Write-Host " Restarting app..." -ForegroundColor Yellow
    az webapp restart --name $appName --resource-group $rgName

    Write-Host ""
    Write-Host " Done! Container pushed and app restarting." -ForegroundColor Green
    Write-Host " URL:   $(Get-TfOutput 'app_url')" -ForegroundColor Cyan
    Write-Host " Debug: $(Get-TfOutput 'app_url')/debug" -ForegroundColor Cyan
}

function Show-Status {
    $appName = Get-TfOutput "app_name"
    $rgName  = Get-TfOutput "resource_group"

    Write-Host "`n=== App Info ===" -ForegroundColor Cyan
    Write-Host " URL:    $(Get-TfOutput 'app_url')"
    Write-Host " App:    $appName"
    Write-Host " RG:     $rgName"
    Write-Host " ACR:    $(Get-TfOutput 'acr_login_server')"
    Write-Host " PG:     $(Get-TfOutput 'postgres_host')"

    Write-Host "`n=== App Service State ===" -ForegroundColor Cyan
    az webapp show --name $appName --resource-group $rgName `
        --query "{State:state, Host:defaultHostName}" --output table

    Write-Host "`n=== Recent Docker Logs (last 15 lines) ===" -ForegroundColor Cyan
    $logFile = "./temp-logs-$(Get-Random).zip"
    az webapp log download --name $appName --resource-group $rgName --log-file $logFile 2>$null
    if (Test-Path $logFile) {
        $logDir = $logFile -replace '\.zip$', ''
        Expand-Archive $logFile -DestinationPath $logDir -Force
        $dockerLog = Get-ChildItem "$logDir/LogFiles" -Filter "*docker.log" -Recurse | Where-Object { $_.Name -notmatch "scm" } | Select-Object -First 1
        if ($dockerLog) { Get-Content $dockerLog.FullName -Tail 15 }
        Remove-Item $logFile, $logDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Show-Logs {
    $appName = Get-TfOutput "app_name"
    $rgName  = Get-TfOutput "resource_group"

    az webapp log config --name $appName --resource-group $rgName --docker-container-logging filesystem --output none 2>$null
    Write-Host " Streaming logs (Ctrl+C to stop)..." -ForegroundColor Cyan
    az webapp log tail --name $appName --resource-group $rgName
}

function Open-Debug {
    $url = Get-TfOutput "app_url"
    Write-Host " Opening debug endpoint..." -ForegroundColor Cyan
    Start-Process "${url}/debug"
}

function Invoke-Destroy {
    Write-Host "`n WARNING: This deletes EVERYTHING — database, app, container registry!" -ForegroundColor Red
    $confirm = Read-Host " Type 'yes' to confirm"
    if ($confirm -eq "yes") {
        terraform destroy -auto-approve
        Write-Host " All resources deleted. No more charges." -ForegroundColor Green
    }
}

switch ($Command) {
    "setup"   { Invoke-Setup }
    "push"    { Invoke-Push }
    "status"  { Show-Status }
    "logs"    { Show-Logs }
    "debug"   { Open-Debug }
    "destroy" { Invoke-Destroy }
}
