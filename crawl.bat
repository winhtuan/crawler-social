@echo off
rem ============================================================
rem  crawl-fb - crawl pages listed in data\fb_pages.json
rem  Output: output\{id}.json per page
rem ============================================================
cd /d D:\capstone\brandhub\crawl-fb

python -m crawlfb --max-posts 50

rem If headless is flagged, comment the line above and use:
rem python -m crawlfb --max-posts 50 --headed

echo.
echo Done. Output is in output\
pause
