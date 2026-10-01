"""APScheduler 排程器骨架，於backend process內執行，不另開worker容器。
實際任務註冊(daily_jobs/intraday_jobs)與啟動時機待後續實作補上。"""

from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
