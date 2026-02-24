"""
Refactor Python files: Move all imports to file header

Rules:
1. Module docstring stays at top
2. All imports immediately after docstring
3. Then blank line
4. Then constants (UPPERCASE)
5. Then classes/functions

This ensures clean import organization across the codebase.
"""


from pathlib import Path
from typing import List, Tuple
import os
import re


def extract_sections(content: str) -> Tuple[str, List[str], str]:
    """
    Extract docstring, imports, and rest of file

    Returns:
        (docstring, import_lines, rest_of_code)
    """
    lines = content.split('\n')

    # Extract docstring (if present)
    docstring = ""
    start_idx = 0

    if lines and lines[0].strip().startswith('"""'):
        # Multi-line docstring
        if lines[0].strip().endswith('"""') and len(lines[0].strip()) > 6:
            # Single-line docstring: """text"""
            docstring = lines[0] + '\n'
            start_idx = 1
        else:
            # Multi-line docstring
            end_idx = None
            for i in range(1, len(lines)):
                if '"""' in lines[i]:
                    end_idx = i
                    break
            if end_idx:
                docstring = '\n'.join(lines[0:end_idx+1]) + '\n'
                start_idx = end_idx + 1
    elif lines and lines[0].strip().startswith("'''"):
        # Alternative docstring style
        if lines[0].strip().endswith("'''") and len(lines[0].strip()) > 6:
            docstring = lines[0] + '\n'
            start_idx = 1
        else:
            end_idx = None
            for i in range(1, len(lines)):
                if "'''" in lines[i]:
                    end_idx = i
                    break
            if end_idx:
                docstring = '\n'.join(lines[0:end_idx+1]) + '\n'
                start_idx = end_idx + 1
    elif lines and lines[0].strip().startswith('#'):
        # Shebang or file-level comment
        if lines[0].startswith('#!') or lines[0].startswith('# -*-'):
            docstring = lines[0] + '\n'
            start_idx = 1

    # Extract imports and rest
    import_lines = []
    rest_lines = []
    in_imports = False
    imports_done = False

    for i in range(start_idx, len(lines)):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines at the beginning
        if not stripped and not in_imports and not imports_done:
            continue

        # Check if this is an import line
        is_import = (
            stripped.startswith('import ') or
            stripped.startswith('from ') or
            (in_imports and stripped and not stripped[0].isalpha() and not stripped.startswith('#'))
        )

        if is_import and not imports_done:
            import_lines.append(line)
            in_imports = True
        elif stripped and in_imports and not is_import:
            # End of imports section
            imports_done = True
            rest_lines.append(line)
        elif imports_done or (stripped and not is_import):
            rest_lines.append(line)
        else:
            rest_lines.append(line)

    # Remove leading empty lines from rest
    while rest_lines and not rest_lines[0].strip():
        rest_lines.pop(0)

    rest_code = '\n'.join(rest_lines)

    return docstring, import_lines, rest_code


def organize_imports(import_lines: List[str]) -> str:
    """
    Organize imports:
    1. Standard library
    2. Third-party
    3. Local imports

    Each group sorted alphabetically.
    """
    stdlib = []
    thirdparty = []
    local = []

    # Known stdlib modules (partial list, extend as needed)
    stdlib_modules = {
        'asyncio', 'os', 'sys', 'json', 'time', 'datetime', 'typing', 'pathlib',
        'dataclasses', 'enum', 'abc', 'collections', 'functools', 'itertools',
        'random', 'math', 're', 'subprocess', 'threading', 'multiprocessing',
        'unittest', 'logging', 'warnings', 'traceback', 'inspect', 'copy',
        'tempfile', 'shutil', 'io', 'csv', 'hashlib', 'uuid', 'decimal',
        'contextlib', 'weakref', 'gc', 'signal', 'atexit'
    }

    for line in import_lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Determine module
        if stripped.startswith('from '):
            module = stripped.split()[1].split('.')[0]
        elif stripped.startswith('import '):
            module = stripped.split()[1].split('.')[0].split(' as ')[0]
        else:
            continue

        # Classify
        if module in stdlib_modules:
            stdlib.append(line)
        elif module in ['domain', 'application', 'infrastructure', 'foundation', 'api']:
            local.append(line)
        else:
            thirdparty.append(line)

    # Sort each group
    stdlib.sort(key=lambda x: x.strip())
    thirdparty.sort(key=lambda x: x.strip())
    local.sort(key=lambda x: x.strip())

    # Combine with blank lines between groups
    result = []
    if stdlib:
        result.extend(stdlib)
    if thirdparty:
        if result:
            result.append('')
        result.extend(thirdparty)
    if local:
        if result:
            result.append('')
        result.extend(local)

    return '\n'.join(result)


def refactor_file(filepath: Path) -> bool:
    """
    Refactor a single file

    Returns True if file was modified
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            original_content = f.read()

        # Skip empty files
        if not original_content.strip():
            return False

        # Extract sections
        docstring, import_lines, rest_code = extract_sections(original_content)

        # Organize imports
        organized_imports = organize_imports(import_lines)

        # Rebuild file
        new_content_parts = []

        if docstring:
            new_content_parts.append(docstring)

        if organized_imports:
            if docstring:
                new_content_parts.append('')  # Blank line after docstring
            new_content_parts.append(organized_imports)
            new_content_parts.append('')  # Blank line after imports
            new_content_parts.append('')  # Extra blank line before code

        if rest_code:
            new_content_parts.append(rest_code)

        new_content = '\n'.join(new_content_parts)

        # Only write if changed
        if new_content != original_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return True

        return False

    except Exception as e:
        print(f"❌ Error processing {filepath}: {e}")
        return False


def main():
    """Refactor all Python files in the project"""
    root = Path('/mnt/volume-SQ/dev/BrokerageService')

    # Find all Python files
    python_files = list(root.rglob('*.py'))
    python_files = [f for f in python_files if '__pycache__' not in str(f)]

    print(f"Found {len(python_files)} Python files to process\n")

    modified_count = 0
    skipped_count = 0

    for filepath in sorted(python_files):
        rel_path = filepath.relative_to(root)

        if refactor_file(filepath):
            print(f"✅ Modified: {rel_path}")
            modified_count += 1
        else:
            skipped_count += 1

    print(f"\n{'='*60}")
    print(f"Refactoring complete:")
    print(f"  Modified: {modified_count}")
    print(f"  Skipped:  {skipped_count}")
    print(f"  Total:    {len(python_files)}")
    print(f"{'='*60}\n")

    return 0 if modified_count == 0 else 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
