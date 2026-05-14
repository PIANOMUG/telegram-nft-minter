Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\FOLIO.DESKTOP-4B4UJ7F\Documents\telegram-nft-minter"
WshShell.Run "C:\Users\FOLIO.DESKTOP-4B4UJ7F\AppData\Local\Python\pythoncore-3.14-64\python.exe -u main.py", 0, False
