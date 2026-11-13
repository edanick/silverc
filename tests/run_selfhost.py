#!/usr/bin/env python3
"""Run the full self-host suite: tests/*.sr, the embedded-runtime suite,
and the guard_reject rejection corpus.

This is the TRACKED entry point for the self-host test run. It lives in
tests/ -- not build/, which is gitignored -- so a clean checkout can run
the whole suite, including guard_reject, from version-controlled files
alone. `build/run_selfhost.py` is a local shim that delegates here.

Compiles every tests/*.sr with the self-hosted compiler and runs the
ones that declare void main(). Compile outputs go to build/selfhost_suite
on Windows and to a native temp dir on Linux; produced binaries run with
cwd = tests so sibling-file expectations hold. Tests that call exit(N)
on purpose (exit_program.sr) pass on their declared exit code, so any
nonzero-but-orderly termination counts as a pass.

The embedded-runtime suite (tests/runtime/*.sr) is separate: those
fixtures must be compiled with `--runtime`, or they would allocate
through the OS heap (which the OS serializes) instead of the
process-global bump allocator under test, and they must exit 0 -- a
nonzero exit there is the allocator handing one block to two threads
(THREAD_SAFETY.md T3), never an expected outcome of the fixture.

The rejection corpus (tests/guard_reject) runs through its sibling
tracked runner run_guard_reject.py after the suites above: every fixture
there must be REFUSED by the compiler, and the safe_*/accept_* controls
must still compile and run. Its failures count into this run's verdict.

Usage:
    python tests/run_selfhost.py [compiler]

    compiler: path to the self-hosted compiler (default: the freshest
              HOST-RUNNABLE build among `silverc` / `silverc.exe` in the
              project root, chosen by magic bytes -- ELF on Linux, PE on
              Windows; a newer mtime only breaks ties between
              host-runnable candidates)

Portability: relative paths only (everything resolves from this file's
position). Linux checkouts on filesystems that cannot exec in place
(vfat + showexec) stage the compiler and every compiled binary into a
native temp dir and chmod +x them there, exactly like
silverc-rs/tests/run_suite.py does.
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TESTS_DIR = BASE / "tests"
RUNTIME_DIR = TESTS_DIR / "runtime"
IS_WINDOWS = sys.platform == "win32"
COMPILE_TIMEOUT = 300
RUN_TIMEOUT = 60
HAS_MAIN_RE = re.compile(r"\bvoid\s+main\s*\(")


def binary_kind(path: Path):
    """The executable format of `path` from its magic bytes, or None.

    `elf` for a Linux ELF image (\\x7fELF), `pe` for a Windows PE image
    (MZ). The name alone cannot decide: a checkout may hold a PE named
    `silverc.exe` beside an ELF named `silverc`, and only the magic says
    which one this host can execute.
    """
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError:
        return None
    if magic == b"\x7fELF":
        return "elf"
    if magic[:2] == b"MZ":
        return "pe"
    return None


def default_compiler() -> Path:
    """The freshest HOST-RUNNABLE self-host compiler in the project root.

    Only a binary whose magic matches this host (ELF on Linux, PE on
    Windows) can run, so foreign-target candidates are excluded no
    matter how new their mtime is. Among host-runnable candidates the
    newer file wins; ties prefer the host's own spelling.
    """
    candidates = [BASE / name for name in ("silverc", "silverc.exe")]
    wanted = "pe" if IS_WINDOWS else "elf"
    runnable = [p for p in candidates if binary_kind(p) == wanted]
    if not runnable:
        sys.exit(
            f"no host-runnable compiler found among: {candidates}\n"
            f"Build it first with:  silverc-rs --os "
            f"{'windows' if IS_WINDOWS else 'linux'} silverc.srp"
        )
    preferred = candidates[1] if IS_WINDOWS else candidates[0]
    return max(runnable, key=lambda p: (p.stat().st_mtime, p is preferred))


COMPILER = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else default_compiler()
GUARD_REJECT_RUNNER = TESTS_DIR / "run_guard_reject.py"
if IS_WINDOWS:
    OUT_DIR = BASE / "build" / "selfhost_suite"
else:
    OUT_DIR = Path(tempfile.gettempdir()) / "silverc-selfhost-suite"


def stage_compiler(path: Path) -> Path:
    """Return a runnable copy of the compiler (vfat cannot exec in place)."""
    if IS_WINDOWS or os.access(path, os.X_OK):
        return path
    staged = Path(tempfile.gettempdir()) / "silverc-selfhost-compiler"
    shutil.copyfile(path, staged)
    staged.chmod(staged.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return staged


def read_file(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


def run(cmd, timeout, cwd):
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        return True, p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        return False, "TIMEOUT", e.stdout or "", e.stderr or ""
    except OSError as e:
        return False, "OSERROR", str(e), ""


def make_executable(path: Path) -> None:
    if IS_WINDOWS:
        return
    try:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def main() -> int:
    if not COMPILER.exists():
        print(f"compiler not found: {COMPILER}")
        return 1
    if not GUARD_REJECT_RUNNER.exists():
        print(f"guard_reject runner not found: {GUARD_REJECT_RUNNER}")
        return 1
    compiler_staged = stage_compiler(COMPILER)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    src_files = sorted(TESTS_DIR.glob("*.sr"))

    passed = []
    failed = []
    for src in src_files:
        name = src.name
        exe = OUT_DIR / name[:-3]
        ok, code, out, err = run(
            [str(compiler_staged), str(src), "-o", str(exe)], COMPILE_TIMEOUT, BASE
        )
        if not ok or code != 0:
            failed.append((name, "COMPILE", (err or out).strip().splitlines()[-1] if (err or out).strip() else ""))
            print(f"FAIL {name} (compile)")
            continue
        source = read_file(src)
        if not HAS_MAIN_RE.search(source):
            passed.append(name)
            print(f"PASS {name} (compile-only)")
            continue
        make_executable(exe)
        ok, code, out, err = run([str(exe)], RUN_TIMEOUT, TESTS_DIR)
        declared = re.findall(r"\bexit\((\d+)\)", source)
        if ok and code == 0:
            passed.append(name)
            print(f"PASS {name}")
        elif ok and declared and str(code) in declared and "Unhandled exception" not in (err or ""):
            passed.append(name)
            print(f"PASS {name}")
        else:
            failed.append((name, f"RUN({code})", (err or out).strip().splitlines()[-1] if (err or out).strip() else ""))
            print(f"FAIL {name} (run, code={code})")

    runtime_files = sorted(RUNTIME_DIR.glob("*.sr"))
    runtime_passed = []
    runtime_failed = []
    for src in runtime_files:
        name = src.name
        exe = OUT_DIR / ("runtime_" + name[:-3])
        ok, code, out, err = run(
            [str(compiler_staged), str(src), "-o", str(exe), "--runtime"], COMPILE_TIMEOUT, BASE
        )
        if not ok or code != 0:
            runtime_failed.append((name, "COMPILE", (err or out).strip().splitlines()[-1] if (err or out).strip() else ""))
            print(f"FAIL {name} (runtime compile)")
            continue
        make_executable(exe)
        ok, code, out, err = run([str(exe)], RUN_TIMEOUT, TESTS_DIR)
        if ok and code == 0:
            runtime_passed.append(name)
            print(f"PASS {name} (runtime)")
        else:
            runtime_failed.append((name, f"RUN({code})", (err or out).strip().splitlines()[-1] if (err or out).strip() else ""))
            print(f"FAIL {name} (runtime, code={code})")

    print()
    print("=== guard_reject (rejection corpus) ===")
    gr = subprocess.run(
        [sys.executable, str(GUARD_REJECT_RUNNER), str(COMPILER)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    sys.stdout.write(gr.stdout or "")
    guard_reject_failed = gr.returncode != 0
    if guard_reject_failed and gr.stderr:
        sys.stderr.write(gr.stderr)

    print()
    print(f"passed: {len(passed)}/{len(src_files)}")
    if runtime_files:
        print(f"runtime: {len(runtime_passed)}/{len(runtime_files)}")
    if guard_reject_failed:
        print("guard_reject: FAILED (see above)")
    if failed:
        print("failed:")
        for name, kind, msg in failed:
            print(f"  {name}: {kind} {msg}")
    if runtime_failed:
        print("runtime failed:")
        for name, kind, msg in runtime_failed:
            print(f"  {name}: {kind} {msg}")
    return 0 if not failed and not runtime_failed and not guard_reject_failed else 1


if __name__ == "__main__":
    sys.exit(main())
