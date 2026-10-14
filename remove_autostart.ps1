$startupFolder = [System.Environment]::GetFolderPath('Startup')
$destShortcut = Join-Path $startupFolder "ClassroomRAGBot.vbs"
if (Test-Path $destShortcut) {
    Remove-Item -Path $destShortcut -Force
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host " [SUCCESS] Removed bot from Windows Startup." -ForegroundColor Green
    Write-Host "==========================================================" -ForegroundColor Cyan
} else {
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host " [NOTICE] Bot is not in Windows Startup." -ForegroundColor Gray
    Write-Host "==========================================================" -ForegroundColor Cyan
}
