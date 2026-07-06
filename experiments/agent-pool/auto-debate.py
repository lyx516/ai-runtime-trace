#!/usr/bin/env python3
"""auto-debate.py — thin entry point.

All logic has been split into the ``engine`` package (config, llm_client,
agent_loader, flow_builder, hooks_wiring, session, artifacts, fsm, evaluate,
evolve, analyze, cli). This file re-exports key symbols for backward
compatibility with tests that load it via ``spec_from_file_location`` and
call ``mod._run_session_loop``, ``mod._init_agent_session_state``, etc.
"""

# ── Environment defaults must be set before engine submodules import ──
import os as _os
_os.environ.setdefault("HERMES_FLOW_PROJECT_ROOT", str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))

from engine.config import *  # noqa: F401,F403
from engine.llm_config import *  # noqa: F401,F403
from engine.llm_client import *  # noqa: F401,F403
from engine.agent_loader import *  # noqa: F401,F403
from engine.artifacts import *  # noqa: F401,F403
from engine.flow_builder import *  # noqa: F401,F403
from engine.hooks_wiring import *  # noqa: F401,F403
from engine.session import *  # noqa: F401,F403
from engine.fsm import *  # noqa: F401,F403
from engine.evaluate import *  # noqa: F401,F403
from engine.evolve import *  # noqa: F401,F403
from engine.analyze import *  # noqa: F401,F403
from engine.cli import main, print_help  # noqa: F401

# ── Backward-compat aliases used by tests ──
# Tests call mod._run_session_loop, mod._init_agent_session_state,
# mod._run_agent_session, mod._find_output_artifact, mod._call_llm_tools.
# These point to the engine implementations.
from engine.session import (
    _build_multi_turn_system_prompt as _build_multi_turn_system_prompt,
    _init_agent_session_state as _init_agent_session_state,
    _run_agent_session as _run_agent_session,
    _run_session_loop as _run_session_loop,
    _handle_agent_recall as _handle_agent_recall,
)
from engine.llm_client import (
    call_llm as call_llm,
    call_llm_tools as _call_llm_tools,
)
from engine.artifacts import (
    find_output_artifact as _find_output_artifact,
    check_artifact as _artifact_check,
)
from engine.hooks_wiring import (
    make_hook_handlers as _make_hook_handlers,
)
from engine.fsm import (
    _run_fsm_loop as _run_fsm_loop,
    run_flow as run_flow,
    resume_flow as resume_flow,
)
from engine.evaluate import (
    persist_performance as _persist_performance,
)
from engine.evolve import (
    evolve as _evolve,
    evolve_all as _evolve_all,
    evolve_agent as _evolve_agent,
    extract_eval_json as _extract_eval_json,
)
from engine.analyze import (
    analyze_all_runs as _analyze_all_runs,
    show_performance as _show_performance,
    list_runs as _list_runs,
    show_feedback as _show_feedback,
)
from engine.agent_loader import (
    load_agents as load_agents,
    load_team_skills as _load_team_skills,
)


if __name__ == "__main__":
    main()