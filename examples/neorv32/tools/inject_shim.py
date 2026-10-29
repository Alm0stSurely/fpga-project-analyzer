#!/usr/bin/env python3
"""Write a copy of fpa's design.html with web/fpa-shim.js inserted before the viewer script
(the same insertion app.js does in the browser). Used at build time in 'record' mode.
usage: inject_shim.py <record|replay> <design.html> <fpa-shim.js> <out.html>"""
import sys

mode, src, shim, out = sys.argv[1:5]
html = open(src, encoding="utf-8").read()
code = open(shim, encoding="utf-8").read()
marker = '<script>\n(function () {\n"use strict";'
i = html.rfind(marker)
if i < 0 or "</script" in code:
    sys.exit("inject_shim: viewer script marker not found (fpa viewer changed?)")
tag = '<script>window.__FPA_SHIM_MODE = "%s";</script>\n<script>%s</script>\n' % (mode, code)
open(out, "w", encoding="utf-8").write(html[:i] + tag + html[i:])
