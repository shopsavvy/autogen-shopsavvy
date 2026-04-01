#!/bin/bash
set -e

echo "=== autogen-shopsavvy tests ==="

echo "Checking project structure..."
test -f src/autogen_shopsavvy/__init__.py && echo "  src/autogen_shopsavvy/__init__.py exists"
test -f src/autogen_shopsavvy/tools.py && echo "  src/autogen_shopsavvy/tools.py exists"
test -f pyproject.toml && echo "  pyproject.toml exists"
test -f README.md && echo "  README.md exists"
test -f LICENSE && echo "  LICENSE exists"

echo "Checking Python syntax validity..."
python3 -c "import ast; ast.parse(open('src/autogen_shopsavvy/tools.py').read())" && echo "  tools.py syntax is valid"
python3 -c "import ast; ast.parse(open('src/autogen_shopsavvy/__init__.py').read())" && echo "  __init__.py syntax is valid"

echo "Checking pyproject.toml..."
python3 -c "
import configparser
try:
    import tomllib
except ImportError:
    import tomli as tomllib
with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
assert 'project' in data
assert data['project']['name'] == 'autogen-shopsavvy'
print('  pyproject.toml is valid')
"

echo ""
echo "All checks passed!"
