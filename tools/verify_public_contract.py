from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sluglang.builtins import CORE_NAMES, STD_MODULE_NAMES  # noqa: E402

EXPECTED_CORE = ("co", "ci", "ty", "cv", "in", "iv", "ln", "sl", "by")
EXPECTED_STD = {
    "@std/sys": ("av", "ev", "cw", "pf", "cp", "pc"),
    "@std/time": ("tm", "mt", "wt"),
    "@std/rand": ("en",),
    "@std/fs": ("fr", "ft", "fw", "fa", "fe", "fd", "fm", "md", "rm", "mv", "fo", "hr", "hw", "hs", "hp", "hf", "hc"),
    "@std/net": ("so", "cn", "bn", "ls", "ac", "sd", "rc", "sc", "gp"),
    "@std/gfx": ("sf", "px", "rf", "dl", "sb", "wn", "wf", "pe", "wx"),
    "@std/audio": ("au", "aq", "ax"),
    "@std/dev": ("do", "dv", "dr", "dw", "dx"),
    "@std/list": ("ap", "ip", "rm", "pp"),
}

errors: list[str] = []

def expect(cond: bool, msg: str) -> None:
    if not cond:
        errors.append(msg)

expect((ROOT / "LANGUAGE_VERSION").read_text().strip() == "1.0", "LANGUAGE_VERSION must be 1.0")
expect((ROOT / "CLI_CONTRACT_VERSION").read_text().strip() == "1", "CLI_CONTRACT_VERSION must be 1")
contract = json.loads((ROOT / "PUBLIC_CONTRACT.json").read_text(encoding="utf-8"))
expect(contract.get("language_version") == "1.0", "PUBLIC_CONTRACT language_version drifted")
expect(contract.get("cli_contract_version") == 1, "PUBLIC_CONTRACT cli_contract_version drifted")
expect(contract.get("identifiers") == {
    "short_variable": "[a-z]",
    "extended_identifier": "_[A-Za-z0-9]+_",
    "ascii_only": True,
    "case_sensitive": True,
    "interior_underscore": False,
}, "PUBLIC_CONTRACT identifier grammar drifted")
expect(tuple(contract.get("root_builtins", ())) == EXPECTED_CORE, "PUBLIC_CONTRACT root builtin set drifted")
expect({k: tuple(v) for k, v in contract.get("standard_modules", {}).items()} == EXPECTED_STD, "PUBLIC_CONTRACT standard modules drifted")
expect(tuple(CORE_NAMES) == EXPECTED_CORE, f"root builtin set drifted: {CORE_NAMES!r}")
expect(dict(STD_MODULE_NAMES) == EXPECTED_STD, "standard-module export surface drifted")

required_docs = [
    "docs/SLUG_V1_SPECIFICATION.md",
    "docs/SLUG_PUBLIC_CLI_V1.md",
    "docs/SLUG_V1_STANDARD_MODULES.md",
    "docs/SLUG_V1_STABILITY_AND_AUTHORITY.md",
]
for rel in required_docs:
    expect((ROOT / rel).is_file(), f"missing {rel}")

spec = (ROOT / "docs/SLUG_V1_SPECIFICATION.md").read_text(encoding="utf-8")
cli = (ROOT / "docs/SLUG_PUBLIC_CLI_V1.md").read_text(encoding="utf-8")
expect("_[A-Za-z0-9]+_" in spec or "one or more ASCII alphanumeric" in spec, "spec does not define the simplified extended-identifier grammar")
for token in EXPECTED_CORE:
    expect(f"`{token}`" in spec, f"spec does not name root builtin {token}")
for uri in EXPECTED_STD:
    expect(f"`{uri}`" in spec, f"spec does not name standard module {uri}")
for command in ("check", "build", "run", "fmt", "crush", "expand"):
    expect(f"`slug {command}`" in cli, f"CLI contract does not define slug {command}")
for code in ("`64`", "`65`", "`69`", "`70`"):
    expect(code in cli, f"CLI exit-code contract missing {code}")

summary = {
    "language_version": "1.0",
    "cli_contract_version": 1,
    "root_builtins": list(CORE_NAMES),
    "standard_modules": {k: list(v) for k, v in STD_MODULE_NAMES.items()},
    "status": "PASS" if not errors else "FAIL",
}
print(json.dumps(summary, sort_keys=True))
if errors:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    raise SystemExit(1)
