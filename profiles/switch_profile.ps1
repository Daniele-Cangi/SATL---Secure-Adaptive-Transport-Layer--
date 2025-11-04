# SATL 3.0 - Profile Switcher
# Usage: .\profiles\switch_profile.ps1 perf|stealth|prod
#
# Profiles:
#   perf    - Performance mode (memory backend, no stealth delays)
#   stealth - Stealth mode (SQLite backend, queue delays, reordering)
#   prod    - Production mode (Caddy TLS termination, SQLite backend)

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('perf','stealth','prod')]
    [string]$profile
)

# UTF-8 encoding for Python
$env:PYTHONUTF8='1'

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  SATL 3.0 Profile Switcher" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Profile: $profile" -ForegroundColor Yellow
Write-Host ""

# Change to SATL directory
Set-Location -Path "C:\Users\dacan\OneDrive\Desktop\SATL2.0"

if ($profile -eq 'perf') {
    Write-Host "[PERF] Starting performance mode..." -ForegroundColor Green
    Write-Host "  - SATL_MODE=performance" -ForegroundColor Gray
    Write-Host "  - SATL_WINDOW_BACKEND=memory" -ForegroundColor Gray
    Write-Host "  - Workers: 3+3+4 (guard/middle/exit)" -ForegroundColor Gray
    Write-Host "  - HTTP parser: httptools" -ForegroundColor Gray
    Write-Host "  - PQC: enabled" -ForegroundColor Gray
    Write-Host ""

    $env:SATL_MODE='performance'
    $env:SATL_WINDOW_BACKEND='memory'
    $env:SATL_PQC='1'
    $env:SATL_PQC_KEYS_DIR='pqc_keys'

    Write-Host "Starting forwarders on ports 9000/9001/9002..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\dacan\OneDrive\Desktop\SATL2.0'; .\start_guard_multiworker.bat"
    Start-Sleep -Seconds 2
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\dacan\OneDrive\Desktop\SATL2.0'; .\start_middle_multiworker.bat"
    Start-Sleep -Seconds 2
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\dacan\OneDrive\Desktop\SATL2.0'; .\start_exit_multiworker.bat"

    Write-Host ""
    Write-Host "Metrics available at:" -ForegroundColor Green
    Write-Host "  http://localhost:10000/metrics (guard)" -ForegroundColor Gray
    Write-Host "  http://localhost:10001/metrics (middle)" -ForegroundColor Gray
    Write-Host "  http://localhost:10002/metrics (exit)" -ForegroundColor Gray
}
elseif ($profile -eq 'stealth') {
    Write-Host "[STEALTH] Starting stealth mode..." -ForegroundColor Green
    Write-Host "  - SATL_MODE=stealth" -ForegroundColor Gray
    Write-Host "  - SATL_WINDOW_BACKEND=sqlite" -ForegroundColor Gray
    Write-Host "  - Queue delays: 50-150ms per hop" -ForegroundColor Gray
    Write-Host "  - Packet reordering: 10%" -ForegroundColor Gray
    Write-Host "  - PQC: enabled" -ForegroundColor Gray
    Write-Host ""

    $env:SATL_MODE='stealth'
    $env:SATL_WINDOW_BACKEND='sqlite'
    $env:SATL_PQC='1'
    $env:SATL_PQC_KEYS_DIR='pqc_keys'

    Write-Host "Starting forwarders on ports 9000/9001/9002..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\dacan\OneDrive\Desktop\SATL2.0'; .\start_guard.bat"
    Start-Sleep -Seconds 2
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\dacan\OneDrive\Desktop\SATL2.0'; .\start_middle.bat"
    Start-Sleep -Seconds 2
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\dacan\OneDrive\Desktop\SATL2.0'; .\start_exit.bat"

    Write-Host ""
    Write-Host "NOTE: Stealth mode has high latency by design (queue delays + reordering)" -ForegroundColor Yellow
}
elseif ($profile -eq 'prod') {
    Write-Host "[PROD] Starting production mode with TLS 1.3..." -ForegroundColor Green
    Write-Host "  - SATL_MODE=performance" -ForegroundColor Gray
    Write-Host "  - SATL_WINDOW_BACKEND=sqlite" -ForegroundColor Gray
    Write-Host "  - TLS 1.3 termination via Caddy" -ForegroundColor Gray
    Write-Host "  - SATL_ALLOW_COMPAT removed (fail-closed)" -ForegroundColor Gray
    Write-Host "  - PQC: enabled" -ForegroundColor Gray
    Write-Host ""

    $env:SATL_MODE='performance'
    $env:SATL_WINDOW_BACKEND='sqlite'
    $env:SATL_PQC='1'
    $env:SATL_PQC_KEYS_DIR='pqc_keys'
    [Environment]::SetEnvironmentVariable('SATL_ALLOW_COMPAT',$null,'Process')

    Write-Host "Starting Caddy (TLS termination)..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\dacan\OneDrive\Desktop\SATL2.0'; .\start_caddy.bat"
    Start-Sleep -Seconds 3

    Write-Host "Starting forwarders with TLS backend..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\dacan\OneDrive\Desktop\SATL2.0'; .\start_forwarders_tls.bat"

    Write-Host ""
    Write-Host "TLS endpoints:" -ForegroundColor Green
    Write-Host "  https://localhost:9000 (guard)" -ForegroundColor Gray
    Write-Host "  https://localhost:9001 (middle)" -ForegroundColor Gray
    Write-Host "  https://localhost:9002 (exit)" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Profile '$profile' started successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "To stop all services:" -ForegroundColor Yellow
Write-Host "  .\profiles\stop_all.ps1" -ForegroundColor Gray
Write-Host ""
