"""Isolated suite entry point; never imported by the production CLI."""
import importlib.util
import sys
import os
import stat
from pathlib import Path

source = Path(__file__).resolve().parents[1] / "operating-layer.py"
spec = importlib.util.spec_from_file_location("operating_layer_fixture", source)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
def _ephemeral_approval_store(paths):
    """Whether this is an isolated canonical-suite store with no symlink escape.

    The lexical output root matters. A same-user replacement of the live output directory with a
    symlink into a test-shaped path must never make the default CLI unprotected.
    """
    try:
        lexical_root = Path(
            getattr(paths, "output_root_input", Path(paths.approvals_path).parents[1])
        ).absolute()
        test_parent = Path("/private/tmp").absolute()
        relative = lexical_root.relative_to(test_parent)
        if (
            len(relative.parts) != 2
            or not relative.parts[0].startswith("operating-layer-test-")
            or relative.parts[1] != "out"
        ):
            return False
        if lexical_root.resolve(strict=True) != lexical_root:
            return False
        suite_root = test_parent / relative.parts[0]
        metadata = suite_root.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
            return False
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            return False
        expected = lexical_root / "operator-intelligence" / "approvals.ndjson"
        actual = Path(paths.approvals_path).absolute()
        if actual != expected or actual.resolve(strict=False) != actual:
            return False
        cursor = suite_root
        for part in ("out", "operator-intelligence"):
            cursor = cursor / part
            if cursor.exists() and cursor.is_symlink():
                return False
        return True
    except (AttributeError, IndexError, OSError, RuntimeError, ValueError):
        return False


def approval_store_is_protected(paths):
    return not _ephemeral_approval_store(paths)


# The harness owns its module only. Production has no flag or path exemption.
engine.approval_store_is_protected = approval_store_is_protected
if __name__ == "__main__":
    sys.exit(engine.main())
