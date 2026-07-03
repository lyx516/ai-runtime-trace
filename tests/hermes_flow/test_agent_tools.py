"""Unit tests for agent-facing tool wrappers — inbox_read, message_send, submit_decision, query_status.

Tests verify that each wrapper delegates correctly to the corresponding flow tool
(flow_send, flow_decide, flow_status) and handles errors appropriately.
"""
