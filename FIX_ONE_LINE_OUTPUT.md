# Fix: Only One Line in Output

## Problem Identified

You're seeing only **1 line** in the output because:

1. **Preprocessing was run with `--limit-rows`** (small number like 7 or 10)
   - This limited the input to only a few rows
   - After filtering inactive suppliers, only 6 French + 1 non-French remained

2. **French SIRENE matching hasn't run yet** or failed
   - `results/results_french_sirene.csv` is **empty (0 rows)**
   - Only non-French Google search ran (1 row)
   - Combined file = 0 + 1 = **1 row**

## Solution

### Option 1: Run WITHOUT limits (Recommended)

```bash
# Run complete pipeline WITHOUT --limit-rows
python run_unified_pipeline.py

# This will process ALL 2440 suppliers:
# - Filter out 1017 inactive (Date dern. Mouvt = null)
# - Process 797 French suppliers (SIRENE)
# - Process 626 non-French suppliers (Google)
```

### Option 2: Check which file you're looking at

The pipeline creates multiple output files:

1. **Preprocessed files** (intermediate):
   - `preprocessed/suppliers_french.xlsx` - Should have **797 rows**
   - `preprocessed/suppliers_non_french.xlsx` - Should have **626 rows**

2. **Final results** (after processing):
   - `results/results_french_sirene.csv` - French suppliers with SIRET matches
   - `results/results_non_french_google.csv` - Non-French suppliers with web data
   - `results/results_combined.csv` - Combined results

**If you're looking at `results_combined.csv` and it only has 1 row:**
- The French SIRENE matching hasn't completed yet
- Run the pipeline again or check for errors

### Option 3: Re-run preprocessing only

```bash
# Re-run preprocessing to fix the files
python quick_test_preprocessing.py

# This will create:
# - preprocessed/suppliers_french.xlsx (797 rows)
# - preprocessed/suppliers_non_french.xlsx (626 rows)
```

## Verification

Check the files:

```bash
python check_output_files.py
```

Expected output:
- `preprocessed/suppliers_french.xlsx`: **797 rows** ✅
- `preprocessed/suppliers_non_french.xlsx`: **626 rows** ✅
- `results/results_french_sirene.csv`: **0 rows** (until SIRENE matching runs)
- `results/results_non_french_google.csv`: **1 row** (if only 1 was processed)
- `results/results_combined.csv`: **1 row** (until both processes complete)

## Next Steps

1. **Re-run preprocessing** (if files are wrong):
   ```bash
   python quick_test_preprocessing.py
   ```

2. **Run full pipeline** (without limits):
   ```bash
   python run_unified_pipeline.py
   ```

3. **Check results**:
   ```bash
   python check_output_files.py
   ```

## Common Issues

### Issue: Files still have only a few rows

**Cause:** You ran with `--limit-rows 10` or similar

**Fix:** Run without `--limit-rows`:
```bash
python run_unified_pipeline.py  # No --limit-rows flag!
```

### Issue: French results CSV is empty

**Cause:** SIRENE matching hasn't run or failed

**Fix:** Check for errors and ensure DuckDB database exists:
```bash
python run_pipeline.py init-db  # If database doesn't exist
python run_unified_pipeline.py --skip-preprocess  # Skip preprocessing, run matching
```

### Issue: Only seeing header row

**Cause:** Excel might be showing only header if file is empty or corrupted

**Fix:** Check file with pandas:
```python
import pandas as pd
df = pd.read_excel("preprocessed/suppliers_french.xlsx")
print(f"Rows: {len(df)}")
```

---

**The preprocessing has been fixed and should now create 797 French + 626 non-French rows!**
