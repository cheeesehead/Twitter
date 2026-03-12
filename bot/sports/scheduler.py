import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from bot.sports.base import SportMonitor, SportEvent
from bot.config import LIVE_POLL_INTERVAL, IDLE_POLL_INTERVAL

log = logging.getLogger(__name__)


class SportsScheduler:
    def __init__(self, monitors: list[SportMonitor], on_events):
        self.monitors = monitors
        self.on_events = on_events  # async callback(events: list[SportEvent])
        self.scheduler = AsyncIOScheduler()
        self._has_live_games = False

    def start(self):
        for monitor in self.monitors:
            self.scheduler.add_job(
                self._poll_monitor,
                IntervalTrigger(seconds=IDLE_POLL_INTERVAL),
                args=[monitor],
                id=f"poll_{monitor.sport_key}",
                replace_existing=True,
            )
        self.scheduler.start()
        log.info("Scheduler started with %d monitors", len(self.monitors))

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
