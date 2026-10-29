"""Design model shared by every extractor, the linter and the viewer.

A design is a set of *defs* (cell types) and a *top* def id. A def owns pins,
child instances (each pointing at another def) and nets. Nets are lists of
endpoints ``[inst, pin]`` where ``inst == ""`` is the def's own boundary pin.
Instance paths ("/stream_proc/stream_scaler_0") address findings and notes.
"""
from __future__ import annotations

import json
import re

SCHEMA = "fpa/1"

_CLK = re.compile(r"(^|_)(a?clk\w*|\w*clock\w*|fclk_clk\d+|\w+_clk|clk_\w+|pl_clk\d+)$", re.I)
_RST = re.compile(r"(rst|reset|resetn|aresetn|rstn|rst_?n|_rst_)", re.I)
_INTR = re.compile(r"(intr|irq|interrupt|introut|irpt)", re.I)
_LOW = re.compile(r"(n|_n|_b|_l|resetn|rstn)$", re.I)
_OUT = re.compile(
    r"(_o$|_out$|^out\d*$|^dout|introut|irpt|interrupt$|^fclk_|^pl_clk|^pl_resetn|"
    r"^peripheral_|^interconnect_aresetn|^bus_struct_reset|^mb_reset|_tready_o)",
    re.I,
)


def new_design(name: str) -> dict:
    return {"schema": SCHEMA, "meta": {"name": name, "sources": []}, "top": "", "defs": {}}


def new_def(name: str, kind: str, **kw) -> dict:
    d = {"name": name, "kind": kind, "pins": [], "insts": [], "nets": []}
    d.update({k: v for k, v in kw.items() if v not in (None, "", [], {})})
    return d


# Names that look like clocks but are enables/selects/counters; e.g. NEORV32's clkgen_i / clk_gen are prescaled
# clock-enable vectors. A real clock is still typed "clk" structurally when it clocks a process.
_NOT_CLK = re.compile(r"(clk_?en|clken|clk_?ena|clk_?gen|enable|clk_?sel|clk_?cnt|clk_?div|_en_?[io]?$|_cnt|_count)", re.I)


def guess_kind(name: str) -> str:
    if _INTR.search(name):
        return "intr"
    if _CLK.search(name) and not _RST.search(name) and not _NOT_CLK.search(name):
        return "clk"
    if _RST.search(name):
        return "rst"
    return "data"


def guess_dir(name: str) -> str:
    return "out" if _OUT.search(name) else "in"


def active_low(name: str) -> bool:
    return bool(_LOW.search(name))


def pin(name: str, dir: str, kind: str = "", **kw) -> dict:
    p = {"name": name, "dir": dir, "kind": kind or guess_kind(name)}
    if p["kind"] == "rst" and "pol" not in kw:
        kw["pol"] = "low" if active_low(name) else "high"
    p.update({k: v for k, v in kw.items() if v not in (None, "", [], {})})
    return p


def norm_dir(d: str) -> str:
    d = (d or "").strip().lower()
    return {"i": "in", "input": "in", "in": "in", "o": "out", "output": "out", "out": "out",
            "io": "inout", "inout": "inout", "buffer": "out"}.get(d, "in")


def width(left, right) -> int:
    try:
        return abs(int(left) - int(right)) + 1
    except (TypeError, ValueError):
        return 0


def pin_index(d: dict) -> dict:
    return {p["name"]: p for p in d["pins"]}


def find_inst(d: dict, name: str):
    for i in d["insts"]:
        if i["name"] == name:
            return i
    return None


def resolve(design: dict, path: str):
    """Return (def, inst) for an instance path; '/' is the top def."""
    d = design["defs"][design["top"]]
    inst = None
    for part in [p for p in path.split("/") if p]:
        d = design["defs"].get(d.get("impl", ""), d) if not d["insts"] else d
        inst = find_inst(d, part)
        if inst is None:
            return None, None
        d = design["defs"][inst["def"]]
    return d, inst


def walk(design: dict, max_depth: int = 64):
    """Yield (path, def, inst) for every instance, depth first, following impl links."""
    defs = design["defs"]

    def rec(d, path, depth):
        if depth > max_depth:
            return
        body = defs.get(d.get("impl", ""), d) if not d["insts"] else d
        for i in body["insts"]:
            p = path + "/" + i["name"]
            cd = defs[i["def"]]
            yield p, cd, i
            yield from rec(cd, p, depth + 1)

    yield from rec(defs[design["top"]], "", 0)


def body(design: dict, d: dict) -> dict:
    """The def whose insts/nets are drawn when entering d (follows impl)."""
    if not d["insts"] and d.get("impl") in design["defs"]:
        return design["defs"][d["impl"]]
    return d


def add_source(design: dict, kind: str, path: str):
    design["meta"]["sources"].append({"kind": kind, "path": path})


def save(design: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(design, f, separators=(",", ":"))


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
