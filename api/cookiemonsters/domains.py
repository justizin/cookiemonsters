"""Reduce a hostname to its registrable domain ("site", eTLD+1).

Uses a vendored copy of the Public Suffix List (shared/public_suffix_list.dat,
MPL-2.0) compiled into ``_generated.py`` by ``tools/sync_generated.py``. No
network access at runtime.

The extension ships the same rules and the same algorithm
(extension/src/common/site.js) so the client and server always agree on what a
"site" is. The server re-derives the site from whatever the client sends, so a
report can never write to a key that is not a real registrable domain.
"""

from __future__ import annotations

import ipaddress
import re
from functools import lru_cache

from ._generated import PSL

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")

# Reserved / special-use TLDs (RFC 2606, RFC 6761, RFC 8375 …). Never graded,
# except when explicitly allowed for local testing.
RESERVED_TLDS = frozenset({"test", "example", "invalid", "localhost", "local", "internal", "home", "lan", "corp", "onion", "alt", "arpa"})


class InvalidSite(ValueError):
    """The input is not a public, registrable domain."""


class _PSL:
    def __init__(self, lines: list[str]):
        self.rules: set[str] = set()
        self.wildcards: set[str] = set()  # stored without the leading "*."
        self.exceptions: set[str] = set()  # stored without the leading "!"
        for line in lines:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("!"):
                self.exceptions.add(line[1:])
            elif line.startswith("*."):
                self.wildcards.add(line[2:])
            else:
                self.rules.add(line)
        self.tlds = {r.rsplit(".", 1)[-1] for r in self.rules | self.wildcards}

    def public_suffix_len(self, labels: list[str]) -> tuple[int, bool]:
        """Return (number of labels in the public suffix, matched_explicit_rule)."""
        best = 0
        explicit = False
        n = len(labels)
        for i in range(n):
            cand = ".".join(labels[i:])
            k = n - i
            if cand in self.exceptions:
                return k - 1, True
            if cand in self.rules and k > best:
                best, explicit = k, True
            if i > 0 and cand in self.wildcards and k + 1 > best:
                best, explicit = k + 1, True
        if best == 0:
            return 1, False  # PSL default rule "*"
        return best, explicit


@lru_cache(maxsize=1)
def _psl() -> _PSL:
    return _PSL(PSL.splitlines())


def normalize_host(raw: str) -> str:
    """Lowercase, strip scheme/port/path/trailing dot, convert IDN to punycode."""
    if not isinstance(raw, str):
        raise InvalidSite("not a string")
    host = raw.strip().lower()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in host:
        raise InvalidSite("credentials are not allowed")
    if host.startswith("["):
        raise InvalidSite("IP addresses are not sites")
    host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    host = host.rstrip(".")
    if not host or len(host) > 253:
        raise InvalidSite("empty or too long")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise InvalidSite("IP addresses are not sites")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidSite("invalid internationalised name") from exc
    labels = host.split(".")
    if not all(_LABEL.match(lab) for lab in labels):
        raise InvalidSite("invalid hostname")
    return host


def registrable_domain(raw: str, *, allow_reserved: bool = False) -> str:
    """Return the eTLD+1 for ``raw`` or raise InvalidSite.

    Rejects IP addresses, single-label names, bare public suffixes, reserved
    TLDs (unless ``allow_reserved``) and TLDs that are not in the PSL.
    """
    host = normalize_host(raw)
    labels = host.split(".")
    if len(labels) < 2:
        raise InvalidSite("single-label names are not sites")
    tld = labels[-1]
    if tld in RESERVED_TLDS:
        if not allow_reserved:
            raise InvalidSite("reserved top-level domain")
        return ".".join(labels[-2:])
    psl = _psl()
    if tld not in psl.tlds:
        raise InvalidSite("unknown top-level domain")
    suffix_len, _ = psl.public_suffix_len(labels)
    if len(labels) <= suffix_len:
        raise InvalidSite("a public suffix is not a site")
    return ".".join(labels[-(suffix_len + 1):])
