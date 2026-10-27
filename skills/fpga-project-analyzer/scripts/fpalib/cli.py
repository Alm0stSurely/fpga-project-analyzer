"""fpa: FPGA project analyzer (AMD/Xilinx Vivado, PYNQ, HLS, Vitis, PetaLinux).

  fpa.py build   [ROOT] [--top M] [--bd NAME] [--src LIST]... [--vivado auto|on|off]  -> ROOT/.fpa/design.json
  fpa.py summary [ROOT]                     whole design in ~40 lines
  fpa.py show    [ROOT] BLOCK [--nets]      one block: pins, peers, nets, domains, address, regs, refs
  fpa.py findings [ROOT]                    all findings with detail and fix
  fpa.py view    [ROOT] [-o FILE]           offline HTML diagram (merges .fpa/overlay.json)
  fpa.py doc     [ROOT] [--no-images]       Markdown design document + SVG diagrams in .fpa/
  fpa.py mcp                               MCP server on stdio, for any MCP-capable AI agent
  fpa.py reports [ROOT|FILES...]            timing / utilization / DRC / methodology facts
  fpa.py logs    FILE [-n N]                grouped errors/warnings of a tool log
  fpa.py deep    [ROOT] --top M             Vivado-elaborated RTL netlist (needs Vivado)
  fpa.py vivado-reports DCP|XPR [ROOT]      run Vivado report_* on a checkpoint and summarize
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

from fpalib import build as B, model as M, reports as R, summary as S, viewer as V


def _root(r):
    return os.path.abspath(r or ".")


def _disp(p):
    r = os.path.relpath(p)
    return p if r.startswith("..") else r


def _db(root):
    return os.path.join(root, ".fpa", "design.json")


def _load(root):
    p = _db(root)
    if not os.path.isfile(p):
        sys.exit("no %s; run: fpa.py build %s" % (_disp(p), _disp(root)))
    return M.load(p)


def cmd_build(a):
    root = _root(a.root)
    out = os.path.join(root, ".fpa")
    os.makedirs(out, exist_ok=True)
    d = B.build(root, out, top=a.top or "", bd=a.bd or "", use_vivado=a.vivado, log=lambda m: print(m, file=sys.stderr),
                srcs=a.src)
    M.save(d, _db(root))
    print(S.summary(d))
    print("\nsaved %s" % _disp(_db(root)))


def cmd_summary(a):
    print(S.summary(_load(_root(a.root))))


def cmd_show(a):
    args = a.args
    if len(args) == 1:
        root, block = ".", args[0]
    elif os.path.isdir(args[0]) and not os.path.isdir(args[1]):
        root, block = args
    else:
        block, root = args[0], args[1]
    print(S.show(_load(_root(root)), block, nets=a.nets))


def cmd_findings(a):
    print(S.findings(_load(_root(a.root))))


def cmd_view(a):
    root = _root(a.root)
    d = _load(root)
    ov = V.load_overlay(a.overlay or os.path.join(root, ".fpa", "overlay.json"))
    out = a.o or os.path.join(root, ".fpa", "design.html")
    for w in V.check_overlay(d, ov):
        print("overlay: " + w, file=sys.stderr)
    V.render(d, out, ov)
    n = len(d.get("findings", [])) + len(ov.get("findings", []))
    print("%s  (%d findings, %d notes, %d flows)  open: file://%s" % (
        _disp(out), n, len(ov.get("notes", {})), len(ov.get("flows", [])), os.path.abspath(out)))


def cmd_doc(a):
    from fpalib import doc
    root = _root(a.root)
    d = _load(root)
    ov = V.load_overlay(os.path.join(root, ".fpa", "overlay.json"))
    out, n = doc.write(d, root, ov, images=not a.no_images, levels=a.levels, log=lambda m: print(m, file=sys.stderr))
    print("%s  (%d diagram%s)" % (_disp(out), n, "" if n == 1 else "s"))


def cmd_mcp(a):
    from fpalib import mcp
    mcp.serve()


def cmd_reports(a):
    paths = []
    for p in a.paths or ["."]:
        if os.path.isdir(p):
            paths += glob.glob(os.path.join(p, "**", "*.rpt"), recursive=True)
        else:
            paths.append(p)
    facts = R.summarize(paths)
    print(R.format_facts(facts) or "no Vivado reports found")


def cmd_logs(a):
    print(R.logs(a.file, a.n))


def cmd_deep(a):
    from fpalib import vivado as VV
    root = _root(a.root)
    VV.deep(root, a.top, a.depth, a.max_cells)


def cmd_vivado_reports(a):
    from fpalib import vivado as VV
    VV.reports(a.target, _root(a.root), a.run)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fpa", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build"); p.add_argument("root", nargs="?"); p.add_argument("--top"); p.add_argument("--bd")
    p.add_argument("--vivado", default="auto", choices=["auto", "on", "off"])
    p.add_argument("--src", action="append", help="explicit sources instead of scanning: file, dir, glob, or a file "
                   "list (make .d, .f, .lst); repeatable")
    p.set_defaults(f=cmd_build)
    p = sub.add_parser("summary"); p.add_argument("root", nargs="?"); p.set_defaults(f=cmd_summary)
    p = sub.add_parser("show"); p.add_argument("args", nargs="+", metavar="[ROOT] BLOCK")
    p.add_argument("--nets", action="store_true", help="list the nets inside the block (names for overlay flows)")
    p.set_defaults(f=cmd_show)
    p = sub.add_parser("findings"); p.add_argument("root", nargs="?"); p.set_defaults(f=cmd_findings)
    p = sub.add_parser("view"); p.add_argument("root", nargs="?"); p.add_argument("-o"); p.add_argument("--overlay")
    p.set_defaults(f=cmd_view)
    p = sub.add_parser("doc"); p.add_argument("root", nargs="?"); p.add_argument("--no-images", action="store_true")
    p.add_argument("--levels", type=int, default=6, help="diagram levels to include (default 6)")
    p.set_defaults(f=cmd_doc)
    p = sub.add_parser("mcp"); p.set_defaults(f=cmd_mcp)
    p = sub.add_parser("reports"); p.add_argument("paths", nargs="*"); p.set_defaults(f=cmd_reports)
    p = sub.add_parser("logs"); p.add_argument("file"); p.add_argument("-n", type=int, default=25); p.set_defaults(f=cmd_logs)
    p = sub.add_parser("deep"); p.add_argument("root", nargs="?"); p.add_argument("--top", required=True)
    p.add_argument("--depth", type=int, default=8); p.add_argument("--max-cells", type=int, default=20000)
    p.set_defaults(f=cmd_deep)
    p = sub.add_parser("vivado-reports"); p.add_argument("target"); p.add_argument("root", nargs="?")
    p.add_argument("--run", default="impl_1"); p.set_defaults(f=cmd_vivado_reports)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
