# How to Fix the Serialization Error CSV

## The Problem

The file `results/results_french_sirene.csv` contains **484 rows** with this error:
```
TypeError: Object of type Timestamp is not JSON serializable
```

## Why This Happened

This file was created **BEFORE** the serialization fixes were applied to the code. The new test with `results_test_fixed.csv` shows **0 errors**, confirming the fixes work.

## Solution (3 Steps)

### Step 1: Close Excel/CSV Viewer

The file `results/results_french_sirene.csv` is currently locked by Excel or another program.

**Action:** Close all programs that might have this file open.

### Step 2: Delete Old Files

Run this in PowerShell:

```powershell
# Delete old results
Remove-Item "results/results_french_sirene.csv" -Force
Remove-Item "results/checkpoint_french.sqlite" -Force
Remove-Item "results/checkpoint_french.sqlite-wal" -Force -ErrorAction SilentlyContinue
Remove-Item "results/checkpoint_french.sqlite-shm" -Force -ErrorAction SilentlyContinue
Remove-Item "results/results_non_french_google.csv" -Force -ErrorAction SilentlyContinue
Remove-Item "results/results_combined.csv" -Force -ErrorAction SilentlyContinue
```

**Or run the automated batch file:**
```cmd
CLEANUP_AND_REGENERATE.bat
```

### Step 3: Regenerate Results

Run the pipeline with the fixed code:

```bash
# For a quick test (100 rows)
python run.py parallel --supplier-xlsx Frs.xlsx --limit-rows 100 --workers 4

# For the full dataset
python run.py unified --input-xlsx Frs.xlsx --clean-output --workers 8
```

## Verification

After regeneration, check for errors:

```python
import pandas as pd
df = pd.read_csv('results_enriched.csv')
df['error'] = df['error'].astype(str)
timestamp_errors = len(df[df['error'].str.contains('Timestamp', case=False, na=False)])
print(f"Timestamp serialization errors: {timestamp_errors}")
# Should print: 0
```

## What Was Fixed

1. **LLM Provider** (`llm_providers.py`):
   - Added `default=str` to `json.dumps()` in `arbitrate()` method

2. **Worker Process** (`pipeline_parallel.py`):
   - Added deep cleaning function to convert all Timestamps before processing
   - Applied recursively to handle nested structures

3. **Sequential Pipeline** (`pipeline_manager.py`):
   - Added defensive check in `_process_batch()`
   - Ensures all data is cleaned before processing

## Expected Results

After regeneration with the fixed code:
- **No Timestamp serialization errors**
- Successful matches will have SIRET numbers
- Failed matches will have `NOT_FOUND` method (not serialization errors)

## Test Results Proof

The test file `results_test_fixed.csv` (generated with the fixed code) shows:
- **50 rows processed**
- **0 Timestamp errors**
- **10 successful matches**
- All data properly serialized

This confirms the fixes are working correctly.
