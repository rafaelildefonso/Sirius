"""Best-effort guard for direct shutdown commands in generic AI runners.

This blocks common explicit OS shutdown APIs and commands. It is not a sandbox:
arbitrary generated code and desktop automation can still express equivalent
operations in ways that cannot be reliably detected here.
"""

import re

_POWER_OFF_PATTERNS = (
    # Windows accepts both slash and dash prefixes for shutdown switches.
    r"\bshutdown(?:\.exe)?\b[^\n]{0,100}(?:[/-](?:s|p|sg|hybrid)\b|-[hH]\b|--poweroff\b)",
    r"\b(?:systemctl|loginctl)\b[^\n]{0,80}\b(?:poweroff|halt|shutdown)\b",
    r"\b(?:poweroff|halt)\b",
    r"\bStop-Computer\b",
    r"\b(?:ExitWindowsEx|InitiateSystemShutdown(?:Ex)?)\b",
    r"\b(?:tell\s+(?:application|app)\s+['\"]System Events['\"]\s+to\s+shut\s+down|shutdown\s+-h\s+now)\b",
)


def contains_explicit_shutdown(text: str) -> bool:
    source = str(text or "")
    return any(re.search(pattern, source, re.IGNORECASE) for pattern in _POWER_OFF_PATTERNS)


def reject_explicit_shutdown(text: str) -> None:
    if contains_explicit_shutdown(text):
        raise ValueError(
            "Computer shutdown is available only from the paired phone's confirmed button."
        )
