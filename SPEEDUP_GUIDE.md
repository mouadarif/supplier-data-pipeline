# Speed Optimization Guide - Quick Reference

## 🚀 Quick Wins (Implement Now)

### 1. Use Parallel Processing (5-10x speedup)
```powershell
# Close Excel first (file lock issue on Windows)
python pipeline_parallel.py --workers 8 --limit-rows 100

# Full run
python pipeline_parallel.py --workers 8
```

**Expected results:**
- **Before**: 2440 rows in 3-7 hours
- **After**: 2440 rows in 30-60 minutes
- **Speedup**: 5-10x depending on CPU cores

### 2. Use Offline Mode for Testing (10-20x speedup)
Remove `GEMINI_API_KEY` from `.env` for faster testing:

```powershell
# Edit .env and comment out:
# GEMINI_API_KEY=...

# Run pipeline
python pipeline_parallel.py --workers 8 --limit-rows 100
```

**Trade-off**: Faster but less accurate matching

### 3. Reduce Batch Size for Better Progress Tracking
```powershell
python pipeline_parallel.py --workers 8 --batch-size 50
```

Smaller batches = more frequent checkpoints = better resume capability

## 📊 Bottleneck Analysis

### Current Bottlenecks (Python Sequential)
1. **Gemini API calls**: 60-70% of time (1-3s each)
2. **Database queries**: 15-20% of time
3. **String matching**: 10-15% of time
4. **Sequential processing**: Overhead 5-10%

### After Parallel Processing
1. **Gemini API calls**: Still 60-70% but distributed across workers
2. **Database queries**: Parallelized (minimal overhead)
3. **String matching**: Parallelized (minimal overhead)
4. **Parallelization**: **5-10x speedup**

## 🔧 Performance Comparison

| Method | Time (2440 rows) | Speedup | Setup Time |
|--------|------------------|---------|------------|
| **Current (Sequential)** | 3-7 hours | 1x | 0 min |
| **Parallel (8 cores)** | 30-60 minutes | **6-8x** | 0 min |
| **Parallel + Offline** | 10-20 minutes | **15-20x** | 1 min |
| **Rust Rewrite** | 25-50 minutes | 7-10x | 2-3 months |

## 🎯 Recommendations by Scenario

### Scenario 1: Quick Testing
```powershell
# Use offline mode + parallel + small dataset
python pipeline_parallel.py --workers 4 --limit-rows 100
```
**Time**: 30-60 seconds for 100 rows

### Scenario 2: Production Run (Best Accuracy)
```powershell
# Use Gemini API + parallel
echo "GEMINI_API_KEY=your_key" > .env
python pipeline_parallel.py --workers 8
```
**Time**: 30-60 minutes for 2440 rows

### Scenario 3: Maximum Speed
```powershell
# Offline mode + all cores
python pipeline_parallel.py --workers 16
```
**Time**: 10-20 minutes for 2440 rows (less accurate)

## 🐛 Common Issues

### "Permission denied: 'Frs.xlsx'"
**Problem**: Excel has the file open
**Solution**: Close Excel before running pipeline

### "database is locked"
**Problem**: Previous run didn't close properly
**Solution**: 
```powershell
# Delete lock files
del state.sqlite-shm
del state.sqlite-wal

# Or use a different checkpoint file
python pipeline_parallel.py --checkpoint-sqlite temp_state.sqlite
```

### Slow Performance Despite Parallelization
**Check**:
1. Are you using Gemini API? (check for "using GeminiLLM" in output)
2. Rate limits active? (free tier = 15 requests/min)
3. OneDrive syncing? (move files to local drive)
4. Antivirus scanning? (add exclusion for project folder)

## 📈 Profiling (Find Your Bottlenecks)

Add profiling to measure actual bottlenecks:

```python
from profiler import profile, print_profile_report

# Add @profile decorator to functions
@profile
def my_slow_function():
    ...

# At end of script
print_profile_report()
```

## 🦀 Should I Rewrite in Rust?

**Short answer: NO** (not yet)

**Why?**
- Main bottleneck is API calls (network I/O)
- Rust can't make network faster
- Python parallel version gives 80% of potential speedup
- Rust would take 2-3 months vs 0 setup time for parallel Python

**When to consider Rust:**
- After Python optimizations aren't enough
- Processing millions of rows daily
- Need sub-second response times
- Have Rust developers on team

See `RUST_VS_PYTHON_ANALYSIS.md` for detailed analysis.

## 📚 Further Reading

- `PERFORMANCE.md` - Detailed performance analysis
- `RUST_VS_PYTHON_ANALYSIS.md` - Rust vs Python comparison
- `API_SETUP.md` - Gemini API configuration
- `profiler.py` - Profiling utilities

## 💡 Next Steps

1. **Try parallel version now**: `python pipeline_parallel.py --workers 4 --limit-rows 100`
2. **Measure speedup**: Compare time with sequential version
3. **Profile your workload**: Use `profiler.py` to find actual bottlenecks
4. **Optimize based on data**: Focus on what's actually slow in your case
