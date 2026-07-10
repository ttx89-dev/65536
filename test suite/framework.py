"""
framework.py — 65536 Test Suite Infrastructure (pytest-era)
═══════════════════════════════════════════════════════════════════════════════

Kept for non-pytest utility scripts (benchmarks, parity check, golden gen).
Pytest test files no longer import from this module — they use bare `assert`.
═══════════════════════════════════════════════════════════════════════════════
"""

import sys
import os
import json
import time
from typing import Any, Callable

# ── Path Setup ──────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ── Assertions ─────────────────────────────────────────────────────────────

class AssertionError(Exception):
    """Raised when a test assertion fails. Carries structured diff context."""

    def __init__(self, message: str, expected=None, actual=None):
        super().__init__(message)
        self.expected = expected
        self.actual = actual


def assert_equal(a: Any, b: Any, context: str = "") -> None:
    """Assert value equality with structured error."""
    if a != b:
        raise AssertionError(f"Expected {a!r}, got {b!r} :: {context}", a, b)


# ── Golden File Registry ───────────────────────────────────────────────────

GOLDEN_DIR = os.path.join(_HERE, "vectors", "golden")
os.makedirs(GOLDEN_DIR, exist_ok=True)


def golden_path(name: str) -> str:
    """Return filesystem path for a golden file."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return os.path.join(GOLDEN_DIR, f"{safe}.json")


class GoldenRegistry:
    """Load/save/compare golden test vectors."""

    def __init__(self, name: str):
        self.path = golden_path(name)
        self._data: dict[str, Any] = {}
        self._dirty = False

    def load(self) -> dict[str, Any]:
        if os.path.exists(self.path):
            with open(self.path) as f:
                self._data = json.load(f)
        return self._data

    def save(self) -> None:
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2, sort_keys=True)
            f.write("\n")
        self._dirty = False

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._dirty = True

    def get(self, key: str, default=None) -> Any:
        return self._data.get(key, default)

    def compare(self, key: str, actual: Any) -> tuple[bool, str]:
        if key not in self._data:
            self._data[key] = actual
            self._dirty = True
            return True, "GOLDEN CREATED"
        expected = self._data[key]
        if actual == expected:
            return True, "MATCH"
        hex_a = actual.hex() if isinstance(actual, bytes) else json.dumps(actual)
        hex_e = expected.hex() if isinstance(expected, bytes) else json.dumps(expected)
        return False, f"MISMATCH {key}\n  Expected: {hex_e}\n  Actual:   {hex_a}"


# ── Timing & Reporting ─────────────────────────────────────────────────────

TimerUnit = float  # seconds


class Timer:
    """Simple wall-clock timer."""

    def __enter__(self) -> "Timer":
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args) -> None:
        self.elapsed = time.perf_counter() - self.start

    def seconds(self) -> float:
        return self.elapsed


def print_report(results: list, title: str = "") -> dict[str, Any]:
    """Print formatted terminal report.

    Returns summary dict: {passed, failed, skipped, total, duration_s}.
    """
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]

    if title:
        print(f"\n─── {title} ───")

    for r in results:
        if r.passed:
            status = f"  \u2713 {r.name}"
            if r.duration_s:
                status += f" ({r.duration_s*1000:.1f}ms)"
            print(status)
        else:
            print(f"  \u2717 {r.name}")
            if r.detail:
                for line in r.detail.strip().split("\n"):
                    print(f"    | {line}")

    total_s = sum(r.duration_s for r in results if r.duration_s)
    summary = {
        "passed": len(passed),
        "failed": len(failed),
        "skipped": 0,
        "total": len(results),
        "duration_s": total_s,
    }
    if failed:
        print(f"\n  FAILED {len(failed)}/{len(results)}  ({total_s*1000:.0f}ms total)")
    else:
        print(f"\n  All {len(passed)} passed  ({total_s*1000:.0f}ms total)" if passed
              else "\n  No tests run")
    return summary


# ── Language Detection ─────────────────────────────────────────────────────

def julia_available() -> tuple[bool, str]:
    """Check if Julia is installed and return version string."""
    import subprocess
    try:
        r = subprocess.run(
            ["julia", "-e", "println(VERSION)"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return True, r.stdout.strip()
        return False, r.stderr.strip()
    except FileNotFoundError:
        return False, "julia not found"
    except Exception as e:
        return False, str(e)


def python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


# ── Encoding Helpers ───────────────────────────────────────────────────────

def bytes_to_hex(b: bytes, sep: str = " ") -> str:
    """Bytes to spaced uppercase hex for display."""
    return b.hex(sep).upper()


def hex_to_bytes(s: str) -> bytes:
    """Inverse of bytes_to_hex — handles spaced or unspaced hex."""
    return bytes.fromhex(s.replace(" ", "").replace("\n", ""))
