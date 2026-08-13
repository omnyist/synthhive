#!/usr/bin/env -S uv run
"""Find sync FK loads hiding inside async code.

Accessing a ForeignKey that wasn't preloaded runs a synchronous query.
In async code Django raises SynchronousOnlyOperation for that, which
surfaces as a 500 in production and never in tests — test fixtures hand
you model instances with their relations already cached, so the lazy
load never happens there.

This has bitten the suite four times (gift leaderboard 500s, dropped
resub publishes, get_active_campaign, then the campaign.tenant publish
sites). Two shapes are checked:

  fetch  a variable assigned from an unguarded async fetch, whose FK is
         read later in the same function
  param  an async function reading a FK on an object it was *handed* —
         safe only while every caller preloads, which is the shape the
         real bugs had and which no single-function check can see

Findings are suggestions, not proof: the check matches attribute names
against every FK name in the project, so an unrelated object carrying a
matching attribute (argparse's `args.session`, a dataclass `.user`)
reports as a hit. Read each one before changing anything.

Usage:
    uv run scripts/audit_async_fk.py [path] [--shape fetch|param|all]

Exits 1 if anything is found, so it can gate CI. `--shape fetch` gates
on the unambiguous shape alone, which is useful in a project whose
param-shape hits are known-safe by a single-caller contract.
"""

from __future__ import annotations

import ast
import pathlib
import sys

FETCH_METHODS = {"aget", "afirst", "acreate", "aget_or_create"}
SKIP_PARAMS = {"self", "cls", "request"}
SKIP_DIRS = (".venv", "migrations", ".archive", "node_modules")


def _skipped(path: pathlib.Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def foreign_key_names(root: pathlib.Path) -> set[str]:
    """Every FK/OneToOne field name declared under root."""
    names: set[str] = set()
    for path in root.rglob("models.py"):
        if _skipped(path):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if getattr(node.value.func, "attr", "") in {
                    "ForeignKey",
                    "OneToOneField",
                }:
                    names.update(
                        t.id for t in node.targets if isinstance(t, ast.Name)
                    )
    return names


def _wrapped_nodes(fn: ast.AST) -> set[int]:
    """Nodes already inside a sync_to_async(...) call — those are fine."""
    wrapped: set[int] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and "sync_to_async" in ast.unparse(node.func):
            wrapped.update(id(sub) for sub in ast.walk(node))
    return wrapped


def check_function(fn: ast.AsyncFunctionDef, fks: set[str]) -> list[tuple[int, str, str]]:
    findings: list[tuple[int, str, str]] = []
    wrapped = _wrapped_nodes(fn)

    fetched: dict[str, bool] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Await):
            call = node.value.value
            if not isinstance(call, ast.Call):
                continue
            source = ast.unparse(call)
            direct = any(f".{m}(" in source for m in FETCH_METHODS)
            # `await sync_to_async(Model.objects.get)(...)` hands the
            # instance back to async code exactly like aget() does.
            threaded = "sync_to_async" in source and ".objects." in source
            if not (direct or threaded):
                continue
            preloaded = "select_related" in source or "prefetch_related" in source
            for target in node.targets:
                if isinstance(target, ast.Name):
                    fetched[target.id] = preloaded

    params = {a.arg for a in fn.args.args if a.arg not in SKIP_PARAMS}

    for node in ast.walk(fn):
        if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)):
            continue
        # Only reads lazy-load; `obj.fk = x` populates the cache instead.
        if not isinstance(node.ctx, ast.Load):
            continue
        if node.attr not in fks or id(node) in wrapped:
            continue
        name = node.value.id
        if name in fetched and not fetched[name]:
            findings.append((node.lineno, f"{name}.{node.attr}", "fetch"))
        elif name in params:
            findings.append((node.lineno, f"{name}.{node.attr}", "param"))
    return findings


def main(argv: list[str]) -> int:
    shape = "all"
    args = argv[1:]
    if "--shape" in args:
        i = args.index("--shape")
        shape = args[i + 1]
        del args[i : i + 2]
    root = pathlib.Path(args[0] if args else ".")
    fks = foreign_key_names(root)
    if not fks:
        print("no model files found; nothing to check")
        return 0

    total = 0
    for path in sorted(root.rglob("*.py")):
        if _skipped(path) or "tests" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for lineno, chain, kind in check_function(node, fks):
                if shape != "all" and kind != shape:
                    continue
                print(f"{path}:{lineno}  [{kind}]  {chain}  (async {node.name})")
                total += 1

    if total:
        print(
            f"\n{total} possible sync FK load(s) in async code.\n"
            "Fix by preloading with select_related at the fetch, or by "
            "resolving the relation through sync_to_async where it's read."
        )
        return 1
    print("no sync FK loads found in async code")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
