"""Vivado Block Design (.bd, JSON) -> design model.

The .bd holds hierarchy, connectivity, non-default IP parameters and the
address map, but lists only some IP pins; directions of the rest are inferred
here and replaced by exact data when a .hwh is merged (see hwh.merge).
"""
from __future__ import annotations

import json

from . import model as M

PS_TYPES = {"processing_system7", "zynq_ultra_ps_e", "versal_cips", "ps_wizard"}
XBAR_TYPES = {"axi_interconnect", "smartconnect", "axi_noc", "axi_crossbar"}


def bus_type(vlnv: str) -> str:
    parts = (vlnv or "").split(":")
    t = parts[2] if len(parts) > 2 else (vlnv or "")
    return t[:-4] if t.endswith("_rtl") else t


def ip_kind(vlnv: str) -> str:
    parts = (vlnv or "").split(":")
    lib, name = (parts[1], parts[2]) if len(parts) > 2 else ("", "")
    if name in PS_TYPES:
        return "ps"
    if name in XBAR_TYPES:
        return "xbar"
    if lib == "module_ref":
        return "modref"
    if lib == "hls":
        return "hls"
    return "ip"


def _intf_pin(name: str, spec: dict) -> dict:
    mode = (spec.get("mode") or "").lower()
    params = {k: v.get("value") for k, v in (spec.get("parameters") or {}).items() if isinstance(v, dict)}
    w = 0
    if params.get("DATA_WIDTH", "").isdigit():
        w = int(params["DATA_WIDTH"])
    elif params.get("TDATA_NUM_BYTES", "").isdigit():
        w = 8 * int(params["TDATA_NUM_BYTES"])
    freq = params.get("FREQ_HZ")
    return M.pin(name, "out" if mode.startswith("master") else "in", "bus",
                 bus=bus_type(spec.get("vlnv", "")), mode=mode or None, w=w or None,
                 proto=params.get("PROTOCOL"), freq=int(float(freq)) if freq else None,
                 clkdom=params.get("CLK_DOMAIN"))


def _sig_pin(name: str, spec: dict) -> dict:
    t = (spec.get("type") or "").lower()
    kind = {"clk": "clk", "rst": "rst", "intr": "intr"}.get(t, "")
    params = {k: v.get("value") for k, v in (spec.get("parameters") or {}).items() if isinstance(v, dict)}
    freq = params.get("FREQ_HZ")
    pol = params.get("POLARITY", "")
    return M.pin(name, M.norm_dir(spec.get("direction")), kind,
                 w=M.width(spec.get("left"), spec.get("right")) or None,
                 freq=int(float(freq)) if freq and kind == "clk" else None,
                 pol="low" if "LOW" in pol.upper() else ("high" if pol else None))


def _ends(items):
    out = []
    for s in items:
        inst, _, p = s.rpartition("/")
        out.append([inst, p])
    return out


def _level(design: dict, comp: dict, prefix: str, def_id: str, name: str, kind: str, vlnv: str = ""):
    d = M.new_def(name, kind, vlnv=vlnv or None)
    for n, spec in (comp.get("interface_ports") or {}).items():
        d["pins"].append(_intf_pin(n, spec))
    for n, spec in (comp.get("ports") or {}).items():
        d["pins"].append(_sig_pin(n, spec))
    design["defs"][def_id] = d
    for cname, c in (comp.get("components") or {}).items():
        path = prefix + "/" + cname
        cvlnv = c.get("vlnv", "")
        if "components" in c or not cvlnv:
            cid = "hier:" + path
            _level(design, c, path, cid, cname if not cvlnv else bus_type(cvlnv),
                   "xbar" if cvlnv else "hier", cvlnv)
        else:
            cid = "ip:" + path
            cd = M.new_def(bus_type(cvlnv) or cname, ip_kind(cvlnv), vlnv=cvlnv or None)
            ref = (c.get("reference_info") or {}).get("ref_name")
            if ref:
                cd["ref"] = ref
            for n, spec in (c.get("interface_ports") or {}).items():
                cd["pins"].append(_intf_pin(n, spec))
            for n, spec in (c.get("ports") or {}).items():
                cd["pins"].append(_sig_pin(n, spec))
            design["defs"][cid] = cd
        params = {k: v.get("value") for k, v in (c.get("parameters") or {}).items() if isinstance(v, dict)}
        inst = {"name": cname, "def": cid}
        if params:
            inst["params"] = params
        d["insts"].append(inst)
    for n, spec in (comp.get("interface_nets") or {}).items():
        d["nets"].append({"name": n, "kind": "bus", "ends": _ends(spec.get("interface_ports", []))})
    for n, spec in (comp.get("nets") or {}).items():
        d["nets"].append({"name": n, "kind": "", "ends": _ends(spec.get("ports", []))})
    return d


def complete_pins(design: dict):
    """Create pins referenced by nets but absent from defs; infer dirs from peers."""
    defs = design["defs"]
    for d in defs.values():
        insts = {i["name"]: defs[i["def"]] for i in d["insts"]}
        for net in d["nets"]:
            for inst, p in net["ends"]:
                target = d if inst == "" else insts.get(inst)
                if target is None or p in M.pin_index(target):
                    continue
                if net["kind"] == "bus":
                    up = p.upper()
                    master = up.startswith("M") and (up[1:2] in "_0123456789" or up.startswith("M_AXI"))
                    np_ = M.pin(p, "out" if master else "in", "bus", mode="master" if master else "slave",
                                inferred=True)
                else:
                    np_ = M.pin(p, M.guess_dir(p), inferred=True)
                target["pins"].append(np_)
    for d in defs.values():
        insts = {i["name"]: defs[i["def"]] for i in d["insts"]}
        for net in d["nets"]:
            pins = []
            for inst, p in net["ends"]:
                target = d if inst == "" else insts.get(inst)
                pp = M.pin_index(target).get(p) if target else None
                if pp:
                    pins.append((inst, pp))
            known_out = [x for x in pins if not x[1].get("inferred") and _drives(x)]
            unknown = [x for x in pins if x[1].get("inferred")]
            if known_out:
                for inst, pp in unknown:
                    _set_sink(inst, pp)
            elif len(unknown) == 1 and len(pins) > 1:
                _set_driver(*unknown[0])
            if not net["kind"]:
                kinds = {pp["kind"] for _, pp in pins if pp["kind"] != "data"}
                net["kind"] = kinds.pop() if len(kinds) == 1 else "data"


def _drives(x):
    inst, pp = x
    out = pp["dir"] == "out"
    return out if inst else not out  # a boundary input drives the inside


def _set_sink(inst, pp):
    if inst:
        pp["dir"] = "in"
        if pp["kind"] == "bus":
            pp["mode"] = "slave"
    else:
        pp["dir"] = "out"
        if pp["kind"] == "bus":
            pp["mode"] = "master"


def _set_driver(inst, pp):
    if inst:
        pp["dir"] = "out"
        if pp["kind"] == "bus":
            pp["mode"] = "master"
    else:
        pp["dir"] = "in"
        if pp["kind"] == "bus":
            pp["mode"] = "slave"


def addressing(des: dict) -> list:
    out = []
    for master, m in (des.get("addressing") or {}).items():
        for space, s in (m.get("address_spaces") or {}).items():
            for seg in (s.get("segments") or {}).values():
                blk = seg.get("address_block", "")
                parts = blk.rsplit("/", 2)
                if len(parts) < 3:
                    continue
                out.append({"master": master, "space": space, "slave": parts[0], "intf": parts[1],
                            "block": parts[2], "base": seg.get("offset", ""), "range": seg.get("range", "")})
            for seg in (s.get("excluded_segments") or {}).values():
                blk = seg.get("address_block", "")
                parts = blk.rsplit("/", 2)
                if len(parts) == 3:
                    out.append({"master": master, "space": space, "slave": parts[0], "intf": parts[1],
                                "block": parts[2], "base": seg.get("offset", ""), "range": seg.get("range", ""),
                                "excluded": True})
    return out


def parse(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        des = json.load(f)["design"]
    info = des.get("design_info", {})
    name = info.get("name", "design")
    design = M.new_design(name)
    design["meta"].update({"part": info.get("device"), "tool": info.get("tool_version")})
    top = "bd:" + name
    design["top"] = top
    d = _level(design, des, "", top, name, "bd")
    d["addr"] = addressing(des)
    complete_pins(design)
    M.add_source(design, "bd", path)
    return design
