# Publishes the local Euro2 server (http://localhost:8000) on your own domain through a free
# Cloudflare Tunnel: HTTPS, no open ports, survives reboots (installed as a Windows service).
#
#   powershell -ExecutionPolicy Bypass -File scripts\cloudflare-tunnel.ps1 -Domain euro2core.com
#
# Prerequisites: the domain is in your Cloudflare account (bought at Cloudflare Registrar or
# with its nameservers pointed at Cloudflare) and cloudflared is installed
# (winget install Cloudflare.cloudflared). Run from an elevated PowerShell (administrator);
# the first run opens the browser once to log in.

param(
    [Parameter(Mandatory = $true)][string]$Domain,
    [string]$TunnelName = "euro2",
    [int]$Port = 8000,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$Cf = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
if (-not (Test-Path $Cf)) { $Cf = (Get-Command cloudflared -ErrorAction Stop).Source }
$Home_ = [Environment]::GetFolderPath("UserProfile")
$Dir = Join-Path $Home_ ".cloudflared"

if ($Uninstall) {
    & $Cf service uninstall 2>$null
    Write-Host "Tunnel service removed. Delete the tunnel in the Cloudflare dashboard if you no longer need it."
    exit 0
}

if (-not (Test-Path (Join-Path $Dir "cert.pem"))) {
    Write-Host ">> Logging in to Cloudflare (a browser window opens: pick the zone '$Domain')"
    & $Cf tunnel login
}

$existing = & $Cf tunnel list --output json 2>$null | ConvertFrom-Json | Where-Object { $_.name -eq $TunnelName }
if (-not $existing) {
    Write-Host ">> Creating tunnel '$TunnelName'"
    & $Cf tunnel create $TunnelName | Out-Null
    $existing = & $Cf tunnel list --output json | ConvertFrom-Json | Where-Object { $_.name -eq $TunnelName }
}
$TunnelId = $existing.id
$Creds = Join-Path $Dir "$TunnelId.json"

$config = @"
tunnel: $TunnelId
credentials-file: $Creds
ingress:
  - hostname: $Domain
    service: http://127.0.0.1:$Port
  - hostname: www.$Domain
    service: http://127.0.0.1:$Port
  - service: http_status:404
"@
$config | Out-File -Encoding ascii (Join-Path $Dir "config.yml")

Write-Host ">> Pointing DNS ($Domain and www) at the tunnel"
& $Cf tunnel route dns --overwrite-dns $TunnelName $Domain | Out-Null
& $Cf tunnel route dns --overwrite-dns $TunnelName "www.$Domain" | Out-Null

Write-Host ">> Installing as a Windows service (starts with Windows)"
# The service runs as SYSTEM and reads its files from the system profile (Cloudflare docs).
$SysDir = "C:\Windows\System32\config\systemprofile\.cloudflared"
New-Item -ItemType Directory -Force $SysDir | Out-Null
Copy-Item (Join-Path $Dir "cert.pem") $SysDir -Force
Copy-Item $Creds $SysDir -Force
$config.Replace($Creds, (Join-Path $SysDir "$TunnelId.json")) + "logfile: $SysDir\cloudflared.log`nloglevel: info`n" |
    Out-File -Encoding ascii (Join-Path $SysDir "config.yml")
Stop-Service cloudflared -ErrorAction SilentlyContinue
& $Cf service uninstall 2>$null | Out-Null
& $Cf service install
# cloudflared installs the service without arguments on Windows; point it at the config (docs)
Set-ItemProperty -Path HKLM:\SYSTEM\CurrentControlSet\Services\Cloudflared -Name ImagePath `
    -Value "`"$Cf`" --config=$SysDir\config.yml tunnel run"
Start-Service cloudflared

Write-Host ""
Write-Host "OK https://$Domain/  (web)   https://$Domain/app/  (app)"
Write-Host "  Add 'https://$Domain' to Ajustes -> Administracion -> Servidor -> Origenes permitidos."
