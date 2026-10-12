@echo off
chcp 65001 >nul
cd /d "%~dp0"
python scripts\launch_catalog_collector.py %*
if errorlevel 1 pause
