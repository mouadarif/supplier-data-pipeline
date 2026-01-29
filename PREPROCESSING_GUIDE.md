# Preprocessing Guide - Country Inference & Supplier Filtering

## Overview

The preprocessing step identifies suppliers by country, filters inactive suppliers, and splits them into two groups:
- **French suppliers** → Processed with SIRENE matching (existing pipeline)
- **Non-French suppliers** → Processed with Google search (new functionality)

---

## Features

### 1. Column Identification
Automatically identifies columns in your Excel file:
- `Nom` / `Name` / `Company Name`
- `Postal` / `Code Postal` / `Postal Code`
- `Ville` / `City` / `Commune`
- `Pays` / `Country` / `Country Code`
- `Date dern. Mouvt` / `Last Movement Date`

### 2. Country Inference
If `Pays` column is empty, the system infers country from:

**Priority Order:**
1. **Postal Code Pattern**
   - French: 5 digits (e.g., `75001`, `69001`)
   - French Overseas: 97xxx or 98xxx (e.g., `97100`, `97400`)
   
2. **City Name**
   - Recognizes common French cities (Paris, Lyon, Marseille, etc.)
   - Detects French city patterns (Saint-, Le, La, Les, etc.)

3. **Fallback**
   - If cannot infer → marked as `UNKNOWN`
   - Unknown suppliers go to non-French group

### 3. Inactive Supplier Filtering
Suppliers with `Date dern. Mouvt = null` are **filtered out** by default.

**Rationale:** These suppliers haven't had any activity and may not need enrichment.

**Override:** Use `--no-filter-inactive` flag to include them.

### 4. Supplier Splitting
After preprocessing, suppliers are split into:

| Group | Destination | Processing Method |
|-------|-------------|------------------|
| **French** | `preprocessed/suppliers_french.xlsx` | SIRENE matching (DuckDB) |
| **Non-French** | `preprocessed/suppliers_non_french.xlsx` | Google search (Gemini API) |

---

## Usage

### Standalone Preprocessing

```python
from preprocess_suppliers import preprocess_suppliers

french_path, non_french_path, stats = preprocess_suppliers(
    input_xlsx="Frs.xlsx",
    output_dir="preprocessed",
    filter_inactive=True,
    limit_rows=None,  # Process all rows
)

print(f"French suppliers: {stats['french_suppliers']}")
print(f"Non-French suppliers: {stats['non_french_suppliers']}")
```

### Integrated Pipeline

```bash
# Run complete pipeline (preprocessing + SIRENE + Google)
python run_unified_pipeline.py

# Skip preprocessing (use existing files)
python run_unified_pipeline.py --skip-preprocess

# Don't filter inactive suppliers
python run_unified_pipeline.py --no-filter-inactive

# Process only first 1000 rows
python run_unified_pipeline.py --limit-rows 1000
```

---

## Example

### Input (`Frs.xlsx`)

| Auxiliaire | Nom | Postal | Ville | Pays | Date dern. Mouvt |
|------------|-----|--------|-------|------|------------------|
| FRS001 | CARREFOUR MARKET | 75001 | PARIS | FRANCE | 2024-01-15 |
| FRS002 | AMAZON FRANCE | 75008 | PARIS | | 2024-02-20 |
| FRS003 | APPLE INC | | CUPERTINO | | None |
| FRS004 | TESCO UK | SW1A 1AA | LONDON | UK | 2024-03-10 |

### Preprocessing Results

**French Suppliers** (`preprocessed/suppliers_french.xlsx`):
- FRS001: CARREFOUR MARKET (has Pays=FRANCE)
- FRS002: AMAZON FRANCE (inferred from postal code 75008)

**Non-French Suppliers** (`preprocessed/suppliers_non_french.xlsx`):
- FRS004: TESCO UK (Pays=UK)

**Filtered Out** (inactive):
- FRS003: APPLE INC (Date dern. Mouvt = null)

---

## Country Inference Logic

### French Detection

**Postal Code:**
```python
# Standard French postal codes
"75001" → FRANCE ✅
"69001" → FRANCE ✅
"13014" → FRANCE ✅

# French overseas territories
"97100" → FRANCE ✅ (Guadeloupe)
"97400" → FRANCE ✅ (Réunion)
"98800" → FRANCE ✅ (New Caledonia)

# Non-French
"SW1A 1AA" → Not French (UK format)
"90210" → Not French (US format)
```

**City Name:**
```python
# Direct matches
"PARIS" → FRANCE ✅
"LYON" → FRANCE ✅
"MARSEILLE" → FRANCE ✅

# Pattern matches
"SAINT-DENIS" → FRANCE ✅ (contains "SAINT-")
"LE HAVRE" → FRANCE ✅ (contains "LE ")
"LA ROCHELLE" → FRANCE ✅ (contains "LA ")
```

### Non-French Detection

If postal code doesn't match French pattern AND city is not recognized as French:
- Marked as non-French
- Sent to Google search pipeline

---

## Configuration

### Column Mapping

The system tries multiple column name variations:

| Standard Name | Possible Variations |
|--------------|---------------------|
| `Nom` | `NAME`, `NOM FOURNISSEUR`, `SUPPLIER NAME`, `COMPANY NAME`, `RAISON SOCIALE` |
| `Postal` | `CODE POSTAL`, `CP`, `ZIP`, `ZIP CODE`, `POSTCODE`, `POSTAL CODE` |
| `Ville` | `CITY`, `COMMUNE`, `LOCALITE` |
| `Pays` | `COUNTRY`, `PAYS FOURNISSEUR`, `COUNTRY CODE` |
| `Date dern. Mouvt` | `DATE DERNIER MOUVEMENT`, `LAST MOVEMENT DATE`, `DERNIER MOUVEMENT` |

---

## Statistics Output

After preprocessing, you get:

```python
{
    'total_original': 1000,        # Original row count
    'filtered_inactive': 50,       # Filtered out (Date dern. Mouvt = null)
    'french_suppliers': 800,       # Sent to SIRENE matching
    'non_french_suppliers': 150,  # Sent to Google search
    'total_processed': 950,       # Total to process
}
```

---

## Integration with Pipeline

### Step-by-Step Flow

```
┌─────────────────────────────────────┐
│ INPUT: Frs.xlsx                     │
│ - Nom, Postal, Ville, Pays         │
│ - Date dern. Mouvt                 │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│ PREPROCESSING                       │
│ 1. Identify columns                │
│ 2. Infer countries                  │
│ 3. Filter inactive                  │
│ 4. Split by country                 │
└─────────────────────────────────────┘
           ↓
    ┌──────┴──────┐
    ↓             ↓
┌─────────┐  ┌──────────────┐
│ FRENCH  │  │ NON-FRENCH   │
│         │  │              │
│ SIRENE  │  │ GOOGLE       │
│ MATCHING│  │ SEARCH       │
└─────────┘  └──────────────┘
    ↓             ↓
┌─────────────────────────────┐
│ COMBINED RESULTS            │
│ - French: SIRET + official │
│ - Non-French: website +    │
│   contact info              │
└─────────────────────────────┘
```

---

## Troubleshooting

### Issue: Column Not Found

**Error:** `Missing required columns: ['Nom']`

**Solution:** Check your Excel file column names. The system looks for:
- Case-insensitive matches
- Common variations (see Column Mapping section)

**Fix:** Rename columns to match standard names, or update `identify_columns()` function.

### Issue: All Suppliers Marked as UNKNOWN

**Possible Causes:**
1. Postal codes not in French format
2. City names not recognized
3. Pays column empty and cannot infer

**Solution:**
1. Check postal code format (should be 5 digits for France)
2. Add more city names to `FRENCH_CITIES` set
3. Fill Pays column in Excel file

### Issue: Too Many Suppliers Filtered Out

**Cause:** `Date dern. Mouvt` column has many null values

**Solution:** Use `--no-filter-inactive` flag to include all suppliers

---

## Performance

- **Preprocessing Speed:** ~1000 rows/second
- **Memory:** Minimal (pandas DataFrame operations)
- **Output:** Two Excel files (French + Non-French)

---

## Next Steps

After preprocessing:

1. **French Suppliers:**
   ```bash
   python run_fast.py --supplier-xlsx preprocessed/suppliers_french.xlsx
   ```

2. **Non-French Suppliers:**
   ```bash
   python run_unified_pipeline.py --skip-sirene
   ```

3. **Both (Unified):**
   ```bash
   python run_unified_pipeline.py
   ```

---

## Related Documentation

- `run_unified_pipeline.py` - Complete pipeline runner
- `google_search_provider.py` - Google search for non-French suppliers
- `pipeline_parallel.py` - SIRENE matching for French suppliers
- `FIXES_COMPLETED.md` - Query improvements documentation

---

**Ready to preprocess your suppliers? Run:**
```bash
python run_unified_pipeline.py
```
