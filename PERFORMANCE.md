# Performance Analysis & Optimization Guide

## Why Processing Takes So Long (1 Day for 2440 Suppliers)

### Main Bottlenecks

1. **Gemini API Calls** (MAJOR)
   - Each row requires 1-2 LLM API calls (cleaning + optional arbitration)
   - Gemini rate limits: ~15 requests/minute for free tier
   - Latency: ~1-3 seconds per call
   - **Impact**: With 2440 rows × 2 seconds = 81 minutes minimum (just API calls)

2. **Database Queries Per Row**
   - FTS search across entire database
   - Parquet file reads for establishments
   - Levenshtein distance calculations in Python
   - **Impact**: ~2-5 seconds per row

3. **No Parallelization**
   - Sequential processing (one row at a time)
   - **Impact**: Cannot utilize multiple CPU cores

4. **Fuzzy String Matching**
   - Multiple rapidfuzz calculations per candidate
   - Levenshtein distance on addresses
   - **Impact**: ~0.5-1 second per row with multiple candidates

### Estimated Time Breakdown (per row)
- Gemini API cleaning: 1-3 seconds
- Direct SIRET lookup: 0.1 seconds
- FTS search: 0.5-1 second
- Fetch establishments: 0.5-1 second
- Fuzzy matching: 0.5-1 second
- Gemini arbitration (if needed): 1-3 seconds

**Total per row**: 3-10 seconds
**For 2440 rows**: 2-7 hours (best case) to 1-2 days (with rate limits)

## Optimizations Implemented

### 1. LLM Response Caching ✅
- Cache cleaning results by (name, address, postal, city)
- Avoids redundant API calls for duplicate suppliers
- **Speedup**: 30-50% if duplicates exist

### 2. Progress Indicators ✅
- Shows processed count, percentage, rate, and ETA
- Helps monitor progress and detect issues

### 3. .env File from Root ✅
- Explicit path resolution for API key loading
- More reliable configuration

## Further Optimizations (Not Yet Implemented)

### High Impact
1. **Batch Gemini API Calls**
   - Group multiple cleaning requests into one call
   - Potential speedup: 3-5x

2. **Parallel Processing**
   - Use multiprocessing.Pool for batch processing
   - Potential speedup: 4-8x (depends on CPU cores)

3. **Pre-cache DuckDB Results**
   - Load all FTS index results into memory
   - Potential speedup: 2-3x for search operations

4. **Skip Gemini for Direct Matches**
   - If SIRET is found directly, don't call LLM
   - Already implemented ✅

### Medium Impact
5. **Use Gemini Pro Instead of Flash**
   - Faster response times
   - Higher rate limits (paid tier)

6. **Reduce FTS Limit**
   - Currently fetching top 20 candidates
   - Could reduce to 5-10 for speed

7. **Early Exit Optimization**
   - Stop processing once high-confidence match found
   - Already partially implemented ✅

## Recommendations

### For Production Use
1. **Get a Gemini API paid tier** - removes rate limits
2. **Run on a dedicated server** - better I/O and no OneDrive sync overhead
3. **Use multiprocessing** - split workload across CPU cores
4. **Pre-process duplicates** - deduplicate suppliers before processing

### For Current Setup
1. **Run overnight** - let it complete unattended
2. **Use checkpointing** - can pause/resume anytime (already implemented ✅)
3. **Monitor with ETA** - new progress indicators show expected completion time
4. **Check cache effectiveness** - review logs for cache hits

## How to Monitor Progress
```powershell
# Run with progress tracking
python run_pipeline.py run

# Example output:
# [pipeline] processed=100/2440 (4%) | rate=0.15 rows/sec | ETA=260.0 mins
# [pipeline] processed=200/2440 (8%) | rate=0.18 rows/sec | ETA=207.0 mins
```

## Quick Win: Use Offline Mode
If you don't need LLM-level accuracy, remove the API key:
```powershell
# In .env file, comment out or remove:
# GEMINI_API_KEY=...

# Run pipeline (will use fast offline heuristic)
python run_pipeline.py run
```
**Speedup**: 10-20x faster (2-4 hours instead of 20+ hours)
