"""CLI entry point — argument parsing and subcommand dispatch.

Subcommands:
  debate <task>                         Start a new task
  debate --self <task>                  Sandboxed task (writes go to .self/)
  debate --apply-sandbox <id> [--yes]   Apply sandboxed changes to real project
  debate --resume <run_id> [opts]       Resume an interrupted run
  debate --analyze                      Cross-run pattern analysis
  debate --evolve                       EvolutionAgent self-evaluation
  debate --evolve-agent <id> [--apply]  Evolve a single agent
  debate --evolve-all                   Evolve all + clear feedback
  debate --feedback [agent_id]          Show pending feedback

LLM configuration:
  debate --set-model <model>            Set default model (persistent)
  debate --set-url <api_url>            Set API URL (persistent)
  debate --set-key <api_key>            Set API key (persistent)
  debate --show-model                   Show current LLM config
  debate --model <model> <task>         Override model for this run
  debate --api-url <url> <task>         Override API URL for this run
  debate --api-key <key> <task>         Override API key for this run
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from engine.config import PROJECT_ROOT, _PROJECT_ROOT_DIR, _SCRIPT_DIR
from engine.agent_loader import load_agents
from engine.flow_builder import manager_select_agents, generate_yaml
from engine.fsm import run_flow, resume_flow
from engine.analyze import (
    analyze_all_runs,
    show_performance,
    list_runs,
    show_feedback,
)
from engine.evolve import evolve, evolve_all, evolve_agent
from engine.llm_config import (
    load_config,
    save_config,
    redact_key,
)


def print_help():
    print("""debate — 多 Agent 协作 FSM 执行框架

用法:
  debate <任务描述>                              启动新任务
  debate --self <任务>                           沙箱模式运行（写操作隔离到 .self/）
  debate --apply-sandbox <id> [--yes]           合入沙箱改动到真实项目
  debate --resume <run_id>                       恢复中断的 run
  debate --resume --history                      显示历史列表
  debate --resume --performance <run_id>         查看 run 评分
  debate --analyze                               跨 run 模式分析
  debate --evolve                                EvolutionAgent 评审未评估的 run
  debate --evolve-agent <agent_id>               为 agent 执行定向进化
  debate --evolve-agent <agent_id> --apply       执行进化计划
  debate --evolve-all                            进化所有 + 清空清单
  debate --feedback [agent_id]                    查看待改进清单
  debate --resume <run_id> --states              查看可恢复状态（不执行）
  debate --resume <run_id> --from-state <STATE>  从指定 state 创建新分支并恢复
  debate --resume <run_id> "补充说明"             恢复时注入额外上下文
  debate --checkpoints                           查看进化检查点
  debate --diff-checkpoint <id>                  对比检查点与当前文件
  debate --revert-checkpoint <id>                 回滚文件到检查点版本

LLM 配置:
  debate --set-model <model>                     设置默认模型（持久化）
  debate --set-url <api_url>                     设置 API URL（持久化）
  debate --set-key <api_key>                     设置 API key（持久化）
  debate --show-model                            查看当前 LLM 配置
  debate --model <model> <task>                  本次运行用指定模型
  debate --api-url <url> <task>                  本次运行用指定 API URL
  debate --api-key <key> <task>                  本次运行用指定 key

  debate -h | --help                             显示此帮助

选项:
  --resume <run_id>        恢复已有 run（自动从 checkpoint 续跑）
  --states                 仅查看可恢复状态，不执行（配合 --resume 使用）
  --from-state <STATE>     回溯到指定 state 创建新分支（配合 --resume 使用）

示例:
  debate "用3句话介绍 Rust 语言"
  debate --self "给 cli.py 加 --quiet 参数"
  debate --apply-sandbox auto-xxx
  debate --resume ede4011e0d60
  debate --resume ede4011e0d60 --states
  debate --resume ede4011e0d60 --from-state SPEC
  debate --resume ede4011e0d60 --from-state PLAN "需要加入性能测试"
  debate --set-model glm-5.2
  debate --model glm-5.2 "设计一个缓存系统"

目录:
  所有 run 存储在 experiments/agent-pool/.runtime-trace/runs/<run_id>/
  Observer Dashboard: http://localhost:8765（首次 resume/new 时自动启动）
  LLM 配置: ~/.runtime-trace/llm_config.json""")


# ═══════════════════════════════════════════════════════════════════════
#  LLM config subcommands
# ═══════════════════════════════════════════════════════════════════════

def _cmd_show_model():
    """Print current LLM configuration."""
    cfg = load_config()
    print(f"\n📋 LLM 配置\n{'='*40}")
    print(f"  Model:       {cfg.model}")
    print(f"  API URL:     {cfg.api_url}")
    print(f"  API Key:     {redact_key(cfg.api_key)}")
    print(f"  Temperature: {cfg.temperature}")
    print(f"  Max Tokens:  {cfg.max_tokens}")
    print(f"  Config file: ~/.runtime-trace/llm_config.json")
    print()


def _cmd_set_model(model: str):
    cfg = save_config(model=model)
    print(f"✅ 默认模型已设置为: {cfg.model}")


def _cmd_set_url(api_url: str):
    cfg = save_config(api_url=api_url)
    print(f"✅ API URL 已设置为: {cfg.api_url}")


def _cmd_set_key(api_key: str):
    cfg = save_config(api_key=api_key)
    print(f"✅ API Key 已设置: {redact_key(cfg.api_key)}")


# ═══════════════════════════════════════════════════════════════════════
#  Resume subcommand
# ═══════════════════════════════════════════════════════════════════════

def _handle_resume(argv: list[str]):
    """Handle --resume and its sub-options."""
    # --history: list all runs
    if len(argv) >= 2 and argv[1] == "--history":
        list_runs()
        return
    # --performance <run_id>: show performance
    if len(argv) >= 3 and argv[1] == "--performance":
        show_performance(argv[2])
        return
    if len(argv) < 2:
        print("❌ --resume requires a run_id (or --history / --performance <id>)")
        sys.exit(1)

    run_id = argv[1]
    from_state = ""
    extra_parts: list[str] = []
    dry_run = False
    i = 2
    while i < len(argv):
        if argv[i] == "--from-state" and i + 1 < len(argv):
            from_state = argv[i + 1]
            i += 2
        elif argv[i] == "--states":
            dry_run = True
            i += 1
        elif argv[i] == "--performance" and i + 1 < len(argv):
            show_performance(argv[i + 1])
            return
        else:
            extra_parts.append(argv[i])
            i += 1
    extra = " ".join(extra_parts)
    resume_flow(run_id, extra_context=extra, from_state=from_state, dry_run=dry_run)


# ═══════════════════════════════════════════════════════════════════════
#  New task (debate <task>)
# ═══════════════════════════════════════════════════════════════════════

def _handle_task(goal: str, cli_model: str = "", cli_url: str = "", cli_key: str = "",
                self_mode: bool = False):
    """Start a new debate task."""
    # Apply CLI LLM overrides for this run (via env vars; load_config reads them)
    if cli_model:
        os.environ["RUNTIME_TRACE_LLM_MODEL"] = cli_model
    if cli_url:
        os.environ["RUNTIME_TRACE_LLM_API_URL"] = cli_url
    if cli_key:
        os.environ["RUNTIME_TRACE_LLM_API_KEY"] = cli_key

    run_name = goal[:60]

    # Sandbox mode: activate before anything else
    if self_mode:
        sandbox_root = _SCRIPT_DIR / ".self" / run_name.replace(" ", "_")
        sandbox_root.mkdir(parents=True, exist_ok=True)
        from tools._security import set_sandbox_root
        set_sandbox_root(sandbox_root)
        print(f"🔒 沙箱模式: {sandbox_root}")

    print(f"\n{'='*60}")
    print(f"🤖 Auto-Debate v2")
    print(f"{'='*60}")
    print(f"任务: {goal}")

    # Show active model
    cfg = load_config()
    print(f"模型: {cfg.model}")

    # Load agents from individual meta.yaml files
    agents = load_agents()
    print(f"Agent 池: {len(agents)} 个智能体")
    for aid, info in sorted(agents.items()):
        has_refs = Path(info["_path"]) / "references"
        ref_count = len(list(has_refs.iterdir())) if has_refs.exists() and has_refs.is_dir() else 0
        print(f"  📁 {aid:20s} | {info.get('role',''):15s} | refs={ref_count}")

    # Phase 1: Manager selects agents + team skill (now returns flow topology)
    agent_ids, flow_topology, output_base = manager_select_agents(goal, agents)

    if not flow_topology:
        print("  ❌ Manager 未返回 flow 拓扑，中止")
        sys.exit(1)

    # Phase 2: Manager generates flow YAML + briefs agents
    print("\n📄 生成 Flow YAML...")
    yaml_path = generate_yaml(goal, agent_ids, run_name, agents, flow_topology, output_base)
    print(f"   → {yaml_path}")

    # Manager briefs each agent via inbox
    print("\n📨 管理者发送任务简报...")
    sys.path.insert(0, str(_PROJECT_ROOT_DIR))
    os.environ["RUNTIME_TRACE_WORKSPACE_ROOT"] = PROJECT_ROOT
    try:
        from runtime_trace.tools import flow_send
    except ModuleNotFoundError:
        print(f"  ⚠️ runtime_trace 加载失败, 检查路径: {_PROJECT_ROOT_DIR}")
        flow_send = None
    for aid in agent_ids:
        print(f"  ✅ {aid}: 已收到任务简报")

    # Phase 3: Flow engine runs (NOT manager)
    _flow_id = yaml_path.stem
    _resolved_output = output_base.replace("{flow_id}", _flow_id) if output_base else f"output/{_flow_id}"
    run_flow(goal, agent_ids, yaml_path, run_name, agents, _resolved_output)


# ═══════════════════════════════════════════════════════════════════════
#  Checkpoint subcommands
# ═══════════════════════════════════════════════════════════════════════

def _cmd_checkpoints(argv: list[str]):
    """Handle --checkpoints, --diff-checkpoint <id>, --revert-checkpoint <id>."""
    import difflib
    from runtime_trace.storage import RuntimeStore

    cmd = argv[0]

    # Collect all run stores
    run_dirs = []
    for base in (Path(PROJECT_ROOT) / ".runtime-trace" / "runs", _SCRIPT_DIR / ".runtime-trace" / "runs"):
        if base.exists():
            run_dirs.extend(sorted(base.iterdir()))
    run_dirs = [d for d in run_dirs if d.is_dir()]

    stores = {}
    for d in run_dirs:
        try:
            s = RuntimeStore(d)
            s.init_schema()
            stores[d.name] = s
        except Exception:
            pass

    if cmd == "--checkpoints":
        total = 0
        for rid, store in sorted(stores.items()):
            for b in store.list_evolution_backups(reverted=0):
                print(f"  #{b['id']:<4} run={b['run_id']:<14} file={b['file_path']:<60} {b['patch_summary']}")
                total += 1
        if total == 0:
            print("  (no checkpoints found)")
        return

    if cmd in ("--diff-checkpoint", "--revert-checkpoint"):
        if len(argv) < 2:
            print(f"❌ {cmd} requires a backup_id")
            sys.exit(1)
        bid = int(argv[1])
        for rid, store in sorted(stores.items()):
            b = store.get_evolution_backup(bid)
            if b:
                abs_path = Path(PROJECT_ROOT) / b["file_path"]
                if cmd == "--diff-checkpoint":
                    current = abs_path.read_text().splitlines(True) if abs_path.exists() else ["(file missing)\n"]
                    original = b["original_content"].splitlines(True)
                    diff = difflib.unified_diff(
                        original, current,
                        fromfile=f"{b['file_path']} (checkpoint #{bid})",
                        tofile=f"{b['file_path']} (current)",
                    )
                    sys.stdout.writelines(diff)
                else:  # --revert-checkpoint
                    if store.revert_evolution_backup(bid):
                        print(f"✅ Reverted #{bid}: {b['file_path']}")
                    else:
                        print(f"❌ Revert failed for #{bid}")
                return
        print(f"❌ Backup #{bid} not found in any run store")
        return

    print(f"❌ Unknown checkpoint command: {cmd}")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════
#  Sandbox apply subcommand
# ═══════════════════════════════════════════════════════════════════════

def _cmd_apply_sandbox(argv: list[str]):
    """Apply sandboxed changes to real project. Archive to independent git first."""
    import subprocess as _sp
    import shutil

    run_id = argv[1]
    auto_yes = "--yes" in argv

    sandbox_dir = _SCRIPT_DIR / ".self" / run_id
    if not sandbox_dir.exists():
        print(f"❌ Sandbox {run_id} not found at {sandbox_dir}")
        sys.exit(1)

    # 1. Archive: independent git init + commit (not affecting project git)
    if not shutil.which("git"):
        print("❌ git not found in PATH")
        sys.exit(1)

    archive_git = sandbox_dir / ".git"
    if not archive_git.exists():
        _sp.run(["git", "init"], cwd=str(sandbox_dir), capture_output=True)
        _sp.run(["git", "-c", "user.name=sandbox", "-c", "user.email=sandbox@local",
                  "commit", "--allow-empty", "-m", "empty root"],
                cwd=str(sandbox_dir), capture_output=True)

    _sp.run(["git", "add", "-A"], cwd=str(sandbox_dir), capture_output=True)
    _sp.run(["git", "-c", "user.name=sandbox", "-c", "user.email=sandbox@local",
              "commit", "-m", f"snapshot before apply {run_id}",
              "--allow-empty"],
            cwd=str(sandbox_dir), capture_output=True)

    # 2. Scan diffs
    changed = []
    for f in sorted(sandbox_dir.rglob("*")):
        if f.is_file() and ".git" not in f.parts:
            rel = f.relative_to(sandbox_dir)
            real = Path(PROJECT_ROOT) / rel
            if not real.exists() or real.read_bytes() != f.read_bytes():
                changed.append(rel)

    if not changed:
        print("✅ No changes to apply.")
        return

    # 3. Print diff summary
    print(f"📋 {len(changed)} file(s) to apply:")
    for rel in changed:
        print(f"   {rel}")

    if not auto_yes:
        try:
            answer = input("Apply these changes? [y/N] ").strip().lower()
        except EOFError:
            answer = "n"
        if answer != "y":
            print("⏭  Skipped.")
            return

    # 4. Apply
    skipped = []
    applied = 0
    for rel in changed:
        src = sandbox_dir / rel
        dst = Path(PROJECT_ROOT) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        applied += 1

    plural = "s" if applied != 1 else ""
    suffix = f" (skipped {len(skipped)} conflict)" if skipped else ""
    print(f"✅ Applied {applied} file{plural}.{suffix}")


# ═══════════════════════════════════════════════════════════════════════
#  Main entry
# ═══════════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print_help()
        sys.exit(0)

    argv = sys.argv[1:]

    # ── LLM config commands ──────────────────────────────────
    if argv[0] == "--show-model":
        _cmd_show_model()
        return
    if argv[0] == "--set-model":
        if len(argv) < 2:
            print("❌ --set-model requires a model name")
            sys.exit(1)
        _cmd_set_model(argv[1])
        return
    if argv[0] == "--set-url":
        if len(argv) < 2:
            print("❌ --set-url requires a URL")
            sys.exit(1)
        _cmd_set_url(argv[1])
        return
    if argv[0] == "--set-key":
        if len(argv) < 2:
            print("❌ --set-key requires a key")
            sys.exit(1)
        _cmd_set_key(argv[1])
        return

    # ── --resume ─────────────────────────────────────────────
    if argv[0] == "--resume":
        _handle_resume(argv)
        return

    # ── Other subcommands ────────────────────────────────────
    if argv[0] == "--analyze":
        analyze_all_runs()
        return
    if argv[0] == "--evolve":
        evolve()
        return
    if argv[0] == "--evolve-agent":
        if len(argv) < 2:
            print("❌ --evolve-agent requires an agent_id")
            sys.exit(1)
        _apply = "--apply" in argv
        evolve_agent(argv[1], apply=_apply)
        return
    if argv[0] == "--evolve-all":
        evolve_all()
        return
    if argv[0] == "--feedback":
        agent_id = argv[1] if len(argv) > 1 else None
        show_feedback(agent_id)
        return

    if argv[0] in ("--checkpoints", "--diff-checkpoint", "--revert-checkpoint"):
        _cmd_checkpoints(argv)
        return

    if argv[0] == "--apply-sandbox":
        if len(argv) < 2:
            print("❌ --apply-sandbox requires a run_id")
            sys.exit(1)
        _cmd_apply_sandbox(argv)
        return

    # ── --self mode: strip flag, pass to _handle_task ────────
    self_mode = "--self" in argv
    if self_mode:
        argv = [a for a in argv if a != "--self"]

    # ── LLM runtime override flags + task ────────────────────
    cli_model = ""
    cli_url = ""
    cli_key = ""
    task_parts: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--model" and i + 1 < len(argv):
            cli_model = argv[i + 1]
            i += 2
        elif argv[i] == "--api-url" and i + 1 < len(argv):
            cli_url = argv[i + 1]
            i += 2
        elif argv[i] == "--api-key" and i + 1 < len(argv):
            cli_key = argv[i + 1]
            i += 2
        else:
            task_parts.append(argv[i])
            i += 1

    goal = " ".join(task_parts)
    if not goal:
        print("❌ 请提供任务描述")
        sys.exit(1)

    _handle_task(goal, cli_model=cli_model, cli_url=cli_url, cli_key=cli_key,
                self_mode=self_mode)

    # Cleanup sandbox state after run to prevent leakage
    if self_mode:
        from tools._security import set_sandbox_root, get_sandbox_root
        sb = get_sandbox_root()
        set_sandbox_root(None)
        if sb:
            print(f"\n🔒 沙箱产物: {sb}")
            print(f"   审核后合入: debate --apply-sandbox {sb.name}")


if __name__ == "__main__":
    main()
