$proc = Get-CimInstance Win32_Process -Filter "name = 'python.exe'" | Where-Object CommandLine -like "*bot.py*"
if ($proc) {
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host " [STATUS] Bot is ONLINE and RUNNING in background!" -ForegroundColor Green
    Write-Host " Process ID (PID): $($proc.ProcessId)" -ForegroundColor Yellow
    Write-Host "==========================================================" -ForegroundColor Cyan
} else {
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host " [STATUS] Bot is currently OFFLINE." -ForegroundColor Red
    Write-Host " To start: double-click 'start_bot.bat' or 'run_background.vbs'" -ForegroundColor Gray
    Write-Host "==========================================================" -ForegroundColor Cyan
}
