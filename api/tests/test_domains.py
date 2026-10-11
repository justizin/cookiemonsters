import json
from pathlib import Path

import pytest

from cookiemonsters.domains import InvalidSite, registrable_domain


@pytest.mark.parametrize(
    "raw,site",
    [
        ("example.com", "example.com"),
        ("WWW.Example.COM.", "example.com"),
        ("https://shop.example.co.uk/orders/1?ref=x", "example.co.uk"),
        ("news.bbc.co.uk:443", "bbc.co.uk"),
        ("a.b.github.io", "b.github.io"),
        ("www.city.kawasaki.jp", "city.kawasaki.jp"),
        ("x.y.foo.kawasaki.jp", "y.foo.kawasaki.jp"),
        ("bücher.de", "xn--bcher-kva.de"),
    ],
)
def test_registrable(raw, site):
    assert registrable_domain(raw) == site


@pytest.mark.parametrize("raw", ["localhost", "127.0.0.1", "[::1]", "10.1.2.3", "co.uk", "github.io", "foo.notatld", "intranet.local", "x.test", "user@example.com", "", "a..b.com", "-bad-.com"])
def test_rejected(raw):
    with pytest.raises(InvalidSite):
        registrable_domain(raw)


def test_reserved_only_when_allowed():
    assert registrable_domain("shop.fixture.test", allow_reserved=True) == "fixture.test"


SHARED = json.loads((Path(__file__).resolve().parents[2] / "shared/domain_vectors.json").read_text())


@pytest.mark.parametrize("host,site", SHARED["cases"], ids=[c[0] for c in SHARED["cases"]])
def test_shared_vectors(host, site):
    if site is None:
        with pytest.raises(InvalidSite):
            registrable_domain(host)
    else:
        assert registrable_domain(host) == site
