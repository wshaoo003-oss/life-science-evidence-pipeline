#!/usr/bin/env python3
"""Discover persistent research runtimes without hardcoded user paths."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path


TOOL_COMMANDS = {
    "instsci": ("instsci",),
    "mineru": ("mineru",),
    "markitdown": ("markitdown",),
    "docling": ("docling",),
    "agent-reach": ("agent-reach",),
}


def candidate_roots() -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    configured = os.environ.get("RESEARCH_PIPELINE_ROOT")
    if configured:
        roots.append(("RESEARCH_PIPELINE_ROOT", Path(configured)))
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    roots.append(("CODEX_HOME/tool-runtimes", codex_home / "tool-runtimes"))
    return roots


def executable_names(command: str) -> tuple[str, ...]:
    if os.name == "nt":
        return (f"{command}.exe", f"{command}.cmd", f"{command}.bat", command)
    return (command,)


def find_tool(tool: str) -> dict:
    commands = TOOL_COMMANDS[tool]
    for command in commands:
        found = shutil.which(command)
        if found:
            return {"available": True, "path": str(Path(found).resolve()), "source": "PATH"}

    directory_aliases = {
        "instsci": ("instsci",),
        "mineru": ("mineru",),
        "markitdown": ("markitdown",),
        "docling": ("docling",),
        "agent-reach": ("agent-reach", "agent_reach"),
    }[tool]
    for source, root in candidate_roots():
        bases = (root, root / "research-pipeline")
        for base in bases:
            for alias in directory_aliases:
                for scripts_dir in (base / alias / "Scripts", base / alias / "bin"):
                    for command in commands:
                        for name in executable_names(command):
                            candidate = scripts_dir / name
                            if candidate.is_file():
                                return {"available": True, "path": str(candidate.resolve()), "source": source}
    return {"available": False, "path": None, "source": None}


def grobid_status(url: str) -> dict:
    endpoint = url.rstrip("/") + "/api/isalive"
    try:
        with urllib.request.urlopen(endpoint, timeout=2) as response:
            body = response.read(200).decode("utf-8", errors="replace").strip()
        return {"available": response.status == 200, "url": url, "detail": body or "HTTP 200"}
    except (OSError, urllib.error.URLError) as exc:
        return {"available": False, "url": url, "detail": str(exc)}


def inspect_runtime() -> dict:
    tools = {name: find_tool(name) for name in TOOL_COMMANDS}
    tools["grobid"] = grobid_status(os.environ.get("GROBID_URL", "http://127.0.0.1:8070"))
    return {
        "python": sys.executable,
        "discovery_order": ["PATH", "RESEARCH_PIPELINE_ROOT", "CODEX_HOME/tool-runtimes"],
        "tools": tools,
        "ready_core": all(tools[name]["available"] for name in ("mineru", "markitdown", "docling")),
        "optional_unavailable": [name for name in ("instsci", "agent-reach", "grobid") if not tools[name]["available"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect_runtime()
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["ready_core"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

