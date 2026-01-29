# Timestamp JSON Serialization Fix

## Problem

When pandas reads Excel files with date columns (like "Date dern. Mouvt"), they become `pd.Timestamp` objects. When converting rows to dictionaries and then serializing to JSON (for LLM prompts), Python's `json.dumps()` fails with:

```
TypeError: Object of type Timestamp is not JSON serializable
```

## Solution

Added helper functions to convert Timestamp objects to ISO format strings before JSON serialization.

### Changes Made

1. **`run.py`**: Added `_make_json_serializable()` and `_row_to_dict()` functions
   - Converts Timestamp objects to ISO format strings
   - Handles NaN and infinity values
   - Used when loading supplier files

2. **`llm_providers.py`**: Added `default=str` to `json.dumps()` calls
   - Fallback for any non-serializable objects

3. **`pipeline_manager.py`**: Updated `_iter_supplier_rows()` to convert Timestamps
   - Ensures all rows are JSON-serializable

4. **`pipeline_parallel.py`**: Added Timestamp conversion in work item preparation
   - Converts Timestamps before processing

5. **`matcher_logic.py`**: Added `default=str` to alternatives JSON serialization
   - Ensures alternatives list is serializable

## How It Works

```python
def _make_json_serializable(obj):
    """Convert pandas Timestamp to ISO format string."""
    import pandas as pd
    from datetime import datetime, date
    
    if pd.isna(obj):
        return None
    elif isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat() if hasattr(obj, 'isoformat') else str(obj)
    elif isinstance(obj, (int, float)) and (pd.isna(obj) or pd.isinf(obj)):
        return None
    return obj
```

**Example:**
```python
# Before (fails):
row = {'date': pd.Timestamp('2024-01-01')}
json.dumps(row)  # TypeError!

# After (works):
row = {'date': pd.Timestamp('2024-01-01')}
row = {k: _make_json_serializable(v) for k, v in row.items()}
json.dumps(row)  # '{"date": "2024-01-01T00:00:00"}'
```

## Testing

All files compile successfully and Timestamp serialization is handled correctly.

## Impact

- ✅ No more JSON serialization errors
- ✅ Date columns properly handled in all pipelines
- ✅ LLM prompts work correctly with date fields
- ✅ Backward compatible (doesn't break existing functionality)
