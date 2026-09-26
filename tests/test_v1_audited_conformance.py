from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sluglang import ast
from sluglang.compiler import build, build_file, frontend, frontend_file
from sluglang.formatter import compact_program, pretty_program, semantic_key
from sluglang.diagnostics import LexError, ParseError


class AuditedV1ConformanceTests(unittest.TestCase):
    @staticmethod
    def logical_stdout(data: bytes) -> bytes:
        # Console output is text-mode I/O. Windows represents each logical newline
        # as CRLF at the host boundary; conformance compares language-level lines.
        # Preserve every other byte exactly, including embedded NUL and UTF-8.
        return data.replace(b"\r\n", b"\n")

    def run_native_bytes(self, source: str, stdin: bytes = b"") -> bytes:
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td) / ("probe.exe" if sys.platform == "win32" else "probe")
            build(source, exe)
            cp = subprocess.run([str(exe)], input=stdin, capture_output=True, check=True)
            return self.logical_stdout(cp.stdout)

    def test_formatted_string_roundtrips(self):
        src = "a:=2 b:=3 c:='sum={ab+}; braces=\\{ok\\}' co[c]"
        p = frontend(src)
        for rendered in (compact_program(p), pretty_program(p)):
            with self.subTest(rendered=rendered):
                self.assertEqual(semantic_key(frontend(rendered)), semantic_key(p))

    def test_formatted_string_native_and_left_to_right(self):
        out = self.run_native_bytes("a:=0 co['{a:=1}{a:=2}{a}']")
        self.assertEqual(out, b"122\n")

    def test_formatted_string_embedded_nul_is_binary_safe(self):
        out = self.run_native_bytes("a:=5 co['x\\0{a}y']")
        self.assertEqual(out, b"x\x005y\n")

    def test_escaped_braces_are_literal(self):
        out = self.run_native_bytes("co['a\\{b\\}c']")
        self.assertEqual(out, b"a{b}c\n")

    def test_unescaped_stray_closing_brace_rejected(self):
        with self.assertRaises(ParseError):
            frontend("co['a}b']")

    def test_deep_nested_source_not_limited_by_python_default_recursion(self):
        depth = 1400
        p = frontend("a:=" + "[" * depth + "1" + "]" * depth)
        self.assertIsInstance(p.statements[0].expr, ast.AssignExpr)

    def test_deep_nested_value_compiles_and_returns_natively(self):
        depth = 900
        value = "[" * depth + "1" + "]" * depth
        src = f"~zz{{rv {value}}} a:=zz[] co[ln[a]]"
        self.assertEqual(self.run_native_bytes(src), b"1\n")

    def test_exact_integer_division(self):
        self.assertEqual(self.run_native_bytes("co[7 2 //]"), b"3\n")
        self.assertEqual(self.run_native_bytes("co[7- 2 //]"), b"-3\n")

    def test_ci_is_text_only(self):
        # Explicit conversion is required if numeric interpretation is wanted.
        out = self.run_native_bytes("a:=ci co[ty[a]] co[a]", b"123\n")
        self.assertEqual(out, b"s\n123\n")

    def test_return_arity_is_not_capped_at_eight(self):
        vals = " ".join(f"{i}$" for i in range(1, 13))
        src = f"~zz{{rv{vals}}}abcdefghijkl:=zz[] co[l]"
        p = frontend(src)
        self.assertEqual(len(p.statements[0].body[0].values), 12)
        self.assertEqual(self.run_native_bytes(src), b"12\n")

    def test_explicit_pack_call_is_not_capped_at_legacy_candidate_limit(self):
        import string
        def ename(i: int) -> str:
            chars = ""
            while True:
                chars = string.ascii_lowercase[i % 26] + chars
                i = i // 26 - 1
                if i < 0:
                    break
            return "_p" + chars + "_"
        count = 120
        params = " ".join(ename(i) for i in range(count))
        args = ",".join(f"{i}$" for i in range(count))
        src = f"~zz{params}{{rv{ename(count - 1)}}} co[zz[{args}]]"
        p = frontend(src)
        self.assertEqual(len(p.statements[0].params), count)
        self.assertEqual(self.run_native_bytes(src), b"119\n")

    def test_structured_errors_rethrow_and_finally_supersession(self):
        out = self.run_native_bytes("tr{tr{er'x'}cae{er}fn{co'i'}}cae{coe}fn{co'o'}")
        self.assertIn(b"payload='x'", out)
        self.assertTrue(out.startswith(b"i\nER("))
        self.assertTrue(out.endswith(b"\no\n"))

    def test_finally_error_supersedes_with_cause(self):
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td) / ("probe.exe" if sys.platform == "win32" else "probe")
            build("tr{er'x'}fn{er'y'}", exe)
            cp = subprocess.run([str(exe)], capture_output=True, check=False)
            self.assertNotEqual(cp.returncode, 0)
            self.assertIn(b"payload='y'", cp.stderr)
            self.assertIn(b"cause=ER(", cp.stderr)
            self.assertIn(b"payload='x'", cp.stderr)

    def test_finalizer_error_is_isolated_from_user_catch(self):
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td) / ("probe.exe" if sys.platform == "win32" else "probe")
            build("#AB{~-{er'boom'}}tr{a:=AB[] a=nn co'inside'}cae{co'caught'} co'after'", exe)
            import os
            env = os.environ.copy()
            env["SLUG_GC_INTERVAL"] = "1"
            cp = subprocess.run([str(exe)], capture_output=True, check=False, env=env)
            self.assertNotEqual(cp.returncode, 0)
            self.assertNotIn(b"caught", cp.stdout)
            self.assertIn(b"uncaught finalizer error", cp.stderr)

    def test_legacy_capability_name_is_not_a_root_builtin(self):
        with self.assertRaises(Exception):
            frontend("a:=fr['x']")


    def test_standard_module_aliases_reach_capabilities(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "main.slg"
            src.write_text(">'@std/fs':FS co[FS.fe['/definitely/not/a/slug/path']]", encoding="utf-8")
            p = frontend_file(src)
            self.assertTrue(p.statements)
            exe = root / ("probe.exe" if sys.platform == "win32" else "probe")
            build_file(src, exe)
            cp = subprocess.run([str(exe)], capture_output=True, check=True)
            self.assertEqual(self.logical_stdout(cp.stdout), b"false\n")

    def test_system_capability_query_uses_canonical_operation_ids(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "main.slg"
            src.write_text(
                ">'@std/sys':SY co[SY.cp['@std/fs.fr']] co[SY.cp['@std/nope.zz']]",
                encoding="utf-8",
            )
            exe = root / ("probe.exe" if sys.platform == "win32" else "probe")
            build_file(src, exe)
            cp = subprocess.run([str(exe)], capture_output=True, check=True)
            self.assertEqual(self.logical_stdout(cp.stdout), b"true\nfalse\n")

    def test_surface_rectangle_extreme_coordinates_do_not_overflow_backend(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "main.slg"
            src.write_text(
                ">'@std/gfx':GX a:=GX.sf[2,2] "
                "GX.rf[a,9223372036854775807$,0,2,2,1] "
                "GX.rf[a,9223372036854775808$-,0,2,2,1] "
                "co[ln[GX.sb[a]]]",
                encoding="utf-8",
            )
            exe = root / ("probe.exe" if sys.platform == "win32" else "probe")
            build_file(src, exe)
            cp = subprocess.run([str(exe)], capture_output=True, check=True)
            self.assertEqual(self.logical_stdout(cp.stdout), b"16\n")

    def test_standard_fs_binary_write_preserves_embedded_nul(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "payload.bin"
            path = str(target).replace("\\", "\\\\").replace("'", "\\'").replace("{", "\\{").replace("}", "\\}")
            src = root / "main.slg"
            src.write_text(f">'@std/fs':FS co[FS.fw['{path}',by['a\\0b']]]", encoding="utf-8")
            exe = root / ("probe.exe" if sys.platform == "win32" else "probe")
            build_file(src, exe)
            cp = subprocess.run([str(exe)], capture_output=True, check=True)
            self.assertEqual(self.logical_stdout(cp.stdout), b"3\n")
            self.assertEqual(target.read_bytes(), b"a\x00b")

    def test_host_text_boundary_rejects_embedded_nul(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "main.slg"
            src.write_text(">'@std/fs':FS co[FS.fe['a\\0b']]", encoding="utf-8")
            exe = root / ("probe.exe" if sys.platform == "win32" else "probe")
            build_file(src, exe)
            cp = subprocess.run([str(exe)], capture_output=True, check=False)
            self.assertNotEqual(cp.returncode, 0)
            self.assertIn(b"embedded NUL", cp.stderr)
            self.assertIn(b"kind='encoding'", cp.stderr)


    def test_decimal_boundary_marker_handles_full_u64_without_prefix_explosion(self):
        self.assertEqual(self.run_native_bytes("co[18446744073709551615$]"), b"18446744073709551615\n")
        with self.assertRaises(Exception):
            frontend("a:=18446744073709551616$")

    def test_mixed_integer_float_comparison_is_exact_past_f64_integer_precision(self):
        out = self.run_native_bytes("co[?9007199254740993$==9007199254740992.] co[?9007199254740993$>9007199254740992.]")
        self.assertEqual(out, b"false\ntrue\n")

    def test_signed_remainder_uses_truncation_toward_zero(self):
        out = self.run_native_bytes("co[7$- 3$ %] co[7$ 3$- %] co[7$- 3$- %]")
        self.assertEqual(out, b"-1\n1\n-1\n")

    def test_negative_step_slices_follow_python_style_normalization(self):
        out = self.run_native_bytes("a:=[0$,1$,2$,3$,4$] co[a[::1$-]] co[a[4$:0$:2$-]]")
        self.assertEqual(out, b"[4,3,2,1,0]\n[4,2]\n")


    def test_constant_return_user_call_is_not_elided_when_effectful(self):
        src = "a:=0;~zz{a=1;rv1};x:=zz[];co[a];co[x]"
        self.assertEqual(self.run_native_bytes(src), b"1\n1\n")

    def test_short_circuit_preserves_effectful_constant_return_call(self):
        # Empty input makes b false, so && must suppress zz. Non-empty input makes
        # b true, so zz must execute even though its return value is statically 1.
        src = "a:=0;~zz{a=1;rv1};b:=ci;x:=?b+zz[];co[a];co[x]"
        self.assertEqual(self.run_native_bytes(src, b"\n"), b"0\nfalse\n")
        self.assertEqual(self.run_native_bytes(src, b"x\n"), b"1\ntrue\n")

    def test_numeric_range_continue_still_advances_iterator(self):
        # A source-level `continue` must execute the range increment exactly once.
        # This specifically guards against lowering the increment after the body,
        # where C `continue` would skip it and hang forever at the continued value.
        out = self.run_native_bytes("s:=0 fli0$5{?i==2{cl}s=si+} co[s]")
        self.assertEqual(out, b"8\n")

    def test_foreach_uses_snapshot_when_source_map_mutates(self):
        out = self.run_native_bytes("m:=['a':1,'b':2] s:='' flkm{s=sk+ m['c']:=3} co[s] co[ln[m]]")
        self.assertEqual(out, b"ab\n3\n")

    def test_cyclic_collection_display_and_equality_terminate(self):
        out = self.run_native_bytes("a:=[nn] b:=[nn] a[0]=a b[0]=b co[a] co[?a==b]")
        self.assertEqual(out, b"[<cycle>]\ntrue\n")

    def test_unicode_index_and_slice_are_codepoint_based(self):
        out = self.run_native_bytes("s:='🐌é𐍈a' co[ln[s]] co[s[0]] co[s[2]] co[s[1:3]] co[s[::1$-]]")
        self.assertEqual(out, "4\n🐌\n𐍈\né𐍈\na𐍈é🐌\n".encode("utf-8"))

    def test_numeric_ranges_cover_signed_and_full_u64_boundaries(self):
        out = self.run_native_bytes(
            "fli2$-2{co[i]} "
            "fli18446744073709551613$18446744073709551615${co[i]}"
        )
        self.assertEqual(
            out,
            b"-2\n-1\n0\n1\n18446744073709551613\n18446744073709551614\n",
        )



    def test_hard_null_literal_wins_inside_return_sequence(self):
        src = "~zz {rv nn;} a:=zz[] co[ty[a]]"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "hard_null_return.slg"
            path.write_text(src, encoding="utf-8")
            exe = Path(td) / ("hard_null_return.exe" if sys.platform == "win32" else "hard_null_return")
            build_file(path, exe)
            p = subprocess.run([str(exe)], capture_output=True, text=True, encoding="utf-8", check=True)
            self.assertEqual(p.stdout, "null\n")

if __name__ == "__main__":
    unittest.main()
