"""Static reader for Block Design Tcl (write_bd_tcl output and similar scripts).

A tiny Tcl interpreter: it runs every branch of if/catch, records the BD
commands (create_bd_*, connect_bd_*, set_property, assign_bd_address) and
ignores everything else. Scripts that rely on apply_bd_automation cannot be
read statically; the result is flagged so the caller can prefer Vivado.
"""
from __future__ import annotations

import re

from . import model as M
from .bdjson import bus_type, ip_kind, complete_pins

_VAR = re.compile(r"[A-Za-z0-9_:]+")


class _Parser:
    def __init__(self, s: str):
        self.s, self.i, self.n = s, 0, len(s)

    def commands(self):
        s = self.s
        while self.i < self.n:
            while self.i < self.n and s[self.i] in " \t\r\n;":
                self.i += 1
            if self.i >= self.n:
                return
            if s[self.i] == "#":
                while self.i < self.n and s[self.i] != "\n":
                    self.i += 2 if s[self.i] == "\\" else 1
                continue
            words = []
            while self.i < self.n:
                while self.i < self.n and (s[self.i] in " \t\r" or s.startswith("\\\n", self.i)):
                    self.i += 2 if s[self.i] == "\\" else 1
                if self.i >= self.n or s[self.i] in "\n;":
                    break
                words.append(self._word())
            if words:
                yield words

    def _word(self):
        c = self.s[self.i]
        if c == "{":
            j = _match(self.s, self.i, "{", "}")
            w = ("b", self.s[self.i + 1:j])
            self.i = j + 1
            return w
        if c == '"':
            j = self.i + 1
            while j < self.n and self.s[j] != '"':
                if self.s[j] == "\\":
                    j += 1
                elif self.s[j] == "[":
                    j = _match(self.s, j, "[", "]")
                j += 1
            w = ("q", self.s[self.i + 1:j])
            self.i = j + 1
            return w
        j = self.i
        while j < self.n and self.s[j] not in " \t\r\n;":
            if self.s[j] == "\\":
                j += 1
            elif self.s[j] == "[":
                j = _match(self.s, j, "[", "]")
            elif self.s.startswith("${", j):
                j = _match(self.s, j + 1, "{", "}")
            j += 1
        w = ("w", self.s[self.i:j])
        self.i = j
        return w


def _match(s, i, open_, close):
    depth, j, n = 0, i, len(s)
    while j < n:
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return j
        elif c == "{" and open_ == "[":
            j = _match(s, j, "{", "}")
        j += 1
    return n - 1


def _split_list(s: str) -> list:
    return [w for _, w in _ListWords(s)]


class _ListWords:
    def __init__(self, s):
        self.p = _Parser(s.replace("\n", " "))

    def __iter__(self):
        for words in self.p.commands():
            for w in words:
                yield w


class _BD:
    def __init__(self):
        self.name, self.part, self.board = "", "", ""
        self.cells = {}            # path -> dict(type, vlnv, ref)
        self.params = {}           # path -> {k: v}
        self.pins = {}             # owner path ("/" = top ports) -> {name: pin}
        self.nets = []             # (scope, kind, name, [objs])
        self.addr = []
        self.automation = False


class Interp:
    MAX_STEPS = 200000

    def __init__(self, search=()):
        self.search = list(search)
        self.sourced = []
        self.bd = _BD()
        self.procs = {}
        self.cur = "/"
        self.steps = 0
        self.globals = {}

    # -- substitution -------------------------------------------------
    def subst(self, text: str, frame: dict) -> str:
        out, i, n = [], 0, len(text)
        while i < n:
            c = text[i]
            if c == "\\" and i + 1 < n:
                nxt = text[i + 1]
                out.append({"n": "\n", "t": "\t", "\n": " "}.get(nxt, nxt))
                i += 2
            elif c == "$":
                if text.startswith("${", i):
                    j = text.index("}", i)
                    name = text[i + 2:j]
                    i = j + 1
                else:
                    m = _VAR.match(text, i + 1)
                    if not m:
                        out.append("$")
                        i += 1
                        continue
                    name = m.group(0)
                    i = m.end()
                    if i < n and text[i] == "(":
                        j = text.find(")", i)
                        name += text[i:j + 1]
                        i = j + 1
                name = name.lstrip(":")
                out.append(frame.get(name) or self.globals.get(name, ""))
            elif c == "[":
                j = _match(text, i, "[", "]")
                out.append(self.run(text[i + 1:j], frame))
                i = j + 1
            else:
                out.append(c)
                i += 1
        return "".join(out)

    def words(self, raw, frame):
        return [w if t == "b" else self.subst(w, frame) for t, w in raw]

    def run(self, script: str, frame: dict) -> str:
        result = ""
        for raw in _Parser(script).commands():
            self.steps += 1
            if self.steps > self.MAX_STEPS:
                break
            result = self.cmd(raw, frame)
        return result

    def source(self, path, frame):
        import os
        cands = [path] if os.path.isabs(path) else [os.path.join(d, path) for d in self.search]
        for c in cands:
            c = os.path.normpath(c)
            if os.path.isfile(c) and c not in self.sourced and len(self.sourced) < 64:
                self.sourced.append(c)
                with open(c, encoding="utf-8", errors="replace") as f:
                    return self.run(f.read(), frame)
        return ""

    # -- paths --------------------------------------------------------
    def abspath(self, name: str) -> str:
        name = name.strip()
        if name.startswith("/"):
            return "/" + name.strip("/") if name != "/" else "/"
        base = self.cur.rstrip("/")
        return base + "/" + name if name else (self.cur or "/")

    @staticmethod
    def _opts(args, flags_with_value):
        opts, rest, i = {}, [], 0
        while i < len(args):
            a = args[i]
            if a.startswith("-") and len(a) > 1 and not a[1].isdigit():
                if a in flags_with_value and i + 1 < len(args):
                    opts[a] = args[i + 1]
                    i += 2
                    continue
                opts[a] = True
            else:
                rest.append(a)
            i += 1
        return opts, rest

    # -- commands -----------------------------------------------------
    def cmd(self, raw, frame) -> str:
        name = raw[0][1] if raw[0][0] == "b" else self.subst(raw[0][1], frame)
        if name == "proc" and len(raw) >= 4:
            self.procs[raw[1][1]] = (_split_list(raw[2][1]), raw[3][1])
            return ""
        if name == "if":
            i = 1
            while i < len(raw):
                w = raw[i][1]
                if w in ("elseif",):
                    i += 1
                    continue
                if w == "else":
                    self.run(raw[i + 1][1], frame) if i + 1 < len(raw) else None
                    break
                if w == "then":
                    i += 1
                    continue
                self.subst(w, frame)  # run commands embedded in the condition
                if i + 1 < len(raw):
                    j = i + 1
                    if raw[j][1] == "then":
                        j += 1
                    self.run(raw[j][1], frame)
                    i = j + 1
                else:
                    break
            return ""
        if name == "catch" and len(raw) >= 2:
            self.run(raw[1][1], frame)
            return "0"
        if name == "foreach" and len(raw) == 4:
            var = raw[1][1]
            items = _split_list(self.words([raw[2]], frame)[0])[:64]
            for it in items:
                frame[var] = it
                self.run(raw[3][1], frame)
            return ""
        if name == "source" and len(raw) >= 2:
            return self.source(self.words(raw[1:], frame)[-1], frame)
        if name in ("for", "while", "switch", "return", "break", "continue", "namespace"):
            return ""
        args = self.words(raw[1:], frame)
        if name in ("variable", "global"):
            frame.setdefault("__g__", set()).update(args[0::2] if name == "variable" else args)
            if name == "variable" and len(args) >= 2:
                self.globals[args[0]] = args[1]
            return ""
        if name == "set":
            if len(args) >= 2:
                # every branch runs, so an unknown ("") result never clobbers a known value
                scope = self.globals if (frame is self.globals or args[0] in frame.get("__g__", ())) else frame
                if args[1] or not scope.get(args[0]):
                    scope[args[0]] = args[1]
                return scope.get(args[0], "")
            return (frame.get(args[0]) or self.globals.get(args[0], "")) if args else ""
        if name == "lappend" and args:
            frame[args[0]] = (frame.get(args[0], "") + " " + " ".join(args[1:])).strip()
            return frame[args[0]]
        if name == "list":
            return " ".join("{%s}" % a if (not a or " " in a) else a for a in args)
        if name == "concat":
            return " ".join(args)
        if name in self.procs:
            params, body = self.procs[name]
            f = {}
            for k, p in enumerate(params):
                pn = _split_list(p)[0] if p else p
                f[pn] = args[k] if k < len(args) else ""
            saved = self.cur
            self.run(body, f)
            self.cur = saved
            return ""
        h = getattr(self, "c_" + name.replace("::", "_"), None)
        return h(args) if h else ""

    def c_create_bd_design(self, a):
        _, rest = self._opts(a, {"-dir", "-bdsource"})
        if rest and not self.bd.name:
            self.bd.name = rest[0]
        return rest[0] if rest else ""

    def c_create_project(self, a):
        o, _ = self._opts(a, {"-part", "-ip_repo_paths"})
        if isinstance(o.get("-part"), str):
            self.bd.part = self.bd.part or o["-part"]
        return ""

    def c_current_bd_instance(self, a):
        _, rest = self._opts(a, set())
        if rest and rest[0] not in (".", ""):
            self.cur = self.abspath(rest[0])
        return self.cur

    def c_get_bd_cells(self, a):
        _, rest = self._opts(a, {"-filter", "-of_objects"})
        return " ".join(self.abspath(r) for r in rest) if rest else ""

    def _objs(self, a, tag):
        _, rest = self._opts(a, {"-filter", "-of_objects"})
        return " ".join(tag + self.abspath(r) for r in rest)

    def c_get_bd_pins(self, a):
        return self._objs(a, "pin:")

    def c_get_bd_intf_pins(self, a):
        return self._objs(a, "ipin:")

    def c_get_bd_ports(self, a):
        _, rest = self._opts(a, {"-filter"})
        return " ".join("port:/" + r.strip("/") for r in rest)

    def c_get_bd_intf_ports(self, a):
        _, rest = self._opts(a, {"-filter"})
        return " ".join("iport:/" + r.strip("/") for r in rest)

    def c_get_bd_addr_spaces(self, a):
        return self._objs(a, "space:")

    def c_get_bd_addr_segs(self, a):
        return self._objs(a, "seg:")

    def c_create_bd_cell(self, a):
        o, rest = self._opts(a, {"-type", "-vlnv", "-reference"})
        if not rest:
            return ""
        path = self.abspath(rest[-1])
        t = o.get("-type", "ip")
        self.bd.cells[path] = {"type": t, "vlnv": o.get("-vlnv", "") if t == "ip" else "",
                               "ref": o.get("-reference", "")}
        return path

    def _pin(self, owner, a, intf):
        o, rest = self._opts(a, {"-dir", "-from", "-to", "-type", "-mode", "-vlnv", "-freq_hz"})
        if not rest:
            return ""
        name = rest[-1]
        if intf:
            mode = str(o.get("-mode", "")).lower()
            p = M.pin(name, "out" if mode.startswith("master") else "in", "bus",
                      bus=bus_type(o.get("-vlnv", "")), mode=mode or None)
        else:
            t = str(o.get("-type", "")).lower()
            p = M.pin(name, M.norm_dir(o.get("-dir")), {"clk": "clk", "rst": "rst", "intr": "intr"}.get(t, ""),
                      w=M.width(o.get("-from"), o.get("-to")) or None,
                      freq=int(float(o["-freq_hz"])) if isinstance(o.get("-freq_hz"), str) else None)
        self.bd.pins.setdefault(owner, {})[name] = p
        return name

    def c_create_bd_port(self, a):
        n = self._pin("/", a, False)
        return "port:/" + n

    def c_create_bd_intf_port(self, a):
        n = self._pin("/", a, True)
        return "iport:/" + n

    def c_create_bd_pin(self, a):
        _, rest = self._opts(a, {"-dir", "-from", "-to", "-type", "-freq_hz"})
        if not rest:
            return ""
        full = self.abspath(rest[-1])
        owner, _, pname = full.rpartition("/")
        a = a[:-1] + [pname]
        self._pin(owner or "/", a, False)
        return "pin:" + full

    def c_create_bd_intf_pin(self, a):
        _, rest = self._opts(a, {"-mode", "-vlnv"})
        if not rest:
            return ""
        full = self.abspath(rest[-1])
        owner, _, pname = full.rpartition("/")
        a = a[:-1] + [pname]
        self._pin(owner or "/", a, True)
        return "ipin:" + full

    def _connect(self, a, kind, flag):
        o, rest = self._opts(a, {flag})
        objs = " ".join(rest).split()
        self.bd.nets.append((self.cur, kind, o.get(flag) if isinstance(o.get(flag), str) else "", objs))
        return ""

    def c_connect_bd_net(self, a):
        return self._connect(a, "", "-net")

    def c_connect_bd_intf_net(self, a):
        return self._connect(a, "bus", "-intf_net")

    def c_set_property(self, a):
        o, rest = self._opts(a, {"-dict"})
        pairs = []
        if isinstance(o.get("-dict"), str):
            items = _split_list(o["-dict"])
            if items and items[0] == "list":
                items = items[1:]
            pairs = list(zip(items[0::2], items[1::2]))
            objs = rest
        elif len(rest) >= 3:
            pairs = [(rest[0], rest[1])]
            objs = rest[2:]
        else:
            return ""
        for k, v in pairs:
            if k == "BOARD_PART":
                self.bd.board = v
        targets = " ".join(objs).split()
        for t in targets:
            if t.startswith(("port:", "iport:")):
                pn = t.split("/", 1)[1]
                p = self.bd.pins.get("/", {}).get(pn)
                if p:
                    for k, v in pairs:
                        k2 = k.replace("CONFIG.", "")
                        if k2 == "FREQ_HZ":
                            try:
                                p["freq"] = int(float(v))
                            except ValueError:
                                pass
                        elif k2 == "POLARITY":
                            p["pol"] = "low" if "LOW" in v.upper() else "high"
            elif t.startswith("/") and t in self.bd.cells:
                prm = self.bd.params.setdefault(t, {})
                for k, v in pairs:
                    if k.startswith("CONFIG."):
                        prm[k[7:]] = v
        return ""

    def c_assign_bd_address(self, a):
        o, rest = self._opts(a, {"-offset", "-range", "-target_address_space", "-external_address_space"})
        space = o.get("-target_address_space", "")
        for seg in " ".join(rest).split():
            if seg.startswith("seg:"):
                self.bd.addr.append((space if isinstance(space, str) else "", seg, o.get("-offset", ""),
                                     o.get("-range", ""), False))
        return ""

    def c_create_bd_addr_seg(self, a):
        o, rest = self._opts(a, {"-offset", "-range"})
        objs = " ".join(rest).split()
        space = next((x for x in objs if x.startswith("space:")), "")
        for seg in [x for x in objs if x.startswith("seg:")]:
            self.bd.addr.append((space, seg, o.get("-offset", ""), o.get("-range", ""), False))
        return ""

    def c_exclude_bd_addr_seg(self, a):
        _, rest = self._opts(a, {"-target_address_space"})
        for seg in " ".join(rest).split():
            if seg.startswith("seg:"):
                self.bd.addr.append(("", seg, "", "", True))
        return ""

    def c_apply_bd_automation(self, a):
        self.bd.automation = True
        return ""

    c_apply_board_connection = c_apply_bd_automation

    def c_current_bd_design(self, a):
        return self.bd.name

    def c_version(self, a):
        return "2024.2"


def _range_text(r):
    try:
        v = int(str(r), 0)
    except ValueError:
        return str(r)
    for unit, mult in (("G", 1 << 30), ("M", 1 << 20), ("K", 1 << 10)):
        if v >= mult and v % mult == 0:
            return "%d%s" % (v // mult, unit)
    return str(v)


def build(it: Interp, path: str) -> dict:
    bd = it.bd
    name = bd.name or "design"
    design = M.new_design(name)
    design["meta"].update({"part": bd.part or None, "board": bd.board or None})
    if bd.automation:
        design["meta"]["incomplete"] = "script uses apply_bd_automation; run with Vivado for full detail"
    defs = design["defs"]
    top_id = "bd:" + name
    design["top"] = top_id
    defs[top_id] = M.new_def(name, "bd", pins=list(bd.pins.get("/", {}).values()))
    ids = {"/": top_id}
    for cpath in sorted(bd.cells, key=lambda p: p.count("/")):
        c = bd.cells[cpath]
        parent = cpath.rsplit("/", 1)[0] or "/"
        if parent not in ids:
            continue
        if c["type"] == "hier":
            cid = "hier:" + cpath
            d = M.new_def(cpath.rsplit("/", 1)[1], "hier")
        else:
            cid = "ip:" + cpath
            vlnv = c["vlnv"] or ("xilinx.com:module_ref:%s:1.0" % c["ref"] if c["ref"] else "")
            d = M.new_def(bus_type(vlnv) or c["ref"] or cpath.rsplit("/", 1)[1], ip_kind(vlnv), vlnv=vlnv or None)
            if c["ref"]:
                d["ref"] = c["ref"]
        d["pins"].extend(bd.pins.get(cpath, {}).values())
        defs[cid] = d
        ids[cpath] = cid
        inst = {"name": cpath.rsplit("/", 1)[1], "def": cid}
        if bd.params.get(cpath):
            inst["params"] = bd.params[cpath]
        defs[ids[parent]]["insts"].append(inst)
    auto = 0
    for scope, kind, nname, objs in bd.nets:
        if scope not in ids:
            continue
        ends = []
        for ob in objs:
            tag, _, p = ob.partition(":")
            if tag in ("port", "iport"):
                ends.append(["", p.strip("/")] if scope == "/" else None)
                continue
            cell, _, pin = p.rpartition("/")
            cell = cell or "/"
            if cell == scope:
                ends.append(["", pin])
            elif (cell.rsplit("/", 1)[0] or "/") == scope:
                ends.append([cell.rsplit("/", 1)[1], pin])
        ends = [e for e in ends if e]
        if len(ends) < 2:
            continue
        if not nname:
            auto += 1
            nname = "net_%d" % auto
        defs[ids[scope]]["nets"].append({"name": nname, "kind": kind, "ends": ends})
    addr = []
    for space, seg, off, rng, excl in bd.addr:
        sp = space.partition(":")[2]
        sg = seg.partition(":")[2].rsplit("/", 2)
        if len(sg) < 3:
            continue
        m, _, spname = sp.rpartition("/")
        e = {"master": m, "space": spname, "slave": sg[0], "intf": sg[1], "block": sg[2],
             "base": off, "range": _range_text(rng)}
        if excl:
            e["excluded"] = True
        addr.append(e)
    defs[top_id]["addr"] = addr
    complete_pins(design)
    M.add_source(design, "bdtcl", path)
    return design


def parse(path: str, search=()) -> dict:
    import os
    with open(path, encoding="utf-8", errors="replace") as f:
        script = f.read()
    it = Interp(list(search) + [os.path.dirname(os.path.abspath(path))])
    it.run(script, it.globals)
    d = build(it, path)
    for p in it.sourced:
        M.add_source(d, "bdtcl", p)
    return d


def looks_like_bd(text: str) -> bool:
    return "create_bd_cell" in text or "create_bd_design" in text
