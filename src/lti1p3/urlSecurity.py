"""Enforces https for platform and tool endpoints, with a loopback exception.

Brightspace and the LTI 1.3 security model expect https in production. The
one exception is loopback addresses, which local development and this
library's own test fixtures need. The rule is a plain function of the URL
rather than a configurable allow-list: the loopback exception is narrow
enough not to weaken production use, and it avoids threading a settings
object through every constructor for one check.
"""

from urllib.parse import urlsplit

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def isSecureUrl(url: str) -> bool:
    """Return True for an https URL, or an http URL whose host is a loopback address."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False

    if parts.scheme == "https":
        return True

    if parts.scheme != "http":
        return False

    return parts.hostname in LOOPBACK_HOSTS
