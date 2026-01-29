# Performance and Safety Fixes

This document describes critical performance bugs that were fixed in `run.py`.

## Fix 1: Critical Performance Bug - Quadratic Complexity in CSV Loading

### Problem
In `_load_supplier_file()`, the script attempted to read large CSVs in chunks to save memory. However, inside the loop, it called `pd.concat(chunks)` on **every iteration** to check the total row count.

**The Issue:** `pd.concat` creates a *new* copy of the entire DataFrame every time. If you have 100 chunks, you are copying the growing dataset 100 times (O(n²) complexity). For a 1GB file, this will quickly consume all RAM and freeze the CPU.

### Solution
Track the number of rows using an integer counter instead of concatenating DataFrames.

**Before:**
```python
for chunk in pd.read_csv(...):
    chunks.append(chunk)
    if limit_rows and len(pd.concat(chunks, ignore_index=True)) >= limit_rows:  # BUG!
        break
df = pd.concat(chunks, ignore_index=True)
```

**After:**
```python
chunks = []
total_rows = 0  # Track rows with integer counter

for chunk in pd.read_csv(...):
    chunks.append(chunk)
    total_rows += len(chunk)
    
    # Check limit using counter, not expensive concat operation
    if limit_rows and total_rows >= limit_rows:
        # Trim last chunk if needed
        if total_rows > limit_rows:
            excess = total_rows - limit_rows
            chunks[-1] = chunks[-1].iloc[:-excess]
        break

# Concat only ONCE at the end
df = pd.concat(chunks, ignore_index=True)
```

### Impact
- **Before:** O(n²) complexity, could freeze on large files
- **After:** O(n) complexity, handles files of any size efficiently

---

## Fix 2: Concurrency Issue - Ineffective Rate Limiting

### Problem
In `process_non_french_suppliers()`, the rate limiting logic (`time.sleep`) was placed *inside* the parallel worker threads.

**The Issue:** If you have 10 workers and a 1-second delay, all 10 workers will fire their requests simultaneously, sleep for 1 second, and then fire 10 more simultaneously. This creates "bursts" of traffic that can still trigger API 429 (Too Many Requests) errors, rather than a smooth 1-request-per-second flow.

### Solution
Throttle the **submission** of tasks to the executor, not the execution. This ensures tasks are spaced out evenly.

**Before:**
```python
def _search_wrapper(row_data):
    result = provider.search_supplier(row_data)
    if rate_limit_delay > 0:
        time.sleep(rate_limit_delay)  # All workers sleep simultaneously!
    return provider.result_to_row(result)

# Submit all tasks instantly
future_to_row = {executor.submit(_search_wrapper, row): row for row in work_items}
```

**After:**
```python
def _search_wrapper(row_data):
    result = provider.search_supplier(row_data)
    return provider.result_to_row(result)  # No sleep here

# Throttle task submission
future_to_row = {}
for i, row in enumerate(work_items):
    # Distribute delay across workers to smooth out submission rate
    if rate_limit_delay > 0 and i > 0:
        time.sleep(rate_limit_delay / max_workers)
    
    future = executor.submit(_search_wrapper, row)
    future_to_row[future] = row
```

### Impact
- **Before:** Burst pattern (10 requests → sleep → 10 requests → sleep)
- **After:** Smooth pattern (1 request every 0.1s with 10 workers)

---

## Fix 3: Pipeline Safety - Stale Data Risk

### Problem
In `cmd_run_unified()`, the script merges results based on `Path(...).exists()`.

**The Issue:** If you run the pipeline once, then run it again with `--skip-google`, the script will see the `results_non_french_google.csv` from the *previous* run and merge it with the *new* SIRENE results. This creates a mix of fresh and stale data without warning.

### Solution
Add a warning system and optional cleanup flag to prevent accidental stale data merging.

**Before:**
```python
if Path(french_output_csv).exists():
    df_french = pd.read_csv(french_output_csv)  # Could be stale!
    results.append(df_french)
```

**After:**
```python
# Check for old files before running
old_files = []
if Path(french_output_csv).exists():
    old_files.append(french_output_csv)
if Path(non_french_output_csv).exists():
    old_files.append(non_french_output_csv)
if Path(combined_output_csv).exists():
    old_files.append(combined_output_csv)

if old_files:
    logger.warning("WARNING: Old output files detected from previous run!")
    for f in old_files:
        mod_time = datetime.fromtimestamp(Path(f).stat().st_mtime)
        logger.warning(f"  - {f} (last modified: {mod_time})")
    
    if args.clean_output:
        logger.info("Cleaning old output files...")
        for f in old_files:
            Path(f).unlink()
    else:
        logger.warning("These files will be merged with new results!")
        logger.warning("Use --clean-output flag to automatically delete old files.")
```

### Usage
```bash
# Run with automatic cleanup
python run.py unified --input-xlsx Frs.xlsx --clean-output

# Run without cleanup (will warn about stale files)
python run.py unified --input-xlsx Frs.xlsx
```

### Impact
- **Before:** Silent stale data merging
- **After:** Explicit warning + optional cleanup

---

## Summary

| Issue | Severity | Impact | Status |
|-------|----------|--------|--------|
| Quadratic CSV loading | Critical | Could freeze on large files | ✅ Fixed |
| Ineffective rate limiting | High | API rate limit errors | ✅ Fixed |
| Stale data merging | Medium | Data quality issues | ✅ Fixed |

All fixes are backward compatible and improve performance and safety without changing the API.
