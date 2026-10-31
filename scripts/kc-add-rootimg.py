#!/usr/bin/env python3
"""Append a __ROOTIMG segment to a Mach-O kernel collection.

Kept as the historical entry point; scripts/kc-add-segment.py is the generic
tool (it takes the segment name as an argument).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "kc_add_segment", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "kc-add-segment.py"))
kc_add_segment = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kc_add_segment)

if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('usage: kc-add-rootimg.py kernel.kc root.hfs out.kc')
    kc_add_segment.main(sys.argv[1], sys.argv[2], sys.argv[3], '__ROOTIMG')
