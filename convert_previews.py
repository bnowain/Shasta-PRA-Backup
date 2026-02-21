"""Batch-convert all compatible downloaded documents to PDF previews.

Usage:
    python convert_previews.py              # convert all missing previews
    python convert_previews.py --force      # re-convert even if cached PDF exists
    python convert_previews.py --dry-run    # show what would be converted
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path

from app.config import BASE_DIR, DB_PATH, DOCS_DIR, SOFFICE_PATH, CONVERTIBLE_EXTENSIONS
from app.routers.documents import convert_to_pdf


def main():
    parser = argparse.ArgumentParser(description="Batch-convert documents to PDF previews")
    parser.add_argument("--force", action="store_true", help="Re-convert even if cached PDF exists")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be converted without converting")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Find all downloaded documents with convertible extensions
    ext_placeholders = ",".join(f"'{e}'" for e in CONVERTIBLE_EXTENSIONS)
    rows = conn.execute(f"""
        SELECT id, title, file_extension, local_path, file_size_mb
        FROM documents
        WHERE downloaded = 1
          AND local_path IS NOT NULL
          AND LOWER(file_extension) IN ({ext_placeholders})
        ORDER BY id
    """).fetchall()

    if not rows:
        print("No convertible documents found.")
        conn.close()
        return

    print(f"Found {len(rows)} convertible documents")
    print(f"LibreOffice: {SOFFICE_PATH}")
    print()

    converted = skipped = failed = already = 0
    start = time.time()

    for i, row in enumerate(rows, 1):
        doc_id = row["id"]
        title = row["title"] or f"doc_{doc_id}"
        ext = (row["file_extension"] or "").lower()
        local_path = row["local_path"]
        size_mb = row["file_size_mb"] or 0

        file_path = Path(local_path)
        if not file_path.is_absolute():
            file_path = BASE_DIR / file_path

        if not file_path.exists():
            print(f"  [{i}/{len(rows)}] SKIP  {title} — file not found")
            skipped += 1
            continue

        cache_path = file_path.parent / (file_path.name + ".preview.pdf")

        if cache_path.exists() and not args.force:
            already += 1
            continue

        if args.dry_run:
            print(f"  [{i}/{len(rows)}] WOULD CONVERT  {title} (.{ext}, {size_mb:.1f} MB)")
            converted += 1
            continue

        print(f"  [{i}/{len(rows)}] Converting {title} (.{ext}, {size_mb:.1f} MB)...", end=" ", flush=True)

        try:
            # Remove existing cache if --force
            if args.force and cache_path.exists():
                cache_path.unlink()

            ok = convert_to_pdf(file_path, cache_path, timeout=180)
            if ok:
                print("OK")
                converted += 1
            else:
                print("FAILED (LibreOffice returned error)")
                failed += 1
        except FileNotFoundError:
            print("FAILED (LibreOffice not installed)")
            print("\nInstall LibreOffice: winget install --id TheDocumentFoundation.LibreOffice")
            conn.close()
            sys.exit(1)
        except Exception as e:
            print(f"FAILED ({e})")
            failed += 1

    conn.close()
    elapsed = time.time() - start

    print()
    print(f"Done in {elapsed:.1f}s")
    print(f"  Converted: {converted}")
    if already:
        print(f"  Already cached: {already}")
    if skipped:
        print(f"  Skipped (missing): {skipped}")
    if failed:
        print(f"  Failed: {failed}")


if __name__ == "__main__":
    main()
