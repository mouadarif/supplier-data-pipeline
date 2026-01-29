# ✅ Refactoring Complete - Single Entry Point

## Summary

**Before:** 3 separate entry point files (`run_pipeline.py`, `run_fast.py`, `run_unified_pipeline.py`)

**After:** 1 unified entry point (`run.py`) with subcommands

---

## 🎯 New Entry Point: `run.py`

### Commands

```bash
# Initialize database
python run.py init-db

# Sequential pipeline (slower, simpler)
python run.py sequential --supplier-xlsx Frs.xlsx

# Parallel pipeline (5-8x faster, recommended for French only)
python run.py parallel --supplier-xlsx Frs.xlsx --workers 8

# Unified pipeline (preprocessing + SIRENE + Google, recommended)
python run.py unified --input-xlsx Frs.xlsx
```

---

## 📋 Migration Guide

| Old Command | New Command |
|------------|-------------|
| `python run_pipeline.py init-db` | `python run.py init-db` |
| `python run_pipeline.py run` | `python run.py sequential` |
| `python run_fast.py` | `python run.py parallel` |
| `python run_unified_pipeline.py` | `python run.py unified` |

---

## 🗑️ Deprecated Files (Can Be Deleted)

These files are now **deprecated** but still work for backward compatibility:

- ❌ `run_pipeline.py` → Use `run.py sequential` or `run.py init-db`
- ❌ `run_fast.py` → Use `run.py parallel`
- ❌ `run_unified_pipeline.py` → Use `run.py unified`

**Recommendation:** Keep them for now, delete later once you're comfortable with `run.py`.

---

## ✅ Benefits

1. **Single Entry Point** - One file to remember: `run.py`
2. **Clear Commands** - Subcommands make purpose obvious
3. **Consistent Interface** - All commands follow same pattern
4. **Better Help** - `python run.py --help` shows all options
5. **Easier Maintenance** - One file instead of three

---

## 📖 Quick Reference

### Initialize Database
```bash
python run.py init-db [--sample-row-groups N] [--force]
```

### Sequential Pipeline
```bash
python run.py sequential --supplier-xlsx Frs.xlsx [--limit-rows N]
```

### Parallel Pipeline (Fast!)
```bash
python run.py parallel --supplier-xlsx Frs.xlsx --workers 8
```

### Unified Pipeline (Complete Solution!)
```bash
python run.py unified --input-xlsx Frs.xlsx --workers 8 --google-workers 20
```

---

## 🎉 Result

**Cleaner, simpler, easier to use!** All functionality consolidated into one entry point.
