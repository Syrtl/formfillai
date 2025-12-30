#!/usr/bin/env python3
"""Syntax check script for Railway builds.
Fails the build if any Python files have syntax errors.
"""
import sys
import py_compile
from pathlib import Path

def check_file(filepath: Path) -> bool:
    """Check if a Python file compiles without errors."""
    try:
        py_compile.compile(str(filepath), doraise=True)
        print(f"✓ {filepath} - OK")
        return True
    except py_compile.PyCompileError as e:
        print(f"✗ {filepath} - ERROR: {e}", file=sys.stderr)
        return False

def main():
    """Check all Python files in the project."""
    base_dir = Path(__file__).parent
    python_files = [
        base_dir / "main.py",
        base_dir / "db.py",
    ]
    
    all_ok = True
    for filepath in python_files:
        if filepath.exists():
            if not check_file(filepath):
                all_ok = False
        else:
            print(f"⚠ {filepath} - NOT FOUND", file=sys.stderr)
            all_ok = False
    
    if not all_ok:
        print("\n✗ Syntax check FAILED. Fix errors before deploying.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\n✓ All syntax checks passed.")
        sys.exit(0)

if __name__ == "__main__":
    main()

