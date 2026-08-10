#!/usr/bin/env python3
"""Run the full test suites with a given compiler and write a report.

Usage:
    python build/run_tests.py [compiler] [report.md]

    compiler: path to the compiler executable (default: build/d3.exe)
    report:   where to write the results (default: silverc-debug/test_report.md)

Suites:
    silverc/tests   - the compiler's own regression suite (296 tests)
    tests/               - top-level language tests (79 tests)

A test passes when it compiles to an .exe and that exe exits with code 0.
Tests are compiled and run with their suite directory as the working
directory (some tests read relative files such as simple.sr).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SELF = ROOT / "silverc"
DEBUG = ROOT / "silverc-debug"
COMPILER = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else SELF / "build" / "silverc.exe"
REPORT = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else DEBUG / "test_report.md"

SUITES = [
    ("silverc", SELF / "tests"),
    ("top-level", ROOT / "tests"),
]

# Tests whose compiled exe is *expected* to exit with a non-zero code
# (e.g. exit_test.sr deliberately calls exit(42) to test the builtin).
EXPECTED_RC = {
    "exit_test.sr": 42,
}


def run_suite(name: str, td: Path, outdir: Path):
    tests = sorted(td.glob("*.sr"))
    results = {}
    for t in tests:
        out = outdir / (name + "_" + t.stem + ".exe")
        try:
            p = subprocess.run([str(COMPILER), str(t), "-o", str(out)],
                               capture_output=True, text=True, cwd=str(td), timeout=600)
            ok = out.exists()
        except subprocess.TimeoutExpired:
            results[t.name] = "COMPILE-TIMEOUT"
            continue
        if not ok:
            results[t.name] = "COMPILE-FAIL"
            continue
        try:
            q = subprocess.run([str(out)], capture_output=True, text=True,
                               cwd=str(td), timeout=120)
        except subprocess.TimeoutExpired:
            results[t.name] = "RUN-TIMEOUT"
            continue
        expected = EXPECTED_RC.get(t.name, 0)
        if q.returncode == expected:
            # External integration fixtures may intentionally report that the
            # service is unavailable. Keep the suite green while preserving
            # that distinction in the report.
            if "SKIP:" in (q.stdout + q.stderr):
                results[t.name] = "PASS (SKIP: external integration unavailable)"
            else:
                results[t.name] = "PASS"
        else:
            results[t.name] = f"RUN-FAIL(rc={q.returncode}, expected={expected})"
    return results


def archive_self_hosting_outputs() -> None:
    """Keep generated compiler-test outputs out of the source project."""
    source_dir = SELF / "tests"
    archive_dir = DEBUG / "tests"
    archive_dir.mkdir(parents=True, exist_ok=True)
    for path in source_dir.iterdir():
        if path.is_file() and path.suffix != ".sr":
            destination = archive_dir / path.name
            if destination.exists():
                destination.unlink()
            path.replace(destination)


def main() -> None:
    if not COMPILER.exists():
        sys.exit(f"Compiler not found: {COMPILER}")
    print(f"Compiler: {COMPILER}", flush=True)
    outdir = DEBUG / "build" / "results"
    # Fresh output dir on every run so stale artifacts never accumulate.
    if outdir.exists():
        import shutil
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    lines = [f"# Silver test report",
             "",
             f"- compiler: `{COMPILER.name}`",
             f"- date: {__import__('datetime').datetime.now().isoformat(timespec='minutes')}",
             ""]
    total_pass = total_tests = 0

    for name, td in SUITES:
        if not td.is_dir():
            print(f"SKIP suite {name}: {td} missing", flush=True)
            continue
        print(f"=== suite {name} ({td}) ===", flush=True)
        results = run_suite(name, td, outdir)
        passed = sum(1 for v in results.values() if v == "PASS")
        skipped = {k: v for k, v in results.items() if v.startswith("PASS (SKIP:")}
        failed = {k: v for k, v in results.items() if not (v == "PASS" or v.startswith("PASS (SKIP:"))}
        total_pass += passed
        total_tests += len(results)
        print(f"{passed}/{len(results)} passed, {len(skipped)} skipped, {len(failed)} failed", flush=True)
        lines += [f"## {name}: {passed}/{len(results)} passed, {len(skipped)} skipped", ""]
        for k, v in sorted(skipped.items()):
            lines += [f"- **{k}**: {v}"]
            print(f"  SKIP {k}: external integration unavailable", flush=True)
        for k, v in sorted(failed.items()):
            lines += [f"- **{k}**: {v}"]
        lines += [""]
        for k, v in sorted(failed.items()):
            print(f"  FAIL {k}: {v}", flush=True)

    archive_self_hosting_outputs()

    total_skipped = sum(
        1 for line in lines if line.startswith("- **") and "PASS (SKIP:" in line
    )
    total_failed = total_tests - total_pass - total_skipped
    lines += [
        f"## TOTAL: {total_pass}/{total_tests} passed, {total_skipped} skipped, {total_failed} failed",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {REPORT}")
    print(f"TOTAL: {total_pass}/{total_tests} passed, {total_skipped} skipped, {total_failed} failed")
    if total_failed != 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
