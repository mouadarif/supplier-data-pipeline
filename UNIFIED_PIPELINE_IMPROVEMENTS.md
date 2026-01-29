# Unified Pipeline Improvements

## ✅ Critical Improvements Applied

### 1. **Schema Alignment (CRITICAL FIX)**

**Problem:**
- French (SIRENE) output: `input_id`, `resolved_siret`, `official_name`, `confidence_score`, `match_method`, `alternatives`, `error`
- Non-French (Google) output: `input_id`, `company_name`, `country`, `city`, `postal_code`, `found_website`, `found_address`, `found_phone`, `found_email`, `confidence_score`, `search_method`
- **Result:** When concatenating, many empty columns and mismatched schemas!

**Solution:**
Created **unified schema** with all columns from both sources:

```python
unified_schema = [
    "input_id",           # Common
    "resolved_siret",     # SIRENE-only (empty for Google)
    "official_name",      # Common (company_name → official_name for Google)
    "confidence_score",  # Common
    "match_method",       # Common (search_method → match_method for Google)
    "alternatives",       # SIRENE-only (empty for Google)
    "found_website",      # Google-only (empty for SIRENE)
    "found_address",     # Google-only (empty for SIRENE)
    "found_phone",       # Google-only (empty for SIRENE)
    "found_email",       # Google-only (empty for SIRENE)
    "country",           # Google-only (empty for SIRENE)
    "city",              # Google-only (empty for SIRENE)
    "postal_code",       # Google-only (empty for SIRENE)
    "search_method",     # Google-only (empty for SIRENE)
    "error",             # Common
]
```

**Changes:**
- ✅ `google_search_provider.py`: `result_to_row()` now outputs unified schema
- ✅ `pipeline_manager.py`: `export_csv()` now outputs unified schema
- ✅ `run_unified_pipeline.py`: Combination logic ensures schema alignment

---

### 2. **Google Search Concurrency (Performance)**

**Problem:**
- Sequential processing: `for idx, row in df.iterrows()`
- If 5,000 suppliers × 1 sec/API call = **~1.5 hours**!

**Solution:**
- ✅ Added `ThreadPoolExecutor` for I/O-bound API calls
- ✅ Default 10 threads (optimal for I/O-bound tasks)
- ✅ Configurable via `--google-workers` argument

**Before:**
```python
for idx, row in df.iterrows():
    result = provider.search_supplier(raw)
    results.append(provider.result_to_row(result))
# Sequential: 5000 rows × 1 sec = 5000 sec (~1.4 hours)
```

**After:**
```python
with ThreadPoolExecutor(max_workers=10) as executor:
    future_to_row = {executor.submit(_search_wrapper, row): row for row in work_items}
    for future in as_completed(future_to_row):
        res = future.result()
        if res:
            results.append(res)
# Parallel: 5000 rows ÷ 10 threads × 1 sec = 500 sec (~8 minutes)
# **Speedup: ~10x faster!**
```

**Benefits:**
- ✅ ~10x speedup for I/O-bound Google API calls
- ✅ Better CPU utilization (threads wait for I/O in parallel)
- ✅ Progress reporting as results complete
- ✅ Error handling per item (one failure doesn't stop others)

---

### 3. **Error Handling**

**Improvements:**
- ✅ Wrapper function catches exceptions per item
- ✅ Errors logged but don't stop processing
- ✅ Error rows included in output with `error` field populated
- ✅ Graceful handling of missing result files

**Error Row Format:**
```python
{
    "input_id": "...",
    "error": "ValueError: API rate limit exceeded",
    "confidence_score": 0.0,
    "match_method": "ERROR",
    # ... other fields empty
}
```

---

### 4. **Progress Reporting**

**Before:**
```python
if idx % 10 == 0:
    print(f"[Google] Progress: {idx}/{len(df)}")
# Only reports every 10 items, no rate/ETA
```

**After:**
```python
if i % 10 == 0 or i == total_items:
    elapsed = time.time() - start_time
    rate = i / elapsed if elapsed > 0 else 0
    remaining = total_items - i
    eta_mins = (remaining / rate) / 60 if rate > 0 else 0
    print(f"[Google] Progress: {i}/{total_items} | rate={rate:.1f}/s | ETA={eta_mins:.1f}m")
# Reports every 10 items with rate and ETA
```

**Benefits:**
- ✅ Real-time progress updates
- ✅ Processing rate (items/second)
- ✅ ETA calculation
- ✅ Better visibility into pipeline health

---

## 📊 Performance Comparison

### Google Search Processing

| Approach | Time (5000 suppliers) | Speedup |
|----------|----------------------|---------|
| **Sequential** | ~1.4 hours | 1x |
| **Threaded (10 workers)** | ~8 minutes | **10x** |

### Schema Alignment

| Approach | Columns | Empty Columns | Issues |
|----------|---------|---------------|--------|
| **Before** | Mismatched | Many | Can't combine properly |
| **After** | Unified (15 cols) | Expected | Clean combination ✅ |

---

## 🔧 Usage

### Basic Usage
```bash
python run_unified_pipeline.py
```

### With Custom Thread Count
```bash
python run_unified_pipeline.py --google-workers 20
```

### Skip Steps
```bash
# Skip Google search (only process French)
python run_unified_pipeline.py --skip-google

# Skip SIRENE (only process non-French)
python run_unified_pipeline.py --skip-sirene
```

### Limit Rows
```bash
# Process first 100 suppliers
python run_unified_pipeline.py --limit-rows 100
```

---

## 📋 Unified Schema Reference

All output files (French, non-French, combined) use this schema:

| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `input_id` | string | Both | Supplier identifier |
| `resolved_siret` | string | SIRENE | French company SIRET |
| `official_name` | string | Both | Company name (official for SIRENE, found for Google) |
| `confidence_score` | float | Both | Match confidence (0.0-1.0) |
| `match_method` | string | Both | How match was found |
| `alternatives` | string | SIRENE | JSON of alternative matches |
| `found_website` | string | Google | Company website URL |
| `found_address` | string | Google | Full business address |
| `found_phone` | string | Google | Phone number |
| `found_email` | string | Google | Contact email |
| `country` | string | Google | Country code |
| `city` | string | Google | City name |
| `postal_code` | string | Google | Postal code |
| `search_method` | string | Google | Search method used |
| `error` | string | Both | Error message if processing failed |

**Note:** Empty columns are expected:
- SIRENE results: `found_*`, `country`, `city`, `postal_code`, `search_method` are empty
- Google results: `resolved_siret`, `alternatives` are empty

---

## ✅ Summary

**Improvements:**
1. ✅ **Schema alignment** - Unified 15-column schema for both sources
2. ✅ **Threading** - ~10x speedup for Google search (I/O-bound)
3. ✅ **Error handling** - Per-item error handling, graceful failures
4. ✅ **Progress reporting** - Real-time updates with rate and ETA

**Result:** Faster, more robust, and properly aligned unified pipeline! 🚀
