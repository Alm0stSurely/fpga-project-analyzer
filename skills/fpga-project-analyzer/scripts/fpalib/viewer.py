"""Render a design (+ optional review overlay) into one offline HTML file."""
from __future__ import annotations

import json
import os

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def load_overlay(path: str) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def merge_overlay(design: dict, ov: dict) -> dict:
    d = dict(design)
    fs = list(design.get("findings", []))
    for i, f in enumerate(ov.get("findings", []), 1):
        f = dict(f)
        f.setdefault("by", "review")
        f.setdefault("id", "R%d" % i)
        f.setdefault("sev", "med")
        f["path"] = "/" + f.get("path", "/").strip("/") if f.get("path", "/").strip("/") else "/"
        fs.append(f)
    d["findings"] = fs
    d["notes"] = {("/" + k.strip("/")): v for k, v in (ov.get("notes") or {}).items()}
    d["flows"] = ov.get("flows") or []
    return d


def check_overlay(design: dict, ov: dict) -> list:
    """Unresolved paths and nets in an overlay, so the author can fix them."""
    from . import model as M
    warn = []

    def body_at(path):
        if not path.strip("/"):
            return M.body(design, design["defs"][design["top"]])
        d, _ = M.resolve(design, path)
        return M.body(design, d) if d else None

    for p in (ov.get("notes") or {}):
        if p.strip("/") and M.resolve(design, p)[0] is None:
            warn.append("note path not found: %s" % p)
    for f in ov.get("findings") or []:
        if f.get("path", "/").strip("/") and M.resolve(design, f["path"])[0] is None:
            warn.append("finding path not found: %s" % f["path"])
    for fl in ov.get("flows") or []:
        bad = []
        for key in fl.get("nets", []):
            lvl, _, net = key.partition("|")
            b = body_at(lvl)
            if b is None or not any(n["name"] == net for n in b["nets"]):
                bad.append(key)
        if bad:
            warn.append("flow '%s': %d of %d nets not found: %s (list names with: show <project> <level> --nets)" % (
                fl.get("name"), len(bad), len(fl.get("nets", [])), ", ".join(bad[:5])))
    return warn


def render(design: dict, out_path: str, overlay: dict = None) -> str:
    d = merge_overlay(design, overlay or {})
    meta = dict(d.get("meta", {}))
    meta.pop("inventory", None)
    d["meta"] = meta
    with open(os.path.join(ASSETS, "viewer.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(ASSETS, "vendor", "elk.bundled.js"), encoding="utf-8") as f:
        elk = f.read()
    data = json.dumps(d, separators=(",", ":")).replace("<", "\\u003c")
    top = d["defs"][d["top"]]["name"]
    html = html.replace("<!--FPA:TITLE-->", "%s · FPGA view" % top.replace("<", ""), 1)
    html = html.replace("/*FPA:DATA*/", data, 1)
    html = html.replace("/*FPA:ELK*/", elk, 1)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
