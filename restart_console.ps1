Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object {
    Write-Host ("Port 8787 owned by PID " + $_.OwningProcess)
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
  }
Get-Process pythonw -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*uvicorn*" } |
  ForEach-Object {
    Write-Host ("Killing pythonw PID " + $_.Id)
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
  }
Start-Sleep -Seconds 1
Set-Location D:\grok_tool\grok_tool
Start-Process -FilePath "pythonw.exe" `
  -ArgumentList "-m","uvicorn","web_console.app:app","--host","127.0.0.1","--port","8787" `
  -WorkingDirectory "D:\grok_tool\grok_tool" `
  -WindowStyle Hidden
Write-Host "Started."
