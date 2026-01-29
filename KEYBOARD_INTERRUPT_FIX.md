# KeyboardInterrupt Handling Fix

## Problem

When user presses Ctrl+C during pipeline execution, especially during ThreadPoolExecutor operations, the cleanup can hang or fail, leaving the process in an inconsistent state.

## Solution

Added proper KeyboardInterrupt handling to:

1. **Gracefully save progress** before exiting
2. **Cancel remaining tasks** without waiting
3. **Provide clear messages** about what was saved
4. **Enable resume** by running the same command again

## Changes Made

### 1. `run.py` - `process_non_french_suppliers()`

**Before:**
```python
with ThreadPoolExecutor(max_workers=max_workers) as executor:
    for i, future in enumerate(as_completed(future_to_row), 1):
        # Process results...
# No interrupt handling - hangs on cleanup
```

**After:**
```python
try:
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        try:
            for i, future in enumerate(as_completed(future_to_row), 1):
                # Process results...
        except KeyboardInterrupt:
            logger.warning("⚠️  Interrupted by user (Ctrl+C)")
            logger.info(f"Saving {len(results)} completed results...")
            # Cancel remaining futures
            for future in future_to_row:
                future.cancel()
            # Don't wait for executor shutdown
            executor.shutdown(wait=False)
            raise
except KeyboardInterrupt:
    # Save partial results
    if results:
        # Save to CSV...
    raise
```

### 2. `run.py` - `cmd_run_unified()`

Added try/except around entire pipeline to catch interrupts and show what was saved.

### 3. `run.py` - `cmd_run_parallel()` and `cmd_run_sequential()`

Added KeyboardInterrupt handling with checkpoint save messages.

### 4. `pipeline_parallel.py` - `run_pipeline_parallel()`

Added KeyboardInterrupt handling in the processing loop to:
- Save progress immediately
- Terminate pool without waiting
- Commit checkpoint

## Behavior on Ctrl+C

### Before Fix:
- Hangs during ThreadPoolExecutor cleanup
- May lose progress
- Unclear error messages

### After Fix:
- ✅ Immediately saves completed results
- ✅ Cancels remaining tasks
- ✅ Shows clear message about what was saved
- ✅ Can resume by running same command again

## Example Output on Interrupt

```
[pipeline] ⚠️  Interrupted by user (Ctrl+C)
[pipeline] Saving progress... (150/1000 processed)
[2026-01-27 20:31:27] [WARNING] ⚠️  PIPELINE INTERRUPTED BY USER (Ctrl+C)
[2026-01-27 20:31:27] [INFO] Partial results may have been saved:
[2026-01-27 20:31:27] [INFO]   French (SIRENE):     results/results_french_sirene.csv (150 rows)
[2026-01-27 20:31:27] [INFO] 
[2026-01-27 20:31:27] [INFO] You can resume by running the same command again.
[2026-01-27 20:31:27] [INFO] Already processed rows will be skipped automatically.
```

## Resume Capability

The pipeline automatically skips already-processed rows:

```bash
# First run (interrupted at 150/1000)
python run.py unified --input-xlsx Frs.xlsx
# Ctrl+C pressed

# Resume (starts from row 151)
python run.py unified --input-xlsx Frs.xlsx
# Automatically skips first 150 rows
```

## Testing

All KeyboardInterrupt scenarios handled:
- ✅ Interrupt during Google search (ThreadPoolExecutor)
- ✅ Interrupt during SIRENE matching (multiprocessing Pool)
- ✅ Interrupt during preprocessing
- ✅ Interrupt during result combination

## Summary

**Fixed:** KeyboardInterrupt handling for graceful shutdown
**Result:** Pipeline can be safely interrupted and resumed! ✅
