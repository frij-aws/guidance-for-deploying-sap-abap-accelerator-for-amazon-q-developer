"""
Root conftest.py — adds src/ and src/aws_abap_accelerator/ to sys.path so that:
  - `import aws_abap_accelerator` works (package imports in tests)
  - `from utils.security import ...` works (non-package imports inside src/)
"""
import sys
import os

# Add src/ so that `import aws_abap_accelerator` works
_src = os.path.join(os.path.dirname(__file__), "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

# Add src/aws_abap_accelerator/ so that `from utils.security import ...` works
_pkg = os.path.join(_src, "aws_abap_accelerator")
if _pkg not in sys.path:
    sys.path.insert(0, _pkg)
