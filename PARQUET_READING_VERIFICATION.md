# Parquet File Reading Verification

## ✅ Confirmed: All Data Reads from Parquet Files

The pipeline **correctly reads all SIRENE data from parquet files** using DuckDB's `read_parquet()` function.

## Verification by Function

### 1. `_direct_id_lookup()` - Line 120
```python
FROM read_parquet(?) e  # Reads from StockEtablissement_utf8.parquet
LEFT JOIN unite_legale_active u USING (siren)
WHERE e.etatAdministratifEtablissement = 'A'
  AND e.siret = ?
```
**✅ Reads from**: `etab_parquet` (StockEtablissement_utf8.parquet)

### 2. `_strict_local_lookup()` - Line 155
```python
glob = os.path.join(partitions_root, f"dept={dept}", "*.parquet")
FROM read_parquet(?) e  # Reads from sirene_partitions/etablissements/dept=XX/*.parquet
JOIN unite_legale_active u USING (siren)
WHERE e.codePostalEtablissement = ?
```
**✅ Reads from**: Partitioned parquet files (`sirene_partitions/etablissements/dept=XX/*.parquet`)

### 3. `_fetch_establishments_for_sirens()` - Line 213
```python
glob = os.path.join(partitions_root, f"dept={dept}", "*.parquet")
FROM read_parquet(?) e  # Reads from sirene_partitions/etablissements/dept=XX/*.parquet
JOIN unite_legale_active u USING (siren)
WHERE e.siren IN (...)
```
**✅ Reads from**: Partitioned parquet files (`sirene_partitions/etablissements/dept=XX/*.parquet`)

### 4. `_fetch_establishments_for_sirens_nationwide()` - Line 258
```python
FROM read_parquet(?) e  # Reads from StockEtablissement_utf8.parquet
JOIN unite_legale_active u USING (siren)
WHERE e.etatAdministratifEtablissement = 'A'
  AND e.siren IN (...)
```
**✅ Reads from**: `etab_parquet` (StockEtablissement_utf8.parquet)

## DuckDB Tables (Not Storage, Just Indexes)

### `unite_legale_active` Table
- **Created FROM parquet**: `SELECT ... FROM read_parquet(?)` (line 114 in db_setup.py)
- **Purpose**: Fast joins and FTS index on company names
- **Data Source**: `StockUniteLegale_utf8.parquet`
- **Note**: This table IS stored in DuckDB for performance, but it's created FROM parquet

### `__paths` Table
- **Purpose**: Stores paths to parquet files
- **Not data storage**: Just metadata

### `__meta` Table
- **Purpose**: Stores database initialization metadata
- **Not data storage**: Just metadata

## Key Point: Establishment Data is ALWAYS from Parquet

**All establishment (etablissement) data is read directly from parquet files**, never from DuckDB tables:

- ✅ Direct ID lookup → `read_parquet(etab_parquet)`
- ✅ Strict local lookup → `read_parquet(partitioned/*.parquet)`
- ✅ Fetch establishments → `read_parquet(partitioned/*.parquet)`
- ✅ Nationwide lookup → `read_parquet(etab_parquet)`

## Database Structure Summary

### DuckDB (`sirene.duckdb`)
- **unite_legale_active**: Table created FROM parquet (for fast joins/FTS)
- **__paths**: Metadata (parquet file paths)
- **__meta**: Metadata (initialization info)
- **NO establishment data stored** - always read from parquet

### SQLite (`state.sqlite`)
- **results**: Pipeline checkpoint (which suppliers processed, results)
- **NOT SIRENE data** - only pipeline progress

## Conclusion

✅ **The code correctly reads all SIRENE data from parquet files**
✅ **DuckDB is used as a query engine, not storage for establishment data**
✅ **All queries use `read_parquet()` to read directly from parquet files**

The database structure is correct and efficient!
