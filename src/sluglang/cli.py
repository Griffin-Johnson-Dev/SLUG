from __future__ import annotations

import argparse
import ast as pyast
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .compiler import build, build_file, emit_c, emit_c_file, emit_ir, emit_ir_file, emit_mir, emit_mir_file, frontend, frontend_file, parse_file
from .crusher import crush
from .diagnostics import SlugError
from .formatter import pretty_program
from .lexer import lex
from .parser import parse
from .project import discover_project, project_for_source


def _configure_utf8_stdio() -> None:
    """Make the bootstrap CLI Unicode-stable even under legacy host code pages.

    Native SLUG text is UTF-8 by language definition.  On Windows, redirected
    Python stdout/stderr may otherwise inherit an ANSI/OEM encoding (for example
    cp1252), so merely decoding native output as UTF-8 is not enough: writing the
    resulting Unicode text back through that stream can fail on non-ASCII data.
    Reconfigure the text wrappers at the CLI boundary.  Test doubles such as
    StringIO do not expose ``reconfigure`` and are intentionally left alone.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="strict")
        except (OSError, ValueError, TypeError):
            # Embedded hosts may expose an immutable/already-detached stream.
            # The caller still gets the host-provided stream semantics there.
            pass


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _default_out(path: str, suffix: str) -> Path:
    return Path(path).with_suffix(suffix)


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    forwarded_run_args: list[str] | None = None
    if "run" in raw_argv:
        run_i = raw_argv.index("run")
        try:
            sep_i = raw_argv.index("--", run_i + 1)
        except ValueError:
            pass
        else:
            forwarded_run_args = raw_argv[sep_i + 1:]
            raw_argv = raw_argv[:sep_i]
    ap = argparse.ArgumentParser(prog="slug", description="SLUG compiler")
    ap.add_argument("--version", action="store_true", help="print compiler implementation version")
    ap.add_argument("--language-version", action="store_true", help="print implemented SLUG language contract version")
    sub = ap.add_subparsers(dest="cmd")

    for name, help_text in (
        ("check", "lex, parse, and semantically check a source file"),
        ("ast", "print the parsed AST"),
        ("crush", "convert .slg to AST-equivalent crushed .slgc"),
        ("expand", "expand .slgc/.slg into roomy formatted .slg"),
        ("ir", "emit typed SLUG high-level IR"),
        ("mir", "emit CFG/SSA optimizer MIR"),
        ("opt-ir", "emit optimized CFG/SSA MIR"),
        ("emit-c", "emit bootstrap C backend output"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("file", nargs="?" if name == "check" else None)
        if name in {"crush", "expand", "ir", "mir", "opt-ir", "emit-c"}:
            p.add_argument("-o", "--output")

    sub.add_parser("tooling-info", help="print stable machine-readable tooling capabilities")

    p = sub.add_parser("project-info", help="print stable machine-readable discovered project context")
    p.add_argument("file", nargs="?")

    p = sub.add_parser("build", help="compile supported SLUG subset to a native executable")
    p.add_argument("file", nargs="?")
    p.add_argument("-o", "--output")
    p.add_argument("--cc")
    p.add_argument("--keep-c")

    p = sub.add_parser("run", help="compile and run a supported SLUG program")
    p.add_argument("file", nargs="?")
    p.add_argument("--cc")
    p.add_argument("args", nargs=argparse.REMAINDER, help="arguments passed to the SLUG program (use -- before option-like values)")

    ns = ap.parse_args(raw_argv)
    if ns.version:
        from . import __version__
        print(__version__)
        return 0
    if ns.language_version:
        print("1.0")
        return 0
    if ns.cmd is None:
        ap.error("a command is required")
    if ns.cmd == "tooling-info":
        from . import __version__
        info = {
            "schema": 1,
            "compiler_version": __version__,
            "language_version": "1.0",
            "cli_contract": 1,
            "manifest_schema": 1,
            "diagnostic_schema": 1,
            "capabilities": {
                "fmt": True,
                "crush": True,
                "expand": True,
                "json_diagnostics": True,
                "project_discovery": True,
                "local_dependencies": True,
                "stdin_overlay": True,
                "failure_locator": True,
                "semantic_provenance": True,
                "lexical_provenance": True,
                "lsp": True,
            },
        }
        print(json.dumps(info, separators=(",", ":"), ensure_ascii=False))
        return 0
    if ns.cmd == "project-info":
        project = project_for_source(ns.file) if ns.file is not None else discover_project()
        if project is None:
            print('{"schema":1,"found":false}')
            return 0
        info = {
            "schema": 1,
            "found": True,
            "manifest": str(project.manifest_path),
            "root": str(project.root) + ("/" if not str(project.root).endswith(("/", "\\")) else ""),
            "name": project.name,
            "entry": project.entry,
            "entry_path": str(project.entry_path),
            "dependency_count": len(project.dependencies),
        }
        print(json.dumps(info, separators=(",", ":"), ensure_ascii=False))
        return 0

    source = ""
    project = None
    project_mode = False
    try:
        if ns.cmd in {"check", "build", "run"} and ns.file is None:
            project = discover_project()
            if project is None:
                raise SlugError("no slug.json project manifest found")
            ns.file = str(project.entry_path)
            project_mode = True
        source = _read(ns.file)
        if ns.cmd == "check":
            frontend_file(ns.file)
            print(f"PASS {ns.file}")
            return 0
        if ns.cmd == "ast":
            print(repr(frontend_file(ns.file)))
            return 0
        if ns.cmd == "crush":
            _, _, symbols, modules = parse_file(ns.file)
            out = Path(ns.output) if ns.output else _default_out(ns.file, ".slgc")
            out.write_text(crush(source, symbols, modules) + "\n", encoding="utf-8")
            print(out)
            return 0
        if ns.cmd == "expand":
            _, program, _, _ = parse_file(ns.file)
            out = Path(ns.output) if ns.output else _default_out(ns.file, ".slg")
            out.write_text(pretty_program(program), encoding="utf-8")
            print(out)
            return 0
        if ns.cmd == "ir":
            out = Path(ns.output) if ns.output else _default_out(ns.file, ".slgir")
            out.write_text(emit_ir_file(ns.file), encoding="utf-8")
            print(out)
            return 0
        if ns.cmd in {"mir", "opt-ir"}:
            out = Path(ns.output) if ns.output else _default_out(ns.file, ".mir" if ns.cmd == "mir" else ".opt.mir")
            out.write_text(emit_mir_file(ns.file, optimized=ns.cmd == "opt-ir"), encoding="utf-8")
            print(out)
            return 0
        if ns.cmd == "emit-c":
            out = Path(ns.output) if ns.output else _default_out(ns.file, ".c")
            out.write_text(emit_c_file(ns.file), encoding="utf-8")
            print(out)
            return 0
        if ns.cmd == "build":
            if project_mode and project is not None:
                project.build_root.mkdir(parents=True, exist_ok=True)
                default = project.default_output(windows=sys.platform.startswith("win"))
            else:
                default = Path(ns.file).with_suffix(".exe" if sys.platform.startswith("win") else "")
            out = Path(ns.output) if ns.output else default
            build_file(ns.file, out, ns.cc, ns.keep_c)
            print(out)
            return 0
        if ns.cmd == "run":
            suffix = ".exe" if sys.platform.startswith("win") else ""
            with tempfile.TemporaryDirectory(prefix="slug-run-") as td:
                exe = Path(td) / ("slug_program" + suffix)
                build_file(ns.file, exe, ns.cc)
                # Native SLUG stdout/stderr are UTF-8 by language definition.
                # Decode explicitly instead of inheriting Windows' legacy OEM/ANSI
                # code pages, then let Python write Unicode to the host terminal.
                run_args = list(ns.args) if forwarded_run_args is None else forwarded_run_args
                if run_args[:1] == ["--"]:
                    run_args = run_args[1:]
                proc = subprocess.run(
                    [str(exe), *run_args],
                    text=True,
                    encoding="utf-8",
                    errors="strict",
                    capture_output=True,
                )
                if proc.stdout:
                    sys.stdout.write(proc.stdout)
                    sys.stdout.flush()
                if proc.stderr:
                    sys.stderr.write(proc.stderr)
                    sys.stderr.flush()
                return proc.returncode
    except SlugError as e:
        print(e.render(source, ns.file), file=sys.stderr)
        return 2
    except Exception as e:
        print(f"slug: {e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
