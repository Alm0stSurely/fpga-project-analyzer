"""Optional Vivado batch helpers: exact BD export, elaborated RTL netlist, reports."""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

from . import model as M

TCL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vivado")
_BIT = re.compile(r"\[\d+\]$")
_REG = re.compile(r"^(RTL_REG\w*|FD[CPRS]E|RTL_LATCH\w*|LD\w*)$")
_RST_PIN = {"CLR", "PRE", "RST", "R", "S", "SET", "CLEAR", "RESET"}
OPS = {"RTL_ADD": "+", "RTL_SUB": "−", "RTL_MULT": "×", "RTL_EQ": "=", "RTL_NEQ": "≠", "RTL_INV": "~", "RTL_AND": "&",
       "RTL_OR": "|", "RTL_XOR": "^", "RTL_LT": "<", "RTL_GT": ">", "RTL_LEQ": "≤", "RTL_GEQ": "≥",
       "RTL_LSHIFT": "<<", "RTL_RSHIFT": ">>", "RTL_MUX": "MUX", "RTL_REDUCTION_OR": "|r", "RTL_REDUCTION_AND": "&r",
       "RTL_REDUCTION_XOR": "^r", "RTL_ROM": "ROM", "RTL_RAM": "RAM", "RTL_BMERGE": "{}", "RTL_BSEL": "[ ]"}


def run(vivado: str, script: str, args: list, cwd: str, log=print, timeout=3600) -> str:
    os.makedirs(cwd, exist_ok=True)
    cmd = [vivado, "-mode", "batch", "-nolog", "-nojournal", "-notrace", "-source", os.path.join(TCL, script),
           "-tclargs"] + [str(a) for a in args]
    log("vivado: %s %s" % (script, " ".join(os.path.basename(str(a)) for a in args)))
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    with open(os.path.join(cwd, script.replace(".tcl", ".log")), "w") as f:
        f.write(p.stdout)
    for ln in p.stdout.splitlines():
        if ln.startswith(("FPA_ERROR", "FPA_WARN", "ERROR:")):
            log(ln[:300])
    return p.stdout


def export_bd(vivado, src, out_dir, part=None, rtl=(), log=print):
    vdir = os.path.join(out_dir, "vivado")
    os.makedirs(vdir, exist_ok=True)
    lst = os.path.join(vdir, "rtl.lst")
    with open(lst, "w") as f:
        f.write("\n".join(os.path.abspath(p) for p in rtl))
    if not part and not src.endswith(".xpr"):
        with open(src, encoding="utf-8", errors="replace") as f:
            m = re.search(r"-part\s+(\S+)", f.read())
        part = m.group(1) if m else "xc7z020clg400-1"
    out = run(vivado, "export_bd.tcl", [os.path.abspath(src), vdir, part or "", lst], vdir, log)
    bd = re.findall(r"^FPA_BD=(.+)$", out, re.M)
    hw = re.findall(r"^FPA_HWH=(.+)$", out, re.M)
    if not bd:
        return None
    return {"bd": bd[0].strip(), "hwh": hw[0].strip() if hw else None}


def _base(n):
    return _BIT.sub("", n)


def import_netlist(path: str, prefix: str = "vh") -> dict:
    """Vivado RTL netlist JSON -> {defs, top}. Bit-sliced cells and nets become buses."""
    with open(path, encoding="utf-8") as f:
        nl = json.load(f)
    top = nl["top"]
    defs = {}
    groups = {}  # (scope, base) -> list of cells
    for c in nl["cells"]:
        if c["ref"] in ("GND", "VCC"):
            continue
        scope, _, local = c["n"].rpartition("/")
        groups.setdefault((scope, _base(local) if c["prim"] else local), []).append(c)
    scopes = {"": {"ref": top, "pins": {}}}
    for (scope, local), cells in groups.items():
        if not cells[0]["prim"]:
            full = (scope + "/" if scope else "") + local
            scopes[full] = {"ref": cells[0]["ref"], "pins": {}}
    bodies = {s: {"insts": [], "nets": {}} for s in scopes}

    def net_scope(n):
        s, _, local = n.rpartition("/")
        return s, _base(local)

    def touch(scope, net, end):
        if not net or "<const" in net:
            return
        s, local = net_scope(net)
        if s in bodies:
            ends = bodies[s]["nets"].setdefault(local, [])
            if end not in ends:
                ends.append(end)

    for p in nl["ports"]:
        name, d, net = p
        pins = scopes[""]["pins"]
        b = _base(name)
        pins.setdefault(b, {"name": b, "dir": M.norm_dir(d), "w": 0})["w"] += 1
        touch("", net, ["", b])
    for (scope, local), cells in groups.items():
        c0 = cells[0]
        if scope not in bodies:
            continue
        pins = {}
        for c in cells:
            for pn, d, up, lo in c["pins"]:
                b = _base(pn)
                pp = pins.setdefault(b, {"name": b, "dir": M.norm_dir(d), "w": 0, "_nets": set()})
                pp["_nets"].add(up or pn)
                pp["w"] = len(pp["_nets"])  # shared controls (clock, CE) stay 1 bit
                touch(scope, up, [local, b])
                if lo:
                    full = (scope + "/" if scope else "") + local
                    touch(full, lo, ["", b])
        ref = c0["ref"]
        if c0["prim"]:
            short = re.sub(r"__\w+$", "", ref)
            kind = "reg" if _REG.match(short) else "prim"
            did = "vp:%s/%s" % (scope, local)
            plist = []
            for b, pp in pins.items():
                k = "data"
                if kind == "reg" and b in ("C", "CLK", "G"):
                    k = "clk"
                elif kind == "reg" and (b.upper() in ("CLR", "PRE") or ("ASYNC" in short and b.upper() in _RST_PIN)):
                    k = "rst"  # only asynchronous controls; sync set/reset pins are data paths
                plist.append(M.pin(b, pp["dir"], k, w=pp["w"] if pp["w"] > 1 else None))
            d = M.new_def(short, kind, op=OPS.get(short))
            d["pins"] = plist
            if kind == "reg":
                d["nregs"] = len(cells)
            defs[did] = d
            label = local + ("[%d:0]" % (len(cells) - 1) if len(cells) > 1 else "")
        else:
            did = "%s:%s" % (prefix, ref)
            label = local
            full = (scope + "/" if scope else "") + local
            scopes[full]["pins"] = pins
        bodies[scope]["insts"].append({"name": label, "def": did, "_local": local})
    for s, info in scopes.items():
        did = "%s:%s" % (prefix, info["ref"])
        if did in defs:
            continue
        d = M.new_def(re.sub(r"__parameterized\d+$", "", info["ref"]), "rtl")
        d["pins"] = [M.pin(p["name"], p["dir"], w=p["w"] if p["w"] > 1 else None) for p in info["pins"].values()]
        rename = {i["_local"]: i["name"] for i in bodies[s]["insts"]}
        d["insts"] = [{"name": i["name"], "def": i["def"]} for i in bodies[s]["insts"]]
        merged = {}
        for n, ends in bodies[s]["nets"].items():
            ends = [[rename.get(e[0], e[0]) if e[0] else "", e[1]] for e in ends]
            if len(ends) < 2:
                continue
            key = frozenset(tuple(e) for e in ends)
            if key in merged:  # bit nets named x_n_0, x_n_1 ... between the same pins
                merged[key]["w"] = merged[key].get("w", 1) + 1
                merged[key]["name"] = re.sub(r"_\d+$", "", merged[key]["name"])
            else:
                merged[key] = {"name": n, "kind": "", "ends": ends}
        d["nets"] = list(merged.values())
        defs[did] = d
    _kinds(defs)
    return {"defs": defs, "top": "%s:%s" % (prefix, top), "truncated": nl.get("truncated")}


def _kinds(defs):
    for d in defs.values():
        idx = {i["name"]: defs.get(i["def"]) for i in d["insts"]}
        clocks = set()
        for n in d["nets"]:
            ks = set()
            for inst, p in n["ends"]:
                t = idx.get(inst) if inst else None
                pp = M.pin_index(t).get(p) if t else None
                if pp and pp["kind"] != "data":
                    ks.add(pp["kind"])
            n["kind"] = "clk" if "clk" in ks else (ks.pop() if len(ks) == 1 else "data")
            if n["kind"] == "clk":
                clocks.update(p for i, p in n["ends"] if i == "")
        for p in d["pins"]:
            if p["name"] in clocks:
                p["kind"] = "clk"


def merge_deep(design: dict, deep: dict):
    """Replace light RTL bodies with Vivado-elaborated ones where module names match."""
    defs = design["defs"]
    for did, d in deep["defs"].items():
        defs.setdefault(did, d)
    by_name = {}
    for did, d in deep["defs"].items():
        if did.startswith("vh:"):
            by_name.setdefault(d["name"].lower(), did)
    n = 0
    for did, d in list(defs.items()):
        if did.startswith("rtl:"):
            v = by_name.get(d["name"].lower())
            if v:
                vd = defs[v]
                d["insts"], d["nets"] = vd["insts"], vd["nets"]
                have = M.pin_index(d)
                for p in vd["pins"]:
                    if p["name"] in have:
                        have[p["name"]]["kind"] = p["kind"] if p["kind"] == "clk" else have[p["name"]]["kind"]
                    else:
                        d["pins"].append(p)
                d["deep"] = True
                n += 1
    return n


def deep(root, top, depth=8, max_cells=20000, log=print):
    from .build import find_vivado, read_xpr, scan
    vivado, _ = find_vivado()
    if not vivado:
        sys.exit("Vivado not found (PATH, XILINX_VIVADO, /tools/Xilinx)")
    inv = scan(root)
    out = os.path.join(root, ".fpa")
    vdir = os.path.join(out, "vivado")
    os.makedirs(vdir, exist_ok=True)
    xp = read_xpr(inv["xpr"][0]) if inv.get("xpr") else {}
    files = [p for p in xp.get("srcs", []) if os.path.isfile(p)] or inv.get("hdl", [])
    lst = os.path.join(vdir, "rtl_files.lst")
    with open(lst, "w") as f:
        f.write("\n".join(os.path.abspath(p) for p in files))
    part = xp.get("part") or "xc7z020clg400-1"
    js = os.path.join(out, "deep_%s.json" % top)
    run(vivado, "rtl_netlist.tcl", [lst, top, part, js, max_cells], vdir, log)
    if not os.path.isfile(js):
        sys.exit("netlist export failed; see %s" % os.path.join(vdir, "rtl_netlist.log"))
    nl = import_netlist(js)
    log("netlist: %d defs%s -> %s (merged on next build)" % (len(nl["defs"]), " (truncated)" if nl["truncated"] else "",
                                                             os.path.relpath(js)))


def reports(target, root, run_name="impl_1", log=print):
    from .build import find_vivado
    from . import reports as R
    vivado, _ = find_vivado()
    if not vivado:
        sys.exit("Vivado not found")
    out = os.path.join(root, ".fpa", "reports")
    run(vivado, "reports.tcl", [os.path.abspath(target), out, run_name], os.path.join(root, ".fpa", "vivado"), log)
    facts = R.summarize(glob.glob(os.path.join(out, "*.rpt")))
    print(R.format_facts(facts, lambda p: os.path.relpath(p, root)))


def import_clock_map(path: str) -> dict:
    """clocks_<top>.json -> {"top", "regs": {cell path without bit index: (root net, driver pin)}}."""
    with open(path, encoding="utf-8") as f:
        cm = json.load(f)
    regs = {}
    for cell, root, drv in cm["regs"]:
        regs.setdefault(_BIT.sub("", cell), (root, drv))
    return {"top": cm["top"], "regs": regs}


def merge_clock_map(design: dict, cm: dict) -> int:
    """Attach a Vivado clock map to every instance of its top module."""
    prefixes = [p for p, d, _ in M.walk(design) if M.body(design, d).get("name") == cm["top"]
                and M.body(design, d)["kind"] == "rtl"]
    if design["defs"][design["top"]]["name"] == cm["top"]:
        prefixes.append("")
    if prefixes:
        design.setdefault("clockmaps", []).append({"top": cm["top"], "prefixes": prefixes, "regs": cm["regs"]})
    return len(prefixes)
