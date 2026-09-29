$ErrorActionPreference = 'Stop'

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

$vendor = Join-Path $PWD 'vendor'
New-Item -ItemType Directory -Force $vendor | Out-Null
Invoke-WebRequest -Uri "https://github.com/yannbouteiller/vgamepad/archive/refs/tags/v0.1.0.zip" -OutFile "$vendor\vgamepad.zip"
Expand-Archive -Path "$vendor\vgamepad.zip" -DestinationPath "$vendor\src" -Force
Copy-Item -Path "$vendor\src\vgamepad-0.1.0\vgamepad" -Destination ".\vgamepad" -Recurse -Force

if (!(Test-Path ".\vgamepad\win\vigem\client\x64\ViGEmClient.dll")) {
  throw "ViGEmClient.dll missing from vgamepad source"
}

python -m py_compile app.py
python -m compileall -q vgamepad

$env:QT_QPA_PLATFORM='offscreen'
python -c "from PySide6.QtWidgets import QApplication; import app; q=QApplication([]); w=app.MainWindow(); print(w.windowTitle()); w.close()"

python -m PyInstaller --noconfirm --clean --onefile --windowed --name AFKController `
  --collect-all dxcam `
  --collect-all comtypes `
  --add-binary "vgamepad\win\vigem\client\x64\ViGEmClient.dll;vgamepad\win\vigem\client\x64" `
  app.py

$hash = (Get-FileHash -Algorithm SHA256 .\dist\AFKController.exe).Hash
"AFKController.exe  SHA256=$hash" | Out-File -Encoding ascii .\dist\SHA256.txt
Write-Host "Built dist\AFKController.exe"
Write-Host "SHA256=$hash"
