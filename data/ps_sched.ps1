$py = "C:\Users\wfy\.conda\envs\shm\python.exe"
Set-Location D:\event-camera\SHM
function Run-Retry($name, $script, $argstr) {
  for ($i=1; $i -le 40; $i++) {
    Add-Content results\ps_sched.log "=== [$name] attempt $i $(Get-Date -Format HH:mm:ss) ==="
    & $py $script $argstr 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Add-Content results\ps_sched.log "=== [$name] DONE ==="; break }
    Add-Content results\ps_sched.log "=== [$name] rc=$LASTEXITCODE retry ==="
    Start-Sleep 60
  }
}
Run-Retry "e3_real" "src\experiments\e3_real.py" ""
Add-Content results\ps_sched.log "PS SCHED DONE"
