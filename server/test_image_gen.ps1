$ErrorActionPreference = "Stop"
Write-Host "=== Starting server ==="
$log = "$env:TEMP\server_test_script.log"
$ps = Start-Process -FilePath python -ArgumentList "main.py" -WorkingDirectory "$PSScriptRoot" -PassThru -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError "${log}_err"
Write-Host "Server PID: $($ps.Id)"
Start-Sleep -Seconds 8

# Verify server is up
try {
    $r = Invoke-WebRequest -Uri http://127.0.0.1:1984/api/system/state -UseBasicParsing -TimeoutSec 5
    Write-Host "Server OK, accounts=$($r.Content)"
} catch {
    Write-Host "Server failed: $_"
    Get-Content $log -ErrorAction SilentlyContinue | Select-Object -Last 10
    Get-Content "${log}_err" -ErrorAction SilentlyContinue | Select-Object -Last 10
    exit 1
}

Write-Host "=== Calling generate_image ==="
$body = @{
    prompt = "majestic alpine mountain peak, golden sunlit, god rays, dark mood, mystical forest foreground, empty dark negative space left side, cinematic 8k, photorealistic --ar 9:20"
    account_id = "acc_577cd0d2"
    output_dir = "output"
} | ConvertTo-Json

try {
    $r = Invoke-WebRequest -Uri http://127.0.0.1:1984/api/call/browser_generate_image -Method Post -Body $body -ContentType "application/json" -TimeoutSec 120 -UseBasicParsing
    Write-Host "=== RESULT ==="
    $r.Content | ConvertFrom-Json | ConvertTo-Json -Depth 3
} catch {
    Write-Host "API call failed: $_"
    Write-Host "Server log last 20 lines:"
    Get-Content "$log" -ErrorAction SilentlyContinue | Select-Object -Last 20
    Get-Content "${log}_err" -ErrorAction SilentlyContinue | Select-Object -Last 5
}

Write-Host "=== Done ==="
Stop-Process -Id $ps.Id -Force -ErrorAction SilentlyContinue
