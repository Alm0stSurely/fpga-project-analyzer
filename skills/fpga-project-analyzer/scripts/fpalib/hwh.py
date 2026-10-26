"""Vivado hardware handoff (.hwh, XML; also inside .xsa) -> design model.

The .hwh lists every enabled IP (flat, hierarchy encoded in FULLNAME) with
exact pin directions, clock/reset/interrupt types, frequencies, polarity,
bus interfaces, memory map and register maps. PYNQ loads this file.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile

from . import model as M
from .bdjson import bus_type, ip_kind

NOC = "__NOC__"
_SIGIS = {"clk": "clk", "rst": "rst", "interrupt": "intr", "intr": "intr"}
_MASTER = {"MASTER", "INITIATOR"}
MAX_REGS, MAX_FIELDS, MAX_PARAMS = 64, 24, 40
_SKIP_PARAMS = {"Component_Name", "EDK_IPTYPE", "C_FAMILY", "EDK_SPECIAL", "C_BASEADDR", "C_HIGHADDR"}


def read_root(path: str):
    if path.lower().endswith(".xsa"):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".hwh")]
            if not names:
                raise ValueError("no .hwh inside " + path)
            # the top-level BD handoff is the largest one
            names.sort(key=lambda n: z.getinfo(n).file_size, reverse=True)
            return ET.fromstring(z.read(names[0]))
    return ET.parse(path).getroot()


def _bus_pin(b) -> dict:
    params = {p.get("NAME"): p.get("VALUE") for p in b.findall("PARAMETER")}
    t = (b.get("TYPE") or "").upper()
    w = b.get("DATAWIDTH") or params.get("DATA_WIDTH") or ""
    if not w and (params.get("TDATA_NUM_BYTES") or "").isdigit():
        w = str(8 * int(params["TDATA_NUM_BYTES"]))
    freq = params.get("FREQ_HZ")
    mode = "master" if t in _MASTER else ("monitor" if t == "MONITOR" else "slave")
    return M.pin(b.get("NAME"), "out" if t in _MASTER else "in", "bus",
                 bus=bus_type(b.get("VLNV", "")), mode=mode,
                 w=int(w) if w.isdigit() else None, proto=params.get("PROTOCOL"),
                 freq=int(float(freq)) if freq else None, clkdom=params.get("CLK_DOMAIN"),
                 unc=True if b.get("BUSNAME", NOC) == NOC else None,
                 n=len(b.findall("PORTMAPS/PORTMAP")) or None)


def _port_pin(p) -> dict:
    kind = _SIGIS.get((p.get("SIGIS") or "").lower(), "data")
    pol = (p.get("POLARITY") or "").upper()
    freq = p.get("CLKFREQUENCY")
    connected = bool(p.get("SIGNAME")) and p.get("SIGNAME") != NOC
    return M.pin(p.get("NAME"), M.norm_dir(p.get("DIR")), kind,
                 w=M.width(p.get("LEFT"), p.get("RIGHT")) or None,
                 freq=int(float(freq)) if freq and kind == "clk" else None,
                 pol="low" if "LOW" in pol else ("high" if "HIGH" in pol else None),
                 unc=None if connected else True)


def _members(mod) -> tuple:
    """Physical ports hidden behind *connected* bus interfaces."""
    hidden = set()
    for b in mod.findall("BUSINTERFACES/BUSINTERFACE"):
        if b.get("BUSNAME", NOC) != NOC:
            for pm in b.findall("PORTMAPS/PORTMAP"):
                hidden.add(pm.get("PHYSICAL"))
    return hidden


def _regs(mod) -> list:
    out = []
    for ab in mod.findall("ADDRESSBLOCKS/ADDRESSBLOCK"):
        for r in ab.findall("REGISTERS/REGISTER"):
            props = {p.get("NAME"): p.get("VALUE") for p in r.findall("PROPERTY")}
            if props.get("IS_ENABLED", "true").lower() == "false":
                continue
            reg = {"name": r.get("NAME"), "off": props.get("ADDRESS_OFFSET"), "size": props.get("SIZE"),
                   "acc": props.get("ACCESS"), "desc": (props.get("DESCRIPTION") or "")[:90],
                   "blk": ab.get("NAME"), "intf": ab.get("INTERFACE")}
            fields = []
            for fl in r.findall("FIELDS/FIELD")[:MAX_FIELDS]:
                fp = {p.get("NAME"): p.get("VALUE") for p in fl.findall("PROPERTY")}
                fields.append({"name": fl.get("NAME"), "bit": fp.get("BIT_OFFSET"), "w": fp.get("BIT_WIDTH"),
                               "acc": fp.get("ACCESS")})
            if fields:
                reg["fields"] = fields
            out.append(reg)
            if len(out) >= MAX_REGS:
                return out
    return out


def _params(mod) -> dict:
    out = {}
    for p in mod.findall("PARAMETERS/PARAMETER"):
        n = p.get("NAME")
        if n in _SKIP_PARAMS or n.startswith("C_S_AXI") or n.startswith("EDK"):
            continue
        out[n] = p.get("VALUE")
        if len(out) >= MAX_PARAMS:
            break
    return out


def module_pins(mod) -> list:
    hidden = _members(mod)
    pins = [_bus_pin(b) for b in mod.findall("BUSINTERFACES/BUSINTERFACE")]
    for p in mod.findall("PORTS/PORT"):
        if p.get("NAME") not in hidden:
            pins.append(_port_pin(p))
    return pins


def _addr(root, inst_to_path) -> list:
    out = []
    for mod in root.findall("MODULES/MODULE"):
        for mr in mod.findall("MEMORYMAP/MEMRANGE"):
            out.append({"master": mod.get("FULLNAME"), "space": mr.get("MASTERBUSINTERFACE"),
                        "slave": inst_to_path.get(mr.get("INSTANCE"), "/" + (mr.get("INSTANCE") or "")),
                        "intf": mr.get("SLAVEBUSINTERFACE"), "block": mr.get("ADDRESSBLOCK"),
                        "base": mr.get("BASEVALUE"), "high": mr.get("HIGHVALUE"), "mem": mr.get("MEMTYPE")})
    return out


def _sysinfo(root):
    si = root.find("SYSTEMINFO")
    si = si.attrib if si is not None else {}
    part = "xc" + si.get("DEVICE", "") + si.get("PACKAGE", "") + si.get("SPEEDGRADE", "") if si.get("DEVICE") else None
    return si.get("NAME", "design"), part, root.get("VIVADOVERSION")


def _phys(root, b) -> list:
    """Physical top-level ports of an external interface: [name, left, right]."""
    ports = {p.get("NAME"): p for p in root.findall("EXTERNALPORTS/PORT")}
    out = []
    for pm in b.findall("PORTMAPS/PORTMAP"):
        n = pm.get("PHYSICAL")
        p = ports.get(n)
        out.append([n, p.get("LEFT") if p is not None else None, p.get("RIGHT") if p is not None else None])
    return out


def merge(design: dict, path: str):
    """Enrich a .bd-derived design with exact pin data from the matching .hwh."""
    root = read_root(path)
    defs = design["defs"]
    inst_to_path = {m.get("INSTANCE"): m.get("FULLNAME") for m in root.findall("MODULES/MODULE")}
    for mod in root.findall("MODULES/MODULE"):
        fn = mod.get("FULLNAME")
        d = defs.get("ip:" + fn) or defs.get("hier:" + fn)
        if d is None:
            continue
        _merge_pins(d, module_pins(mod))
        regs = _regs(mod)
        if regs:
            d["regs"] = regs
        if mod.get("MODTYPE") and d.get("kind") in ("ip", "modref", "hls", "ps", "xbar"):
            d["name"] = mod.get("MODTYPE")
    top = defs[design["top"]]
    ext = []
    for b in root.findall("EXTERNALINTERFACES/BUSINTERFACE"):
        bp = _bus_pin(b)
        bp["phys"] = _phys(root, b)
        ext.append(bp)
    hidden = {x[0] for bp in ext for x in bp["phys"]}
    for p in root.findall("EXTERNALPORTS/PORT"):
        if p.get("NAME") not in hidden:
            ext.append(_port_pin(p))
    _merge_pins(top, ext, boundary=True)
    if not top.get("addr"):
        top["addr"] = _addr(root, inst_to_path)
    name, part, tool = _sysinfo(root)
    design["meta"].setdefault("part", part)
    design["meta"]["tool"] = design["meta"].get("tool") or tool
    M.add_source(design, "hwh", path)


def _merge_pins(d: dict, exact: list, boundary: bool = False):
    have = {p["name"].lower(): p for p in d["pins"]}
    for e in exact:
        cur = have.get(e["name"].lower())
        if cur is None:
            d["pins"].append(e)
            continue
        cur.pop("inferred", None)
        for k, v in e.items():
            if k == "name" or (boundary and k in ("dir", "mode")):
                continue
            if k == "unc" and not boundary:
                cur[k] = v
            elif v is not None:
                cur[k] = v
        if not e.get("unc"):
            cur.pop("unc", None)


def parse(path: str) -> dict:
    """Standalone .hwh -> design (no .bd): rebuild hierarchy from FULLNAME."""
    root = read_root(path)
    name, part, tool = _sysinfo(root)
    design = M.new_design(name)
    design["meta"].update({"part": part, "tool": tool})
    defs = design["defs"]
    top_id = "bd:" + name
    design["top"] = top_id
    top = M.new_def(name, "bd")
    defs[top_id] = top
    hier = {"": top}

    def ensure_hier(parts):
        key = "/".join(parts)
        if key in hier:
            return hier[key]
        parent = ensure_hier(parts[:-1])
        hid = "hier:/" + key
        h = M.new_def(parts[-1], "hier")
        defs[hid] = h
        parent["insts"].append({"name": parts[-1], "def": hid})
        hier[key] = h
        return h

    inst_to_path = {}
    sig_ends, bus_ends = {}, {}
    for mod in root.findall("MODULES/MODULE"):
        fn = mod.get("FULLNAME")
        parts = [p for p in fn.split("/") if p]
        inst_to_path[mod.get("INSTANCE")] = fn
        parent = ensure_hier(parts[:-1])
        did = "ip:" + fn
        d = M.new_def(mod.get("MODTYPE") or parts[-1], ip_kind(mod.get("VLNV", "")), vlnv=mod.get("VLNV"))
        d["pins"] = module_pins(mod)
        regs = _regs(mod)
        if regs:
            d["regs"] = regs
        if ip_kind(mod.get("VLNV", "")) == "modref":
            d["ref"] = mod.get("MODTYPE")
        defs[did] = d
        inst = {"name": parts[-1], "def": did}
        params = _params(mod)
        if params:
            inst["params"] = params
        parent["insts"].append(inst)
        hidden = _members(mod)
        for b in mod.findall("BUSINTERFACES/BUSINTERFACE"):
            if b.get("BUSNAME", NOC) != NOC:
                bus_ends.setdefault(b.get("BUSNAME"), []).append((parts, b.get("NAME")))
        for p in mod.findall("PORTS/PORT"):
            sn = p.get("SIGNAME")
            if sn and sn != NOC and p.get("NAME") not in hidden:
                sig_ends.setdefault(sn, []).append((parts, p.get("NAME")))
    ext_hidden = set()
    for b in root.findall("EXTERNALINTERFACES/BUSINTERFACE"):
        bp = _bus_pin(b)
        bp["phys"] = _phys(root, b)
        ext_hidden.update(x[0] for x in bp["phys"])
        top["pins"].append(bp)
        bus_ends.setdefault(b.get("BUSNAME"), []).append(([], b.get("NAME")))
    for p in root.findall("EXTERNALPORTS/PORT"):
        if p.get("NAME") in ext_hidden:
            continue
        top["pins"].append(_port_pin(p))
        sn = p.get("SIGNAME")
        if sn and sn != NOC:
            sig_ends.setdefault(sn, []).append(([], p.get("NAME")))
    for kind, table in (("bus", bus_ends), ("", sig_ends)):
        for net, ends in table.items():
            _place_net(design, hier, net, kind, ends, defs)
    from .bdjson import complete_pins
    complete_pins(design)
    top["addr"] = _addr(root, inst_to_path)
    M.add_source(design, "hwh", path)
    return design


def _place_net(design, hier, net, kind, ends, defs):
    """Put a flat net into its lowest common hierarchy, adding boundary pins."""
    owners = [e[0][:-1] if e[0] else [] for e in ends]
    lca = owners[0]
    for o in owners[1:]:
        n = 0
        while n < min(len(lca), len(o)) and lca[n] == o[n]:
            n += 1
        lca = lca[:n]
    _route(design, hier, lca, net, kind, ends, defs)


def _pin_of(defs, hier, parts, pname):
    if not parts:
        return M.pin_index(hier[""]).get(pname)
    parent = hier["/".join(parts[:-1])]
    inst = M.find_inst(parent, parts[-1])
    return M.pin_index(defs[inst["def"]]).get(pname) if inst else None


def _route(design, hier, level, net, kind, ends, defs, boundary=None):
    here = hier["/".join(level)]
    local = [["", boundary]] if boundary else []
    deeper = {}
    for parts, pname in ends:
        if not parts:
            local.append(["", pname])
        elif len(parts) == len(level) + 1:
            local.append([parts[-1], pname])
        else:
            deeper.setdefault(parts[len(level)], []).append((parts, pname))
    for child, sub in deeper.items():
        hd = hier["/".join(level + [child])]
        bname = sub[0][1] if sub[0][1] not in M.pin_index(hd) else net
        if bname not in M.pin_index(hd):
            src = _pin_of(defs, hier, sub[0][0], sub[0][1]) or {}
            bp = {k: v for k, v in src.items() if k not in ("unc", "phys", "n")}
            bp["name"] = bname
            hd["pins"].append(bp)
        local.append([child, bname])
        _route(design, hier, level + [child], net, kind, sub, defs, boundary=bname)
    if len(local) > 1:
        here["nets"].append({"name": net, "kind": kind, "ends": local})
