"""Find a project's sources, pick the best extractor for each, and assemble one design."""
from __future__ import annotations

import glob
import os
import re
import shutil
import xml.etree.ElementTree as ET

from . import bdjson, bdtcl, hdl, hwh, lint, model as M, refs, reports, xdc

SKIP_DIRS = {".git", ".svn", ".Xil", "node_modules", ".fpa", "__pycache__", ".ipynb_checkpoints", ".venv", "venv"}
GEN_SUFFIX = (".cache", ".hw", ".ip_user_files", ".sim", ".runs", ".gen")
EXT = {
    ".xpr": "xpr", ".bd": "bd", ".hwh": "hwh", ".xsa": "xsa", ".bit": "bit", ".xdc": "xdc", ".v": "hdl",
    ".sv": "hdl", ".vh": "hdl_inc", ".svh": "hdl_inc", ".vhd": "hdl", ".vhdl": "hdl", ".tcl": "tcl",
    ".ipynb": "nb", ".py": "py", ".c": "c", ".h": "c", ".cc": "c", ".cpp": "c", ".hpp": "c", ".dts": "dt",
    ".dtsi": "dt", ".rpt": "rpt", ".log": "log", ".dcp": "dcp", ".xci": "xci", ".bb": "yocto",
    ".bbappend": "yocto",
}


def _generated(rel_parts):
    return any(p.endswith(GEN_SUFFIX) for p in rel_parts)


def scan(root: str) -> dict:
    inv = {}
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel_parts = os.path.relpath(dirpath, root).split(os.sep)
        gen = _generated(rel_parts)
        ipgen = "sources_1" in rel_parts and ("ip" in rel_parts or "bd" in rel_parts) and \
            any(p.endswith(".srcs") for p in rel_parts)
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            kind = EXT.get(ext)
            if fn == "component.xml":
                kind = "ipxact"
            if not kind:
                continue
            path = os.path.join(dirpath, fn)
            if kind in ("hdl", "hdl_inc", "c", "py", "nb", "tcl") and (gen or ipgen):
                if not (kind == "hdl" and fn.endswith("_wrapper.v")):
                    continue
            if kind == "xdc" and gen and not fn.endswith("board.xdc"):
                continue
            inv.setdefault(kind, []).append(path)
    for k in inv:
        inv[k].sort()
    if "tcl" in inv:
        bdt = []
        for p in inv["tcl"]:
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    if bdtcl.looks_like_bd(f.read(200000)):
                        bdt.append(p)
            except OSError:
                pass
        if bdt:
            inv["bdtcl"] = bdt
    if "c" in inv:
        hls = []
        for p in inv["c"]:
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    if "#pragma hls" in f.read().lower():
                        hls.append(p)
            except OSError:
                pass
        if hls:
            inv["hls"] = hls
    return inv


def collect_srcs(items, root):
    """Explicit sources: files, dirs, globs, or file lists (make .d, .f, .lst). Returns (inventory, incdirs)."""
    files, incdirs = [], []
    for it in items:
        p = it if os.path.isabs(it) else os.path.join(root, it)
        if any(c in it for c in "*?["):
            files += sorted(glob.glob(p, recursive=True))
        elif os.path.isdir(p):
            for dp, dn, fn in os.walk(p):
                dn[:] = [d for d in dn if d not in SKIP_DIRS]
                files += [os.path.join(dp, f) for f in sorted(fn)]
        elif os.path.isfile(p) and p.endswith((".d", ".f", ".lst", ".list", ".txt")):
            base = os.path.dirname(p)
            with open(p, encoding="utf-8", errors="replace") as f:
                for tok in f.read().replace("\\\n", " ").split():
                    if tok.endswith(":") or tok in ("\\",) or tok.startswith("-"):
                        continue
                    if tok.startswith("+incdir+"):
                        incdirs += [os.path.normpath(os.path.join(base, d)) for d in tok[8:].split("+") if d]
                        continue
                    q = os.path.normpath(os.path.join(base, tok))
                    if os.path.isfile(q):
                        files.append(q)
        elif os.path.isfile(p):
            files.append(os.path.abspath(p))
    inv = {}
    for q in dict.fromkeys(os.path.abspath(f) for f in files):
        kind = EXT.get(os.path.splitext(q)[1].lower())
        if kind:
            inv.setdefault(kind, []).append(q)
    bdt = []
    for q in inv.get("tcl", []):
        with open(q, encoding="utf-8", errors="replace") as f:
            if bdtcl.looks_like_bd(f.read(200000)):
                bdt.append(q)
    if bdt:
        inv["bdtcl"] = bdt
    incdirs += sorted({os.path.dirname(q) for q in inv.get("hdl_inc", [])})
    return inv, incdirs


def find_vivado():
    cands = []
    w = shutil.which("vivado")
    if w:
        cands.append(w)
    env = os.environ.get("XILINX_VIVADO")
    if env:
        cands.append(os.path.join(env, "bin", "vivado"))
    for pat in ("/tools/Xilinx/Vivado/*/bin/vivado", "/tools/Xilinx/*/Vivado/bin/vivado",
                "/opt/Xilinx/Vivado/*/bin/vivado", "/opt/Xilinx/*/Vivado/bin/vivado",
                os.path.expanduser("~/Xilinx/Vivado/*/bin/vivado"), "C:/Xilinx/Vivado/*/bin/vivado.bat",
                "C:/AMDDesignTools/*/Vivado/bin/vivado.bat"):
        cands.extend(sorted(glob.glob(pat), reverse=True))
    for c in cands:
        if os.path.isfile(c):
            m = re.search(r"(20\d\d\.\d)", c)
            return c, (m.group(1) if m else "")
    return None, ""


def read_xpr(path: str) -> dict:
    root = ET.parse(path).getroot()
    pdir = os.path.dirname(os.path.abspath(path))
    name = os.path.splitext(os.path.basename(path))[0]
    subst = {"$PPRDIR": pdir, "$PSRCDIR": os.path.join(pdir, name + ".srcs"),
             "$PGENDIR": os.path.join(pdir, name + ".gen"), "$PIPUSERFILESDIR": os.path.join(pdir, name + ".ip_user_files")}

    def fix(p):
        for k, v in subst.items():
            p = p.replace(k, v)
        return os.path.normpath(p)

    info = {"name": name, "dir": pdir, "srcs": [], "xdc": [], "bd": [], "part": None, "top": None}
    for opt in root.iter("Option"):
        if opt.get("Name") == "Part" and not info["part"]:
            info["part"] = opt.get("Val")
    for fs in root.iter("FileSet"):
        n = fs.get("Name")
        if n not in ("sources_1", "constrs_1"):
            continue
        for f in fs.findall("File"):
            p = fix(f.get("Path", ""))
            low = p.lower()
            if n == "constrs_1" and low.endswith(".xdc"):
                info["xdc"].append(p)
            elif low.endswith(".bd"):
                info["bd"].append(p)
            elif low.endswith((".v", ".sv", ".vhd", ".vhdl")):
                info["srcs"].append(p)
        cfg = fs.find("Config")
        if n == "sources_1" and cfg is not None:
            for opt in cfg.findall("Option"):
                if opt.get("Name") == "TopModule":
                    info["top"] = opt.get("Val")
    return info


def _stem(p):
    return os.path.splitext(os.path.basename(p))[0]


def choose_bd(inv: dict, xp: dict, want: str = ""):
    """Return (kind, main_path, hwh_path) for the best Block Design source."""
    bds = [p for p in (xp.get("bd") if xp else []) if os.path.isfile(p)] or inv.get("bd", [])
    hwhs = inv.get("hwh", [])
    names = [_stem(p) for p in bds] + [_stem(p) for p in hwhs] + [_stem(p) for p in inv.get("xsa", [])]
    if want:
        names = [n for n in names if n == want] or names
    if bds:
        bd = next((p for p in bds if _stem(p) in names[:1]), bds[0])
        h = next((p for p in hwhs if _stem(p) == _stem(bd) and "hw_handoff" in p), None) or \
            next((p for p in hwhs if _stem(p) == _stem(bd)), None)
        return "bd", bd, h
    if hwhs:
        h = next((p for p in hwhs if _stem(p) in names[:1]), hwhs[0])
        return "hwh", h, h
    if inv.get("xsa"):
        return "xsa", inv["xsa"][0], inv["xsa"][0]
    if inv.get("bdtcl"):
        return "bdtcl", inv["bdtcl"][0], None
    return None, None, None


def _part_near(script):
    """Part from a sibling build script (set part "..." / -part ...)."""
    for p in sorted(glob.glob(os.path.join(os.path.dirname(script), "*.tcl"))):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                m = re.search(r'(?:set\s+part\s+"?|-part\s+)(x[a-z]{1,3}\d[\w-]+)', f.read(100000))
        except OSError:
            continue
        if m:
            return m.group(1)
    return None


def bd_prefix(design: dict) -> str:
    return design["meta"].get("bd_path", "")


def build(root: str, out_dir: str, top: str = "", bd: str = "", use_vivado: str = "auto", log=print,
          srcs=None) -> dict:
    root = os.path.abspath(root)

    def rel(p):
        if not p or not os.path.isabs(p):
            return p
        r = os.path.relpath(p, root)
        return r if not r.startswith("../../..") else p

    inv = scan(root)
    incdirs, rundirs = [], []
    if srcs:
        explicit, incdirs = collect_srcs(srcs, root)
        rundirs = [os.path.dirname(os.path.join(root, x)) for x in srcs if x.endswith((".d", ".f", ".lst", ".list"))]
        for k in ("hdl", "hdl_inc", "xdc", "bdtcl", "bd", "hwh", "xsa", "xpr"):
            if k in explicit or k in ("hdl", "xdc"):
                inv[k] = explicit.get(k, [])
        for k in ("nb", "py", "c", "dt", "rpt", "log", "bit"):
            inv[k] = sorted(set(inv.get(k, [])) | set(explicit.get(k, [])))
    xp = read_xpr(inv["xpr"][0]) if inv.get("xpr") else {}
    kind, main, hwh_path = choose_bd(inv, xp, bd)
    vivado, vver = find_vivado()
    design = None
    if kind == "bdtcl" and vivado and use_vivado == "on":  # sourcing Tcl runs project code: explicit opt-in only
        from . import vivado as V
        got = V.export_bd(vivado, main, out_dir, part=xp.get("part") if xp else None,
                          rtl=xp.get("srcs") or inv.get("hdl", []), log=log)
        if got:
            kind, main, hwh_path = "bd", got["bd"], got.get("hwh")
    if kind == "bd":
        design = bdjson.parse(main)
        if hwh_path:
            hwh.merge(design, hwh_path)
    elif kind in ("hwh", "xsa"):
        design = hwh.parse(main)
    elif kind == "bdtcl":
        design = bdtcl.parse(main, search=rundirs + [root])
        if design["meta"].get("incomplete"):
            log("note: %s uses apply_bd_automation; static view is partial%s" % (
                rel(main), " (exact: --vivado on)" if vivado else ""))
        if not design["meta"].get("part"):
            design["meta"]["part"] = _part_near(main)
    rtl_files = [p for p in (xp.get("srcs") or []) if os.path.isfile(p)] or inv.get("hdl", [])
    mods = hdl.parse_files(rtl_files, incdirs)
    if design is None:
        design = M.new_design(top or (xp.get("top") if xp else "") or "rtl")
    ids, roots = hdl.build_defs(design, mods, rel) if mods else ({}, [])
    meta = design["meta"]
    meta.setdefault("part", xp.get("part") if xp else None)
    if xp:
        meta["part"] = meta.get("part") or xp.get("part")
        M.add_source(design, "xpr", inv["xpr"][0])
    if mods:
        M.add_source(design, "rtl", "%d files" % len(rtl_files))
    deep = sorted(glob.glob(os.path.join(out_dir, "deep_*.json")))
    if deep:
        from . import vivado as V
        for dp in deep:
            n = V.merge_deep(design, V.import_netlist(dp))
            M.add_source(design, "vivado-rtl", dp)
            log("merged Vivado netlist %s (%d modules)" % (os.path.basename(dp), n))
    _graft(design, mods)
    _pick_top(design, roots, top or (xp.get("top") if xp else ""))
    for cp in sorted(glob.glob(os.path.join(out_dir, "clocks_*.json"))):
        from . import vivado as V
        n = V.merge_clock_map(design, V.import_clock_map(cp))
        M.add_source(design, "vivado-clocks", cp)
        log("merged Vivado clock map %s (%d instance%s)" % (os.path.basename(cp), n, "" if n == 1 else "s"))
    for s in meta["sources"]:
        s["path"] = rel(s["path"])
    findings = []
    miss = {}
    for f, line, name in hdl.MISSING_INCLUDES:
        miss.setdefault(name, []).append("%s:%d" % (rel(f), line))
    for name, where in miss.items():
        findings.append({"sev": "high", "path": "/", "rule": "include-missing",
                         "title": "`include \"%s\" not found" % name,
                         "detail": "Included by %s. Usually a generated file: the build directory is stale or "
                                   "incomplete, so Vivado will fail to elaborate." % ", ".join(where[:4]),
                         "fix": "Re-run the step that generates it, or add its directory to the include path.",
                         "by": "lint"})
    xdc_files = (xp.get("xdc") if xp else []) or inv.get("xdc", []) + \
        [p for p in inv.get("xdc", []) if p.endswith("board.xdc")]
    findings += _io_check(design, xdc_files, rel)
    # cells constrained ASYNC_REG in XDC, for the synchronizer check in lint
    areg = sorted({c for k, v, cells in xdc.parse(xdc_files)["cell_props"]
                   if k == "ASYNC_REG" and str(v).strip("{}\"").lower() in ("true", "yes", "1") for c in cells})
    if areg:
        design["meta"]["xdc_async_reg"] = areg
    expect_bit = ""
    if xp and xp.get("top"):
        expect_bit = xp["top"] + ".bit"
    elif design["top"].startswith("bd:"):
        expect_bit = design["defs"][design["top"]]["name"] + "_wrapper.bit"  # make_wrapper default top
    ann, rf = refs.scan(design, inv, rel, bitfiles=inv.get("bit", []), hwhfiles=inv.get("hwh", []) +
                        inv.get("xsa", []), expect_bit=expect_bit)
    design["annotations"] = ann
    findings += rf
    facts = reports.summarize(inv.get("rpt", []))
    if facts:
        design["reports"] = {k: {"file": rel(v["file"]), "data": v["data"]} for k, v in facts.items()}
        findings += _report_findings(facts, rel)
    meta["root"] = root  # lint reads RTL sources (ASYNC_REG attributes) relative to it
    findings += lint.run(design)["findings"]
    for i, f in enumerate(findings, 1):
        f["id"] = "L%d" % i
    design["findings"] = findings
    meta["vivado"] = vver or None
    meta["logs"] = _rank_logs(inv.get("log", []), rel)
    meta["inventory"] = {k: len(v) for k, v in inv.items()}
    return design


def _rank_logs(paths, rel, limit=6):
    """Logs with errors first (with counts), so the failing run is the one the agent opens."""
    rows = []
    for p in paths:
        try:
            if os.path.getsize(p) > 20_000_000:
                continue
            with open(p, encoding="utf-8", errors="replace") as f:
                n = sum(1 for ln in f if ln.startswith("ERROR"))
        except OSError:
            continue
        rows.append((-n, "impl" not in p, rel(p), n))
    rows.sort()
    return [r[2] + (" (%d errors)" % r[3] if r[3] else "") for r in rows[:limit]]


def _graft(design, mods):
    defs = design["defs"]
    rtl = {k[4:].lower(): k for k in defs if k.startswith("rtl:")}
    bd_top = design["top"] if design["top"].startswith("bd:") else ""
    for did, d in list(defs.items()):
        if d["kind"] == "modref" and d.get("ref"):
            tgt = rtl.get(d["ref"].lower())
            if tgt:
                d["impl"] = tgt
        elif d["kind"] in ("ip", "hls") and d.get("vlnv") and not d["vlnv"].startswith("xilinx.com:ip"):
            tgt = rtl.get(d["name"].lower())
            if tgt:
                d["impl"] = tgt
    if bd_top:
        bname = defs[bd_top]["name"]
        for d in defs.values():
            for inst in d["insts"]:
                if inst["def"] == "bb:" + bname:
                    inst["def"] = bd_top
        defs.pop("bb:" + bname, None)


def _pick_top(design, roots, want):
    defs = design["defs"]
    bd_top = design["top"] if design["top"].startswith("bd:") else ""
    cand = None
    if want and "rtl:" + want in defs:
        body = defs["rtl:" + want]
        real = [i for i in body["insts"] if defs[i["def"]]["kind"] not in ("prim", "reg", "comb", "latch")]
        if not bd_top or any(i["def"] != bd_top for i in real) or want == design.get("_force_top"):
            cand = "rtl:" + want
    if not cand and not bd_top and roots:
        def size(did, seen=()):
            d = defs[did]
            return 1 + sum(size(i["def"], seen + (did,)) for i in d["insts"] if i["def"] not in seen + (did,))
        roots = sorted(roots, key=lambda r: (not re.search(r"top|wrapper", r, re.I), -size(r)))
        cand = roots[0]
    if cand:
        design["top"] = cand
        if bd_top:
            for path, d, inst in M.walk(design):
                if inst["def"] == bd_top:
                    design["meta"]["bd_path"] = path
                    break
    if not design["top"] and defs:
        design["top"] = next(iter(defs))


def _io_check(design, xdc_files, rel):
    defs = design["defs"]
    top = defs[design["top"]]
    has_ps = any(d["kind"] == "ps" for d in defs.values())
    port_bits = []
    for p in top["pins"]:
        if p["kind"] == "bus":
            if p.get("bus") in ("ddrx", "ddr", "fixedio", "fixed_io") or p["name"] in ("DDR", "FIXED_IO"):
                continue
            for name, left, right in p.get("phys", []):
                port_bits += xdc.bits(name, 0, left, right)
        else:
            if has_ps and p["name"].startswith(("DDR_", "FIXED_IO_")):
                continue
            port_bits += xdc.bits(p["name"], p.get("w") or 1)
    if not port_bits:
        return []
    x = xdc.parse(xdc_files)
    miss = xdc.unconstrained(port_bits, x)
    out = []
    if not xdc_files and miss:
        names = sorted({b.split("[")[0] for b in miss})
        return [{"sev": "high", "path": "/", "rule": "io-unconstrained",
                 "title": "No XDC: %d top-level ports have no pin/IOSTANDARD" % len(names),
                 "detail": ", ".join(names[:12]) + (" …" if len(names) > 12 else "") +
                           ". write_bitstream fails with DRC NSTD-1 / UCIO-1.",
                 "fix": "Add a constraints file (start from the board's master XDC).", "by": "lint"}]
    groups = {}
    for b, props in miss.items():
        groups.setdefault((b.split("[")[0], tuple(props)), []).append(b)
    for (base, props), bs in groups.items():
        out.append({"sev": "high", "path": "/", "port": base, "rule": "io-unconstrained",
                    "title": "%s: no %s" % (", ".join(bs[:6]) + (" …" if len(bs) > 6 else ""), " / ".join(props)),
                    "detail": "write_bitstream fails with DRC NSTD-1 / UCIO-1." +
                              ("" if xdc_files else " No XDC in project."),
                    "fix": "set_property -dict {PACKAGE_PIN <pin> IOSTANDARD <std>} [get_ports {%s}]" % bs[0],
                    "by": "lint"})
    for t in xdc.unknown_targets(port_bits, x)[:10]:
        out.append({"sev": "low", "path": "/", "rule": "xdc-unknown-port",
                    "title": "XDC targets missing port %s" % t, "detail": "Vivado drops it ([Vivado 12-584]).",
                    "by": "lint"})
    out += _clock_check(design, top, x)
    return out


def _clock_check(design, top, x):
    """Input clock ports need create_clock; skip ports that feed AMD IP (it constrains its own inputs)."""
    defs = design["defs"]
    body = M.body(design, top)
    idef = {i["name"]: defs[i["def"]] for i in body["insts"]}

    def feeds_ip(port):
        for n in body["nets"]:
            if ["", port] in n["ends"]:
                return any(i and (idef.get(i, {}).get("vlnv") or "").startswith("xilinx.com:ip:") for i, _ in n["ends"])
        return False

    clocked = set()
    for _, _, pats in x["clocks"]:
        clocked.update(pats)
    out = []
    for p in top["pins"]:
        if p["dir"] not in ("in", "inout"):
            continue
        if p["kind"] == "clk":
            names = [p["name"]]
        elif p["kind"] == "bus" and "clock" in (p.get("bus") or ""):
            names = [n for n, _, _ in p.get("phys", []) if not n.endswith("_n")]  # diff pair: the P side
        else:
            continue
        if not names or feeds_ip(p["name"]):
            continue
        if any(xdc._match(pat, n) for n in names for pat in clocked):
            continue
        out.append({"sev": "med", "path": "/", "port": p["name"], "rule": "clock-unconstrained",
                    "title": "Input clock %s has no create_clock" % names[0],
                    "detail": "Paths it clocks are not timed (check_timing no_clock), so 'timing met' does not cover them.",
                    "fix": "create_clock -period <ns> -name %s [get_ports %s]" % (p["name"], names[0]), "by": "lint"})
    return out


def _report_findings(facts, rel):
    out = []
    t = facts.get("timing", {}).get("data") or {}
    if t.get("wns") is not None and t["wns"] < 0:
        out.append({"sev": "high", "path": "/", "rule": "timing-setup", "title": "Setup timing fails: WNS %.3f ns" % t["wns"],
                    "detail": "%d failing endpoints" % t.get("tns_fail", 0), "by": "lint"})
    if t.get("whs") is not None and t["whs"] < 0:
        out.append({"sev": "high", "path": "/", "rule": "timing-hold", "title": "Hold timing fails: WHS %.3f ns" % t["whs"],
                    "by": "lint"})
    for k, v in (t.get("check_timing") or {}).items():
        if k in ("no_clock", "unconstrained_internal_endpoints", "multiple_clock", "loops", "latch_loops"):
            out.append({"sev": "med", "path": "/", "rule": "check-timing", "title": "check_timing: %s = %d" % (k, v),
                        "by": "lint"})
    c = facts.get("cdc", {}).get("data") or {}
    crit = [r for r in c.get("summary", []) if r["sev"] == "Critical"]
    if crit:
        top = c.get("groups", [])[:3]
        out.append({"sev": "high", "path": "/", "rule": "report-cdc",
                    "title": "report_cdc: %d critical CDC paths (%s)" % (sum(r["n"] for r in crit),
                                                                         ", ".join(r["id"] for r in crit)),
                    "detail": "; ".join("%s→%s %s → %s" % (g["from_clk"], g["to_clk"], g["from"].rsplit("/", 1)[-1],
                                                          g["to"].rsplit("/", 1)[-1]) for g in top),
                    "by": "lint"})
    meth = facts.get("methodology", {}).get("data") or []
    for r in meth:
        if r["id"] in ("TIMING-6", "TIMING-7", "TIMING-9", "TIMING-10", "TIMING-14", "TIMING-16"):
            out.append({"sev": "med", "path": "/", "rule": "methodology", "title": "%s ×%d %s" % (r["id"], r["n"], r["desc"]),
                        "detail": "Clocks are timed as related; any crossing between them needs a synchronizer "
                                  "and set_clock_groups -asynchronous." if r["id"] in ("TIMING-6", "TIMING-7") else "",
                        "by": "lint"})
    return out
