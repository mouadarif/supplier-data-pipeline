## Supplier → SIRENE local enrichment pipeline (DuckDB)

This folder contains a local, resumable pipeline to map dirty supplier rows from `Frs.xlsx` to the official French SIRENE database (local parquet files).

### What's included

**Core Pipeline:**
- `run.py`: **MAIN ENTRY POINT** - Unified CLI with all commands (init-db, sequential, parallel, unified)
- `preprocess_suppliers.py`: Preprocessing (country inference, filtering, splitting)
- `google_search_provider.py`: Google search for non-French suppliers
- `db_setup.py`: Builds DuckDB database + indexes, creates department partitions
- `matcher_logic.py`: Matching logic (DIRECT_ID → STRICT_LOCAL → FTS_BROAD → scoring/arbiter)
- `pipeline_manager.py`: Sequential batch processing + SQLite checkpointing
- `pipeline_parallel.py`: Parallel processing (4-8x faster)
- `llm_providers.py`: LLM clients (offline heuristic + Gemini API with caching)

**Note:** Old entry points (`run_pipeline.py`, `run_fast.py`, `run_unified_pipeline.py`) have been moved to `legacy/` folder. Use `run.py` instead.

**Performance & Analysis:**
- `profiler.py`: profiling utilities to measure bottlenecks
- `PERFORMANCE.md`: detailed performance analysis
- `RUST_VS_PYTHON_ANALYSIS.md`: Rust vs Python comparison
- `API_SETUP.md`: Gemini API setup guide

### Quickstart

```bash
# 1. Install dependencies
python -m pip install -r requirements.txt

# 2. Initialize database (one-time setup)
python run.py init-db --sample-row-groups 2

# 3. Run unified pipeline (recommended - preprocessing + SIRENE + Google)
python run.py unified --input-xlsx Frs.xlsx --limit-rows 200
```

### **🚀 UNIFIED PIPELINE (Recommended!)**

**Complete solution** - preprocessing + SIRENE + Google search:

```bash
# Run complete pipeline (preprocessing + French SIRENE + non-French Google)
python run.py unified --input-xlsx Frs.xlsx
```

This automatically:
- ✅ Identifies and infers countries from postal codes/cities
- ✅ Filters inactive suppliers (Date dern. Mouvt = null)
- ✅ Splits into French (SIRENE) and non-French (Google) groups
- ✅ Processes French suppliers with SIRENE matching (parallel, 5-8x faster)
- ✅ Processes non-French suppliers with Google search (threaded, 10x faster)
- ✅ Combines all results into one file with unified schema

**Options:**
```bash
# Skip preprocessing (use existing files)
python run.py unified --skip-preprocess

# Don't filter inactive suppliers
python run.py unified --no-filter-inactive

# Process only first 1000 rows
python run.py unified --limit-rows 1000

# Skip Google search (only process French)
python run.py unified --skip-google

# Skip SIRENE matching (only process non-French)
python run.py unified --skip-sirene

# Custom worker counts
python run.py unified --workers 8 --google-workers 20
```

### **⚡ PARALLEL MODE (French Suppliers Only, 5-8x Faster!)**

**For French suppliers only** - automatically optimized:

```bash
# Uses all CPU cores, avoids OneDrive locks
python run.py parallel --supplier-xlsx Frs.xlsx
```

**Expected time:**
- 2440 suppliers with API: 30-60 minutes (vs 3-7 hours sequential)
- 2440 suppliers offline: 5-10 minutes (vs 1-2 hours sequential)

**Options:**
```bash
# Custom workers
python run.py parallel --supplier-xlsx Frs.xlsx --workers 8

# Limit rows
python run.py parallel --supplier-xlsx Frs.xlsx --limit-rows 1000

# Use OneDrive checkpoint (slower)
python run.py parallel --supplier-xlsx Frs.xlsx --use-onedrive-checkpoint
```

### **Sequential Mode (Slower but Simpler)**

```bash
# Simple sequential processing
python run.py sequential --supplier-xlsx Frs.xlsx
```

### **Database Setup**

```bash
# Full database (takes longer with multi-GB parquets)
python run.py init-db

# Fast dev/test mode (first 2 row groups only)
python run.py init-db --sample-row-groups 2

# Force rebuild
python run.py init-db --force
```

See `PERFORMANCE_DEEP_ANALYSIS.md` for bottleneck analysis.

### Tests

```bash
pytest -q
```

