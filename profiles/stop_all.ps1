# SATL 3.0 - Stop All Services
# Usage: .\profiles\stop_all.ps1
#
# Stops all SATL-related processes (Caddy, Python forwarders, Uvicorn workers)

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  SATL 3.0 - Stop All Services" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Stop Caddy
Write-Host "Stopping Caddy..." -ForegroundColor Yellow
Get-Process -Name 'caddy' -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*SATL2.0*' } | Stop-Process -Force -ErrorAction SilentlyContinue

# Stop Python/Uvicorn processes
Write-Host "Stopping Python forwarders..." -ForegroundColor Yellow
Get-Process -Name 'python','uvicorn' -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*SATL2.0*' -or $_.Path -like '*SATL2.0*' } | Stop-Process -Force -ErrorAction SilentlyContinue

# Give processes time to terminate
Start-Sleep -Seconds 2

# Verify all stopped
$remaining_caddy = Get-Process -Name 'caddy' -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*SATL2.0*' }
$remaining_python = Get-Process -Name 'python','uvicorn' -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*SATL2.0*' -or $_.Path -like '*SATL2.0*' }

if ($remaining_caddy -or $remaining_python) {
    Write-Host ""
    Write-Host "Warning: Some processes may still be running" -ForegroundColor Red
    Write-Host "Run again or manually kill processes on ports 9000-9002, 10000-10002" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "All SATL services stopped successfully!" -ForegroundColor Green
}

Write-Host ""
