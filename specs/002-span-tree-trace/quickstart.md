# Quickstart: Span Tree Trace

This quickstart describes how an AI debugging agent reads traces from a flow run.

## 1. Setup (already exists)

Traces are always-on. After `flow_init()` creates a run, the `trace_events` table is populated automatically.

## 2. Read the full trace tree

From a completed or active run directory:

```sql
-- All spans for one trace, in execution order
SELECT * FROM trace_events
WHERE run_id = '<run_id>' AND trace_id = '<trace_id>'
ORDER BY rowid;
```

Expected result:
- Root span (parent_span_id = "") first: event_type = "flow_init"
- Child spans below: load_flow, validate_flow, create_run
- Each child has parent_span_id matching the root's span_id

## 3. Find all gate evaluations

```sql
-- Every gate decision across the run
SELECT trace_id, ts_start, inputs, outputs, decisions, error
FROM trace_events
WHERE run_id = '<run_id>' AND event_type = 'evaluate_gate'
ORDER BY ts_start;
```

Expected result:
- Each row shows the required_roles (`inputs`), present decisions (`inputs`), gate result (`decisions`), and next state (`outputs.next_state_if_ready`).

## 4. Find rejected message routes

```sql
-- All routing decisions (delivered or rejected)
SELECT trace_id, ts_start, inputs, outputs, decisions
FROM trace_events
WHERE run_id = '<run_id>' AND event_type = 'route_message'
  AND json_extract(outputs, '$.delivery_outcome') = 'rejected'
ORDER BY ts_start;
```

Expected result:
- The span's `inputs.intended_recipients` shows who was intended.
- The span's `decisions` shows which recipient failed availability.
- The span's `outputs.delivery_outcome` = "rejected".

## 5. Find errors across the entire run

```sql
-- All failed spans (exception occurred)
SELECT trace_id, event_type, ts_start, error, inputs
FROM trace_events
WHERE run_id = '<run_id>' AND error IS NOT NULL
ORDER BY ts_start;
```

Expected result:
- Each failed span shows `error.type`, `error.message`, and `error.traceback`.
- The `inputs` field shows the exact arguments that triggered the failure.

## 6. Reconstruct a causal chain

From a non-root span's parent_span_id:

```sql
-- Find the parent span of any span
SELECT * FROM trace_events
WHERE run_id = '<run_id>' AND span_id = '<parent_span_id>';
```

Then recursively query to trace back to the root.

## 7. Performance verification

Check that tracing added acceptable overhead:

```sql
-- Average duration per event type
SELECT event_type, count(*) as n, avg(duration_ms) as avg_ms
FROM trace_events
WHERE run_id = '<run_id>'
GROUP BY event_type
ORDER BY avg_ms DESC;
```

Expected result: average duration under 1ms for most event types.
