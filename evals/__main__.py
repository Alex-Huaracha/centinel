"""Run the eval cases through Claude Code and report how often each one passes.

    uv run python -m evals [case ...] [--runs N]

Each run is one `claude -p` conversation whose only tools are Centinel's,
served from the eval database and the case's emails. It uses the Claude Code
login, so it counts against the subscription's usage limits.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from evals.cases import CASES, Case
from evals.database import create_eval_database, create_eval_engine, reset

ROOT = Path(__file__).resolve().parent.parent

# Replaces Claude Code's own coding prompt, so the model sees about what a chat
# client gives it. Nobody answers during a run, so questions go at the end.
SYSTEM_PROMPT = (
    "You are a helpful assistant. The user cannot reply during this "
    "conversation: do what they ask, and put any questions for them in your "
    "final message."
)

# The user's timezone; UTC keeps the case dates simple.
TIMEZONE = "UTC"

RUN_TIMEOUT_SECONDS = 900


@dataclass(frozen=True)
class RunResult:
    problems: list[str]
    turns: int | None
    transcript: Path


def _mcp_config(case: Case) -> dict:
    return {
        "mcpServers": {
            "centinel": {
                "command": "uv",
                "args": [
                    "--directory",
                    str(ROOT),
                    "run",
                    "python",
                    "-m",
                    "evals.server",
                    case.name,
                ],
                "env": {"TIMEZONE": TIMEZONE},
            }
        }
    }


def run_case(claude: str, engine: Engine, case: Case, transcript: Path) -> RunResult:
    reset(engine, case)
    with tempfile.TemporaryDirectory() as workdir:
        config = Path(workdir) / "mcp.json"
        config.write_text(json.dumps(_mcp_config(case)), encoding="utf-8")
        # Run from an empty directory, so no project CLAUDE.md is loaded.
        completed = subprocess.run(
            [
                claude,
                "-p",
                case.prompt,
                "--system-prompt",
                SYSTEM_PROMPT,
                "--mcp-config",
                str(config),
                "--strict-mcp-config",
                # No built-in tools (shell, files, web): only Centinel's.
                "--tools",
                "",
                "--allowedTools",
                "mcp__centinel",
                "--output-format",
                "stream-json",
                "--verbose",
                "--no-session-persistence",
            ],
            cwd=workdir,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=RUN_TIMEOUT_SECONDS,
        )
    transcript.write_text(completed.stdout + completed.stderr, encoding="utf-8")

    result = next(
        (
            message
            for line in reversed(completed.stdout.splitlines())
            if line.startswith("{")
            and (message := json.loads(line)).get("type") == "result"
        ),
        None,
    )
    if result is None or result.get("is_error"):
        return RunResult(["claude did not finish the run"], None, transcript)
    with Session(engine) as session:
        problems = case.problems(session, result.get("result", ""))
    return RunResult(problems, result.get("num_turns"), transcript)


def main() -> None:
    names = [case.name for case in CASES]
    parser = argparse.ArgumentParser(prog="python -m evals")
    parser.add_argument("cases", nargs="*", choices=names, metavar="case")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    claude = shutil.which("claude")
    if claude is None:
        sys.exit("Claude Code (claude) is not on PATH.")
    selected = [case for case in CASES if not args.cases or case.name in args.cases]

    create_eval_database()
    engine = create_eval_engine()
    transcripts = (
        Path(tempfile.gettempdir())
        / "centinel-evals"
        / (datetime.now().strftime("%Y%m%d-%H%M%S"))
    )
    transcripts.mkdir(parents=True)

    passed_runs = 0
    for case in selected:
        results = []
        for run in range(1, args.runs + 1):
            print(f"{case.name} {run}/{args.runs}...", end=" ", flush=True)
            result = run_case(
                claude, engine, case, transcripts / f"{case.name}-{run}.jsonl"
            )
            print("pass" if not result.problems else "FAIL", flush=True)
            for problem in result.problems:
                print(f"    {problem}")
            results.append(result)
        passed = sum(not result.problems for result in results)
        passed_runs += passed
        print(f"  => {case.name}: {passed}/{args.runs}\n", flush=True)

    total = len(selected) * args.runs
    print(f"Passed {passed_runs}/{total} runs. Transcripts: {transcripts}")
    engine.dispose()


if __name__ == "__main__":
    main()
