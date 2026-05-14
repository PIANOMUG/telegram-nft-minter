@echo off
schtasks /Create /SC ONLOGON /TN "NFTMinterBot" /TR "powershell.exe -NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"C:\Users\FOLIO.DESKTOP-4B4UJ7F\Documents\telegram-nft-minter\start_bot.ps1\"" /DELAY 0000:30 /F
echo.
echo Task created. The bot will auto-start on every login.
echo To start now, run: start_bot.vbs
pause
