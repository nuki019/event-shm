$py = "C:\Users\wfy\.conda\envs\shm\python.exe"
Set-Location D:\event-camera\SHM
for ($i=1; $i -le 40; $i++) {
  Add-Content results\cache.log "=== cache attempt $i $(Get-Date -Format HH:mm:ss) ==="
  & $py src\experiments\cache_residuals.py 40 2>&1 | Out-Null
  if ($LASTEXITCODE -eq 0) { Add-Content results\cache.log "=== cache DONE ==="; break }
  Add-Content results\cache.log "=== cache rc=$LASTEXITCODE retry ==="
  Start-Sleep 60
}
