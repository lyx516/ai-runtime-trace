# pyfinder — Feature Analysis

## 1. Overview

**pyfinder** is a Python command-line tool that recursively searches files in a directory tree for lines matching a given regular expression pattern, and outputs the matching lines with highlighted matches.

It is inspired by tools like `grep -rn` but with native Python regex support and terminal-friendly highlighting.

---

## 2. Core Use Cases

| # | Use Case | Description |
|---|----------|-------------|
| 1 | Basic search | `pyfinder "pattern"` — search all files recursively in current dir |
| 2 | Search in specific directory | `pyfinder "pattern" /path/to/search` |
| 3 | File type filter | `pyfinder "pattern" --include "*.py"` — only search Python files |
| 4 | Exclude pattern | `pyfinder "pattern" --exclude "*.log"` — skip log files |
| 5 | Case-insensitive | `pyfinder "pattern" -i` |
| 6 | Show line numbers | `pyfinder "pattern" -n` |
| 7 | Show only file names | `pyfinder "pattern" -l` |
| 8 | Color output on/off | `pyfinder "pattern" --color=always/never/auto` |
| 9 | Max depth | `pyfinder "pattern" --max-depth 3` |
| 10 | Count matches per file | `pyfinder "pattern" -c` |

---

## 3. Feature Requirements

### 3.1 CLI Interface

- Entry point: `pyfinder` (installed via `pip install` or run as `python -m pyfinder`)
- Positional arguments:
  - `pattern` (required): A valid Python regex pattern
  - `path` (optional, default `"."`): Directory or file to search
- Named options (comprehensive list):

| Flag | Long | Description | Default |
|------|------|-------------|---------|
| `-i` | `--ignore-case` | Case-insensitive matching | False |
| `-n` | `--line-number` | Show line numbers | False |
| `-l` | `--files-with-matches` | Only print file names with matches | False |
| `-c` | `--count` | Print match count per file | False |
| `-v` | `--invert-match` | Select non-matching lines | False |
| `-w` | `--word-regexp` | Match whole words only | False |
| `-r` | `--recursive` | Recursive search (default: True) | True |
| | `--include` | Glob pattern for files to include | None |
| | `--exclude` | Glob pattern for files to exclude | None |
| | `--exclude-dir` | Directory names to exclude | `__pycache__`, `.git`, `.svn` |
| | `--max-depth` | Maximum directory depth | None (unlimited) |
| | `--color` | Color output: `always`, `never`, `auto` | `auto` |
| | `--no-ignore` | Do not respect `.gitignore` | False |
| `-E` | `--extended-regexp` | (Default behavior, flag for compatibility) | True |
| `-h` | `--help` | Show help and exit | |
| | `--version` | Show version and exit | |

### 3.2 Search Engine

- Uses Python's `re` module for regex matching
- Reads files as text (UTF-8, with fallback for encoding errors)
- Recursive directory traversal using `pathlib` or `os.walk`
- Binary file detection: skip files that appear to be binary
- Respect `.gitignore` patterns when searching (optional via `--no-ignore`)

### 3.3 Output Format

Default output format (with color):
```
path/to/file.py:42:def foo(bar):  # ← "bar" highlighted
```

Components:
1. **File path** — relative path from search root
2. **Line number** — if `-n` is specified
3. **Colon separator**
4. **Line content** — with matched portions highlighted in color (default: red/bold)

### 3.4 Highlighting

- Matched portions of the line are highlighted using ANSI escape codes
- Default highlight: bold red (\\033[1;31m) around matches
- Reset: \\033[0m after each match
- When `--color=never`, no ANSI codes emitted
- When `--color=auto` (default), ANSI codes emitted only when stdout is a TTY
- When `--color=always`, ANSI codes always emitted (useful for piping to `less -R`)

### 3.5 Error Handling

| Condition | Behavior |
|-----------|----------|
| Invalid regex | Print error message, exit code 2 |
| Directory not found | Print error message, exit code 2 |
| Permission denied on file | Skip file, print warning to stderr |
| Binary file detected | Skip file, print notice to stderr |
| Encoding error | Try fallback encoding (latin-1), skip if fails |
| No matches found | Exit code 1 (like grep) |
| Matches found | Exit code 0 |

### 3.6 Performance Considerations

- Lazy file reading: read line by line, not whole file at once
- Skip binary files early (check first few bytes)
- Respect `--max-depth` to limit traversal
- Use `pathlib.rglob()` with pattern filters for efficiency

---

## 4. Architecture

```
pyfinder/
├── __init__.py          # Version info
├── __main__.py          # python -m pyfinder support
├── cli.py               # Argument parsing (argparse)
├── core.py              # Search engine logic
├── formatter.py         # Output formatting & highlighting
├── walker.py            # File tree traversal with filters
└── utils.py             # Binary detection, encoding helpers
```

### Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `__init__.py` | Package metadata, `__version__` |
| `__main__.py` | Entry point for `python -m pyfinder` |
| `cli.py` | `argparse` definition, parse args, call core |
| `core.py` | Orchestrate search: walk files → match regex → format output |
| `formatter.py` | Build output strings with ANSI highlighting |
| `walker.py` | Recursive file discovery with include/exclude/depth/ignore filters |
| `utils.py` | Binary detection, safe file reading, encoding fallback |

---

## 5. Dependencies

- **Python 3.8+** (standard library only — no third-party dependencies)
- `argparse` — CLI argument parsing
- `re` — Regular expression matching
- `pathlib` — File system path handling
- `sys`, `os` — I/O and exit codes
- `fnmatch` — Glob pattern matching for include/exclude filters

Zero third-party dependencies keeps installation simple and fast.

---

## 6. Output Examples

### Basic search (color output):
```
$ pyfinder "def foo"
src/main.py:10:  def foo(bar):      # "def foo" in bold red
src/utils.py:3:def foo(x, y):       # "def foo" in bold red
```

### With line numbers:
```
$ pyfinder "TODO" -n
src/app.py:5:  # TODO: implement caching
src/app.py:42: # TODO: add error handling
```

### File names only:
```
$ pyfinder "class " -l
src/models.py
src/views.py
```

### No matches:
```
$ pyfinder "nonexistent_pattern"
$ echo $?
1
```

---

## 7. Exit Codes

| Code | Meaning |
|------|---------|
| 0 | At least one match found |
| 1 | No matches found |
| 2 | Error (invalid regex, missing path, etc.) |

---

## 8. Future Considerations (Out of Scope for v1)

- Multi-threaded/async search for large codebases
- Context lines (`-C`, `-B`, `-A` like grep)
- Binary file content search (hex dump)
- Output to file (`-o`)
- JSON output format
- Watch mode (file system monitoring)
- `.pyfinderrc` configuration file
- PCRE2 support via `regex` library

---

## 9. Test Strategy

| Layer | Scope | Tools |
|-------|-------|-------|
| Unit | Individual modules (formatter, walker, utils) | `pytest` |
| Integration | End-to-end search with temp directories | `pytest` + `tmp_path` |
| CLI | Argument parsing, exit codes | `pytest` + `CliRunner` or `subprocess` |
| Edge cases | Binary files, encoding errors, empty files, symlinks | `pytest` parameterized |

---

## 10. Summary

pyfinder is a focused, zero-dependency Python CLI tool for recursive regex search with colored output. It follows the Unix philosophy of doing one thing well. The implementation should be clean, well-tested, and follow Python best practices with type hints and docstrings throughout.

**Estimated implementation effort:** ~400-600 lines of Python code across 6 modules.
