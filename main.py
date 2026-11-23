"""Entry point. The project is a FastAPI application; a terminal CLI is included.

    uvicorn main:app --reload                               # API server (docs at /docs)
    python main.py                                          # same, on port 8000
    python main.py cli --pr https://github.com/o/r/pull/1   # review a GitHub PR
    git diff | python main.py cli --diff -                  # review your local changes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.api import create_app
from src.utils import load_settings, setup_logging

settings = load_settings()
setup_logging(settings.log_level, settings.log_dir)
app = create_app(settings)

BOLD, DIM, RED, YELLOW, GREEN, CYAN, RESET = "\033[1m", "\033[2m", "\033[31m", "\033[33m", "\033[32m", "\033[36m", "\033[0m"
SEVERITY_COLOR = {"critical": RED + BOLD, "high": RED, "medium": YELLOW, "low": DIM}


def cli(args: argparse.Namespace) -> None:
    from src.agent import REVIEWERS, ReviewPanel, open_checkpointer
    from src.api.reviews import ReviewManager
    from src.models import anthropic_factory

    diff = None
    if args.diff:
        diff = sys.stdin.read() if args.diff == "-" else Path(args.diff).read_text(encoding="utf-8")
    checkpointer = open_checkpointer(settings.sessions_dir)
    manager = ReviewManager(settings, lambda: ReviewPanel(settings, anthropic_factory(settings), checkpointer))
    review = manager.start(diff=diff, pr_url=args.pr, title=args.title or "", description="",
                           reviewers=args.reviewers or list(REVIEWERS))
    for event in manager.stream(review):
        if not event:
            continue
        kind = event["type"]
        if kind == "fetched":
            print(f"{DIM}fetched {event['title']}{RESET}")
        elif kind == "specialist_started":
            print(f"{DIM}{REVIEWERS[event['reviewer']].icon} {event['reviewer']} reviewing…{RESET}")
        elif kind == "specialist_done":
            print(f"{GREEN}✓{RESET} {event['reviewer']}: {event['count']} finding(s)")
        elif kind == "specialist_failed":
            print(f"{RED}✗ {event['reviewer']}: {event['error']}{RESET}")
        elif kind == "lead_started":
            print(f"{DIM}🧑‍⚖️ lead reviewer verifying and ranking…{RESET}")
        elif kind == "error":
            sys.exit(f"{RED}{event['message']}{RESET}")

    report = review.report
    verdict = {"approve": GREEN + "APPROVE", "comment": YELLOW + "COMMENT", "request_changes": RED + "REQUEST CHANGES"}
    print(f"\n{BOLD}{verdict[report['verdict']]}{RESET}\n\n{report['summary']}\n")
    for f in report["findings"]:
        where = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
        print(f"{SEVERITY_COLOR[f['severity']]}[{f['severity'].upper()}]{RESET} {BOLD}{where}{RESET}  {f['title']}"
              f"  {DIM}({', '.join(f['raised_by'])}){RESET}")
        print(f"  {f['explanation']}\n  {CYAN}fix:{RESET} {f['suggestion']}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Agent Code Review")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="Run the FastAPI server (default).")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    c = sub.add_parser("cli", help="Review a diff or PR in the terminal.")
    source = c.add_mutually_exclusive_group(required=True)
    source.add_argument("--diff", help="Path to a diff file, or '-' to read stdin.")
    source.add_argument("--pr", help="GitHub pull request URL.")
    c.add_argument("--title", help="Title for a pasted diff.")
    c.add_argument("--reviewers", nargs="+", help="Subset of specialists to run.")
    args = parser.parse_args()
    if args.command == "cli":
        cli(args)
    else:
        import uvicorn

        uvicorn.run(app, host=getattr(args, "host", "0.0.0.0"), port=getattr(args, "port", 8000))


if __name__ == "__main__":
    main()
