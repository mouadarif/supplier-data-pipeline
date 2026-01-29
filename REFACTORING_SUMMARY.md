# Refactoring Summary - Consolidated Entry Points

## ✅ Problem Solved

**Before:** Multiple entry point files doing similar things:
- `run_pipeline.py` - Sequential pipeline + init-db
- `run_fast.py` - Parallel pipeline wrapper
- `run_unified_pipeline.py` - Full unified pipeline

**After:** Single unified entry point:
- `run.py` - **ONE file** with subcommands for all functionality

---

## 📁 New Structure

### Main Entry Point: `run.py`

**Single command-line interface with subcommands:**

```bash
# Initialize database
python run.py init-db

# Sequential SIRENE matching (slower, simpler)
python run.py sequential --supplier-xlsx Frs.xlsx

# Parallel SIRENE matching (5-8x faster, recommended)
python run.py parallel --supplier-xlsx Frs.xlsx --workers 8

# Unified pipeline (preprocessing + SIRENE + Google)
python run.py unified --input-xlsx Frs.xlsx
```

### Core Modules (Unchanged)

These remain separate as they should be:
- `pipeline_manager.py` - Sequential pipeline logic
- `pipeline_parallel.py` - Parallel pipeline logic
- `preprocess_suppliers.py` - Preprocessing logic
- `google_search_provider.py` - Google search provider
- `matcher_logic.py` - Matching logic
- `llm_providers.py` - LLM providers
- `db_setup.py` - Database setup

---

## 🔄 Migration Guide

### Old → New Commands

| Old Command | New Command |
|------------|-------------|
| `python run_pipeline.py init-db` | `python run.py init-db` |
| `python run_pipeline.py run` | `python run.py sequential` |
| `python run_fast.py` | `python run.py parallel` |
| `python run_unified_pipeline.py` | `python run.py unified` |

### Deprecated Files

These files are now **deprecated** and can be deleted:
- ❌ `run_pipeline.py` → Use `run.py sequential` or `run.py init-db`
- ❌ `run_fast.py` → Use `run.py parallel`
- ❌ `run_unified_pipeline.py` → Use `run.py unified`

**Note:** Old files still work for backward compatibility, but `run.py` is the recommended entry point.

---

## 📋 Command Reference

### `init-db` - Initialize Database

```bash
python run.py init-db [OPTIONS]

Options:
  --duckdb-path PATH          DuckDB database path (default: sirene.duckdb)
  --ul-parquet PATH           Unite Legale parquet file
  --etab-parquet PATH         Etablissement parquet file
  --partitions-dir PATH       Partitions directory
  --sample-row-groups N       Fast dev/test mode (first N row groups)
  --force                     Force rebuild (overwrite existing)
```

### `sequential` - Sequential Pipeline

```bash
python run.py sequential [OPTIONS]

Options:
  --supplier-xlsx PATH        Input Excel file (default: Frs.xlsx)
  --duckdb-path PATH          DuckDB database (default: sirene.duckdb)
  --checkpoint-sqlite PATH    Checkpoint file (default: state.sqlite)
  --output-csv PATH           Output CSV (default: results_enriched.csv)
  --batch-size N              Batch size (default: 100)
  --limit-rows N              Limit to N rows
  --retry-errors              Retry failed rows
```

### `parallel` - Parallel Pipeline (Recommended)

```bash
python run.py parallel [OPTIONS]

Options:
  --supplier-xlsx PATH        Input Excel file (default: Frs.xlsx)
  --duckdb-path PATH          DuckDB database (default: sirene.duckdb)
  --checkpoint-sqlite PATH    Checkpoint file (default: state.sqlite)
  --output-csv PATH           Output CSV (default: results_enriched.csv)
  --batch-size N              Batch size (default: 100)
  --limit-rows N              Limit to N rows
  --workers N                 Number of workers (default: CPU count)
  --use-onedrive-checkpoint   Use OneDrive checkpoint (slower)
  --retry-errors              Retry failed rows
```

### `unified` - Unified Pipeline

```bash
python run.py unified [OPTIONS]

Options:
  --input-xlsx PATH           Input Excel file (default: Frs.xlsx)
  --duckdb-path PATH          DuckDB database (default: sirene.duckdb)
  --output-dir PATH            Output directory (default: results)
  --workers N                 SIRENE workers (default: CPU count)
  --google-workers N          Google search threads (default: 10)
  --limit-rows N              Limit to N rows
  --skip-preprocess           Skip preprocessing step
  --skip-google               Skip Google search
  --skip-sirene               Skip SIRENE matching
  --no-filter-inactive        Don't filter inactive suppliers
```

---

## ✅ Benefits

1. **Single Entry Point** - One file to remember: `run.py`
2. **Clear Commands** - Subcommands make it obvious what each does
3. **Consistent Interface** - All commands follow same pattern
4. **Better Help** - `python run.py --help` shows all options
5. **Easier Maintenance** - One file to update instead of three

---

## 🗑️ Cleanup (Optional)

You can safely delete these deprecated files:
```bash
# Backup first (optional)
mkdir -p deprecated
mv run_pipeline.py deprecated/
mv run_fast.py deprecated/
mv run_unified_pipeline.py deprecated/
```

Or keep them for backward compatibility - they still work!

---

## 📝 Examples

### Quick Start

```bash
# 1. Initialize database (one-time setup)
python run.py init-db

# 2. Run unified pipeline (recommended)
python run.py unified --input-xlsx Frs.xlsx

# 3. Or run just SIRENE matching (faster)
python run.py parallel --supplier-xlsx Frs.xlsx
```

### Advanced Usage

```bash
# Process first 100 rows with 8 workers
python run.py parallel --supplier-xlsx Frs.xlsx --limit-rows 100 --workers 8

# Unified pipeline with custom settings
python run.py unified \
    --input-xlsx Frs.xlsx \
    --workers 8 \
    --google-workers 20 \
    --output-dir my_results

# Skip preprocessing (use existing files)
python run.py unified --skip-preprocess
```

---

## ✅ Summary

**Refactored:** 3 entry point files → 1 unified `run.py`

**Result:** Cleaner, easier to use, easier to maintain! 🎉
