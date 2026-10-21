#!/usr/bin/env python3
"""
Candidly Codebase Bundle Generator
----------------------------------
One-run utility script to package backend and frontend logic files into a single
clean ZIP archive for code review, debugging, and AI analysis.

Usage:
    python create_bundle.py [output_filename.zip]

Default output:
    candidly_codebase_bundle.zip
"""

import sys
import os
import zipfile
from pathlib import Path

# Directories to traverse for logic files
SOURCE_DIRS = [
    "backend/app",
    "frontend/src",
    "tests",
]

# Explicit single files to bundle (configs, entry points, key scripts, docs)
EXPLICIT_FILES = [
    "requirements.txt",
    "frontend/package.json",
    "frontend/vite.config.js",
    "frontend/tailwind.config.js",
    "frontend/index.html",
    "scripts/simulate_agentic_interview.py",
    "ARCHITECTURE_AND_CODEBASE_DOSSIER.md",
    "INTERVIEW_ENGINE_CONTEXT.md",
]

# Extensions allowed when scanning directories
ALLOWED_EXTENSIONS = {
    ".py",
    ".jsx",
    ".js",
    ".tsx",
    ".ts",
    ".css",
    ".html",
    ".json",
    ".md",
}

# Directories and patterns to strictly ignore
IGNORED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".claude",
    "dist",
    "build",
    "coverage",
    ".system_generated",
    "candidly-screenshots",
}

# Explicit file patterns to strictly exclude for security & size
IGNORED_PATTERNS = {
    ".env",
    ".env.local",
    ".env.production",
    ".DS_Store",
}

IGNORED_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".zip",
    ".tar",
    ".gz",
    ".wav",
    ".mp3",
    ".pcm",
    ".ogg",
    ".webm",
    ".mp4",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
}


def should_include(path: Path) -> bool:
    """Return True if path should be included in the bundle."""
    # Check ignored directory parts
    for part in path.parts:
        if part in IGNORED_PARTS:
            return False

    # Check ignored filenames/patterns
    if path.name in IGNORED_PATTERNS or path.name.startswith(".env"):
        return False

    # Check ignored extensions
    if path.suffix.lower() in IGNORED_EXTENSIONS:
        return False

    # Check allowed extensions
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return False

    return True


def create_bundle(output_zip: str = "candidly_codebase_bundle.zip") -> str:
    root_dir = Path(__file__).resolve().parent
    out_path = root_dir / output_zip

    print("=" * 65)
    print("  CANDIDLY CODEBASE BUNDLE GENERATOR")
    print("=" * 65)
    print(f"Root Directory: {root_dir}")
    print(f"Output File:    {out_path.name}")
    print("-" * 65)

    files_to_add = set()

    # 1. Scan source directories
    for s_dir in SOURCE_DIRS:
        dir_path = root_dir / s_dir
        if not dir_path.exists():
            continue
        for f in dir_path.rglob("*"):
            if f.is_file() and should_include(f.relative_to(root_dir)):
                files_to_add.add(f.relative_to(root_dir))

    # 2. Add explicit single files
    for ef in EXPLICIT_FILES:
        f = root_dir / ef
        if f.exists() and f.is_file() and should_include(f.relative_to(root_dir)):
            files_to_add.add(f.relative_to(root_dir))

    # Sort files for deterministic archive creation
    sorted_files = sorted(list(files_to_add))

    # Group counts for logging
    backend_count = sum(1 for f in sorted_files if str(f).startswith("backend"))
    frontend_count = sum(1 for f in sorted_files if str(f).startswith("frontend"))
    tests_count = sum(1 for f in sorted_files if str(f).startswith("tests"))
    other_count = len(sorted_files) - (backend_count + frontend_count + tests_count)

    print(f"Discovered {len(sorted_files)} logic & context files:")
    print(f"  • Backend logic:  {backend_count:3d} files")
    print(f"  • Frontend logic: {frontend_count:3d} files")
    print(f"  • Test suites:    {tests_count:3d} files")
    print(f"  • Configs & docs: {other_count:3d} files")
    print("-" * 65)

    # Write ZIP archive
    with zipfile.ZipFile(out_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel_path in sorted_files:
            abs_path = root_dir / rel_path
            zf.write(abs_path, arcname=str(rel_path))

    compressed_size = out_path.stat().st_size
    print(f"✓ Archive successfully created: {out_path.name}")
    print(f"✓ Total Compressed Size:        {compressed_size / 1024:.1f} KB ({compressed_size / (1024*1024):.2f} MB)")
    print("=" * 65)
    return str(out_path)


if __name__ == "__main__":
    out_filename = sys.argv[1] if len(sys.argv) > 1 else "candidly_codebase_bundle.zip"
    create_bundle(out_filename)
