"""Tests for fast-connect fallback without replaying a setter."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import gateway_extended as gateway


class FastFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_standard_failure_before_write_falls_back(self):
        args = SimpleNamespace(command='status', value=None)
        with patch.object(gateway, 'fast_standard', AsyncMock(return_value={'ok': False, 'setter_attempted': False})), \
             patch.object(gateway.base.engine, 'run', AsyncMock(return_value={'ok': True})) as fallback:
            result = await gateway.dispatch(args)
        self.assertTrue(result['ok'])
        self.assertIn('fast_attempt', result)
        fallback.assert_awaited_once()

    async def test_standard_failure_after_write_does_not_replay(self):
        args = SimpleNamespace(command='volume', value='20')
        with patch.object(gateway, 'fast_standard', AsyncMock(return_value={'ok': False, 'setter_attempted': True})), \
             patch.object(gateway.base.engine, 'run', AsyncMock()) as fallback:
            result = await gateway.dispatch(args)
        self.assertFalse(result['ok'])
        fallback.assert_not_awaited()

    async def test_extended_failure_before_write_falls_back(self):
        args = SimpleNamespace(command='subwoofer', value='down')
        with patch.object(gateway, 'run_extended', AsyncMock(side_effect=[{'ok': False, 'setter_attempted': False}, {'ok': True}])) as runner:
            result = await gateway.dispatch(args)
        self.assertTrue(result['ok'])
        self.assertEqual(runner.await_count, 2)
        self.assertIn('fast_attempt', result)

    async def test_extended_failure_after_write_does_not_replay(self):
        args = SimpleNamespace(command='subwoofer', value='down')
        with patch.object(gateway, 'run_extended', AsyncMock(return_value={'ok': False, 'setter_attempted': True})) as runner:
            result = await gateway.dispatch(args)
        self.assertFalse(result['ok'])
        self.assertEqual(runner.await_count, 1)


if __name__ == '__main__':
    unittest.main()
