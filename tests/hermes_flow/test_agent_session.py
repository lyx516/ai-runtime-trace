"""Unit tests for Agent Session management — context packet building, file serialization, result parsing.

Tests verify that:
- prepare_context() builds a complete AgentContextPacket from store data
- Context file writer produces valid JSON matching the schema
- parse_result() correctly reads and validates session result files
"""
