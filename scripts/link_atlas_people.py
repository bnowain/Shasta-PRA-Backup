#!/usr/bin/env python3
"""
Populate PRA people table and request_people links.

Sources:
  1. poc_name — county staff contacts (structured field, always populated)
  2. Atlas unified people — search all 2,700+ names against request_text;
     create request_people links where found.

Run from anywhere:
  python3 Shasta-PRA-Backup/scripts/link_atlas_people.py

Options:
  --dry-run     Show what would be inserted without writing
  --atlas-url   Atlas API base URL (default: http://127.0.0.1:8888)
  --db          Path to PRA database (default: auto-detected)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PRA_DB_DEFAULT = Path(__file__).parent.parent / "shasta_nextrequest_backup" / "nextrequest.db"
ATLAS_API_DEFAULT = "http://127.0.0.1:8888"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def open_read_db(path: str) -> sqlite3.Connection:
    """Read-only connection using immutable URI — avoids WAL lock on NTFS/WSL."""
    db = sqlite3.connect(f"file:///{path}?immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    return db


def open_write_db(path: str) -> sqlite3.Connection:
    """Write connection — use BEGIN IMMEDIATE to avoid upgrade-lock failures on NTFS/WSL."""
    db = sqlite3.connect(path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("PRAGMA wal_checkpoint(PASSIVE)")
    return db


# ---------------------------------------------------------------------------
# Steps 1 & 2: Read phase (immutable connection), Write phase (IMMEDIATE txn)
# WSL/NTFS requires separating reads and writes to avoid lock escalation errors.
# ---------------------------------------------------------------------------

def fetch_atlas_people(atlas_url: str) -> list[dict]:
    url = f"{atlas_url}/api/people?limit=10000"
    try:
        resp = urllib.request.urlopen(url, timeout=30)
        return json.loads(resp.read())
    except Exception as e:
        print(f"ERROR: Could not reach Atlas at {atlas_url}: {e}", file=sys.stderr)
        print("Make sure Atlas is running (python run.py from Atlas/)", file=sys.stderr)
        sys.exit(1)


def read_phase(rdb: sqlite3.Connection, atlas_people: list[dict], dry_run: bool) -> dict:
    """
    Read phase: collect all insertions needed without writing anything.
    Returns: {
      staff_to_add: list[str],           # new poc_name entries
      people_to_link: list[(name, [request_ids])],  # Atlas people with matches
      existing_people: dict[name -> id], # pre-loaded from DB
    }
    """
    # Staff
    staff_rows = rdb.execute(
        "SELECT DISTINCT poc_name FROM requests WHERE poc_name IS NOT NULL AND poc_name != '' ORDER BY poc_name"
    ).fetchall()
    existing_names = {r[0] for r in rdb.execute("SELECT canonical_name FROM people").fetchall()}
    staff_to_add = [r[0].strip() for r in staff_rows if r[0].strip() and r[0].strip() not in existing_names]

    if staff_to_add:
        print(f"  Staff to add: {len(staff_to_add)}")
        for n in staff_to_add:
            print(f"    [staff] {n}")
    else:
        print(f"  Staff: all {len(staff_rows)} already present")

    # Atlas people → request_text matching
    existing_people = {r[0]: r[1] for r in rdb.execute("SELECT canonical_name, id FROM people").fetchall()}
    people_to_link = []

    for person in atlas_people:
        display_name = person["display_name"]
        aliases = person.get("aliases") or []
        all_names = [display_name] + aliases

        matched: set[str] = set()
        for name in all_names:
            rows = rdb.execute(
                "SELECT pretty_id FROM requests WHERE request_text LIKE ?",
                (f"%{name}%",),
            ).fetchall()
            for row in rows:
                matched.add(row[0])

        if matched:
            people_to_link.append((display_name, sorted(matched)))
            print(f"  {display_name}: {len(matched)} request(s)")

    return {
        "staff_to_add": staff_to_add,
        "people_to_link": people_to_link,
        "existing_people": existing_people,
    }


def write_phase(wdb: sqlite3.Connection, plan: dict) -> dict:
    """Write phase: single BEGIN IMMEDIATE transaction for all inserts."""
    staff_to_add = plan["staff_to_add"]
    people_to_link = plan["people_to_link"]
    existing_people = plan["existing_people"]  # mutable — updated as we insert

    people_added = 0
    links_added = 0

    wdb.execute("BEGIN IMMEDIATE")

    # Insert staff
    for name in staff_to_add:
        wdb.execute("INSERT OR IGNORE INTO people (canonical_name, role) VALUES (?, 'staff')", (name,))

    # Insert subjects + links
    for display_name, request_ids in people_to_link:
        if display_name not in existing_people:
            wdb.execute(
                "INSERT OR IGNORE INTO people (canonical_name, role) VALUES (?, 'subject')",
                (display_name.strip(),),
            )
            person_id = wdb.execute("SELECT last_insert_rowid()").fetchone()[0]
            existing_people[display_name] = person_id
            people_added += 1
        else:
            person_id = existing_people[display_name]

        for rid in request_ids:
            wdb.execute(
                "INSERT OR IGNORE INTO request_people (request_pretty_id, person_id, role, source) VALUES (?, ?, 'subject', 'atlas_name_match')",
                (rid, person_id),
            )
            if wdb.execute("SELECT changes()").fetchone()[0] > 0:
                links_added += 1

    wdb.execute("COMMIT")

    return {
        "staff_added": len(staff_to_add),
        "people_added": people_added,
        "people_with_links": len(people_to_link),
        "links_added": links_added,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Populate PRA people from poc_name and Atlas")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    parser.add_argument("--atlas-url", default=ATLAS_API_DEFAULT)
    parser.add_argument("--db", default=str(PRA_DB_DEFAULT))
    args = parser.parse_args()

    if args.dry_run:
        print("[DRY RUN — no changes will be written]\n")

    db_path = args.db

    # --- Read phase (immutable connection) ---
    print("Step 1 & 2: Read phase — scanning poc_name and request_text...")
    rdb = open_read_db(db_path)
    atlas_people = fetch_atlas_people(args.atlas_url)
    print(f"  Atlas unified people: {len(atlas_people)}\n")
    plan = read_phase(rdb, atlas_people, args.dry_run)
    rdb.close()

    if args.dry_run:
        print(f"\n[DRY RUN] Would add: {len(plan['staff_to_add'])} staff, "
              f"{len(plan['people_to_link'])} people with links")
        return

    # --- Write phase (separate connection, BEGIN IMMEDIATE) ---
    print("\nStep 3: Write phase — inserting people and links...")
    wdb = open_write_db(db_path)
    stats = write_phase(wdb, plan)

    # --- Summary ---
    total_people = wdb.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    total_links = wdb.execute("SELECT COUNT(*) FROM request_people").fetchone()[0]
    wdb.close()

    print(f"\nResults:")
    print(f"  Staff added:                 {stats['staff_added']}")
    print(f"  Atlas people with PRA links: {stats['people_with_links']}")
    print(f"  New subjects added:          {stats['people_added']}")
    print(f"  New request-person links:    {stats['links_added']}")
    print(f"\nPRA database totals:")
    print(f"  People: {total_people}")
    print(f"  Request-person links: {total_links}")



if __name__ == "__main__":
    main()
