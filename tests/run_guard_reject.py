#!/usr/bin/env python3
"""Run the self-host rejection corpus: every fixture the compiler must REFUSE.

`tests/guard_reject/` holds the shapes the self-hosted compiler must not
compile (RC-5 in MEMORY_ISSUES_FIXES_REGRESSION.md: the corpus existed but
no runner executed it). This runner closes that gap for `silverc`.

A REJECTION fixture (`reject_*`) passes when the compiler refuses it: a
non-zero exit AND a diagnostic on stdout/stderr AND the diagnostic names
the fragment the fixture declares. "It did not compile" is not the same
claim as "the Guard refused this shape for this reason": a fixture broken
by a typo (a missing semicolon, say) must not pass as a rejection. The
declared fragment may use either corpus spelling:

    // expect-diagnostic: <fragment>      (the newer silverc-rs convention)
    // Expect: <fragment>                 (the older prose convention)
    // Expected pre-emit diagnostic: <fragment>.

A CONTROL fixture (`safe_*`, `accept_*`) passes when it still compiles --
and, when it declares a `void main()`, when its binary runs and exits 0.
Without a control the suite cannot tell "the Guard refuses this shape"
from "the compiler refuses everything", so a suite with no control is a
failure.

The declared fragment must appear in the compiler's output. The compiler
lays a guard diagnostic out as `GuardError: <Kind> at line L, column C:
<name>: <message>`, while the prose declarations write `<Kind>: <message>`
-- so the fragment is split on `:` and every part must appear (compared
case-insensitively, ignoring quote characters): the kind pins WHICH rule
refused the program, the message pins what it said.

Usage:
    python tests/run_guard_reject.py [compiler]

    compiler: path to the self-hosted compiler (default: the freshest
              HOST-RUNNABLE build among `silverc` / `silverc.exe` in the
              project root -- the file's magic bytes decide what this
              host can run, ELF on Linux, PE on Windows; a newer mtime
              never makes a foreign-target binary runnable, so it only
              breaks ties between host-runnable candidates)

Portability: relative paths only (everything resolves from this file's
position), no OS-specific code. Linux checkouts on filesystems that
cannot exec in place (vfat + showexec) stage the compiler and every
compiled control binary into a native temp dir and `chmod +x` them there,
exactly like silverc-rs/tests/run_suite.py does. A binary can also be
invoked through the loader (`/lib64/ld-linux-x86-64.so.2 <bin> <args>`);
the runner execs the staged copy directly, which is equivalent.

Wired into the self-host entry point: `tests/run_selfhost.py` (tracked)
invokes this runner after its suites, so a normal test run executes the
corpus. `build/run_selfhost.py` is a gitignored local shim that delegates
to the tracked runner.
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUITE_DIR = ROOT / "tests" / "guard_reject"
IS_WINDOWS = sys.platform == "win32"
COMPILE_TIMEOUT = 120
RUN_TIMEOUT = 60

# A fixture with one of these stems is a control: a shape the language
# still accepts, so the suite proves a rule that rejects everything
# cannot pass.
CONTROL_PREFIXES = ("safe_", "accept_")

# The directive a rejection fixture uses to declare its diagnostic; both
# corpus spellings are accepted (see the module docstring). The corpus
# convention is the LAST line, so adding one never moves the line numbers
# the diagnostic reports.
DIRECTIVE_RE = re.compile(
    r"(?i)^expect(?:ed)?(?:\s+pre-emit)?(?:[-\s]+diagnostic)?\s*:\s*(.+)$"
)

STAGE_ROOT = Path(tempfile.gettempdir()) / "silverc-guard-reject"
RUN_TAG = "run-" + str(time.time_ns())
CREATED_DIRS = []
STALE_RUN_SECONDS = 3600


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

    A checkout may hold both `silverc` and `silverc.exe`, built for
    different targets. Only a binary whose magic matches this host (ELF
    on Linux, PE on Windows) can run, so foreign-target candidates are
    excluded no matter how new their mtime is -- a freshly rebuilt
    Windows PE must never shadow the runnable Linux ELF. Among
    host-runnable candidates the newer file wins; ties prefer the
    host's own spelling (extensionless on Linux, `.exe` on Windows).
    """
    candidates = [ROOT / name for name in ("silverc", "silverc.exe")]
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


def stage(path: Path, suite_name: str) -> Path:
    """Return a runnable copy of `path` (vfat checkouts cannot exec in place)."""
    if os.access(path, os.X_OK) and path.parent != STAGE_ROOT:
        return path
    staged = STAGE_ROOT / suite_name / RUN_TAG / path.name
    staged.parent.mkdir(parents=True, exist_ok=True)
    if staged.parent not in CREATED_DIRS:
        CREATED_DIRS.append(staged.parent)
    shutil.copyfile(path, staged)
    staged.chmod(staged.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return staged


def prune_stale_runs() -> None:
    """Delete scratch directories this run's predecessors left behind."""
    now = time.time()
    if not STAGE_ROOT.is_dir():
        return
    for child in STAGE_ROOT.iterdir():
        if child.name.startswith("run-") and now - child.stat().st_mtime > STALE_RUN_SECONDS:
            shutil.rmtree(child, ignore_errors=True)


def cleanup_run() -> None:
    for d in dict.fromkeys(CREATED_DIRS):
        shutil.rmtree(d, ignore_errors=True)
    CREATED_DIRS.clear()


def has_main(source: str) -> bool:
    return "void main(" in source


def normalize(text: str) -> str:
    """Case-fold, drop quote characters, collapse whitespace."""
    lowered = text.casefold().replace("'", "").replace('"', "").replace("`", "")
    return " ".join(lowered.split())


def expected_diagnostic(source: str):
    """The diagnostic fragment a rejection fixture declares, or None."""
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped.startswith("//"):
            continue
        m = DIRECTIVE_RE.match(stripped[2:].strip())
        if m:
            return m.group(1).strip().rstrip(".")
    return None


def diagnostic_declared_in(fragment: str, output: str) -> bool:
    """Every `:`-separated part of the fragment must appear in the output.

    The compiler interleaves the position between kind and message
    (`Kind at line L, column C: name: message`), so a fragment declared
    as `Kind: message` is matched part-wise; quotes and letter case drift
    between the corpus prose and the compiler's phrasing.
    """
    parts = [normalize(p) for p in fragment.split(":")]
    parts = [p for p in parts if p]
    if not parts:
        return False
    haystack = normalize(output)
    return all(p in haystack for p in parts)


def first_diagnostic_line(output: str) -> str:
    """The first diagnostic line of the compiler's output (for a failure message)."""
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("[") or stripped.lower().startswith(
            ("silver compiler", "copyright")
        ):
            continue
        return stripped
    return "(no diagnostic)"


def run(cmd, timeout):
    try:
        p = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        return True, p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired as e:
        return False, "TIMEOUT", (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), (e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
    except OSError as e:
        return False, "OSERROR", str(e), ""


def main() -> int:
    if not COMPILER.exists():
        print(f"compiler not found: {COMPILER}")
        return 1
    compiler = stage(COMPILER, "compiler")
    if not SUITE_DIR.is_dir():
        print(f"=== suite guard_reject: directory not found: {SUITE_DIR} ===")
        return 1

    print(f"Compiler: {COMPILER}")
    prune_stale_runs()
    # rglob, not glob: a fixture in a subdirectory must not be silently
    # unrun (an unrun fixture is a comment, not a test).
    fixtures = sorted(SUITE_DIR.rglob("*.sr"))
    out_dir = STAGE_ROOT / "out" / RUN_TAG
    out_dir.mkdir(parents=True, exist_ok=True)
    CREATED_DIRS.append(out_dir)

    passed = 0
    failed = 0
    failures = []
    if not any(f.name.startswith(CONTROL_PREFIXES) for f in fixtures):
        failed += 1
        failures.append(
            "guard_reject has no control fixture (a `safe_*`/`accept_*` "
            "file that must still compile)"
        )

    for fixture in fixtures:
        source = fixture.read_text(encoding="utf-8", errors="replace")
        out = out_dir / (fixture.stem + (".exe" if IS_WINDOWS else ""))
        if out.exists():
            out.unlink()
        ok, code, stdout, stderr = run(
            [str(compiler), str(fixture), "-o", str(out)], COMPILE_TIMEOUT
        )
        output = stdout + stderr
        compiled = ok and code == 0

        if fixture.name.startswith(CONTROL_PREFIXES):
            if not compiled:
                failed += 1
                failures.append(
                    f"{fixture.name} (control rejected: it must compile -- "
                    f"{first_diagnostic_line(output)})"
                )
                print(f"FAIL {fixture.name} (control rejected)")
                continue
            if has_main(source):
                try:
                    runnable = stage(out, "controls")
                except OSError as e:
                    failed += 1
                    failures.append(f"{fixture.name} (control could not be staged: {e})")
                    print(f"FAIL {fixture.name} (stage)")
                    continue
                ok, code, stdout, stderr = run([str(runnable)], RUN_TIMEOUT)
                if not ok or code != 0:
                    failed += 1
                    failures.append(
                        f"{fixture.name} (control exited {code}: "
                        f"{(stderr or stdout).strip().splitlines()[-1] if (stderr or stdout).strip() else ''})"
                    )
                    print(f"FAIL {fixture.name} (control exited {code})")
                    continue
                print(f"PASS {fixture.name} (control compiled and ran)")
            else:
                print(f"PASS {fixture.name} (control compiled)")
            passed += 1
            continue

        # A rejection fixture: the compiler must refuse it, naming why.
        if not ok:
            failed += 1
            failures.append(f"{fixture.name} (compile {code})")
            print(f"FAIL {fixture.name} (compile {code})")
            continue
        if compiled:
            failed += 1
            failures.append(
                f"{fixture.name} (COMPILED: this shape must be refused)"
            )
            print(f"FAIL {fixture.name} (compiled: this shape must be refused)")
            continue
        if not output.strip():
            failed += 1
            failures.append(f"{fixture.name} (refused with exit {code} but no diagnostic)")
            print(f"FAIL {fixture.name} (no diagnostic)")
            continue
        expected = expected_diagnostic(source)
        if not expected:
            failed += 1
            failures.append(
                f"{fixture.name} (no expected diagnostic declared: add a "
                f"// expect-diagnostic: <fragment> line -- the compiler said: "
                f"{first_diagnostic_line(output)})"
            )
            print(f"FAIL {fixture.name} (no declared diagnostic)")
            continue
        if not diagnostic_declared_in(expected, output):
            failed += 1
            failures.append(
                f"{fixture.name} (wrong diagnostic: expected '{expected}', "
                f"got '{first_diagnostic_line(output)}')"
            )
            print(f"FAIL {fixture.name} (wrong diagnostic)")
            continue
        print(f"PASS {fixture.name} (refused: {first_diagnostic_line(output)})")
        passed += 1

    cleanup_run()
    print()
    print(f"=== suite guard_reject ({SUITE_DIR}) ===")
    print(f"{passed}/{passed + failed} passed, {failed} failed")
    for f in failures:
        print(f"  FAILED: {f}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
