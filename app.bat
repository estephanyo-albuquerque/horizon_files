@echo off
title Horizon
echo Iniciando o aplicativo Streamlit...
cd /d "%~dp0"
start "" python -m streamlit run Horizon.py --server.maxUploadSize 1000
timeout /t 5 >nul
start "" http://localhost:8501
exit