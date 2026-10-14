@echo off
chcp 65001 >nul
title Classroom RAG Assistant Discord Bot
cd /d "%~dp0"
echo ==================================================
echo   Starting Classroom RAG Assistant Discord Bot...
echo ==================================================
python bot.py
pause
