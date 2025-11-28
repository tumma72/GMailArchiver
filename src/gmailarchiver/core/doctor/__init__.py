"""Doctor package for system diagnostics and auto-repair."""

from gmailarchiver.connectors.auth import _get_bundled_credentials_path, _get_default_token_path
from gmailarchiver.core.doctor._diagnostics import CheckResult, CheckSeverity
from gmailarchiver.core.doctor._repair import FixResult
from gmailarchiver.core.doctor.facade import Doctor, DoctorReport

__all__ = [
    "Doctor",
    "DoctorReport",
    "CheckResult",
    "CheckSeverity",
    "FixResult",
    "_get_default_token_path",
    "_get_bundled_credentials_path",
]
