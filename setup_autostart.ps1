$startupFolder = [System.Environment]::GetFolderPath('Startup')
$targetScript = Join-Path $PSScriptRoot "run_background.vbs"
$destShortcut = Join-Path $startupFolder "ClassroomRAGBot.vbs"

Copy-Item -Path $targetScript -Destination $destShortcut -Force
if (Test-Path $destShortcut) {
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host " [SUCCESS] Windows Auto-Start Configured Successfully!" -ForegroundColor Green
    Write-Host " Bot will automatically launch in background when Windows starts." -ForegroundColor White
    Write-Host " Startup file: $destShortcut" -ForegroundColor Gray
    Write-Host "==========================================================" -ForegroundColor Cyan
} else {
    Write-Host "[ERROR] Could not copy to startup folder." -ForegroundColor Red
}
