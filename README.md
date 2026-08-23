# Silver Compiler

A modern, expressive systems language for turning limitless imagination into
powerful creations, tools, command-line applications, and experiences.

Silver brings familiar C-style structure together with concise syntax,
strong types, native compilation, and a growing standard library, giving you
one language for many possibilities.

## Credits

- **Author:** Edan M.
- **Version:** 0.4.0
- **Copyright:** © 2025 Edan M.

## Quick start

### Build a Silver program

Run these commands from the workspace root. Place the compiler on your `PATH` under the command name `silverc`, then compile a program:

```bash
# Example after installing/renaming the compiler to `silverc`
silverc path/to/program.sr -o program.exe
```

Silver source files use the `.sr` extension. Programs begin at `void main()`:

```silver
void main() {
    string message = "Hello from Silver";
    printline(message);
}
```

### Run Silver code directly

For immediate execution without a native compilation step, use the Silver
interpreter in `silveri/`:

```bash
silveri path/to/program.sr
```

## Language highlights

- Native compilation for fast, standalone applications
- Clear, type-first declarations with optional inference through `var`
- Mutable and immutable variables using explicit `mut`
- Dynamic arrays with expressive collection operations
- Classes, constructors, properties, inheritance, and foundations
- Nullable types with `?` and union types with `<type1 | type2>`
- Pattern matching, ternary expressions, loops, and recursion
- String interpolation with `$"..."`
- Modules and imports with a simple `import` syntax
- Standard-library support for filesystem, networking, JSON, system, and other APIs
- A cross-platform design direction for compilers, interpreters, and native tooling

## A small example

```silver
class Greeter {
    public prop string name;

    construct (string name) {
        this.name = name;
    }

    public string greet() {
        return $"Hello, {this.name}!";
    }
}

void main() {
    Greeter greeter = new Greeter("Silver");
    printline(greeter.greet());
}
```

## Project layout

| Directory | Purpose |
| --- | --- |
| `silverc/` | The Silver compiler project and standard library |
| `silveri/` | Silver interpreter for direct execution |
| `DOCS/` | Language feature documentation and examples |
| `silver-vscode-extension/` | VS Code language support |

## License

Edan M. © 2025 All Rights Reserved Proprietary
