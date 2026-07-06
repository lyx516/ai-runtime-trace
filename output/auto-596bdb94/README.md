# 🔍 pyfinder

**Recursively search files for regex patterns — with colorful highlighting.**

`pyfinder` is a Python command-line tool that searches files in a directory tree for lines matching a regular expression pattern. It highlights matches in color, supports common `grep`-style flags, and requires **zero third-party dependencies** — just Python 3.8+.

```bash
# Quick example
pyfinder "def class" --include "*.py"
```

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Options Reference](#options-reference)
- [Output Format](#output-format)
- [Exit Codes](#exit-codes)
- [Examples](#examples)
- [How It Works](#how-it-works)
- [FAQ / Troubleshooting](#faq--troubleshooting)
- [Development](#development)
- [License](#license)

---

## Installation

### Via pip (recommended)

```bash
pip install pyfinder
```

### From source

```bash
git clone https://github.com/youruser/pyfinder.git
cd pyfinder
pip install .
```

### Run without installing

```bash
python -m pyfinder "pattern"
```

### Verify installation

```bash
pyfinder --version
```

---

## Quick Start

Search for the word "TODO" in all files under the current directory:

```bash
pyfinder "TODO"
```

Search only `.py` files in a specific directory, with line numbers:

```bash
pyfinder "def " ~/projects/myapp --include "*.py" -n
```

Case-insensitive search for "error" across your project:

```bash
pyfinder "error" -i
```

---

## Usage

```
pyfinder PATTERN [PATH] [OPTIONS]
```

| Argument | Description | Default |
|----------|-------------|---------|
| `PATTERN` | A valid Python regular expression (required) | — |
| `PATH` | File or directory to search | `.` (current directory) |

### Basic syntax

```bash
pyfinder "<regex>" [path] [flags]
```

---

## Options Reference

### General Options

| Short | Long | Description | Default |
|-------|------|-------------|---------|
| `-h` | `--help` | Show help message and exit | — |
| | `--version` | Show version number and exit | — |

### Search Behavior

| Short | Long | Description | Default |
|-------|------|-------------|---------|
| `-i` | `--ignore-case` | Case-insensitive matching | off |
| `-v` | `--invert-match` | Select non-matching lines | off |
| `-w` | `--word-regexp` | Match whole words only (equivalent to `\bpattern\b`) | off |
| `-r` | `--recursive` | Search directories recursively | on |

### Output Control

| Short | Long | Description | Default |
|-------|------|-------------|---------|
| `-n` | `--line-number` | Show line numbers in output | off |
| `-l` | `--files-with-matches` | Print only file names containing matches | off |
| `-c` | `--count` | Print match count per file instead of matching lines | off |
| | `--color` | Color output: `always`, `never`, or `auto` | `auto` |

### File Filtering

| Flag | Description | Default |
|------|-------------|---------|
| `--include <glob>` | Only search files matching this glob pattern (e.g. `"*.py"`) | all files |
| `--exclude <glob>` | Skip files matching this glob pattern (e.g. `"*.log"`) | none |
| `--exclude-dir <name>` | Directory names to skip | `__pycache__`, `.git`, `.svn` |
| `--max-depth <N>` | Maximum recursion depth (`1` = current dir only) | unlimited |
| `--no-ignore` | Do **not** respect `.gitignore` patterns | off (`.gitignore` respected) |

---

## Output Format

### Default output (with color)

```
path/to/file.py:42:def foo(bar):  # ← "foo(bar)" highlighted in bold red
```

Each match on a line is wrapped in ANSI bold-red escape codes when color is enabled.

### With `--line-number` (`-n`)

```
src/app.py:5:  # TODO: implement caching
src/app.py:42: # TODO: add error handling
```

### With `--files-with-matches` (`-l`)

```
src/models.py
src/views.py
```

### With `--count` (`-c`)

```
src/app.py:3
src/utils.py:1
```

### Color modes explained

| Mode | Behavior |
|------|----------|
| `auto` (default) | Highlight only when output goes directly to a terminal (TTY) |
| `always` | Always highlight — useful when piping to `less -R` |
| `never` | No ANSI codes, plain text output |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| **0** | At least one match was found |
| **1** | No matches were found |
| **2** | An error occurred (invalid regex, path not found, etc.) |

This follows the same convention as `grep`, making `pyfinder` suitable for use in scripts and CI pipelines.

---

## Examples

### 1. Basic search

```bash
pyfinder "class "
```

Search all files recursively in the current directory for lines containing `class `.

### 2. Search in a specific directory

```bash
pyfinder "def __init__" ~/projects/myapp
```

### 3. File-type filter

```bash
pyfinder "TODO" --include "*.py" --include "*.md"
```

Only search `.py` and `.md` files. You can repeat `--include` to add multiple patterns.

### 4. Exclude files

```bash
pyfinder "password" --exclude "*.lock" --exclude "*.min.js"
```

### 5. Case-insensitive search

```bash
pyfinder "error" -i
```

Matches `error`, `Error`, `ERROR`, `ErRoR`, etc.

### 6. Invert match (lines that do NOT match)

```bash
pyfinder "^$" -v
```

Show all non-empty lines.

### 7. Whole-word matching

```bash
pyfinder -w "foo"
```

Matches `foo` but not `foobar`.

### 8. Count matches per file

```bash
pyfinder "import" -c
```

### 9. List only file names

```bash
pyfinder "class " -l
```

Useful for getting a quick list of files that contain a pattern.

### 10. Limit recursion depth

```bash
pyfinder "TODO" --max-depth 2
```

Only search the current directory and one level of subdirectories.

### 11. Pipe with color preserved

```bash
pyfinder "error" --color=always | less -R
```

### 12. Use in a script

```bash
if pyfinder "FIXME" --include "*.py"; then
    echo "WARNING: There are FIXMEs in the codebase!"
fi
```

---

## How It Works

### Architecture

`pyfinder` is built from four core modules, using only the Python standard library:

```
pyfinder/
├── __init__.py      # Package metadata & version
├── __main__.py      # Enables `python -m pyfinder`
├── cli.py           # CLI argument parsing (argparse)
├── core.py          # Search orchestrator — ties everything together
├── formatter.py     # Output formatting & ANSI highlighting
├── walker.py        # File tree traversal with filters
└── utils.py         # Binary detection, safe file reading
```

### Search pipeline

1. **Parse arguments** — `cli.py` uses `argparse` to read the pattern, path, and flags.
2. **Traverse files** — `walker.py` recursively walks the directory tree, applying include/exclude globs, `.gitignore` rules, and max-depth limits. Binary files are detected and skipped by inspecting the first few bytes.
3. **Match lines** — `core.py` reads each file line by line (lazy, memory-efficient) and tests each line against the compiled regex.
4. **Format output** — `formatter.py` builds the output string with file path, optional line number, and highlighted matches using ANSI escape codes.
5. **Print results** — Results are printed to stdout; errors and warnings go to stderr.

### Key design decisions

- **Zero dependencies** — Works with any Python 3.8+ installation, no `pip install` of third-party packages needed.
- **Lazy file reading** — Files are read line by line, not loaded entirely into memory. Safe for large files.
- **Encoding fallback** — Files are read as UTF-8 first; if that fails, falls back to `latin-1`.
- **Binary detection** — Files with null bytes or non-text content in the first 8 KB are skipped.

---

## FAQ / Troubleshooting

### Q: How is this different from `grep -rn`?

`pyfinder` uses Python's `re` module for regex (which supports lookaheads, named groups, and other advanced features), provides native color highlighting, respects `.gitignore` by default, and works consistently across all platforms (Windows, macOS, Linux) without needing to install `grep`.

### Q: The output has no color, why?

By default (`--color=auto`), color is only enabled when output goes directly to a terminal. If you're piping to another command or redirecting to a file, use `--color=always`.

### Q: Can I search binary files?

No — `pyfinder` skips files that appear to be binary. This prevents garbled output and performance issues.

### Q: Which Python version is required?

Python 3.8 or later. No third-party packages are needed.

### Q: The regex I used works in grep but not in pyfinder?

`pyfinder` uses Python's `re` module, which has a slightly different syntax than POSIX `grep`. For example, `\d` works in Python but not in basic `grep`. If you need help with Python regex syntax, see the [Python re documentation](https://docs.python.org/3/library/re.html).

### Q: Error: "invalid regex"

Your pattern contains a syntax error. Try quoting it: `pyfinder "pattern with spaces"`. If the pattern itself is valid Python regex, double-check for unescaped special characters.

---

## Development

### Setup

```bash
git clone https://github.com/youruser/pyfinder.git
cd pyfinder
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

### Running tests

```bash
pytest
```

### Project structure

```
pyfinder/
├── src/
│   └── pyfinder/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── core.py
│       ├── formatter.py
│       ├── walker.py
│       └── utils.py
├── tests/
│   ├── test_cli.py
│   ├── test_core.py
│   ├── test_formatter.py
│   ├── test_walker.py
│   └── test_utils.py
├── README.md
└── pyproject.toml
```

### Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing`)
3. Commit your changes (`git commit -am 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing`)
5. Open a Pull Request

Please ensure tests pass and add new tests for any new functionality.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

*pyfinder — search smarter, not harder.*
