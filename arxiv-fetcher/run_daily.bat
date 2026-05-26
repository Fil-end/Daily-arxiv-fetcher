@echo off
call conda activate Filend
python "%~dp0arxiv_daily.py" >> "%~dp0logs\arxiv_daily_%date:~0,4%%date:~5,2%%date:~8,2%.log" 2>&1
