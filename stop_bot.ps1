$proc = Get-CimInstance Win32_Process -Filter "name = 'python.exe'" | Where-Object CommandLine -like "*bot.py*"
if ($proc) {
    Write-Host "==========================================================" -ForegroundColor Cyan
    $proc | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force
        Write-Host " Stopped bot process (PID: $($_.ProcessId))" -ForegroundColor Yellow
    }
    Write-Host " [SUCCESS] Classroom RAG Assistant bot stopped!" -ForegroundColor Green
    Write-Host "==========================================================" -ForegroundColor Cyan
} else {
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host " [NOTICE] No active bot process found." -ForegroundColor Gray
    Write-Host "==========================================================" -ForegroundColor Cyan
}
