"""Windows adapters for RoccatMouse diagnostics."""

from .clock import QpcClock
from .raw_input import RawInputSource

__all__ = ["QpcClock", "RawInputSource"]
