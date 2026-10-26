"""Condense Vivado reports and tool logs into a few lines of facts."""
from __future__ import annotations

import os
import re

_NUM = r"(-?\d+(?:\.\d+)?|inf|NA)"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def timing(text: str) -> dict:
    out = {}
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith("WNS(ns)") and "WHS(ns)" in ln and "From Clock" not in ln:
            vals = lines[i + 2].split() if i + 2 < len(lines) else []
            if len(vals) >= 8:
                out.update(wns=_f(vals[0]), tns=_f(vals[1]), tns_fail=int(vals[2]), whs=_f(vals[4]),
                           ths=_f(vals[5]), ths_fail=int(vals[6]))
                if len(vals) >= 10:
                    out.update(wpws=_f(vals[8]), tpws=_f(vals[9]))
            break
    out["met"] = "All user specified timing constraints are met" in text
    chk = {m.group(1): int(m.group(2)) for m in re.finditer(r"^\d+\. checking (\w+) \((\d+)\)", text, re.M)}
    out["check_timing"] = {k: v for k, v in chk.items() if v}
    clocks = []
    m = re.search(r"\| Clock Summary\n.*?\nClock\s+Waveform.*?\n-+.*?\n(.*?)\n\s*\n", text, re.S)
    if m:
        for ln in m.group(1).splitlines():
            parts = ln.split()
            if len(parts) >= 4 and _f(parts[-1]):
                clocks.append({"name": parts[0].strip(), "period": _f(parts[-2]), "mhz": _f(parts[-1])})
    out["clocks"] = clocks
    inter = []
    m = re.search(r"\| Inter Clock Table\n.*?\nFrom Clock.*?\n-+.*?\n(.*?)\n\s*\n", text, re.S)
    if m:
        for ln in m.group(1).splitlines():
            p = ln.split()
            if len(p) >= 8:
                inter.append({"from": p[0], "to": p[1], "wns": _f(p[2]), "whs": _f(p[6])})
    out["inter_clock"] = inter
    paths = []
    for m in re.finditer(r"^Slack \((VIOLATED|MET)\)\s*:\s*(-?[\d.]+)ns.*?\n\s+Source:\s+(\S+).*?\n.*?\n\s+Destination:"
                         r"\s+(\S+).*?\n.*?\n\s+Path Group:\s+(\S+).*?\n\s+Path Type:\s+(\w+)", text, re.M):
        if m.group(1) == "VIOLATED":
            paths.append({"slack": _f(m.group(2)), "from": m.group(3), "to": m.group(4), "group": m.group(5),
                          "type": m.group(6)})
        if len(paths) >= 5:
            break
    out["violations"] = paths
    return out


_UTIL_ROWS = {
    "LUT": r"(Slice LUTs|CLB LUTs)\*?",
    "FF": r"(Slice Registers|CLB Registers)",
    "BRAM": r"Block RAM Tile",
    "URAM": r"URAM",
    "DSP": r"DSPs",
    "IO": r"Bonded IOB",
}


def utilization(text: str) -> dict:
    out = {}
    for key, pat in _UTIL_ROWS.items():
        m = re.search(r"^\|\s*%s\s*\|([^\n]*)$" % pat, text, re.M)
        if m:
            cells = [c.strip() for c in m.group(m.lastindex).split("|") if c.strip()]
            nums = [c for c in cells if re.fullmatch(r"[\d.<]+", c)]
            if nums:
                out[key] = {"used": _f(nums[0]), "pct": _f(nums[-1].lstrip("<"))}
    return out


def rule_table(text: str) -> list:
    """DRC / methodology summary rows: | ID | Severity | Description | Count |."""
    rows = []
    for m in re.finditer(r"^\|\s*([A-Z][A-Z0-9_]*-\d+)\s*\|\s*([A-Za-z ]+?)\s*\|\s*(.*?)\s*\|\s*(\d+)\s*\|", text, re.M):
        rows.append({"id": m.group(1), "sev": m.group(2), "desc": m.group(3), "n": int(m.group(4))})
    return rows


_CELL = re.compile(r"(\[\d+\])?/[A-Za-z0-9_]+$")


def _cell(pin):
    """design_1_i/.../inst/gain_q_reg[15]/C -> .../gain_q_reg"""
    c = _CELL.sub("", pin)
    return re.sub(r"\[\d+\]$", "", c).replace("/inst/", "/")


def cdc(text: str) -> dict:
    summary = [{"id": m.group(1), "sev": m.group(2), "n": int(m.group(3)), "desc": m.group(4).strip()}
               for m in re.finditer(r"^(CDC-\d+)\s+(Critical|Warning|Info)\s+(\d+)\s+(.+)$", text, re.M)]
    pairs = {}
    src = dst = None
    for ln in text.splitlines():
        m = re.match(r"^Source Clock:\s*(\S+)", ln)
        if m:
            src = m.group(1)
            continue
        m = re.match(r"^Destination Clock:\s*(\S+)", ln)
        if m:
            dst = m.group(1)
            continue
        m = re.match(r"^\s*\d+\s+(CDC-\d+)\s+(Critical|Warning|Info)\s+.+?\s{2,}\d+\s+\S+\s+(\S+)\s+(\S+)\s*$", ln)
        if m and src:
            key = (src, dst, m.group(1), _cell(m.group(3)), _cell(m.group(4)))
            pairs[key] = pairs.get(key, 0) + 1
    groups = [{"from_clk": k[0], "to_clk": k[1], "id": k[2], "from": k[3], "to": k[4], "n": n}
              for k, n in sorted(pairs.items(), key=lambda kv: -kv[1])]
    return {"summary": summary, "groups": groups}


def clock_interaction(text: str) -> list:
    rows = []
    for m in re.finditer(r"^(\S+)\s+(\S+)\s+\S+ - \S+\s+[-\d.]+\s+[-\d.]+\s+\d+\s+\d+\s+[-\d.]+\s+(.+?)\s{2,}(.+?)\s*$",
                         text, re.M):
        cls, cons = m.group(3).strip(), m.group(4).strip()
        if "unsafe" in cons.lower() or cls == "No Common Clock":
            rows.append({"from": m.group(1), "to": m.group(2), "class": cls, "constraints": cons})
    return rows


def classify(path: str, text: str) -> str:
    base = os.path.basename(path).lower()
    head = text[:4000]
    if "Design Timing Summary" in text or "timing_summary" in base:
        return "timing"
    if "Utilization Design Information" in head or "utilization" in base:
        return "util"
    if "Report Methodology" in head or "methodology" in base:
        return "methodology"
    if "Report DRC" in head or "_drc" in base:
        return "drc"
    if "CDC Report" in head or "report_cdc" in head or base.endswith("cdc.rpt"):
        return "cdc"
    if "Clock Interaction" in head:
        return "clock_interaction"
    return ""


def summarize(paths: list) -> dict:
    facts = {}
    for p in paths:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        kind = classify(p, text)
        if not kind:
            continue
        prev = facts.get(kind)
        # prefer post-route over earlier stages when several runs are present
        stage = 2 if "routed" in p else 1 if ("placed" in p or "opt" in p) else 0
        if prev and prev["_stage"] > stage:
            continue
        parser = {"timing": timing, "util": utilization, "methodology": rule_table, "drc": rule_table,
                  "cdc": cdc, "clock_interaction": clock_interaction}[kind]
        facts[kind] = {"_stage": stage, "file": p, "data": parser(text)}
    return facts


def format_facts(facts: dict, rel=lambda p: p) -> str:
    out = []
    t = facts.get("timing", {}).get("data")
    if t:
        status = "MET" if t.get("met") else "NOT MET"
        out.append("timing %s  WNS %s  TNS %s (%s fail)  WHS %s  THS %s (%s fail)   [%s]" % (
            status, t.get("wns"), t.get("tns"), t.get("tns_fail"), t.get("whs"), t.get("ths"), t.get("ths_fail"),
            rel(facts["timing"]["file"])))
        if t.get("clocks"):
            out.append("clocks " + ", ".join("%s %g MHz" % (c["name"], c["mhz"]) for c in t["clocks"]))
        cross = [c for c in t.get("inter_clock", [])]
        if cross:
            out.append("inter-clock timed paths " + ", ".join("%s→%s WNS %s" % (c["from"], c["to"], c["wns"])
                                                               for c in cross))
        if t.get("check_timing"):
            out.append("check_timing " + ", ".join("%s=%d" % kv for kv in t["check_timing"].items()))
        for v in t.get("violations", []):
            out.append("  VIOLATED %.3fns %s %s → %s" % (v["slack"], v["type"], v["from"], v["to"]))
    u = facts.get("util", {}).get("data")
    if u:
        out.append("util " + "  ".join("%s %g (%g%%)" % (k, v["used"], v["pct"]) for k, v in u.items()
                                        if v.get("used") is not None and v.get("pct") is not None))
    for kind in ("drc", "methodology"):
        rows = facts.get(kind, {}).get("data")
        if rows:
            bad = [r for r in rows if r["sev"].lower() in ("error", "critical warning")]
            rest = len(rows) - len(bad)
            out.append("%s %s%s" % (kind, ", ".join("%s(%s)×%d %s" % (r["id"], "E" if r["sev"].lower() == "error"
                                                                      else "CW", r["n"], r["desc"]) for r in bad)
                                     or "no errors/critical", (" +%d warning rules" % rest) if rest else ""))
    c = facts.get("cdc", {}).get("data")
    if c:
        out.append("report_cdc " + (", ".join("%s %s ×%d %s" % (r["id"], r["sev"], r["n"], r["desc"])
                                              for r in c["summary"]) or "clean"))
        for g in c["groups"][:6]:
            out.append("  %s %s→%s  %s → %s  (%d paths)" % (g["id"], g["from_clk"], g["to_clk"], g["from"], g["to"],
                                                         g["n"]))
    ci = facts.get("clock_interaction", {}).get("data")
    if ci:
        out.append("clock_interaction " + ", ".join("%s→%s %s / %s" % (r["from"], r["to"], r["class"], r["constraints"])
                                                    for r in ci[:8]))
    return "\n".join(out)


# ----------------------------------------------------------------------------
# logs

_MSG = re.compile(r"^(ERROR|CRITICAL WARNING|WARNING):\s*\[([^\]]+)\]\s*(.*)$")
_YOCTO = re.compile(r"^ERROR:\s+(\S+)\s+do_(\w+):\s*(.*)$")
_LOGFILE = re.compile(r"Logfile of failure stored in:\s*(\S+)")
_GCC = re.compile(r"^(\S+?):(\d+):(?:\d+:)?\s*(fatal error|error):\s*(.*)$")
_SEV_ORDER = {"ERROR": 0, "CRITICAL WARNING": 1, "WARNING": 2}


def _short(msg, n=180):
    if len(msg) <= n:
        return msg
    tail = re.search(r"((?:Problem ports|Problem pins|ports?|cells?|nets?):\s*.{0,80})$", msg, re.I)
    head = msg[:n - 40]
    return head + " … " + (tail.group(1) if tail else msg[-40:])


def logs(path: str, limit: int = 25) -> str:
    groups = {}
    yocto, failure_logs, gcc = [], [], []
    with open(path, encoding="utf-8", errors="replace") as f:
        for no, ln in enumerate(f, 1):
            ln = ln.rstrip("\n")
            m = _MSG.match(ln)
            if m:
                key = (m.group(1), m.group(2))
                g = groups.setdefault(key, {"n": 0, "line": no, "msg": m.group(3)})
                g["n"] += 1
                continue
            m = _YOCTO.match(ln)
            if m:
                yocto.append((no, m.group(1), m.group(2), m.group(3)))
                continue
            m = _LOGFILE.search(ln)
            if m:
                failure_logs.append(m.group(1))
                continue
            m = _GCC.match(ln)
            if m:
                gcc.append((no, m.group(1), m.group(2), m.group(4)))
    out = []
    counts = {}
    for (sev, _), g in groups.items():
        counts[sev] = counts.get(sev, 0) + g["n"]
    out.append("%s  " % os.path.basename(path) + "  ".join("%s=%d" % (k, counts.get(k, 0))
                                                             for k in ("ERROR", "CRITICAL WARNING", "WARNING")))
    ranked = sorted(groups.items(), key=lambda kv: (_SEV_ORDER[kv[0][0]], -kv[1]["n"]))
    for (sev, mid), g in ranked[:limit]:
        tag = {"ERROR": "E", "CRITICAL WARNING": "CW", "WARNING": "W"}[sev]
        out.append("%-2s [%s] ×%d L%d: %s" % (tag, mid, g["n"], g["line"], _short(g["msg"])))
    for no, recipe, task, msg in yocto[:10]:
        out.append("E yocto %s do_%s L%d: %s" % (recipe, task, no, _short(msg, 140)))
    for p in failure_logs[:5]:
        out.append("  task log (read this for the real error): %s" % p)
    for no, file, line, msg in gcc[:10]:
        out.append("E gcc %s:%s L%d: %s" % (file, line, no, _short(msg, 140)))
    return "\n".join(out)
