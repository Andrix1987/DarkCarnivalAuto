@echo off
cd /d "%~dp0"
echo Installing Python libraries...
python -m pip install mss opencv-python numpy pyautogui pytesseract
echo.
echo Done.
pause
