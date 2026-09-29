# AFK Controller

Standalone Windows controller + screen-vision application based on the supplied **AFK V2.1** GPC behavior.

## Premium Controller Settings UI
The main screen follows the blue/cyan layout supplied as the visual reference:
- Config / Reload / Save / Engine status
- Enable Aim Assist
- Enable Controller Input
- Enable Virtual Controller
- DS4 Output (off = Xbox 360)
- Human Movement + Human Strength
- Target Color with editable Hex value such as `#E600FF`
- Color Tolerance
- Aim Trigger: L2 / R2 / L2+R2 / L1 / R1 / L1+R1
- Aim Bone: Head / Chest / Random
- controller slot and HidHide controls

## AFK V2.1 logic ported
- screen-color target detection
- sticky target persistence
- anti-recoil
- hair triggers
- auto hold breath
- auto ping
- bunny hop
- slide cancel
- rapid fire
- YY spam

The physical left stick is passed through unchanged. Vision correction and anti-recoil are added only to the right-stick output.

## Target Color
Type any `#RRGGBB` value in the UI or click the color square to open the picker. The value is persisted to:

`%APPDATA%\AFKController\settings.json`

## Runtime
- Python 3.12 source
- PySide6 premium UI
- dxcam screen capture
- OpenCV / NumPy color detection
- XInput physical controller input
- vgamepad + ViGEmBus virtual controller
- Xbox 360 and DS4 virtual output
- optional HidHide helper

The UI opens even when ViGEmBus is missing. vgamepad is imported lazily only when the virtual controller is started.

## Build
Run:

`build_windows.ps1`

or use GitHub Actions. The final artifact is:

`AFKController.exe`

End users do not need Python.
