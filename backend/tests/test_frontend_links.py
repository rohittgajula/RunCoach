"""Every in-app link points at a route that exists, and every section is linked.

This is here because the bug shipped twice. 7cf332e ("Strip the app back to
running, strength and the schedule") deleted the Reports, Experiments and Compare
routes from pages/Insights but left Health → More linking to all three, so every
one of those rows bounced the athlete back to Overview; the same commit orphaned
the Diet page. In the other direction, /health/labs and /health/body had routes
and no link, so the only way to reach the blood panel was to type the URL.

A route with no link is unreachable; a link with no route is a dead end. Neither
shows up in a diff and neither fails a build, so it takes a test.

It reads the TSX as text rather than running a bundler, which bounds what it can
see: only `to="/literal"` and `navigate('/literal')` links, never a computed
template string. Those it skips, so this is a floor, not a proof.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"

# CI checks out the whole repo, so this runs there. The dev container mounts only
# backend/, so it skips there rather than failing on a tree it cannot see.
pytestmark = pytest.mark.skipif(not SRC.is_dir(), reason="frontend/src not mounted")

# `to="/x"` and `navigate('/x')` — how everything in this app links. A link holding
# ${...} is computed and deliberately not matched.
LINK_RE = re.compile(r"""to=["'](/[^"'{}\s]*)["']|navigate\(\s*["'](/[^"'{}\s]*)["']""")
ROUTE_RE = re.compile(r"""<Route\s+[^>]*path=["']([^"']+)["']""")

# Nested routers: the App mount, and the file holding its <Route> elements. Listed
# rather than guessed, so a new nested router has to be added here consciously.
NESTED = {
    "/health": "pages/Insights.tsx",
    "/me": "pages/Me.tsx",
    "/admin-panel": "pages/AdminPanel.tsx",
}

# Links that deliberately leave the router. Keep short and justified.
ALLOW = {"/"}


def _files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.tsx") if p.is_file())


def _paths_in(page: Path) -> list[str]:
    return [p for p in ROUTE_RE.findall(page.read_text()) if p != "*"]


def _routes() -> set[str]:
    """Every declared path, absolute.

    A mount declared `/health/*` contributes only `/health` itself plus the paths
    its own router declares — never `/health/<anything>`. That distinction is the
    whole point: treating the mount as a wildcard is what let the dead Reports,
    Experiments and Compare links pass unnoticed.
    """
    out: set[str] = set()
    for raw in _paths_in(SRC / "App.tsx"):
        out.add(raw.rstrip("*").rstrip("/") or "/")
    for mount, rel in NESTED.items():
        page = SRC / rel
        if not page.is_file():
            raise AssertionError(f"{rel} is gone; update NESTED in this test")
        out.add(mount)
        for raw in _paths_in(page):
            out.add(f"{mount}/{raw.strip('/')}")
    return out


def _matches(link: str, routes: set[str]) -> bool:
    """Exact, or segment-for-segment with `:param` standing in for one segment."""
    if link in ALLOW or link in routes:
        return True
    parts = link.strip("/").split("/")
    for route in routes:
        rparts = route.strip("/").split("/")
        if len(rparts) == len(parts) and all(
            r.startswith(":") or r == p for r, p in zip(rparts, parts)
        ):
            return True
    return False


def _links(page: Path) -> set[str]:
    out = set()
    for a, b in LINK_RE.findall(page.read_text()):
        out.add((a or b).split("?")[0].split("#")[0].rstrip("/") or "/")
    return out


def test_every_link_has_a_route():
    routes = _routes()
    assert "/health/labs" in routes and "/health" in routes, "the test cannot read the routes"
    dead = {
        f"{page.relative_to(SRC)} → {link}"
        for page in _files()
        for link in _links(page)
        if not _matches(link, routes)
    }
    assert not dead, (
        "links with no route — each one bounces to the fallback:\n  " + "\n  ".join(sorted(dead))
    )


@pytest.mark.parametrize(
    "path",
    [
        "/health/labs", "/health/body", "/diet",
        "/health/reports", "/health/compare", "/health/experiments",
    ],
)
def test_section_is_linked_not_just_routed(path: str):
    """A section the athlete can only reach by typing the URL is not shipped.

    Every path here was exactly that: built, routed, deployed, unreachable.
    """
    linked = sorted(
        p.relative_to(SRC).as_posix()
        for p in _files()
        if p.name not in ("App.tsx", "Insights.tsx") and path in _links(p)
    )
    assert linked, f"nothing links to {path}; it is only reachable by typing the URL"
