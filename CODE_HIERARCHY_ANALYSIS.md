# Code Hierarchy Analysis & Cleanup Plan

## Import Hierarchy (from run.py)

```
run.py (Main Entry Point)
├── db_setup.py
│   └── (stdlib only: duckdb, pyarrow)
│
├── google_search_provider.py
│   └── google.genai (external)
│
├── pipeline_manager.py (Sequential Pipeline)
│   ├── llm_providers.py
│   │   └── google.genai (external)
│   └── matcher_logic.py
│       ├── llm_providers.py (circular but OK - uses CleanedSupplier)
│       └── rapidfuzz (external)
│
├── pipeline_parallel.py (Parallel Pipeline)
│   ├── llm_providers.py
│   ├── matcher_logic.py
│   └── pipeline_manager.py (uses PipelineConfig, StateStore, get_input_id)
│
└── preprocess_suppliers.py
    └── (stdlib only: pandas)
```

## Core Modules (KEEP)

### Essential Pipeline Files:
1. **run.py** - Main CLI entry point ✅
2. **db_setup.py** - Database initialization ✅
3. **pipeline_manager.py** - Sequential pipeline ✅
4. **pipeline_parallel.py** - Parallel pipeline ✅
5. **matcher_logic.py** - Core matching logic ✅
6. **llm_providers.py** - LLM interface ✅
7. **preprocess_suppliers.py** - Preprocessing ✅
8. **google_search_provider.py** - Google search ✅

## Files to Clean Up

### Test Files (Move to tests/ or delete):
- `test_*.py` (all test files)
- `verify_*.py`
- `diagnose_*.py`
- `quick_test_*.py`
- `run_tests_*.py`

### Utility/Example Files (Not Used in Pipeline):
- `_inspect_frs.py` - Inspection utility
- `batch_gemini_example.py` - Example only
- `check_output_files.py` - Utility
- `demo_improvements.py` - Demo
- `inspect_parquet_columns.py` - Utility
- `profiler.py` - Not imported
- `prompts.py` - Not imported
- `regenerate_results.py` - Utility script
- `CLEANUP_AND_REGENERATE.bat` - Utility script

### Configuration Files (KEEP):
- `.env.example` ✅
- `pytest.ini` ✅ (for tests)

## Performance Issues Found

### 1. Parallel Processing (pipeline_parallel.py)
**Current**: Uses `multiprocessing.Pool` - each worker creates its own LLM client
**Issue**: No connection pooling, each worker initializes Gemini client separately
**Impact**: Slower startup, no shared connection reuse

### 2. No Batch API Calls
**Current**: Each row makes 1-2 individual API calls
**Issue**: Not batching multiple rows into single API call
**Impact**: 5-10x slower than it could be

### 3. Sequential API Calls in Workers
**Current**: Workers process rows sequentially within each worker
**Issue**: Even with multiprocessing, each worker waits for API response
**Impact**: Not fully utilizing parallelism for I/O-bound operations

### 4. No Async/Await for API Calls
**Current**: Synchronous API calls block worker threads
**Issue**: Workers wait for network I/O instead of processing other rows
**Impact**: Underutilized parallelism

## Optimization Plan

### Phase 1: Clean Up Unused Code
1. Move all test files to `tests/` directory
2. Delete utility/example files not used in pipeline
3. Remove unused imports

### Phase 2: Optimize Parallel Processing
1. Add connection pooling for Gemini clients
2. Implement batch API calls (group 10-20 rows per call)
3. Use async/await for API calls within workers
4. Add worker-level batching

### Phase 3: Performance Monitoring
1. Add timing metrics for each component
2. Log bottleneck identification
3. Add performance profiling hooks
