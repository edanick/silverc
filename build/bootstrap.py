#!/usr/bin/env python3
"""Bootstrap the self-hosted Silver compiler and keep only the final compiler.

Chain (stages):
    0. silverc (Rust)  -- compiles -->  d1.exe
    1. d1              -- compiles -->  d2.exe
    2. d2              -- compiles -->  silverc.exe   <-- final artifact (stage 3)

The final `build/silverc.exe` is a fully self-hosting compiler: compiling the
amalgamated compiler source with it must produce a byte-identical binary.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SELF = ROOT / "silverc"
DRIVER = SELF / "compiler_driver.sr"
STRING = SELF / "std" / "string.sr"
PROJECT = SELF / "std" / "project.sr"
SRC = SELF / "build" / "compiler_driver.amalgamated.sr"
RUST = ROOT / "silverc-rs" / "target" / "release" / "silverc.exe"
OUT = SELF / "build"
FINAL = OUT / "silverc.exe"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def remove_generated(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def strip_once(source: str, marker: str, label: str) -> str:
    count = source.count(marker)
    if count != 1:
        raise RuntimeError(f"expected exactly one {label}, found {count}")
    return source.replace(marker, "", 1)


def make_amalgamation() -> None:
    """Create the deterministic single-file bootstrap input from source modules."""
    string_source = STRING.read_text(encoding="utf-8")
    project_source = PROJECT.read_text(encoding="utf-8")
    driver_source = DRIVER.read_text(encoding="utf-8")

    string_source = strip_once(string_source, "mod export string;", "string module declaration")
    project_source = strip_once(project_source, "mod export project;", "project module declaration")
    project_source = strip_once(project_source, "import * from string;", "project string import")
    driver_source = strip_once(driver_source, "mod export compiler;", "compiler module declaration")
    driver_source = strip_once(driver_source, "import * from string;", "compiler string import")
    driver_source = strip_once(driver_source, "import * from project;", "compiler project import")

    # Built-in fs imports intentionally remain because they select filesystem
    # builtins. Module declarations and source-module imports are removed when
    # the three implementation files become one translation unit.
    SRC.write_text(string_source + "\n" + project_source + "\n" + driver_source, encoding="utf-8")


def build(label: str, compiler: Path, out: Path) -> Path:
    print(f"[bootstrap] {label:<14} <- {compiler.name:<22} compiling amalgamated compiler ...",
          flush=True)
    out.unlink(missing_ok=True)
    p = subprocess.run([str(compiler), str(SRC), "-o", str(out)],
                       capture_output=True, text=True, timeout=18000)
    if p.returncode != 0 or not out.exists():
        print(f"  FAILED rc={p.returncode}")
        print((p.stdout + p.stderr)[-2000:])
        sys.exit(1)
    print(f"  OK  {out.stat().st_size:>8} bytes   sha256={sha256(out)[:16]}")
    return out


def main() -> None:
    if not RUST.exists():
        sys.exit(f"Rust compiler not found: {RUST}\n"
                 f"Build it first with:  cd silverc-rs && cargo build --release")
    OUT.mkdir(parents=True, exist_ok=True)

    d1 = OUT / "d1.exe"
    d2 = OUT / "d2.exe"
    verify = OUT / "verify.exe"
    try:
        make_amalgamation()
        d1 = build("d1", RUST, d1)
        d2 = build("d2", d1, d2)
        final = build("d3", d2, FINAL)
        verify = build("verify", final, verify)
        if sha256(verify) == sha256(final):
            print(f"STABLE: verify == {FINAL.name} ({final.stat().st_size} bytes) "
                  f"- silverc.exe is self-hosting")
        else:
            print("UNSTABLE: verify differs - bootstrap is NOT stable!")
            sys.exit(1)
    finally:
        remove_generated(d1, d2, verify, SRC)

    print(f"Done. Final artifact: {FINAL} ({FINAL.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
