#!/usr/bin/env python3
"""
Telegram Scheduler for ELO Bot

Schedules:
- Daily leaderboard (configurable time)
- Periodic rank checks (future enhancement)
"""

import asyncio
from datetime import datetime, time
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


class TelegramScheduler:
    """Schedule automated Telegram messages."""

    def __init__(self, bot, database):
        """
        Initialize scheduler.

        Args:
            bot: ELOTelegramBot instance
            database: Database instance
        """
        self.bot = bot
        self.db = database
        self.scheduler = AsyncIOScheduler()

    def schedule_daily_leaderboard(self, hour: int = 9, minute: int = 0):
        """
        Schedule daily leaderboard at specific time.

        Args:
            hour: Hour (0-23)
            minute: Minute (0-59)
        """
        self.scheduler.add_job(
            self.bot.send_daily_leaderboard,
            trigger=CronTrigger(hour=hour, minute=minute),
            id='daily_leaderboard',
            name='Daily Leaderboard',
            replace_existing=True
        )

        print(f"[SCHEDULER] Daily leaderboard scheduled for {hour:02d}:{minute:02d}")

    def start(self):
        """Start the scheduler."""
        self.scheduler.start()
        print("[SCHEDULER] Scheduler started")

    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()
        print("[SCHEDULER] Scheduler stopped")
