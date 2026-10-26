"""Link software to hardware blocks: PYNQ notebooks/Python, bare-metal C, device tree, HLS.

Each reference becomes an annotation on an instance path; PYNQ-specific
mistakes (unknown IP names, .bit/.hwh pairing, MMIO outside the map) become
findings.
"""
from __future__ import annotations

import json
import os
import re

from . import model as M

MAX_PER_BLOCK = 8
_OVERLAY = re.compile(r"(\w+)\s*=\s*(?:pynq\.)?Overlay\(\s*['\"]([^'\"]+)['\"]")
_MMIO = re.compile(r"MMIO\(\s*(0x[0-9a-fA-F_]+)")
_XPAR = re.compile(r"\bXPAR_([A-Z0-9_]+?)_(BASEADDR|HIGHADDR|DEVICE_ID|BASEADDRESS|HIGHADDRESS|[A-Z0-9_]*INTR)\b")
_HEX = re.compile(r"\b0x([0-9a-fA-F]{8})\b")
_DT_NODE = re.compile(r"^\s*(\w+)\s*:\s*[\w,-]+@([0-9a-fA-F]+)\s*\{")
_DT_REF = re.compile(r"^\s*&(\w+)\s*\{")
_HLS_IF = re.compile(r"#pragma\s+HLS\s+INTERFACE\s+(.*)", re.I)
_FUNC = re.compile(r"^\s*(?:extern\s+\"C\"\s+)?(?:void|int|[\w:<>]+)\s+(\w+)\s*\(")


def _lines_of(path):
    if path.endswith(".ipynb"):
        try:
            with open(path, encoding="utf-8") as f:
                nb = json.load(f)
        except (OSError, ValueError):
            return
        for ci, cell in enumerate(nb.get("cells", [])):
            if cell.get("cell_type") != "code":
                continue
            src = cell.get("source", "")
            src = "".join(src) if isinstance(src, list) else src
            for li, ln in enumerate(src.splitlines(), 1):
                yield "cell %d:%d" % (ci + 1, li), ln
        return
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for no, ln in enumerate(f, 1):
                yield no, ln.rstrip("\n")
    except OSError:
        return


def _addr_index(design):
    top = design["defs"][design["top"]]
    rows = []
    for a in top.get("addr", []):
        try:
            base = int(a["base"], 0)
        except (ValueError, TypeError):
            continue
        from .lint import _size
        size = _size(a) or 0x1000
        if a.get("block") and "DDR" in a.get("block", "").upper():
            continue
        rows.append((base, base + size - 1, a["slave"]))
    return rows


def scan(design: dict, files: dict, rel=lambda p: p, bitfiles=(), hwhfiles=(), expect_bit=""):
    insts = {}
    upper = {}
    for path, d, inst in M.walk(design, 3):
        insts[path] = d
        upper[path.strip("/").replace("/", "_").upper()] = path
    pynq_paths = {p.strip("/").replace("/", "."): p for p in insts}
    addr = _addr_index(design)
    ann, findings = [], []
    count = {}

    def add(path, kind, file, line, text):
        k = (path, kind)
        count[k] = count.get(k, 0) + 1
        if count[k] <= MAX_PER_BLOCK:
            ann.append({"path": path, "kind": kind, "file": rel(file), "line": line, "text": text.strip()[:120]})

    def by_addr(v):
        for lo, hi, slave in addr:
            if lo <= v <= hi:
                return slave
        return None

    for f in files.get("py", []) + files.get("nb", []):
        ol_vars, alias = {}, {}
        for line, text in _lines_of(f):
            for var, p in alias.items():
                if re.search(r"\b%s\." % re.escape(var), text) and not re.match(r"\s*%s\s*=" % re.escape(var), text):
                    add(p, "py", f, line, text)
            m = _OVERLAY.search(text)
            if m:
                ol_vars[m.group(1)] = m.group(2)
                bit = os.path.basename(m.group(2))
                stem = os.path.splitext(bit)[0]
                if not any(os.path.splitext(os.path.basename(h))[0] == stem for h in hwhfiles):
                    findings.append({"sev": "med", "path": "/", "rule": "pynq-hwh",
                                     "title": "Overlay('%s') has no %s.hwh in the project" % (bit, stem),
                                     "detail": "%s %s" % (rel(f), line),
                                     "fix": "PYNQ needs %s.bit and %s.hwh side by side." % (stem, stem),
                                     "by": "lint"})
                built = [b for b in bitfiles if os.path.splitext(os.path.basename(b))[0] != stem]
                if not bitfiles and expect_bit and os.path.splitext(expect_bit)[0] != stem:
                    built = [expect_bit]
                if built and not any(os.path.splitext(os.path.basename(b))[0] == stem for b in bitfiles):
                    findings.append({"sev": "med", "path": "/", "rule": "pynq-bitname",
                                     "title": "Notebook loads %s but the build makes %s" % (
                                         bit, os.path.basename(built[0])),
                                     "detail": "%s %s" % (rel(f), line),
                                     "fix": "Copy/rename the bitstream to %s.bit next to %s.hwh." % (stem, stem),
                                     "by": "lint"})
            for var in ol_vars:
                for chain in re.findall(r"\b%s\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)" % re.escape(var), text):
                    parts = chain.split(".")
                    hit = None
                    for k in range(len(parts), 0, -1):
                        hit = pynq_paths.get(".".join(parts[:k]))
                        if hit:
                            break
                    if hit:
                        add(hit, "py", f, line, text)
                        am = re.match(r"\s*(\w+)\s*=\s*%s\.%s\s*$" % (re.escape(var), re.escape(chain)), text)
                        if am:
                            alias[am.group(1)] = hit
                    elif re.search(r"_\d+$", parts[0]) and parts[0] not in ("ip_dict", "hierarchy_dict"):
                        findings.append({"sev": "med", "path": "/", "rule": "pynq-unknown-ip",
                                         "title": "%s.%s is not in the design" % (var, parts[0]),
                                         "detail": "%s %s: %s" % (rel(f), line, text.strip()[:100]),
                                         "fix": "Use the BD instance name (see ol.ip_dict.keys()).", "by": "lint"})
                for key in re.findall(r"%s\.ip_dict\[\s*['\"]([\w/]+)['\"]" % re.escape(var), text):
                    p = pynq_paths.get(key.replace("/", "."))
                    if p:
                        add(p, "py", f, line, text)
            for m in _MMIO.finditer(text):
                v = int(m.group(1).replace("_", ""), 16)
                slave = by_addr(v)
                if slave:
                    add(slave, "py", f, line, text)
                elif addr:
                    findings.append({"sev": "med", "path": "/", "rule": "mmio-unmapped",
                                     "title": "MMIO(%s) is outside the address map" % m.group(1),
                                     "detail": "%s %s" % (rel(f), line), "by": "lint"})
    for f in files.get("c", []):
        hls_top, pragmas = None, []
        for line, text in _lines_of(f):
            for m in _XPAR.finditer(text):
                p = upper.get(m.group(1))
                if p:
                    add(p, "c", f, line, text)
            for m in _HEX.finditer(text):
                slave = by_addr(int(m.group(1), 16))
                if slave:
                    add(slave, "c", f, line, text)
            fm = _FUNC.match(text)
            if fm:
                hls_top = fm.group(1) if not pragmas else hls_top
            hm = _HLS_IF.search(text)
            if hm and hls_top:
                pragmas.append((hls_top, line, hm.group(1)))
        for fn, line, prag in pragmas:
            for path, d in insts.items():
                if d.get("kind") == "hls" and d.get("name") == fn:
                    add(path, "hls", f, line, "INTERFACE " + prag)
                    d.setdefault("src", {"file": rel(f), "line": line})
    for f in files.get("dt", []):
        for line, text in _lines_of(f):
            m = _DT_NODE.match(text) or _DT_REF.match(text)
            if not m:
                continue
            label = m.group(1)
            p = next((pp for pp in insts if pp.rsplit("/", 1)[-1] == label), None)
            if p is None and len(m.groups()) > 1:
                p = by_addr(int(m.group(2), 16))
            if p:
                add(p, "dt", f, line, text)
    return ann, findings
