#!/usr/bin/env python3
"""VLM batch description script — Stage 3 of the document intelligence pipeline.

Describes documents where OCR yielded no text (photos, maps, diagrams).

Routing priority:
  1. Mission Control (port 8860) — uses vision_model capability class, routes to
     best available: llama3.2-vision:11b ->qwen2-vl:7b ->claude-haiku (cloud fallback)
  2. Direct Ollama — if MC is down but a vision model is locally available
  3. Error — no backend available

To pull local vision models (once, then MC handles them):
    ollama pull llama3.2-vision:11b
    ollama pull qwen2-vl:7b

Note: If those models already exist in Mission Control's Ollama instance,
they are automatically available — no separate pull needed.

Usage:
    python describe_documents.py                     # run with auto-detected backend
    python describe_documents.py --dry-run           # show what would be described
    python describe_documents.py --test              # describe 3 docs, print results
    python describe_documents.py --limit 10          # process at most N docs
    python describe_documents.py --force             # re-describe already-described docs
    python describe_documents.py --backend           # show which backend will be used
    python describe_documents.py --fallback-model qwen2-vl:7b  # prefer specific Ollama model
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.config import DB_PATH
from app.services.vision import (
    MC_HEALTH,
    describe_document,
    get_backend,
    get_visual_documents,
    grade_description,
    is_mc_available,
    list_vision_models,
)


def get_forced_candidates(conn, limit: int = 0) -> list[dict]:
    """Get all visual docs regardless of prior VLM description (for --force)."""
    sql = """
        SELECT d.id, d.title, d.file_extension, d.file_size_mb, d.local_path,
               d.request_pretty_id, COALESCE(SUM(LENGTH(dt.text_content)), 0) as total_chars
        FROM documents d
        LEFT JOIN document_text dt ON dt.document_id = d.id
        WHERE d.downloaded = 1
          AND d.local_path IS NOT NULL
          AND LOWER(d.file_extension) IN ('jpg','jpeg','png','tif','tiff','bmp','pdf')
        GROUP BY d.id
        HAVING total_chars < 10
        ORDER BY d.file_size_mb ASC
    """
    if limit > 0:
        sql += f" LIMIT {limit}"
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser(description="VLM document description batch script")
    parser.add_argument("--backend", action="store_true", help="Show which backend will be used and exit")
    parser.add_argument("--fallback-model", default="qwen2.5vl:7b",
                        help="Ollama model to use when MC is down (default: qwen2.5vl:7b)")
    parser.add_argument("--test", action="store_true", help="Test mode: describe 3 docs, print output")
    parser.add_argument("--dry-run", action="store_true", help="Show candidates without running")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N documents")
    parser.add_argument("--force", action="store_true", help="Re-describe already-described docs")
    parser.add_argument("--grade", action="store_true", help="Grade each description after generation")
    args = parser.parse_args()

    # Backend check mode
    if args.backend:
        backend = get_backend()
        mc_up = is_mc_available()
        vision_models = list_vision_models()

        print(f"Active backend:    {backend}")
        print(f"Mission Control:   {'UP' if mc_up else 'DOWN'} ({MC_HEALTH if mc_up else 'not responding'})")
        print(f"Ollama vision:     {vision_models if vision_models else 'none'}")
        if backend == "mc":
            print("  ->Will route through MC vision_model class (llama3.2-vision ->qwen2-vl ->haiku fallback)")
        elif backend == "ollama":
            print(f"  ->Will call Ollama directly with: {vision_models[0]}")
        else:
            print("  ->No backend available. Pull a model or start Mission Control.")
            print("    ollama pull llama3.2-vision:11b")
        return

    limit = 3 if args.test else args.limit

    # Check backend
    backend = get_backend()
    if backend == "none" and not args.dry_run:
        print("ERROR: No vision backend available.")
        print("  Option 1: Start Mission Control (port 8860)")
        print("  Option 2: Pull a local vision model:")
        print("    ollama pull llama3.2-vision:11b")
        print("    ollama pull qwen2-vl:7b")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))

    docs = get_forced_candidates(conn, limit=limit) if args.force else get_visual_documents(conn, limit=limit)

    if not docs:
        print("No documents need VLM description.")
        conn.close()
        return

    mode_str = " ".join(filter(None, [
        "DRY RUN" if args.dry_run else None,
        "TEST" if args.test else None,
    ])) or ""

    print(f"\n{'[' + mode_str + '] ' if mode_str else ''}"
          f"Documents to describe: {len(docs)}")
    print(f"Backend: {backend}"
          + (" (MC vision_model ->llama3.2-vision ->qwen2-vl ->haiku)" if backend == "mc"
             else f" ({args.fallback_model})"))
    print("-" * 60)

    if args.dry_run:
        for doc in docs:
            print(f"  [{doc['file_extension']}] {doc['title'][:50]} "
                  f"({doc['file_size_mb']:.1f} MB) id={doc['id']}")
        conn.close()
        return

    ok = failed = 0
    t_start = time.time()

    for i, doc in enumerate(docs, 1):
        doc_label = doc['title'] or f"doc {doc['id']}"
        ext = doc['file_extension']
        size_mb = doc['file_size_mb'] or 0

        print(f"[{i}/{len(docs)}] [{ext}] {doc_label[:50]} ({size_mb:.1f} MB)", end="", flush=True)

        result = describe_document(
            conn,
            doc_id=doc['id'],
            local_path=doc['local_path'],
            ext=ext,
            fallback_model=args.fallback_model,
        )

        if result['success']:
            ok += 1
            model_tag = result.get('model_id') or result['backend']
            print(f" ->{result['char_count']} chars [{model_tag}]")
            if args.test or args.grade:
                cur = conn.execute(
                    "SELECT text_content FROM document_text "
                    "WHERE document_id=? AND method='vlm_description' LIMIT 1",
                    (doc['id'],)
                )
                row = cur.fetchone()
                description = row[0] if row and row[0] else ""
                if args.test and description:
                    print(f"\n--- Description ---\n{description}\n---\n")
                if args.grade and description:
                    from app.services.vision import _build_context_prompt
                    context = _build_context_prompt(conn, doc['id'])
                    grade = grade_description(description, context)
                    if "error" in grade:
                        print(f"    Grade: ERROR ({grade['error'][:60]})")
                    else:
                        total = grade['weighted_total']
                        passed = "PASS" if grade['passed'] else "FAIL"
                        s = grade['scores']
                        print(f"    Grade: {total}/100 [{passed}] via {grade['grader_model']}")
                        print(f"      fields={s.get('field_completeness')}/10  "
                              f"gender={s.get('gender_stated')}/10  "
                              f"text={s.get('text_accuracy')}/10  "
                              f"redund={s.get('no_redundancy')}/10  "
                              f"spec={s.get('no_speculation')}/10  "
                              f"ctx={s.get('context_use')}/10")
                        if grade['notes']:
                            print(f"      Note: {grade['notes']}")
        else:
            failed += 1
            print(f" ->FAILED: {result['error'][:80]}")

    elapsed = time.time() - t_start
    conn.close()

    print("-" * 60)
    print(f"Done in {elapsed:.1f}s — {ok} described, {failed} failed")
    if ok and elapsed > 0:
        print(f"Avg: {elapsed / ok:.1f}s per document")


if __name__ == "__main__":
    main()
