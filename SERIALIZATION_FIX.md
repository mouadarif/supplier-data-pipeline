# Timestamp Serialization Fix

## Problem

The CSV output file `results/results_french_sirene.csv` contained serialization errors in the `error` column:

```
TypeError: Object of type Timestamp is not JSON serializable
```

This occurred because pandas `Timestamp` objects from Excel date columns (like "Date dern. Mouvt") were not being properly converted to strings before JSON serialization in several places.

## Root Causes

1. **Missing `default=str` in `arbitrate()` method**: The `GeminiLLM.arbitrate()` method in `llm_providers.py` was calling `json.dumps()` without `default=str`, causing failures when candidate dictionaries contained Timestamps.

2. **Pickling/Unpickling in Parallel Pipeline**: When data is pickled and sent to worker processes in `pipeline_parallel.py`, pandas Timestamps are preserved as Timestamp objects. The initial conversion in the main process wasn't sufficient because unpickled data might recreate Timestamps.

3. **Nested Structures**: Timestamps in nested dictionary structures might not have been caught by the initial conversion.

## Fixes Applied

### Fix 1: Added `default=str` to `arbitrate()` method

**File:** `llm_providers.py`

**Before:**
```python
f"A: {json.dumps(a, ensure_ascii=False)}\n"
f"B: {json.dumps(b, ensure_ascii=False)}\n"
```

**After:**
```python
f"A: {json.dumps(a, ensure_ascii=False, default=str)}\n"
f"B: {json.dumps(b, ensure_ascii=False, default=str)}\n"
```

### Fix 2: Deep cleaning in worker function

**File:** `pipeline_parallel.py`

Added recursive Timestamp cleaning in `_process_row_worker()` to ensure all Timestamps are converted before processing:

```python
def _clean_value(obj):
    """Recursively clean Timestamps and other non-serializable objects."""
    if obj is None:
        return None
    if not isinstance(obj, (dict, list, tuple)) and pd.isna(obj):
        return None
    if isinstance(obj, dict):
        return {k: _clean_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_value(item) for item in obj]
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat() if hasattr(obj, 'isoformat') else str(obj)
    if isinstance(obj, (int, float)) and math.isinf(obj):
        return None
    return obj

# Deep clean the raw dict before processing
raw = _clean_value(raw)
```

### Fix 3: Defensive check in sequential pipeline

**File:** `pipeline_manager.py`

Added a defensive check in `_process_batch()` to ensure raw dicts are fully cleaned:

```python
# FIX: Ensure raw dict is fully cleaned (defensive check)
raw = {k: _make_json_serializable(v) for k, v in raw.items()}
```

## Impact

- **Before:** Serialization errors caused rows to fail with `TypeError` messages in the error column
- **After:** All Timestamps are properly converted to ISO format strings before JSON serialization

## Testing

To verify the fix works:

1. Re-run the pipeline:
   ```bash
   python run.py parallel --supplier-xlsx Frs.xlsx --workers 8
   ```

2. Check the output CSV:
   ```bash
   # Should have no "TypeError: Object of type Timestamp" errors
   grep -c "TypeError.*Timestamp" results/results_french_sirene.csv
   # Should return 0
   ```

3. Verify successful matches:
   ```bash
   # Count successful matches (non-empty resolved_siret)
   python -c "import pandas as pd; df = pd.read_csv('results/results_french_sirene.csv'); print(f'Successful matches: {df[\"resolved_siret\"].notna().sum()}')"
   ```

## Files Modified

1. `llm_providers.py` - Added `default=str` to `arbitrate()` method
2. `pipeline_parallel.py` - Added deep cleaning in worker function
3. `pipeline_manager.py` - Added defensive check in batch processing

All fixes are backward compatible and improve robustness without changing the API.
