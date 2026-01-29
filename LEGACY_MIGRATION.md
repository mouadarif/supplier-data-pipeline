# Legacy Files Migration Complete ✅

## Summary

All deprecated entry point files and related documentation have been moved to the `legacy/` folder.

## Files Moved to `legacy/`

### Entry Point Files (Deprecated)
- ✅ `run_pipeline.py` → Use `run.py sequential` or `run.py init-db`
- ✅ `run_fast.py` → Use `run.py parallel`
- ✅ `run_unified_pipeline.py` → Use `run.py unified`

### Documentation Files
- ✅ `QUICK_START_FAST.md` → See main `README.md` for updated instructions

## Current Structure

```
.
├── run.py                    # ✅ MAIN ENTRY POINT (use this!)
├── pipeline_manager.py       # Core modules (unchanged)
├── pipeline_parallel.py
├── preprocess_suppliers.py
├── google_search_provider.py
├── ...
└── legacy/                   # 📦 Deprecated files
    ├── README.md            # Explains what's here
    ├── run_pipeline.py      # Old entry point
    ├── run_fast.py          # Old entry point
    ├── run_unified_pipeline.py  # Old entry point
    └── QUICK_START_FAST.md  # Old documentation
```

## Migration Guide

| Old Command | New Command |
|------------|-------------|
| `python run_pipeline.py init-db` | `python run.py init-db` |
| `python run_pipeline.py run` | `python run.py sequential` |
| `python run_fast.py` | `python run.py parallel` |
| `python run_unified_pipeline.py` | `python run.py unified` |

## Why Keep Legacy Files?

1. **Backward Compatibility** - Old scripts/workflows may reference them
2. **Reference** - To understand codebase evolution
3. **Gradual Migration** - Teams can migrate at their own pace

## Recommendation

**Use `run.py`** - It's the modern, unified entry point with all functionality.

See `legacy/README.md` for more details.
