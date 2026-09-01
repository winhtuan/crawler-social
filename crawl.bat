@echo off
rem ============================================================
rem  crawl-fb - crawl pages listed in data\fb_pages.json
rem  Output: output\{id}_{run_id}.json per page
rem ============================================================
cd /d "%~dp0"

rem find python (prefer `python`, fall back to the `py` launcher)
where python >nul 2>nul && (set PY=python) || (set PY=py)

rem rotate proxy -> crawl -> upload (upload still runs on Ctrl+C)
%PY% run.py --max-posts 100

rem Debug with a visible browser: comment the line above and use:
rem %PY% run.py --max-posts 10 --headed

echo.
echo Done. Output is in output\
pause
