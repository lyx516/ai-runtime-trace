"""Unit tests for the Runtime Loop — inbox dispatch, session result collection, gate evaluation, idle timeout.

Tests verify that the loop correctly:
- Detects unread inbox entries and schedules sessions
- Collects session results and processes decisions
- Evaluates gates automatically when all decisions are present
- Detects idle timeout and advances state
"""
