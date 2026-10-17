# Mac Tests

Snapshot of the macOS workspace's test sources and fixtures. The repository's
original `tests/` directory is preserved unchanged. Generated executables,
build caches and test output files are not included in this snapshot.

Example from the repository root:

```sh
mkdir -p build
./executables/macos/silverc --os macx64 "Mac Tests/hello.sr" -o build/mac-hello
chmod +x build/mac-hello
arch -x86_64 ./build/mac-hello
```

Previous stage-1 compiler fixture sweep: 112/124 passed, including guard
accept/reject fixtures and the intentional exit code 42 of `exit_program.sr`.
The remaining 12 fixtures had runtime failures. This is not an all-passing
suite. Stage 2 cannot rebuild the compiler project; no valid stage 3 exists.
