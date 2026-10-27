"""MCP server (stdio, JSON-RPC 2.0, one message per line) exposing the analyzer to any MCP-capable agent.

Run with `fpa mcp`. Standard library only.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import traceback

from . import build as B, model as M, reports as R, summary as S, viewer as V

VERSION = "0.2.0"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "FPGA Project Analyzer: explains and reviews AMD/Xilinx FPGA projects (Vivado block designs, RTL, PYNQ). "
    "Workflow: analyze(project) -> show_block for blocks that matter -> annotate(project, notes, flows, findings) "
    "to put a short role note per block and confirmed findings on the diagram -> give the user the diagram path. "
    "Findings from analyze are candidates; confirm them against the source before reporting.")

_P = {"type": "string", "description": "Project folder (absolute path)"}
TOOLS = [
    {"name": "analyze", "description": "Extract the project, run the checks and return a ~40-line summary "
                                       "(blocks, clock domains, buses, interrupts, address map, findings). Run first.",
     "inputSchema": {"type": "object", "required": ["project"], "properties": {
         "project": _P, "src": {"type": "array", "items": {"type": "string"},
                                "description": "Optional build file lists (make .d/.f/.lst), dirs or globs"},
         "top": {"type": "string", "description": "Optional top module"}}}},
    {"name": "show_block", "description": "One block: pins, peers, net names, clock domains, address, registers, "
                                          "software references, source file:line. '/' is the top level.",
     "inputSchema": {"type": "object", "required": ["project", "block"], "properties": {
         "project": _P, "block": {"type": "string", "description": "Instance path, e.g. /stream_proc/scaler_0"},
         "nets": {"type": "boolean", "description": "Also list the nets inside the block"}}}},
    {"name": "findings", "description": "All findings with detail and fix.",
     "inputSchema": {"type": "object", "required": ["project"], "properties": {"project": _P}}},
    {"name": "build_log", "description": "Condense a Vivado/HLS/PetaLinux/gcc log to grouped errors and warnings.",
     "inputSchema": {"type": "object", "required": ["file"], "properties": {
         "file": {"type": "string", "description": "Log file path"}}}},
    {"name": "annotate", "description": "Write the review overlay (role notes, highlighted flows, confirmed findings) "
                                        "and re-render the diagram. Returns the diagram path and any unresolved names.",
     "inputSchema": {"type": "object", "required": ["project"], "properties": {
         "project": _P,
         "notes": {"type": "object", "description": "{\"/block/path\": \"3-8 word role\"}"},
         "flows": {"type": "array", "description": "[{\"name\": str, \"nets\": [\"<level>|<net>\"]}]"},
         "findings": {"type": "array", "description": "[{\"sev\": \"high|med|low|info\", \"path\": str, "
                                                      "\"title\": str, \"detail\": str, \"fix\": str}]"}}}},
    {"name": "render_view", "description": "Write the interactive offline diagram (.fpa/design.html) and return its path.",
     "inputSchema": {"type": "object", "required": ["project"], "properties": {"project": _P}}},
    {"name": "design_doc", "description": "Write a Markdown design document with SVG diagrams (.fpa/design.md).",
     "inputSchema": {"type": "object", "required": ["project"], "properties": {
         "project": _P, "images": {"type": "boolean", "description": "Render diagram images (needs Chrome)"}}}},
    {"name": "reports", "description": "Timing, utilization, DRC, methodology and CDC facts from Vivado .rpt files.",
     "inputSchema": {"type": "object", "required": ["path"], "properties": {
         "path": {"type": "string", "description": "Folder or report file"}}}},
]


def _root(p):
    return os.path.abspath(os.path.expanduser(p))


def _db(root):
    path = os.path.join(root, ".fpa", "design.json")
    if not os.path.isfile(path):
        raise ValueError("not analyzed yet: call analyze with project=%s first" % root)
    return M.load(path)


def _overlay(root):
    return V.load_overlay(os.path.join(root, ".fpa", "overlay.json"))


def call(name, a):
    if name == "analyze":
        root = _root(a["project"])
        out = os.path.join(root, ".fpa")
        os.makedirs(out, exist_ok=True)
        notes = []
        d = B.build(root, out, top=a.get("top") or "", srcs=a.get("src") or None, use_vivado="auto",
                    log=notes.append)
        M.save(d, os.path.join(out, "design.json"))
        return "\n".join(notes + [S.summary(d)])
    if name == "show_block":
        return S.show(_db(_root(a["project"])), a["block"], nets=bool(a.get("nets")))
    if name == "findings":
        return S.findings(_db(_root(a["project"])))
    if name == "build_log":
        return R.logs(_root(a["file"]))
    if name == "reports":
        p = _root(a["path"])
        paths = [os.path.join(dp, f) for dp, _, fs in os.walk(p) for f in fs if f.endswith(".rpt")] \
            if os.path.isdir(p) else [p]
        return R.format_facts(R.summarize(paths)) or "no Vivado reports found"
    if name == "render_view":
        root = _root(a["project"])
        out = V.render(_db(root), os.path.join(root, ".fpa", "design.html"), _overlay(root))
        return "diagram: file://%s" % out
    if name == "annotate":
        root = _root(a["project"])
        d = _db(root)
        ov = _overlay(root)
        for k in ("notes", "flows", "findings"):
            if a.get(k) is not None:
                ov[k] = a[k]
        with open(os.path.join(root, ".fpa", "overlay.json"), "w", encoding="utf-8") as f:
            json.dump(ov, f, indent=1)
        warn = V.check_overlay(d, ov)
        out = V.render(d, os.path.join(root, ".fpa", "design.html"), ov)
        return "\n".join(["diagram: file://%s" % out] + ["warning: " + w for w in warn])
    if name == "design_doc":
        from . import doc
        root = _root(a["project"])
        logs = []
        out, n = doc.write(_db(root), root, _overlay(root), images=a.get("images", True), log=logs.append)
        return "\n".join(logs + ["document: %s (%d diagrams)" % (out, n)])
    raise ValueError("unknown tool %s" % name)


def handle(msg):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        v = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": v if v in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "fpga-project-analyzer", "version": VERSION},
            "instructions": INSTRUCTIONS}}
    if mid is None:  # notifications (initialized, cancelled, ...) need no answer
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):  # stdout is the protocol channel
                text, err = call(params.get("name"), params.get("arguments") or {}), False
        except Exception as e:  # report tool failures to the agent instead of dying
            text, err = "%s: %s" % (type(e).__name__, e), True
            traceback.print_exc(file=sys.stderr)
        extra = buf.getvalue().strip()
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": (extra + "\n" if extra else "") + text}], "isError": err}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}}


def serve(stdin=sys.stdin, stdout=sys.stdout):
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(msg)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
