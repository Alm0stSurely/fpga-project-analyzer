#!/usr/bin/env python3
"""Check the probe -> fpa node table against the real diagram and write fpa-map.json.

usage: fpa_map.py <design.html> <ghdl.tree.txt> <activity-map.json> <neorv32_sim_api.cpp> <out fpa-map.json>

* design.html: fpa's viewer; its design JSON (script#fpa-data) gives every instance path the
  diagram can show (fpa drops generate scopes from paths and draws every generate branch).
* ghdl.tree.txt: `ghdl --elab-run ... --disp-tree=inst` of the same sources and top, the ground
  truth of which instances exist for this configuration.
* Every table entry must name a node that exists in design.html and is elaborated (for a process
  node: its enclosing instance is). Every probe must be one of neo_probe_names().
* The fpa instances that GHDL does not elaborate (disabled generate branches) are written as
  "phantoms" (subtree roots), so the page can dim them.
Exits non-zero if any check fails.
"""
import json
import re
import sys


def load_design(path):
    html = open(path, encoding="utf-8").read()
    m = re.search(r'<script type="application/json" id="fpa-data">(.*?)</script>', html, re.S)
    if not m:
        sys.exit("fpa_map: no script#fpa-data in %s" % path)
    return json.loads(m.group(1))


def fpa_paths(d):
    """All instance paths (any kind) and the kind of each, as the viewer walks them."""
    defs = d["defs"]

    def body(x):
        return defs[x["impl"]] if (not x["insts"] and x.get("impl") in defs) else x

    out = {}

    def rec(x, p, depth):
        if depth > 16:
            return
        for i in body(x)["insts"]:
            cd = defs[i["def"]]
            q = p + "/" + i["name"]
            out[q] = cd["kind"]
            rec(cd, q, depth + 1)

    rec(defs[d["top"]], "", 0)
    return out


def ghdl_logical(path):
    """Logical (generate scopes dropped) paths of elaborated component instances."""
    stack, out = [], set()
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"^([ |`+-]*)(\S+) \[(.+?)\]", line.rstrip("\n"))
        if not m:
            continue
        depth = len(m.group(1)) // 2
        name, kind = m.group(2), m.group(3)
        del stack[depth:]
        stack.append((name, kind))
        if kind == "entity" and len(stack) >= 2 and stack[-2][1] == "instance":
            out.add("/" + "/".join(n for n, k in stack[:-1] if k == "instance"))
    return out


def main():
    design, tree, table, api_cpp, out = sys.argv[1:6]
    d = load_design(design)
    paths = fpa_paths(d)
    elab = ghdl_logical(tree)
    if not elab:
        sys.exit("fpa_map: no elaborated instances in %s" % tree)
    m = re.search(r'NEO_PROBE_NAMES\[\]\s*=\s*((?:\s*"[^"]*")+)', open(api_cpp).read())
    probes = "".join(re.findall(r'"([^"]*)"', m.group(1))).split(",")

    rtl = {p for p, k in paths.items() if k == "rtl"}
    absent = sorted(p for p in rtl if p not in elab)
    phantoms = [p for p in absent if not any(p.startswith(q + "/") for q in absent)]
    missing = sorted(p for p in elab if p not in rtl)

    src = json.load(open(table))
    errors = []
    for e in src["entries"]:
        p = e["fpa"]
        if p not in paths:
            errors.append("%s: %s is not a node in design.html" % (e["id"], p))
            continue
        inst = p if paths[p] == "rtl" else p.rsplit("/", 1)[0]
        if inst not in elab:
            errors.append("%s: %s is not elaborated in this configuration" % (e["id"], inst))
        for pr in e["probes"]:
            if pr not in probes:
                errors.append("%s: unknown probe %s" % (e["id"], pr))
        e["kind"] = paths[p]
    for msg in errors:
        print("fpa_map: ERROR " + msg, file=sys.stderr)
    if errors:
        sys.exit(1)

    res = {
        "about": src.get("about", ""),
        "checked": "every 'fpa' path exists in design.html (%d instance paths) and is elaborated by GHDL" % len(paths),
        "entries": src["entries"],
        "phantoms": phantoms,
        "counts": {"fpa_rtl_instances": len(rtl), "elaborated": len(elab), "not_elaborated": len(absent),
                   "elaborated_missing_in_fpa": len(missing)},
        "probe_names": probes,
    }
    json.dump(res, open(out, "w"), indent=1)
    print("fpa_map: %d entries OK; %d of %d fpa RTL instances elaborated, %d not (%d subtree roots dimmed); "
          "%d elaborated paths missing in fpa" % (len(src["entries"]), len(rtl) - len(absent), len(rtl),
                                                   len(absent), len(phantoms), len(missing)))


if __name__ == "__main__":
    main()
