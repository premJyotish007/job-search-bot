# TODO: Scraper Feature Pipeline

## Upcoming Backlog

- [ ] **Limit database to top 100 unapplied jobs**:
  - Re-architect the save and merge flow in `merge_and_save_jobs` and `save_single_job_to_json` to cap the total stored unapplied listings at 100.
  - When new listings are scraped or merged, if the count of unapplied listings exceeds 100, prune the oldest unapplied entries (by job ID or scraping order) while preserving all applied listings.
