"""Writes report output files from a Report object."""

import json
from dataclasses import asdict

import viewer_sim as vs


def save_html(report, out_path):
    vs.write_html(report, out_path)


def save_json(report, out_path):
    with open(out_path, "w") as f:
        json.dump(asdict(report), f, indent=2)
