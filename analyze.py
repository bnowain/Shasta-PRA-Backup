#!/usr/bin/env python3
"""
Quick analysis tool for the NextRequest backup database.

Usage:
    python analyze.py                          # Overview
    python analyze.py --search "Sinner"        # Search request text
    python analyze.py --department "Sheriff"    # Filter by department
    python analyze.py --contact "Volberg"       # Filter by POC
    python analyze.py --export-csv              # Export all to CSV
"""

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("shasta_nextrequest_backup/nextrequest.db")

def connect():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)

def overview(conn):
    print("=" * 60)
    print("  NextRequest Backup Database")
    print("=" * 60)

    r = lambda q: conn.execute(q).fetchone()[0]
    print(f"\n  Requests:           {r('SELECT COUNT(*) FROM requests')}")
    print(f"  Details scraped:    {r('SELECT COUNT(*) FROM requests WHERE detail_scraped=1')}")
    print(f"  Timeline events:    {r('SELECT COUNT(*) FROM timeline_events')}")
    print(f"  Documents listed:   {r('SELECT COUNT(*) FROM documents')}")
    print(f"  Documents saved:    {r('SELECT COUNT(*) FROM documents WHERE downloaded=1')}")
    print(f"  Departments:        {r('SELECT COUNT(*) FROM departments')}")

    print("\n  Status breakdown:")
    for row in conn.execute("SELECT COALESCE(request_state,'?'), COUNT(*) FROM requests GROUP BY request_state ORDER BY COUNT(*) DESC"):
        print(f"    {row[0]:.<30} {row[1]}")

    print("\n  Top departments:")
    for row in conn.execute("SELECT COALESCE(department_names,'?'), COUNT(*) FROM requests GROUP BY department_names ORDER BY COUNT(*) DESC LIMIT 15"):
        print(f"    {row[0][:45]:.<47} {row[1]}")

    print("\n  Top points of contact:")
    for row in conn.execute("SELECT COALESCE(poc_name,'?'), COUNT(*) FROM requests GROUP BY poc_name ORDER BY COUNT(*) DESC LIMIT 10"):
        print(f"    {row[0]:.<30} {row[1]}")

    print("\n  Submit types:")
    for row in conn.execute("SELECT COALESCE(request_submit_type,'?'), COUNT(*) FROM requests WHERE detail_scraped=1 GROUP BY request_submit_type ORDER BY COUNT(*) DESC"):
        print(f"    {row[0]:.<30} {row[1]}")

    print("\n  Requests with most documents:")
    for row in conn.execute("SELECT request_pretty_id, COUNT(*) as n FROM documents GROUP BY request_pretty_id ORDER BY n DESC LIMIT 10"):
        print(f"    {row[0]:.<20} {row[1]} docs")

    mb = conn.execute("SELECT COALESCE(SUM(file_size_bytes),0)/1048576.0 FROM documents WHERE downloaded=1").fetchone()[0]
    print(f"\n  Total downloaded:   {mb:.1f} MB")

    errors = conn.execute("SELECT COUNT(*) FROM scrape_log WHERE action IN ('error','download_fail','download_error','no_url')").fetchone()[0]
    if errors:
        print(f"\n  ⚠️  Errors: {errors}")

def search(conn, q):
    rows = conn.execute("""
        SELECT pretty_id, request_state, poc_name, substr(request_text,1,250), page_url
        FROM requests WHERE request_text LIKE ? OR request_text_html LIKE ?
        ORDER BY pretty_id DESC
    """, (f'%{q}%', f'%{q}%')).fetchall()
    print(f"\nFound {len(rows)} results for '{q}':\n")
    for r in rows:
        print(f"  [{r[0]}] {r[1] or '?'} — POC: {r[2] or '?'}")
        if r[3]: print(f"    {r[3][:200]}...")
        print(f"    {r[4]}\n")

def by_department(conn, dept):
    rows = conn.execute("""
        SELECT pretty_id, request_state, department_names, poc_name, substr(request_text,1,200)
        FROM requests WHERE department_names LIKE ?
        ORDER BY pretty_id DESC
    """, (f'%{dept}%',)).fetchall()
    print(f"\n{len(rows)} requests for department '{dept}':\n")
    for r in rows:
        print(f"  [{r[0]}] {r[1]} — {r[2]} — POC: {r[3] or '?'}")
        if r[4]: print(f"    {r[4][:150]}...")
        print()

def by_contact(conn, name):
    rows = conn.execute("""
        SELECT pretty_id, request_state, department_names, poc_name, substr(request_text,1,200)
        FROM requests WHERE poc_name LIKE ?
        ORDER BY pretty_id DESC
    """, (f'%{name}%',)).fetchall()
    print(f"\n{len(rows)} requests for POC '{name}':\n")
    for r in rows:
        print(f"  [{r[0]}] {r[1]} — {r[2]}")
        if r[4]: print(f"    {r[4][:150]}...")
        print()

def export_csv(conn):
    out = Path("shasta_nextrequest_backup/requests_export.csv")
    rows = conn.execute("""
        SELECT pretty_id, request_state, request_text, department_names,
               poc_name, request_date, request_submit_type, due_date, page_url
        FROM requests ORDER BY pretty_id DESC
    """).fetchall()
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['ID','Status','Text','Departments','POC','Date','Submit Type','Due','URL'])
        w.writerows(rows)
    print(f"Exported {len(rows)} requests to {out}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--search', type=str)
    p.add_argument('--department', type=str)
    p.add_argument('--contact', type=str)
    p.add_argument('--export-csv', action='store_true')
    args = p.parse_args()

    conn = connect()
    if args.search: search(conn, args.search)
    elif args.department: by_department(conn, args.department)
    elif args.contact: by_contact(conn, args.contact)
    elif args.export_csv: export_csv(conn)
    else: overview(conn)
    conn.close()

if __name__ == "__main__":
    main()
