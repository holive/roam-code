"""Integration tests for new commands and enhancements.

Covers: understand, dead --summary/--by-kind/--clusters, context (batch),
and the --json envelope.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import roam, git_init, git_commit, index_in_process


# ============================================================================
# Shared fixture: a small Python project with known dependency structure
# ============================================================================

@pytest.fixture(scope="module")
def indexed_project(tmp_path_factory):
    """Create a temp directory with 3-4 Python files, init git, and index.

    Dependency structure:
      main.py  ->  service.py  ->  models.py
                   service.py  ->  utils.py
    """
    proj = tmp_path_factory.mktemp("newfeatures")

    (proj / "models.py").write_text(
        'class User:\n'
        '    """A user model."""\n'
        '    def __init__(self, name: str, email: str):\n'
        '        self.name = name\n'
        '        self.email = email\n'
        '\n'
        '    def display(self):\n'
        '        return f"{self.name} <{self.email}>"\n'
        '\n'
        'class Role:\n'
        '    """A role model."""\n'
        '    def __init__(self, title):\n'
        '        self.title = title\n'
        '\n'
        '    def describe(self):\n'
        '        return f"Role: {self.title}"\n'
    )

    (proj / "utils.py").write_text(
        'def validate_email(email: str) -> bool:\n'
        '    """Check if email is valid."""\n'
        '    return "@" in email\n'
        '\n'
        'def format_name(first: str, last: str) -> str:\n'
        '    """Format a full name."""\n'
        '    return f"{first} {last}"\n'
        '\n'
        'def unused_helper():\n'
        '    """This function is never called."""\n'
        '    return 42\n'
    )

    (proj / "service.py").write_text(
        'from models import User, Role\n'
        'from utils import validate_email, format_name\n'
        '\n'
        'def create_user(name: str, email: str) -> User:\n'
        '    """Create and validate a user."""\n'
        '    if not validate_email(email):\n'
        '        raise ValueError("Invalid email")\n'
        '    return User(name, email)\n'
        '\n'
        'def get_user_role(user: User) -> Role:\n'
        '    """Get the role for a user."""\n'
        '    return Role("member")\n'
        '\n'
        'def list_users():\n'
        '    """List all users."""\n'
        '    return []\n'
    )

    (proj / "main.py").write_text(
        'from service import create_user, list_users\n'
        '\n'
        'def main():\n'
        '    """Application entry point."""\n'
        '    user = create_user("Alice", "alice@example.com")\n'
        '    print(user.display())\n'
        '    print(list_users())\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    main()\n'
    )

    git_init(proj)

    # Add a second commit for git history
    (proj / "service.py").write_text(
        'from models import User, Role\n'
        'from utils import validate_email, format_name\n'
        '\n'
        'def create_user(name: str, email: str) -> User:\n'
        '    """Create and validate a user."""\n'
        '    if not validate_email(email):\n'
        '        raise ValueError("Invalid email")\n'
        '    full = format_name(name, "")\n'
        '    return User(full, email)\n'
        '\n'
        'def get_user_role(user: User) -> Role:\n'
        '    """Get the role for a user."""\n'
        '    return Role("member")\n'
        '\n'
        'def list_users():\n'
        '    """List all users."""\n'
        '    return []\n'
    )
    git_commit(proj, "refactor service")

    out, rc = index_in_process(proj, "--force")
    assert rc == 0, f"Index failed: {out}"
    return proj


# ============================================================================
# TestUnderstand
# ============================================================================

class TestUnderstand:
    def test_understand_text(self, indexed_project):
        """roam understand should show Key abstractions, Health, and file counts."""
        out, rc = roam("understand", cwd=indexed_project)
        assert rc == 0, f"understand failed: {out}"
        assert "Key abstractions" in out, f"Missing 'Key abstractions' in: {out}"
        assert "Health:" in out or "Health" in out, f"Missing Health in: {out}"
        # Should mention file counts
        assert "files" in out.lower(), f"Missing file counts in: {out}"

    def test_understand_json(self, indexed_project):
        """roam --json understand should return valid JSON with expected keys."""
        out, rc = roam("--json", "understand", cwd=indexed_project)
        assert rc == 0, f"understand --json failed: {out}"
        data = json.loads(out)
        assert "command" in data, f"Missing 'command' key in JSON: {data.keys()}"
        assert data["command"] == "understand"
        assert "tech_stack" in data, f"Missing 'tech_stack' key in JSON: {data.keys()}"
        assert "architecture" in data, f"Missing 'architecture' key in JSON: {data.keys()}"
        assert "summary" in data
        assert "timestamp" in data.get("_meta", data)


# ============================================================================
# TestDeadEnhanced
# ============================================================================

class TestDeadEnhanced:
    def test_dead_summary(self, indexed_project):
        """roam dead --summary should print a one-line summary."""
        out, rc = roam("dead", "--summary", cwd=indexed_project)
        assert rc == 0, f"dead --summary failed: {out}"
        assert "Dead exports:" in out or "safe" in out.lower(), \
            f"Missing summary line in: {out}"

    def test_dead_by_kind(self, indexed_project):
        """roam dead --by-kind should group dead symbols by kind."""
        out, rc = roam("dead", "--by-kind", cwd=indexed_project)
        assert rc == 0, f"dead --by-kind failed: {out}"
        # Grouped output should show the header mentioning 'by kind'
        assert "kind" in out.lower() or "Kind" in out, \
            f"Missing kind grouping header in: {out}"

    def test_dead_clusters(self, indexed_project):
        """roam dead --clusters should attempt cluster detection."""
        out, rc = roam("--detail", "dead", "--clusters", cwd=indexed_project)
        assert rc == 0, f"dead --clusters failed: {out}"
        # Output should mention clusters or at least run without error.
        # If no clusters exist, the basic dead output still appears.
        assert "Unreferenced" in out or "cluster" in out.lower() or "Dead" in out.lower(), \
            f"Unexpected output from dead --clusters: {out}"


# ============================================================================
# TestContextBatch
# ============================================================================

class TestContextBatch:
    def test_context_single(self, indexed_project):
        """roam context <symbol> should show context for a single symbol."""
        out, rc = roam("context", "create_user", cwd=indexed_project)
        assert rc == 0, f"context failed: {out}"
        assert "Context for" in out, f"Missing 'Context for' in: {out}"

    def test_context_batch(self, indexed_project):
        """roam context <sym1> <sym2> should produce batch output."""
        out, rc = roam("context", "create_user", "list_users", cwd=indexed_project)
        assert rc == 0, f"context batch failed: {out}"
        # Batch mode should show 'Batch Context' header or 'Shared callers'
        assert "Batch Context" in out or "Shared callers" in out or \
            "shared" in out.lower() or "Files to read" in out, \
            f"Missing batch context output in: {out}"


# ============================================================================
# TestJsonEnvelope
# ============================================================================

class TestJsonEnvelope:
    """Verify that key commands produce valid JSON with the standard envelope."""

    def _assert_envelope(self, out, expected_command):
        """Parse JSON and assert standard envelope keys."""
        data = json.loads(out)
        assert "command" in data, f"Missing 'command' in JSON: {list(data.keys())}"
        assert data["command"] == expected_command, \
            f"Expected command={expected_command}, got {data['command']}"
        assert "timestamp" in data.get("_meta", data), f"Missing 'timestamp' in _meta or JSON: {list(data.keys())}"
        assert "summary" in data, f"Missing 'summary' in JSON: {list(data.keys())}"
        return data

    def test_json_dead(self, indexed_project):
        """roam --json dead should have standard envelope."""
        out, rc = roam("--json", "dead", cwd=indexed_project)
        assert rc == 0, f"dead --json failed: {out}"
        self._assert_envelope(out, "dead")

    def test_json_health(self, indexed_project):
        """roam --json health should have standard envelope."""
        out, rc = roam("--json", "health", cwd=indexed_project)
        assert rc == 0, f"health --json failed: {out}"
        self._assert_envelope(out, "health")

    def test_json_understand(self, indexed_project):
        """roam --json understand should have standard envelope."""
        out, rc = roam("--json", "understand", cwd=indexed_project)
        assert rc == 0, f"understand --json failed: {out}"
        data = self._assert_envelope(out, "understand")
        # Understand-specific keys
        assert "tech_stack" in data
        assert "architecture" in data

    def test_json_context(self, indexed_project):
        """roam --json context should have standard envelope."""
        out, rc = roam("--json", "context", "create_user", cwd=indexed_project)
        assert rc == 0, f"context --json failed: {out}"
        data = self._assert_envelope(out, "context")
        assert "callers" in data or "symbol" in data or "symbols" in data


# ============================================================================
# v6.0 Commands — comprehensive tests for new intelligence features
# ============================================================================

class TestV6Complexity:
    """Tests for cognitive complexity analysis."""

    def test_complexity_runs(self, indexed_project):
        out, rc = roam("complexity", cwd=indexed_project)
        assert rc == 0, f"complexity failed: {out}"
        assert "complexity" in out.lower() or "analyzed" in out.lower()

    def test_complexity_bumpy_road(self, indexed_project):
        out, rc = roam("complexity", "--bumpy-road", cwd=indexed_project)
        # May not find bumpy-road files in small project - that's OK
        assert rc == 0, f"bumpy-road failed: {out}"

    def test_complexity_json(self, indexed_project):
        out, rc = roam("--json", "complexity", cwd=indexed_project)
        assert rc == 0, f"complexity --json failed: {out}"
        data = json.loads(out)
        assert data["command"] == "complexity"
        assert "symbols" in data or "summary" in data

    def test_complexity_by_file(self, indexed_project):
        out, rc = roam("complexity", "--by-file", cwd=indexed_project)
        assert rc == 0, f"complexity --by-file failed: {out}"

    def test_complexity_threshold(self, indexed_project):
        out, rc = roam("complexity", "--threshold", "0", cwd=indexed_project)
        assert rc == 0


class TestV6Debt:
    """Tests for hotspot-weighted debt."""

    def test_debt_runs(self, indexed_project):
        out, rc = roam("debt", cwd=indexed_project)
        assert rc == 0, f"debt failed: {out}"

    def test_debt_json(self, indexed_project):
        out, rc = roam("--json", "debt", cwd=indexed_project)
        assert rc == 0, f"debt --json failed: {out}"
        data = json.loads(out)
        assert data["command"] == "debt"
        assert "summary" in data


class TestV6AffectedTests:
    """Tests for affected-tests command."""

    def test_affected_tests_by_file(self, indexed_project):
        out, rc = roam("affected-tests", "service.py", cwd=indexed_project)
        # May find tests or not depending on test file structure
        assert rc == 0, f"affected-tests failed: {out}"

    def test_affected_tests_json(self, indexed_project):
        out, rc = roam("--json", "affected-tests", "create_user", cwd=indexed_project)
        assert rc == 0, f"affected-tests --json failed: {out}"
        data = json.loads(out)
        assert data["command"] == "affected-tests"


class TestV6EntryPoints:
    """Tests for entry point catalog."""

    def test_entry_points_runs(self, indexed_project):
        out, rc = roam("entry-points", cwd=indexed_project)
        assert rc == 0, f"entry-points failed: {out}"

    def test_entry_points_json(self, indexed_project):
        out, rc = roam("--json", "entry-points", cwd=indexed_project)
        assert rc == 0, f"entry-points --json failed: {out}"
        data = json.loads(out)
        assert data["command"] == "entry-points"


class TestV6Preflight:
    """Tests for pre-flight checklist."""

    def test_preflight_symbol(self, indexed_project):
        out, rc = roam("preflight", "create_user", cwd=indexed_project)
        assert rc == 0, f"preflight failed: {out}"
        assert "Pre-flight" in out or "risk" in out.lower()

    def test_preflight_json(self, indexed_project):
        out, rc = roam("--json", "preflight", "create_user", cwd=indexed_project)
        assert rc == 0, f"preflight --json failed: {out}"
        data = json.loads(out)
        assert data["command"] == "preflight"
        assert "summary" in data
        assert "risk_level" in data["summary"]


class TestV6TaskContext:
    """Tests for task-aware context mode."""

    def test_context_task_refactor(self, indexed_project):
        out, rc = roam("context", "--task", "refactor", "create_user", cwd=indexed_project)
        assert rc == 0, f"context --task refactor failed: {out}"
        assert "Refactor" in out or "refactor" in out.lower()

    def test_context_task_debug(self, indexed_project):
        out, rc = roam("context", "--task", "debug", "create_user", cwd=indexed_project)
        assert rc == 0, f"context --task debug failed: {out}"

    def test_context_task_extend(self, indexed_project):
        out, rc = roam("context", "--task", "extend", "create_user", cwd=indexed_project)
        assert rc == 0, f"context --task extend failed: {out}"

    def test_context_task_review(self, indexed_project):
        out, rc = roam("context", "--task", "review", "create_user", cwd=indexed_project)
        assert rc == 0, f"context --task review failed: {out}"

    def test_context_task_understand(self, indexed_project):
        out, rc = roam("context", "--task", "understand", "create_user", cwd=indexed_project)
        assert rc == 0, f"context --task understand failed: {out}"


class TestV6EnhancedUnderstand:
    """Tests for enhanced understand with conventions, complexity, patterns."""

    def test_understand_has_conventions(self, indexed_project):
        out, rc = roam("understand", cwd=indexed_project)
        assert rc == 0
        assert "Conventions" in out or "convention" in out.lower()

    def test_understand_has_complexity(self, indexed_project):
        out, rc = roam("understand", cwd=indexed_project)
        assert rc == 0
        assert "Complexity" in out or "complexity" in out.lower()

    def test_understand_json_has_new_fields(self, indexed_project):
        out, rc = roam("--json", "understand", cwd=indexed_project)
        assert rc == 0
        data = json.loads(out)
        assert "conventions" in data
        assert "complexity" in data or "complexity" in str(data)


