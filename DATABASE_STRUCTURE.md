# Database Structure Documentation

## Overview

The pipeline uses **two separate databases**:

1. **DuckDB** (`sirene.duckdb`) - For querying SIRENE parquet files
2. **SQLite** (`state.sqlite`) - For checkpointing pipeline progress

## DuckDB Database Structure

### Purpose
DuckDB is used as a **query engine** over parquet files. It does NOT store the actual SIRENE data - it reads directly from parquet files.

### Tables Created

#### 1. `unite_legale_active` Table
```sql
CREATE TABLE unite_legale_active AS
SELECT
  siren,
  upper(denominationUniteLegale) AS denominationUniteLegale,
  activitePrincipaleUniteLegale,
  etatAdministratifUniteLegale
FROM read_parquet(?)  -- Reads from StockUniteLegale_utf8.parquet
WHERE etatAdministratifUniteLegale = 'A'
  AND denominationUniteLegale IS NOT NULL
  AND length(trim(denominationUniteLegale)) > 0
```

**Purpose**: Stores active legal entities (companies) with their names
**Data Source**: `StockUniteLegale_utf8.parquet` (read via `read_parquet()`)
**FTS Index**: Created on `denominationUniteLegale` for fast text search

#### 2. `__paths` Table (Metadata)
```sql
CREATE TABLE __paths AS
SELECT
  ul_parquet,      -- Path to StockUniteLegale_utf8.parquet
  etab_parquet,    -- Path to StockEtablissement_utf8.parquet
  partitions_root  -- Path to sirene_partitions/etablissements/
```

**Purpose**: Stores paths to parquet files for queries

#### 3. `__meta` Table (Metadata)
```sql
CREATE TABLE __meta(
  key VARCHAR,
  value VARCHAR
)
```

**Purpose**: Stores metadata about database initialization

### Parquet File Reading

**All queries read directly from parquet files**, not from DuckDB tables:

#### Direct ID Lookup
```sql
SELECT ... 
FROM read_parquet(?) e  -- Reads from StockEtablissement_utf8.parquet
LEFT JOIN unite_legale_active u USING (siren)
WHERE e.etatAdministratifEtablissement = 'A'
  AND e.siret = ?
```

#### Partitioned Lookup
```sql
SELECT ...
FROM read_parquet(?) e  -- Reads from sirene_partitions/etablissements/dept=XX/*.parquet
JOIN unite_legale_active u USING (siren)
WHERE e.codePostalEtablissement = ?
  AND levenshtein(u.denominationUniteLegale, ?) <= 3
```

#### Nationwide Lookup
```sql
SELECT ...
FROM read_parquet(?) e  -- Reads from StockEtablissement_utf8.parquet
JOIN unite_legale_active u USING (siren)
WHERE e.etatAdministratifEtablissement = 'A'
  AND e.siren IN (...)
```

### Partitioned Data Structure

Partitions are created in `sirene_partitions/etablissements/`:
```
sirene_partitions/
└── etablissements/
    ├── dept=01/
    │   └── *.parquet
    ├── dept=02/
    │   └── *.parquet
    ...
    └── dept=99/
        └── *.parquet
```

**Created by**: `db_setup.py` using `COPY ... TO ... PARTITION_BY (dept)`
**Filter**: Only active establishments (`etatAdministratifEtablissement = 'A'`)

## SQLite Database Structure (Checkpointing)

### Purpose
SQLite is used **only for checkpointing** pipeline progress, NOT for storing SIRENE data.

### Table: `results`
```sql
CREATE TABLE results (
  input_id TEXT PRIMARY KEY,           -- Supplier ID from input file
  resolved_siret TEXT,                 -- Matched SIRET (if found)
  official_name TEXT,                  -- Official company name from SIRENE
  confidence_score REAL,               -- Match confidence (0.0-1.0)
  match_method TEXT,                   -- How match was found (DIRECT_ID, STRICT_LOCAL, etc.)
  alternatives_json TEXT,              -- JSON array of alternative matches
  error TEXT,                          -- Error message (if processing failed)
  updated_at_epoch INTEGER             -- Timestamp of last update
)
```

**Purpose**: Tracks which suppliers have been processed and their results
**Data Source**: Results from `match_supplier_row()` function
**NOT**: Does NOT store SIRENE data - only pipeline results

### Index
```sql
CREATE INDEX idx_error ON results(error);
```

**Purpose**: Fast lookup of failed rows for retry

## Data Flow

```
Input File (Frs.xlsx)
    ↓
Preprocessing (preprocess_suppliers.py)
    ↓
For each supplier row:
    ↓
match_supplier_row() in matcher_logic.py
    ↓
    ├─→ Query DuckDB → read_parquet() → StockEtablissement_utf8.parquet
    ├─→ Query DuckDB → read_parquet() → sirene_partitions/etablissements/dept=XX/*.parquet
    └─→ Query DuckDB → unite_legale_active table (from StockUniteLegale_utf8.parquet)
    ↓
MatchResult object
    ↓
StateStore.upsert_result() → SQLite results table (checkpoint)
    ↓
Export to CSV (results_enriched.csv)
```

## Key Points

1. ✅ **SIRENE data is ALWAYS read from parquet files** via `read_parquet()`
2. ✅ **DuckDB is a query engine**, not a storage engine for SIRENE data
3. ✅ **SQLite only stores pipeline results**, not SIRENE data
4. ✅ **Partitions are pre-filtered** to contain only active establishments
5. ✅ **All queries use `read_parquet()`** to read directly from parquet files

## Verification

To verify parquet files are being read:

1. Check `db_setup.py` - Creates partitions from parquet files
2. Check `matcher_logic.py` - All queries use `read_parquet()`
3. Check `__paths` table in DuckDB - Contains paths to parquet files
4. Monitor file I/O during queries - Should see parquet file reads
