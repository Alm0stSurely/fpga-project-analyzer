"""Structural checks and clock-domain analysis over the design model.

Clock nets are traced to their true source (through hierarchy, module
references and clock buffers). Data drivers carry {domain: origin} sets that
propagate through logic and into submodules; a register sampling a domain
other than its own clock is a crossing unless it is a 1-bit two-flop chain.
Results are candidate findings ("by": "lint") plus per-net domains the viewer
uses to colour wires.
"""
from __future__ import annotations

import re

from . import model as M

CLK_BUF = re.compile(r"^(BUFG\w*|BUFH\w*|BUFR|BUFIO|BUFGCTRL|IBUFG\w*|util_ds_buf)$", re.I)
CLK_GEN = re.compile(r"^(MMCM\w+|PLLE\d\w*|clk_wiz|DCM\w*|processing_system7|zynq_ultra_ps_e|versal_cips)$", re.I)
CDC_SAFE = re.compile(r"^(axis_clock_converter|axi_clock_converter|fifo_generator|axis_data_fifo|xpm_cdc_\w+|"
                      r"xpm_fifo_async|axi_interconnect|smartconnect|axi_crossbar|proc_sys_reset|util_ds_buf|"
                      r"axis_interconnect|axi_dwidth_converter|axi_protocol_converter)$", re.I)
SYNCED_INPUTS = re.compile(r"^(gpio\d?_io_i|ext_reset_in|aux_reset_in|dcm_locked|mb_debug_sys_rst|IRQ_F2P|"
                           r"pl_ps_irq\d+|In\d+)$")
MAX_DEPTH = 40


class _Ends(dict):
    """(inst, pin) -> nets; a bus pin can be split across several nets."""

    def get(self, key, default=None):
        v = dict.get(self, key)
        return v[0] if v else default

    def all(self, key):
        return dict.get(self, key, [])


class _Ctx:
    def __init__(self, design):
        self.design = design
        self.defs = design["defs"]
        self.parents = {}          # path -> (parent_path, inst_name)
        self.bodies = {"": M.body(design, self.defs[design["top"]])}
        self.inst_def = {}
        for path, d, inst in M.walk(design):
            pp, _, name = path.rpartition("/")
            self.parents[path] = (pp, name)
            self.bodies[path] = M.body(design, d)
            self.inst_def[path] = d
        self.domains = {}
        self.clk_memo = {}
        self.eval_memo = {}
        self.crossings = []
        self.netdom = {}           # "path|net" -> [domain ids]
        self._nets = {}

    def nets_of(self, path):
        if path not in self._nets:
            body = self.bodies[path]
            by_name = {n["name"]: n for n in body["nets"]}
            by_end = _Ends()
            for n in body["nets"]:
                for inst, p in n["ends"]:
                    by_end.setdefault((inst, p), []).append(n["name"])
            self._nets[path] = (by_name, by_end)
        return self._nets[path]

    def child(self, path, inst):
        return path + "/" + inst

    def leaf(self, path):
        b = self.bodies.get(path)
        return b is None or not b["insts"]

    def dom(self, did, freq=None, gen=None):
        if did not in self.domains:
            parts = [p for p in did.replace("port:", "").split("/") if p]
            name = parts[-1] if parts else did
            if len(parts) >= 2 and gen:
                name = parts[-1]
            self.domains[did] = {"name": name, "src": did}
            if freq:
                self.domains[did]["freq"] = freq
            if gen:
                self.domains[did]["group"] = gen
        elif freq and "freq" not in self.domains[did]:
            self.domains[did]["freq"] = freq
        return did


def resolve_clock(cx: _Ctx, path: str, net: str, depth: int = 0):
    key = (path, net)
    if key in cx.clk_memo:
        return cx.clk_memo[key]
    cx.clk_memo[key] = None
    if depth > MAX_DEPTH:
        return None
    by_name, by_end = cx.nets_of(path)
    n = by_name.get(net)
    if n is None:
        return None
    body = cx.bodies[path]
    res = None
    for inst, pin in n["ends"]:
        if inst == "":
            continue
        cpath = cx.child(path, inst)
        idef = cx.inst_def.get(cpath)
        pp = M.pin_index(idef).get(pin) if idef else None
        if not pp or pp["dir"] != "out":
            continue
        if not cx.leaf(cpath):
            inner = cx.nets_of(cpath)[1].get(("", pin))
            if inner:
                res = resolve_clock(cx, cpath, inner, depth + 1)
                if res:
                    break
        if CLK_BUF.match(idef["name"]):
            for q in idef["pins"]:
                if q["dir"] == "in" and q["name"].upper().startswith("I"):
                    upnet = by_end.get((inst, q["name"]))
                    if upnet:
                        res = resolve_clock(cx, path, upnet, depth + 1)
                        break
            if res:
                break
        gen = cpath if CLK_GEN.match(idef["name"]) else None
        res = cx.dom(cpath + "/" + pin, pp.get("freq"), gen)
        break
    if res is None:
        for inst, pin in n["ends"]:
            if inst != "":
                continue
            if path == "":
                bp = M.pin_index(body).get(pin, {})
                if bp.get("dir") in ("in", "inout"):
                    res = cx.dom("port:/" + pin, bp.get("freq"))
                    break
            else:
                ppath, iname = cx.parents[path]
                upnet = cx.nets_of(ppath)[1].get((iname, pin))
                if upnet:
                    res = resolve_clock(cx, ppath, upnet, depth + 1)
                    if res:
                        break
    cx.clk_memo[key] = res
    return res


def _related(cx, a, b):
    ga = cx.domains.get(a, {}).get("group")
    gb = cx.domains.get(b, {}).get("group")
    return ga is not None and ga == gb and not ga.endswith(("processing_system7_0",)) and "ps" not in ga


def _leaf_domains(cx, path, idef):
    by_end = cx.nets_of(cx.parents[path][0])[1]
    iname = cx.parents[path][1]
    doms = set()
    for q in idef["pins"]:
        if q["kind"] == "clk" and q["dir"] == "in" and not q.get("unc"):
            n = by_end.get((iname, q["name"]))
            d = resolve_clock(cx, cx.parents[path][0], n) if n else None
            if d:
                doms.add(d)
    return doms


def evaluate(cx: _Ctx, path: str, ctx: dict, depth: int = 0) -> dict:
    """Propagate {domain: origin} driver sets through one level; return outputs."""
    key = (path, tuple(sorted((k, tuple(sorted(v.items()))) for k, v in ctx.items())))
    if key in cx.eval_memo:
        return cx.eval_memo[key]
    cx.eval_memo[key] = {}
    if depth > MAX_DEPTH:
        return {}
    body = cx.bodies[path]
    by_name, by_end = cx.nets_of(path)
    defs = cx.defs
    drivers = {n["name"]: {} for n in body["nets"] if n["kind"] not in ("bus", "intr", "clk")}
    bpins = M.pin_index(body)
    for n in body["nets"]:
        if n["name"] not in drivers:
            continue
        for inst, p in n["ends"]:
            if inst == "" and bpins.get(p, {}).get("dir") in ("in", "inout"):
                drivers[n["name"]].update(ctx.get(p, {}))
    regs, combs, children, leaves = [], [], [], []
    for inst in body["insts"]:
        idef = defs[inst["def"]]
        cpath = cx.child(path, inst["name"])
        if idef["kind"] == "reg":
            clk = next((q for q in idef["pins"] if q["kind"] == "clk"), None)
            cn = by_end.get((inst["name"], clk["name"])) if clk else None
            d = resolve_clock(cx, path, cn) if cn else None
            regs.append((inst, idef, d))
            if d:
                cx.netdom[path + "|" + cn] = [d]
        elif idef["kind"] in ("comb", "latch"):
            combs.append((inst, idef))
        elif not cx.leaf(cpath):
            children.append((inst, idef, cpath))
        else:
            leaves.append((inst, idef, cpath))
    leaf_info = []
    for inst, idef, cpath in leaves:
        if idef["kind"] == "bb" or CDC_SAFE.match(idef["name"]) or idef.get("cdc"):
            leaf_info.append((inst, idef, cpath, "opaque", None))
            continue
        doms = _leaf_domains(cx, cpath, idef)
        has_clk = any(q["kind"] == "clk" and q["dir"] == "in" for q in idef["pins"])
        if not has_clk:
            leaf_info.append((inst, idef, cpath, "comb", None))
        elif len(doms) == 1:
            leaf_info.append((inst, idef, cpath, "seq", next(iter(doms))))
        else:
            leaf_info.append((inst, idef, cpath, "opaque", None))
    def nets(inst, pin):
        return [n for n in by_end.all((inst["name"], pin)) if n in drivers]

    for inst, idef, d in regs:
        if not d:
            continue
        for q in idef["pins"]:
            if q["dir"] == "out":
                for n in nets(inst, q["name"]):
                    drivers[n][d] = path + "/" + inst["name"]
    for inst, idef, cpath, mode, d in leaf_info:
        if mode != "seq":
            continue
        for q in idef["pins"]:
            if q["dir"] == "out" and q["kind"] in ("data", "rst"):
                for n in nets(inst, q["name"]):
                    drivers[n][d] = cpath + "/" + q["name"]

    def ins_of(inst, idef):
        acc = {}
        for q in idef["pins"]:
            if q["dir"] in ("in", "inout") and q["kind"] in ("data", "rst"):
                for n in nets(inst, q["name"]):
                    acc.update(drivers[n])
        return acc

    def push(inst, pin, dd):
        hit = False
        for n in nets(inst, pin):
            if any(k not in drivers[n] for k in dd):
                drivers[n].update(dd)
                hit = True
        return hit

    for _ in range(8):
        changed = False
        for inst, idef in combs:
            acc = ins_of(inst, idef)
            for q in idef["pins"]:
                if q["dir"] == "out" and push(inst, q["name"], acc):
                    changed = True
        for inst, idef, cpath, mode, _ in leaf_info:
            if mode != "comb":
                continue
            acc = ins_of(inst, idef)
            for q in idef["pins"]:
                if q["dir"] == "out" and push(inst, q["name"], acc):
                    changed = True
        for inst, idef, cpath in children:
            cctx = {}
            for q in idef["pins"]:
                if q["dir"] in ("in", "inout"):
                    acc = {}
                    for n in nets(inst, q["name"]):
                        acc.update(drivers[n])
                    if acc:
                        cctx[q["name"]] = acc
            outs = evaluate(cx, cpath, cctx, depth + 1)
            for pname, dd in outs.items():
                if push(inst, pname, dd):
                    changed = True
        if not changed:
            break
    for n, dd in drivers.items():
        if dd:
            cx.netdom[path + "|" + n] = sorted(dd)
    # crossings into registers at this level
    sink_regs = {}
    for inst, idef, d in regs:
        for q in idef["pins"]:
            if q["dir"] == "in" and q["kind"] == "data":
                for n in by_end.all((inst["name"], q["name"])):
                    sink_regs.setdefault(n, []).append((inst, d))
    for inst, idef, d in regs:
        if not d:
            continue
        outs = [n for o in idef["pins"] if o["dir"] == "out" for n in by_end.all((inst["name"], o["name"]))]
        for q in idef["pins"]:
            if q["dir"] != "in" or q["kind"] not in ("data", "rst"):
                continue
            for n in nets(inst, q["name"]):
                for src, origin in drivers[n].items():
                    if src == d or _related(cx, src, d):
                        continue
                    net = by_name.get(n, {})
                    direct = _direct(path, net, origin, inst["name"])
                    w = (net.get("w") or 0) if direct else 0
                    chain = bool(outs) and all(any(sd == d for _, sd in sink_regs.get(o, [])) for o in outs)
                    cx.crossings.append({"level": path, "reg": path + "/" + inst["name"], "net": n,
                                         "pin": q["name"], "from": src, "to": d, "origin": origin, "w": w,
                                         "rst": q["kind"] == "rst", "via": not direct,
                                         "sync": bool(chain and direct and (net.get("w") or 1) <= 1)})
    for inst, idef, cpath, mode, d in leaf_info:
        if mode != "seq":
            continue
        for q in idef["pins"]:
            if q["dir"] != "in" or q["kind"] != "data" or SYNCED_INPUTS.match(q["name"]):
                continue
            for n in nets(inst, q["name"]):
                for src, origin in drivers[n].items():
                    if src != d and not _related(cx, src, d):
                        cx.crossings.append({"level": path, "reg": cpath, "net": n, "pin": q["name"], "from": src,
                                             "to": d, "origin": origin, "w": by_name.get(n, {}).get("w") or 0,
                                             "ip": True, "sync": False})
    out = {}
    for n in body["nets"]:
        for inst, p in n["ends"]:
            if inst == "" and bpins.get(p, {}).get("dir") in ("out", "inout") and drivers.get(n["name"]):
                out[p] = dict(drivers[n["name"]])
    cx.eval_memo[key] = out
    return out


def _direct(path, net, origin, skip):
    """True when the origin drives this net without logic in between at this level."""
    for inst, _ in net.get("ends", []):
        if inst == skip:
            continue
        if inst == "":
            if not origin.startswith(path + "/"):
                return True
            continue
        p = path + "/" + inst
        if origin == p or origin.startswith(p + "/"):
            return True
    return False


def _clock_nets(cx):
    for path, body in cx.bodies.items():
        for n in body["nets"]:
            if n["kind"] == "clk":
                d = resolve_clock(cx, path, n["name"])
                if d:
                    cx.netdom[path + "|" + n["name"]] = [d]


def dname(cx, d):
    info = cx.domains.get(d, {})
    f = info.get("freq")
    return info.get("name", d) + (" %g MHz" % (f / 1e6) if f else "")


def _finding(sev, path, rule, title, detail="", fix="", **kw):
    f = {"sev": sev, "path": path or "/", "rule": rule, "title": title, "by": "lint"}
    if detail:
        f["detail"] = detail
    if fix:
        f["fix"] = fix
    f.update({k: v for k, v in kw.items() if v is not None})
    return f


def cdc_findings(cx):
    out, seen = [], set()
    nets = {}
    for c in cx.crossings:
        nets.setdefault((c["reg"], c["from"], bool(c.get("rst"))), {}).setdefault(c["net"], c)
    for c in cx.crossings:
        k = (c["reg"], c["from"], bool(c.get("rst")))
        if k in seen:
            continue
        seen.add(k)
        group = nets[k]
        if len(group) > 1:
            ws = [g["w"] for g in group.values()]
            c = dict(c, net=", ".join(group), w=sum(ws) if all(ws) else 0,
                     via=any(g.get("via") for g in group.values()), sync=False)
        w = c["w"]
        bits = ("%d-bit " % w) if w else ""
        src, dst = dname(cx, c["from"]), dname(cx, c["to"])
        if c.get("sync"):
            out.append(_finding("info", c["reg"], "cdc-sync", "2-FF synchronizer %s → %s" % (src, dst),
                                "%s samples %s from %s" % (c["reg"], c["net"], c["origin"]),
                                "Mark both flops ASYNC_REG and exclude the first stage from timing.",
                                net=c["net"], level=c["level"]))
            continue
        if c.get("rst"):
            out.append(_finding("med", c["reg"], "rst-cdc", "Reset from %s used in %s" % (src, dst),
                                "%s resets %s (clocked by %s) without a reset synchronizer" % (c["origin"], c["reg"], dst),
                                "Synchronize reset deassertion into the destination clock (xpm_cdc_async_rst or a "
                                "proc_sys_reset on that clock).", net=c["net"], level=c["level"]))
            continue
        sev = "low" if c.get("ip") else "high"
        fix = ("Use xpm_cdc_single (2-FF, ASYNC_REG) for this 1-bit signal." if w == 1 else
               "Multi-bit: register it in the destination clock, or use xpm_cdc_handshake / xpm_cdc_array_single "
               "with a qualifier, or an async FIFO for streaming data.")
        if c.get("ip"):
            fix = "Check the IP datasheet for input synchronization; otherwise add a synchronizer."
        how = ("reaches %s through combinational logic (%s)" % (c["reg"], c["net"]) if c.get("via")
               else "drives %s, sampled by %s" % (c["net"], c["reg"]))
        if c.get("via"):
            fix = "Synchronize at the source signal (not after logic): " + fix
        out.append(_finding(sev, c["reg"], "cdc", "Unsynchronized %sCDC %s → %s" % (bits, src, dst),
                            "%s %s" % (c["origin"], how), fix, net=c["net"], level=c["level"]))
    return out


def structural(design, cx):
    out = []
    defs = design["defs"]
    for path, d, inst in M.walk(design):
        if d["kind"] in ("reg", "comb", "latch"):
            continue
        for p in d["pins"]:
            if not p.get("unc"):
                continue
            if p["dir"] == "in" and p["kind"] == "clk":
                out.append(_finding("high", path, "clk-unconnected", "Clock input %s unconnected" % p["name"],
                                    fix="Connect it to the clock of the logic driving this block's interfaces."))
            elif p["dir"] == "in" and p["kind"] == "rst" and not any(
                    q["kind"] == "rst" and q["dir"] == "in" and not q.get("unc") for q in d["pins"]):
                out.append(_finding("med", path, "rst-unconnected", "Reset input %s unconnected" % p["name"],
                                    fix="Drive it from a proc_sys_reset on the same clock."))
            elif p["dir"] == "out" and p["kind"] == "intr" and d["kind"] != "ps":
                out.append(_finding("low", path, "intr-unrouted", "Interrupt %s not routed" % p["name"],
                                    "Fine if software polls; otherwise wire it to the PS interrupt input.",
                                    "Add it to the xlconcat feeding IRQ_F2P / pl_ps_irq."))
    for path in [""] + [p for p, _, _ in M.walk(design)]:
        body = cx.bodies.get(path)
        if not body:
            continue
        insts = {i["name"]: defs[i["def"]] for i in body["insts"]}
        for n in body["nets"]:
            if n["kind"] != "rst":
                continue
            pins = []
            for inst, pn in n["ends"]:
                t = body if inst == "" else insts.get(inst)
                q = M.pin_index(t).get(pn) if t else None
                if q and q.get("pol") and not q.get("inferred"):
                    pins.append((inst, q))
            pols = {q["pol"] for _, q in pins}
            if len(pols) > 1:
                desc = ", ".join("%s/%s:%s" % (i or "<port>", q["name"], q["pol"]) for i, q in pins)
                out.append(_finding("high", path or "/", "rst-polarity", "Reset polarity mismatch on %s" % n["name"],
                                    desc, "Insert an inverter (util_vector_logic NOT) or use the matching reset "
                                          "output (peripheral_reset vs peripheral_aresetn).", net=n["name"],
                                    level=path or "/"))
    top = defs[design["top"]]
    addr = [a for a in top.get("addr", []) if not a.get("excluded")]
    spaces = {}
    for a in addr:
        try:
            base = int(a["base"], 0)
        except (ValueError, TypeError):
            continue
        size = _size(a)
        if size:
            spaces.setdefault((a["master"], a["space"]), []).append((base, base + size - 1, a))
    for (m, s), rows in spaces.items():
        rows.sort(key=lambda r: r[0])
        for x, y in zip(rows, rows[1:]):
            if y[0] <= x[1] and (x[2]["slave"], x[2]["intf"]) != (y[2]["slave"], y[2]["intf"]):
                out.append(_finding("high", y[2]["slave"], "addr-overlap",
                                    "Address overlap with %s in %s" % (x[2]["slave"], m),
                                    "%s %s..%s overlaps %s" % (y[2]["slave"], hex(y[0]), hex(y[1]), x[2]["slave"]),
                                    "Re-run assign_bd_address or fix the offsets in the Address Editor."))
    mapped = {(a["slave"], a["intf"]) for a in addr}
    for path, d, inst in M.walk(design, 2):
        if not d.get("regs"):
            continue
        intfs = {r.get("intf") for r in d["regs"] if r.get("intf")}
        for p in d["pins"]:
            if p["kind"] == "bus" and p.get("mode") == "slave" and p.get("bus") == "aximm" and not p.get("unc") \
                    and (not intfs or p["name"] in intfs) and (path, p["name"]) not in mapped:
                out.append(_finding("med", path, "addr-unmapped", "%s/%s has no address" % (path, p["name"]),
                                    fix="Assign it in the Address Editor (assign_bd_address)."))
    return out


def _size(a):
    if a.get("high"):
        try:
            return int(a["high"], 0) - int(a["base"], 0) + 1
        except ValueError:
            return 0
    r = str(a.get("range", "")).upper()
    m = re.match(r"^(\d+)\s*([KMG]?)$", r)
    if m:
        return int(m.group(1)) * {"": 1, "K": 1 << 10, "M": 1 << 20, "G": 1 << 30}[m.group(2)]
    try:
        return int(r, 0)
    except ValueError:
        return 0


def run(design: dict) -> dict:
    cx = _Ctx(design)
    _clock_nets(cx)
    evaluate(cx, "", {})
    findings = structural(design, cx) + cdc_findings(cx)
    design["domains"] = cx.domains
    design["netdom"] = cx.netdom
    return {"findings": findings}
