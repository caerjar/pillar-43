"""Catalog constants — magic numbers extracted from the monolithic catalog.py."""

from __future__ import annotations

# ── Memory & batching ────────────────────────────────────────────────────────
# 16, not 100: embedding runs in the API process now and a 100-text
# batch of 2000-char chunks OOM-kills it mid-request ("Server disconnected"),
# leaving the library un-embedded and semantic search empty. 16 keeps peak
# memory bounded; throughput on a 200-file library is still seconds.
EMBED_BATCH_SIZE = 16  # Qdrant embedding batch
CATALOG_BATCH_SIZE = 500  # SQL commit cadence during scan
CATALOG_TEXT_LIMIT = 200_000  # bytes of extracted text stored in DB

# ── Chunking ─────────────────────────────────────────────────────────────────
# Passages, not whole files. Before chunking, one vector per file was computed
# from its first 2000 chars, so nothing past a document's opening was
# retrievable at all.
#
# 1200 chars ≈ 280-320 tokens of English prose. BAAI/bge-small-en-v1.5
# truncates at 512, and we prepend a heading breadcrumb to the embed text, so
# this leaves headroom rather than silently losing the tail of a passage.
# Overlap keeps a thought that straddles a boundary reachable from both sides.
CHUNK_MAX_CHARS = 1200
CHUNK_OVERLAP_CHARS = 200
CHUNK_MIN_CHARS = 200  # shorter trailing runt merges into its predecessor
# Belt-and-braces: CATALOG_TEXT_LIMIT already caps input at 200k chars, which
# at ~1000 net chars/chunk implies ~200 chunks. This guards a pathological
# file (e.g. one with no whitespace) from producing an unbounded row count.
MAX_CHUNKS_PER_FILE = 250
# NOTE: the chunk→file search fan-out lives in services/vector_store.py, not
# here — that module cannot import from this package without a cycle.
MAX_TEXT_EXTRACT_BYTES = (
    65 * 1024 * 1024
)  # was 50 MB; raised 2026-05-11 per user request

# ── File / dir exclusions for the file scan ──────────────────────────────────
EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".obsidian",
        "node_modules",
    }
)

EXCLUDE_FILES: frozenset[str] = frozenset(
    {
        "pillar43.db",
        "pillar43.db-wal",
        "pillar43.db-shm",
        "pillar43.config.json",
        # Common project root files that are code/build artifacts
        "requirements.txt",
        "requirements-dev.txt",
        "Pipfile",
        "Pipfile.lock",
        "Makefile",
        "makefile",
        "GNUmakefile",
        "Dockerfile",
        ".dockerignore",
        "docker-compose.yml",
        "docker-compose.yaml",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Cargo.lock",
        "go.sum",
        "poetry.lock",
        "Gemfile.lock",
        ".gitignore",
        ".gitattributes",
        ".editorconfig",
        ".eslintrc",
        ".eslintrc.json",
        ".prettierrc",
        ".prettierrc.json",
        "tsconfig.json",
        "jest.config.js",
        "webpack.config.js",
        "vite.config.ts",
        "vite.config.js",
    }
)

# Code/config file extensions skipped wholesale — they never appear in search,
# AI summaries, or Organize/Connections features. .md is always indexed.
CODE_CONFIG_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Python
        ".py",
        ".pyc",
        ".pyo",
        ".pyd",
        ".pyw",
        # JavaScript / TypeScript
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        # Web / styles
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".html",
        ".htm",
        # Data & config
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        # Shell
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ps1",
        ".bat",
        ".cmd",
        # Compiled / binary code
        ".o",
        ".so",
        ".dll",
        ".wasm",
        # Other languages
        ".rb",
        ".go",
        ".rs",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".java",
        ".kt",
        ".swift",
        ".sql",
        ".php",
        ".lua",
        ".r",
        ".rmd",
        # Build artifacts & lock files
        ".lock",
        ".map",
        ".min.js",
        ".min.css",
        # Haskell
        ".hs",
        ".lhs",
        ".cabal",
        # Elixir / Erlang
        ".ex",
        ".exs",
        ".erl",
        ".hrl",
        # Functional / other
        ".clj",
        ".cljs",
        ".cljc",
        ".scala",
        ".sbt",
        ".dart",
        ".ml",
        ".mli",
        ".elm",
        ".nix",
        ".tf",
        ".tfvars",
        ".proto",
        # Misc build / config
        ".gradle",
        ".cmake",
        ".makefile",
        # Frontend frameworks / template engines
        ".vue",
        ".svelte",
        ".astro",
        ".coffee",
        ".pug",
        ".jade",
        ".hbs",
        ".handlebars",
        ".ejs",
        ".erb",
        ".jinja",
        ".j2",
        # C# / .NET
        ".cs",
        ".csx",
        ".vb",
        ".fs",
        ".fsx",
        ".fsi",
        # Other languages
        ".groovy",
        ".pl",
        ".pm",
        ".t",  # Perl
        ".m",
        ".mm",  # MATLAB / Objective-C
        ".nim",
        ".zig",
        ".jl",  # Nim, Zig, Julia
        ".d",  # D language
        ".el",
        ".lisp",
        ".rkt",
        ".scm",
        ".ss",  # Lisp family
        ".pyx",
        ".pxi",
        ".pxd",  # Cython
        # Schema / query / data languages
        ".graphql",
        ".gql",
        ".prisma",
        ".bicep",
        ".hcl",  # IaC
        # Shader / assembly
        ".glsl",
        ".hlsl",
        ".wgsl",
        ".frag",
        ".vert",
        ".comp",
        ".asm",
        ".s",
        # Executables & installers
        ".exe",
        ".app",
        ".pkg",
        ".msi",
        ".deb",
        ".rpm",
        ".apk",
        ".bin",
        ".run",
        ".command",
        ".out",
        ".dmg",
        ".iso",
        ".vbs",
        ".wsf",
        ".reg",
    }
)

# Marker filenames that flag a directory as a code-project root.
# Maps filename → human label used when annotating the README.
CODE_PROJECT_MARKERS: dict[str, str] = {
    "Cargo.toml": "Rust",
    "package.json": "JavaScript/TypeScript",
    "requirements.txt": "Python",
    "setup.py": "Python",
    "pyproject.toml": "Python",
    "go.mod": "Go",
    "Gemfile": "Ruby",
    "pom.xml": "Java",
    "build.gradle": "Java/Kotlin",
    "build.gradle.kts": "Kotlin",
    "stack.yaml": "Haskell",
    "Package.swift": "Swift",
    "CMakeLists.txt": "C/C++",
    "composer.json": "PHP",
    "pubspec.yaml": "Dart/Flutter",
    "mix.exs": "Elixir",
    "rebar.config": "Erlang",
    "project.clj": "Clojure",
    "build.sbt": "Scala",
    "flake.nix": "Nix",
    "default.nix": "Nix",
}

README_NAMES: frozenset[str] = frozenset(
    {
        "readme.md",
        "readme.txt",
        "readme.rst",
        "readme",
    }
)

SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        "target",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "vendor",
        ".cache",
    }
)

# Files that should be treated as 'reference' authorship by default.
REFERENCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".epub",
        ".mp4",
        ".mov",
        ".mp3",
        ".wav",
        ".docx",
        ".doc",
    }
)
