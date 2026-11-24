"""Bulk-ingest a folder of documents, then run the gap analysis for the asset.

Example:
    python scripts/ingest_folder.py data/oem_manuals/PUMP-P101 --kind oem --asset PUMP-P101
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blueprint.config import get_settings  # noqa: E402
from blueprint.ingest import SUPPORTED_SUFFIXES  # noqa: E402
from blueprint.models import SourceKind  # noqa: E402
from blueprint.pipeline import Blueprint  # noqa: E402


def main() -> None:
    """Parse arguments, ingest every supported file in the folder, then run the analysis."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--kind", choices=[k.value for k in SourceKind], required=True)
    ap.add_argument("--asset", required=True, help="Asset ID / tag the documents apply to")
    ap.add_argument("--vendor", help="Vendor name (required for --kind vendor)")
    ap.add_argument("--sample", action="store_true", help="Tag documents as synthetic sample data")
    ap.add_argument("--no-analyze", action="store_true", help="Skip the gap analysis after ingest")
    args = ap.parse_args()

    if args.kind == "vendor" and not args.vendor:
        ap.error("--vendor is required for vendor documents")

    bp = Blueprint.from_settings(get_settings())
    files = sorted(p for p in args.folder.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES and p.name != "README.md")
    if not files:
        sys.exit(f"No supported files in {args.folder}")
    for path in files:
        _, n_tasks, n_chunks = bp.ingest(
            path.name, path.read_bytes(), kind=SourceKind(args.kind), asset_id=args.asset,
            vendor=args.vendor, is_sample=args.sample,
        )
        print(f"{path.name}: {n_tasks} tasks, {n_chunks} chunks")

    if not args.no_analyze:
        findings = bp.analyze(args.asset)
        print(f"Gap analysis for {args.asset}: {len(findings)} findings")


if __name__ == "__main__":
    main()
