# Parallel Pipeline Improvements

## ✅ Key Improvements Applied

### 1. **`imap_unordered` for Better Load Balancing**

**Before:**
```python
# Process in chunks - waits for entire chunk before yielding results
for chunk_start in range(0, len(worker_args), chunk_size):
    results = pool.map(_process_row_worker, chunk_args)  # Blocks until ALL done
    # Process results...
```

**After:**
```python
# Yields results as soon as they're ready - better load balancing
iterator = pool.imap_unordered(_process_row_worker, worker_args, chunksize=1)
for input_id, result, error in iterator:  # Processes as they complete
    # Handle result immediately...
```

**Benefits:**
- ✅ Results processed as soon as workers finish (no waiting for slowest worker)
- ✅ Better CPU utilization (workers stay busy)
- ✅ More responsive progress reporting
- ✅ Handles variable processing times better

---

### 2. **Incremental Commits**

**Before:**
```python
# Commit only after entire chunk completes
for chunk in chunks:
    results = pool.map(...)
    for result in results:
        state.upsert_result(result)
    state.commit()  # Only commits at chunk boundaries
```

**After:**
```python
# Commit every batch_size items as they complete
for input_id, result, error in iterator:
    if result:
        state.upsert_result(result)
    processed_count += 1
    
    if processed_count % cfg.batch_size == 0:
        state.commit()  # Frequent commits = less data loss risk
```

**Benefits:**
- ✅ More frequent checkpoints (reduces data loss risk)
- ✅ Progress visible sooner
- ✅ Better for long-running jobs

---

### 3. **Simplified Checkpoint Handling**

**Before:**
```python
# Try to modify frozen dataclass (problematic)
cfg = PipelineConfig(...)  # Recreate entire config
```

**After:**
```python
# Use local variable for checkpoint path
try:
    state = StateStore(cfg.checkpoint_sqlite)
    cfg_checkpoint = cfg.checkpoint_sqlite
except sqlite3.OperationalError:
    fallback = ...
    state = StateStore(fallback)
    cfg_checkpoint = fallback  # Simple variable, no dataclass modification
```

**Benefits:**
- ✅ Cleaner code
- ✅ No need to recreate frozen dataclass
- ✅ Easier to understand

---

### 4. **Better Progress Reporting**

**Before:**
```python
# Only reports at chunk boundaries
print(f"[pipeline] processed={processed}/{total_to_process} ...")
# Might wait minutes between reports if chunk is large
```

**After:**
```python
# Reports every batch_size items (as they complete)
if processed_count % cfg.batch_size == 0:
    print(f"[pipeline] {processed_count}/{total_to_process} | rate={rate:.1f}/s | ETA={eta_mins:.1f}m")
# More frequent, responsive updates
```

**Benefits:**
- ✅ More frequent progress updates
- ✅ Better visibility into pipeline health
- ✅ More accurate ETA (updates as work completes)

---

### 5. **Consistent ID Calculation**

**Before:**
```python
# ID calculated in main loop
input_id = get_input_id(raw)
# But also recalculated in worker (inconsistent)
```

**After:**
```python
# Re-calculate ID inside worker to be safe
input_id = str(raw.get("Auxiliaire") or raw.get("Code tiers") or raw.get("index"))
# Comment clarifies this is intentional for safety
```

**Benefits:**
- ✅ Explicit about ID recalculation
- ✅ Defensive programming (handles edge cases)
- ✅ Clear intent

---

## 📊 Performance Comparison

### Old Approach (Chunked `pool.map`)
- **Latency:** Must wait for slowest worker in chunk
- **Throughput:** Good for uniform workloads
- **Progress:** Only at chunk boundaries
- **Checkpoints:** Only at chunk boundaries

### New Approach (`imap_unordered`)
- **Latency:** Processes results immediately
- **Throughput:** Better for variable workloads (LLM calls, network I/O)
- **Progress:** Every `batch_size` items
- **Checkpoints:** Every `batch_size` items

---

## 🎯 Use Cases Where This Helps

1. **Variable Processing Times**
   - LLM API calls have variable latency
   - Some suppliers harder to match than others
   - **Benefit:** Fast workers don't wait for slow ones

2. **Long-Running Jobs**
   - Processing thousands of suppliers
   - **Benefit:** Frequent checkpoints reduce data loss risk

3. **Monitoring & Debugging**
   - Need to see progress in real-time
   - **Benefit:** More frequent progress updates

4. **Resource Utilization**
   - Want to keep all CPU cores busy
   - **Benefit:** Better load balancing across workers

---

## 🔧 Configuration

The improvements maintain backward compatibility:

```python
cfg = PipelineConfig(
    supplier_xlsx="Frs.xlsx",
    batch_size=100,  # Commits every 100 items
    limit_rows=None,  # Process all
)

run_pipeline_parallel(cfg, num_workers=8)
```

**Key Parameters:**
- `batch_size`: How often to commit (default: 100)
- `num_workers`: Parallel workers (default: CPU count)
- `chunksize=1`: Keeps workers responsive (can increase for very fast tasks)

---

## ✅ Summary

**Improvements:**
1. ✅ `imap_unordered` for better load balancing
2. ✅ Incremental commits (every `batch_size` items)
3. ✅ Simplified checkpoint handling
4. ✅ Better progress reporting
5. ✅ Consistent ID calculation

**Result:** More responsive, efficient, and robust parallel pipeline! 🚀
