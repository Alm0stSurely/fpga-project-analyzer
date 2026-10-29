"""XDC reader: which top-level port bits have PACKAGE_PIN / IOSTANDARD, and clocks."""
from __future__ import annotations

import fnmatch
import re

from .bdtcl import Interp, _split_list


class _XdcInterp(Interp):
    def __init__(self):
        super().__init__()
        self.props = []     # (prop, value, [patterns], line-ish)
        self.cell_props = []  # (prop, value, [cell patterns]) from set_property ... [get_cells ...]
        self.clocks = []    # (name, period, [patterns])

    def c_get_ports(self, a):
        _, rest = self._opts(a, {"-filter", "-of_objects"})
        pats = []
        for r in rest:
            pats.extend(_split_list(r) if " " in r else [r])
        return " ".join("xport:" + p for p in pats)

    def c_get_cells(self, a):
        _, rest = self._opts(a, {"-filter", "-of_objects"})
        pats = []
        for r in rest:
            pats.extend(_split_list(r) if " " in r else [r])
        return " ".join("xcell:" + p for p in pats)

    def c_set_property(self, a):
        o, rest = self._opts(a, {"-dict"})
        if isinstance(o.get("-dict"), str):
            items = _split_list(o["-dict"])
            if items and items[0] == "list":
                items = items[1:]
            pairs = list(zip(items[0::2], items[1::2]))
            objs = rest
        elif len(rest) >= 3:
            pairs, objs = [(rest[0], rest[1])], rest[2:]
        else:
            return ""
        words = " ".join(objs).split()
        pats = [x[6:] for x in words if x.startswith("xport:")]
        cells = [x[6:] for x in words if x.startswith("xcell:")]
        for k, v in pairs:
            if pats:
                self.props.append((k.upper(), v, pats))
            if cells:
                self.cell_props.append((k.upper(), v, cells))
        return ""

    def c_create_clock(self, a):
        o, rest = self._opts(a, {"-period", "-name", "-waveform"})
        pats = [x[6:] for x in " ".join(rest).split() if x.startswith("xport:")]
        self.clocks.append((o.get("-name") if isinstance(o.get("-name"), str) else (pats[0] if pats else ""),
                            o.get("-period"), pats))
        return ""


def parse(paths: list) -> dict:
    it = _XdcInterp()
    for p in paths:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                it.run(f.read(), it.globals)
        except OSError:
            continue
    return {"props": it.props, "clocks": it.clocks, "cell_props": it.cell_props}


def _match(pat, name):
    pat = pat.strip("{}")
    return fnmatch.fnmatchcase(name, pat.replace("[", "\x00").replace("]", "\x01").replace("\x00", "[[]")
                               .replace("\x01", "[]]")) if any(c in pat for c in "*?") else pat == name


def bits(name: str, w, left=None, right=None) -> list:
    if left is not None and right is not None:
        lo, hi = sorted((int(left), int(right)))
        return ["%s[%d]" % (name, i) for i in range(lo, hi + 1)]
    if w and w > 1:
        return ["%s[%d]" % (name, i) for i in range(w)]
    return [name]


def unconstrained(port_bits: list, x: dict) -> dict:
    """port bit -> missing properties (subset of PACKAGE_PIN, IOSTANDARD)."""
    have = {b: set() for b in port_bits}
    for prop, _, pats in x["props"]:
        if prop not in ("PACKAGE_PIN", "IOSTANDARD", "LOC"):
            continue
        prop = "PACKAGE_PIN" if prop == "LOC" else prop
        for b in port_bits:
            base = b.split("[")[0]
            if any(_match(p, b) or _match(p, base) for p in pats):
                have[b].add(prop)
    return {b: sorted({"PACKAGE_PIN", "IOSTANDARD"} - s) for b, s in have.items()
            if {"PACKAGE_PIN", "IOSTANDARD"} - s}


def unknown_targets(port_bits: list, x: dict) -> list:
    names = set(port_bits) | {b.split("[")[0] for b in port_bits}
    bad = []
    for prop, _, pats in x["props"]:
        for p in pats:
            if not any(_match(p, n) for n in names):
                bad.append(p)
    return sorted(set(bad))
