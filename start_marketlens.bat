@echo off
echo Starting Market Lens...
cd /d C:\Users\User\.cursor\worktrees\Market_Lens\avi
call venv\Scripts\activate
streamlit run app.py
pause
