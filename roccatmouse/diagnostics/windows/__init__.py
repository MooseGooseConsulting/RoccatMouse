"""Windows adapters for RoccatMouse diagnostics."""

from .clock import QpcClock
from .device import TyonDeviceControl
from .raw_accelerator import (
    RawAcceleratorSource,
    RawModeLifecycle,
    RawStreamHealth,
    find_paired_vendor_interface,
    find_raw_interface,
    open_hid_interface,
    parse_xcelerator_report,
    raw_mode_marker_path,
    xcal_command,
)
from .raw_input import RawInputSource

__all__ = [
    "QpcClock",
    "RawAcceleratorSource",
    "RawInputSource",
    "RawModeLifecycle",
    "RawStreamHealth",
    "TyonDeviceControl",
    "find_paired_vendor_interface",
    "find_raw_interface",
    "open_hid_interface",
    "parse_xcelerator_report",
    "raw_mode_marker_path",
    "xcal_command",
]
