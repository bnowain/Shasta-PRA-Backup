# Shasta PRA Backup — Next Session TODO

## Verify After Backfill
- [ ] Run `python start.py`, navigate to a record with documents (e.g., 25-200)
- [ ] Click a PDF in the documents table — lightbox should render it inline
- [ ] Click "Pull" button — should report "everything up to date" if backfill is complete
- [ ] Check record 26-185 — should now have timeline events and documents

## Test the Pull Button End-to-End
- [ ] Verify SSE progress overlay: phases 1→2→3→4 with status messages
- [ ] Verify "already running" guard if clicked twice
- [ ] Verify error handling (disconnect wifi, try pull)
- [ ] Verify "Done" button reloads page with fresh data

## Known Issues to Fix
- [ ] Stale server processes on Windows — `start.py` has port-kill but needs testing
- [ ] PDF lightbox was untested after the `Content-Disposition` + path fix (server couldn't restart due to stale PIDs)
- [ ] The scrape router's `from scraper import ...` assumes `scraper.py` is on `sys.path` — works when started from project root but may break if CWD differs

## Future Enhancements
- [ ] Phase 2 page-level progress in Pull overlay (currently reports start/end only)
- [ ] Add "Download Files" as separate optional button (for Phase 4 only on demand)
- [ ] Add last-scraped timestamp display in topbar or footer
- [ ] Consider adding a "Force Refresh" option to re-scrape specific records on demand
- [ ] Update Atlas RAG index after a pull (re-run pre_index.py)
