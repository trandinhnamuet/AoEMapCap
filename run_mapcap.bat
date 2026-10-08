@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m mapcap.main --interval 5 --out "D:\Game\AoE-HD\Screenshot\FullMap" %*
pause
