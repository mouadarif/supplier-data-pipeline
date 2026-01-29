# Legacy Files

This folder contains deprecated files that have been replaced by the unified `run.py` entry point.

## Deprecated Entry Points

These files are **deprecated** but still work for backward compatibility:

- `run_pipeline.py` → Use `run.py sequential` or `run.py init-db`
- `run_fast.py` → Use `run.py parallel`
- `run_unified_pipeline.py` → Use `run.py unified`

## Deprecated Documentation

- `QUICK_START_FAST.md` → See main `README.md` for updated instructions

## Migration Guide

See `../REFACTORING_COMPLETE.md` for migration instructions.

## Why These Files Exist

These files are kept for:
1. **Backward compatibility** - Old scripts/workflows may reference them
2. **Reference** - To understand the evolution of the codebase
3. **Gradual migration** - Teams can migrate at their own pace

## Recommendation

**Use `run.py` instead** - It's the modern, unified entry point with all functionality.

```bash
# Old way (deprecated)
python run_fast.py

# New way (recommended)
python run.py parallel
```
