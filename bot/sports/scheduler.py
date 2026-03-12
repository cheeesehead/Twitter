import asyncio
import logging
from typing import Callable, Awaitable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from bot.sports.base import SportMonitor, SportEvent
from bot.config import LIVE_POLL_INTERVAL, IDLE_POLL_INTERVAL

log = logging.getLogger(__name__)

FEED_POLL_INTERVAL = 300  # 5 minutes for news/RSS feeds


class SportsScheduler:
    def __init__(self, monitors: list[SportMonitor], on_events):
        self.monitors = monitors
        self.on_events = on_events  # async callback(events: list[SportEvent])
        self.scheduler = AsyncIOScheduler()
        self._has_live_games = False
        self._feed_jobs: list[tuple[str, Callable]] = []

    def register_feed(self, job_id: str, poll_fn: Callable[[], Awaitable[None]]):
        """Register an async feed polling function to run on the scheduler."""
        self._feed_jobs.append((job_id, poll_fn))

    def start(self):
        for monitor in self.monitors:
            self.scheduler.add_job(
                self._poll_monitor,
                IntervalTrigger(seconds=IDLE_POLL_INTERVAL),
                args=[monitor],
                id=f"poll_{monitor.sport_key}",
                replace_existing=True,
            )

        # Register news/RSS feed polling jobs
        for job_id, poll_fn in self._feed_jobs:
            self.scheduler.add_job(
                self._poll_feed,
                IntervalTrigger(seconds=FEED_POLL_INTERVAL),
                args=[job_id, poll_fn],
                id=job_id,
                replace_existing=True,
            )

        self.scheduler.start()
        log.info(
            "Scheduler started with %d monitors and %d feed jobs",
            len(self.monitors),
            len(self._feed_jobs),
        )

    def stop(self):
        self.scheduler.shutdown(wait=False)

    async def _poll_monitor(self, monitor: SportMonitor):
        try:
            events = await monitor.poll()
            if events:
                log.info("%s: detected %d events", monitor.sport_key, len(events))
                await self.on_events(events)

            # Adjust polling interval based on whether games are live
            self._adjust_interval(monitor)
        except Exception:
            log.exception("Error polling %s", monitor.sport_key)

    async def _poll_feed(self, job_id: str, poll_fn: Callable[[], Awaitable[None]]):
        try:
            await poll_fn()
        except Exception:
            log.exception("Error polling feed %s", job_id)

    def _adjust_interval(self, monitor: SportMonitor):
        has_live = any(
            s.get("status") == "in_progress"
            for s in monitor._previous_states.values()
        )
        job = self.scheduler.get_job(f"poll_{monitor.sport_key}")
        if not job:
            return

        current = job.trigger.interval.total_seconds()
        target = LIVE_POLL_INTERVAL if has_live else IDLE_POLL_INTERVAL

        if current != target:
            job.reschedule(IntervalTrigger(seconds=target))
            mode = "LIVE" if has_live else "IDLE"
            log.info("%s: switched to %s polling (%ds)", monitor.sport_key, mode, target)
