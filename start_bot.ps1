# Start the NFT bot with auto-restart on crash
$python = "C:\Users\FOLIO.DESKTOP-4B4UJ7F\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$script = "C:\Users\FOLIO.DESKTOP-4B4UJ7F\Documents\telegram-nft-minter\main.py"
$logDir = "C:\Users\FOLIO.DESKTOP-4B4UJ7F\Documents\telegram-nft-minter"
$log = Join-Path $logDir "bot.log"

while ($true) {
    $date = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$date Starting bot..." | Out-File -Append $log
    try {
        $p = Start-Process -FilePath $python -ArgumentList "-u", "`"$script`"" -WorkingDirectory $logDir -NoNewWindow -PassThru -RedirectStandardOutput (Join-Path $logDir "bot_out.log") -RedirectStandardError (Join-Path $logDir "bot_err.log")
        $p.WaitForExit()
        $exitCode = $p.ExitCode
        $date = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        "$date Bot exited (code: $exitCode). Restarting in 5s..." | Out-File -Append $log
    } catch {
        $date = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        "$date Error: $_" | Out-File -Append $log
    }
    Start-Sleep -Seconds 5
}
