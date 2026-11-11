"""Scheduler recovery uses an isolated runtime and never dispatches platform requests."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import test_workspace
from config import DEFAULT_SETTINGS
from engine import Runner
from storage import init, set_meta


class SchedulerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        init()
        set_meta('settings', DEFAULT_SETTINGS)

    async def run_two_ticks(self, runner):
        errors = []

        async def next_tick(delay):
            self.assertEqual(delay, 15)
            errors.append(runner.scheduler_error)
            if len(errors) == 2:
                raise asyncio.CancelledError()

        with patch('engine.asyncio.sleep', side_effect=next_tick):
            with self.assertRaises(asyncio.CancelledError):
                await runner.schedule_loop()
        return errors

    async def test_schedule_error_retries_and_clears_after_success(self):
        runner = Runner()
        with patch('keyword_planner.daily_tick'), patch.object(
            runner, 'schedule_tick', new=AsyncMock(side_effect=[OSError('temporary fixture'), None])
        ) as tick:
            errors = await self.run_two_ticks(runner)
        self.assertEqual(tick.await_count, 2)
        self.assertIn('每日计划执行暂时异常', errors[0])
        self.assertEqual(errors[1], '')

    async def test_settings_error_does_not_terminate_scheduler(self):
        runner = Runner()
        with patch('keyword_planner.daily_tick'), patch(
            'engine.get_meta', side_effect=[OSError('temporary fixture'), DEFAULT_SETTINGS]
        ), patch.object(runner, 'schedule_tick', new=AsyncMock()) as tick:
            errors = await self.run_two_ticks(runner)
        tick.assert_awaited_once()
        self.assertTrue(errors[0])
        self.assertEqual(errors[1], '')

    async def test_keyword_failure_does_not_block_execution_plans(self):
        runner = Runner()
        with patch('keyword_planner.daily_tick', side_effect=[ValueError('fixture'), None]), patch.object(
            runner, 'schedule_tick', new=AsyncMock()
        ) as tick:
            errors = await self.run_two_ticks(runner)
        self.assertEqual(tick.await_count, 2)
        self.assertIn('每日关键词整理暂时异常', errors[0])
        self.assertEqual(errors[1], '')

    async def test_schedule_cancellation_propagates_without_retry(self):
        runner = Runner()
        with patch('keyword_planner.daily_tick'), patch.object(
            runner, 'schedule_tick', new=AsyncMock(side_effect=asyncio.CancelledError())
        ) as tick, patch('engine.asyncio.sleep', new=AsyncMock()) as sleep:
            with self.assertRaises(asyncio.CancelledError):
                await runner.schedule_loop()
        tick.assert_awaited_once()
        sleep.assert_not_awaited()

    async def test_snapshot_reports_dead_scheduler_without_hiding_live_worker(self):
        runner = Runner()
        worker = asyncio.get_running_loop().create_future()
        scheduler = asyncio.get_running_loop().create_future()
        scheduler.set_result(None)
        runner.jobs = [worker, scheduler]
        runner.started = True
        snapshot = runner.snapshot()
        self.assertTrue(snapshot['worker_alive'])
        self.assertFalse(snapshot['scheduler_alive'])
        self.assertEqual(snapshot['state'], 'error')
        self.assertIn('每日计划执行器已停止', snapshot['error'])
        worker.cancel()

    async def test_snapshot_keeps_both_errors_and_legacy_worker_status(self):
        runner = Runner()
        worker = asyncio.get_running_loop().create_future()
        runner.jobs = [worker]
        runner.started = True
        runner.worker_error = '队列错误'
        runner.scheduler_error = '计划错误'
        snapshot = runner.snapshot()
        self.assertTrue(snapshot['worker_alive'])
        self.assertIn('队列错误', snapshot['error'])
        self.assertIn('计划错误', snapshot['error'])
        self.assertNotEqual(snapshot['state'], 'error')
        worker.cancel()


if __name__ == '__main__':
    unittest.main()
