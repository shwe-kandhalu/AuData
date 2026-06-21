from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import audit_pdf, write_html_report, write_json_report, write_markdown_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal PDF statistical auditor.")
    parser.add_argument("pdf", help="Path to the PDF to audit.")
    parser.add_argument(
        "--out-dir",
        default="auditor_output",
        help="Directory for JSON, Markdown, and HTML reports.",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.001,
        help="Absolute tolerance for exact reported p-values.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = audit_pdf(pdf_path, tolerance=args.tolerance)
    write_json_report(result, out_dir / "findings.json")
    write_markdown_report(result, out_dir / "report.md")
    write_html_report(result, out_dir / "report.html")

    print(json.dumps(result, indent=2))
    print(f"\nWrote reports to {out_dir}")
    return 0
