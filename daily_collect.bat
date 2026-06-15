@echo off
REM Daily Kakao favorites collection -> build -> push -> email report.
REM Registered in Windows Task Scheduler (daily 09:00).
cd /d D:\Mycanoe_map
python daily_collect.py
