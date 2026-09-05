param([string]$Url)
Set-Clipboard -Value $Url
$ws = New-Object -ComObject WScript.Shell
$ws.AppActivate(19780) | Out-Null
Start-Sleep -Milliseconds 600
$ws.SendKeys('^l')
Start-Sleep -Milliseconds 400
$ws.SendKeys('^a')
Start-Sleep -Milliseconds 200
$ws.SendKeys('^v')
Start-Sleep -Milliseconds 300
$ws.SendKeys('{ENTER}')
