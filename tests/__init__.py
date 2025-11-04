"""
SATL 3.0 - Test Configuration Lock
Binding invariants for all test executions
"""
from enum import Enum
from typing import Literal


class TestMode(str, Enum):
    """Test execution modes - NON-NEGOTIABLE"""
    PERFORMANCE = "performance"
    STEALTH = "stealth"
    FUNCTIONAL = "functional"
    SECURITY = "security"


# Invariants (binding)
SPO_STATUS: Literal["logic-secure"] = "logic-secure"
PQC_STATUS: Literal["design-level"] = "design-level"

# Valid modes
VALID_MODES = {TestMode.PERFORMANCE, TestMode.STEALTH, TestMode.FUNCTIONAL, TestMode.SECURITY}


def validate_test_header(mode: str) -> bool:
    """
    Validate test header compliance

    Returns:
        True if valid, False otherwise
    """
    if mode not in [m.value for m in VALID_MODES]:
        return False
    return True


def get_test_header(mode: TestMode) -> str:
    """
    Generate mandatory test header

    Returns:
        Formatted header string
    """
    return f"""MODE: {mode.value}
SPO: {SPO_STATUS}
PQC: {PQC_STATUS}"""


def print_test_header(mode: TestMode):
    """Print mandatory test header to stdout"""
    print("="*70)
    print(get_test_header(mode))
    print("="*70)


# Performance mode constraints (binding)
PERF_CONFIG = {
    "queue_delay_ms": (0, 0),
    "reorder_rate": 0.0,
    "padding": "minimal",
    "max_hops": 3
}

# Stealth mode constraints (binding)
STEALTH_CONFIG = {
    "queue_delay_ms": (50, 150),
    "reorder_rate": 0.1,
    "padding": "nhpp",
    "max_hops": 3
}

# Success criteria (binding)
PERF_CRITERIA = {
    "p95_latency_ms": 100,
    "success_rate": 0.99
}

STEALTH_CRITERIA = {
    "p95_latency_ms_min": 200,
    "p95_latency_ms_max": 800,
    "variance_min": 1000,
    "success_rate": 0.99
}
