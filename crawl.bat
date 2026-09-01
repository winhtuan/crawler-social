@echo off
rem ============================================================
rem  crawl-fb - crawl pages listed in data\fb_pages.json
rem  Output: output\{id}.json per page
rem ============================================================
cd /d D:\capstone\brandhub\crawl-fb

rem rotate proxy -> crawl -> upload (upload still runs on Ctrl+C)
python run.py --max-posts 100

rem If headless is flagged, comment the line above and use:
rem python run.py --max-posts 10 --headed

echo.
echo Done. Output is in output\
pause
