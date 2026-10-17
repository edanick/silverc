# macOS executable

`silverc` is the x86_64 macOS stage-1 compiler built by the Rust compiler.
Apple silicon requires Rosetta 2. From the repository root:

```sh
./executables/macos/silverc --version
```

112/124 compiler fixtures passed. Stage 2 builds but throws `Unhandled
exception` when rebuilding the compiler project, including on a fresh retry.
No valid stage 3 exists. Broken later-stage outputs are not included.
See [`Mac Tests`](../../Mac%20Tests/) for fixtures and verification notes.
This executable is not notarized.
