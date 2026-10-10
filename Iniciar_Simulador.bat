@echo off
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python
"%PY%" -c "import pygame, moderngl, numpy" 2>nul || "%PY%" -m pip install -r requirements.txt
"%PY%" main.py
if errorlevel 1 pause
