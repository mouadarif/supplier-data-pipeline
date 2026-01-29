# SIRENE Parquet File Column Reference

This document lists all the column names used in the SIRENE database Parquet files and how they're accessed.

## File Structure

The SIRENE database consists of two main Parquet files:

1. **`StockUniteLegale_utf8.parquet`** - Legal entities (companies)
2. **`StockEtablissement_utf8.parquet`** - Establishments (locations/branches)

## StockUniteLegale Columns (Legal Entities)

**Total: 35 columns**

### Primary Identifiers
- **`siren`** (9 digits) - Unique company identifier
- **`denominationUniteLegale`** - Official company name
- **`sigleUniteLegale`** - Company acronym/abbreviation
- **`nomUniteLegale`** - Last name (for individuals)
- **`nomUsageUniteLegale`** - Used name (for individuals)
- **`prenom1UniteLegale`** - First name (for individuals)
- **`prenom2UniteLegale`** - Second first name
- **`prenom3UniteLegale`** - Third first name
- **`prenom4UniteLegale`** - Fourth first name
- **`prenomUsuelUniteLegale`** - Usual first name
- **`pseudonymeUniteLegale`** - Pseudonym
- **`sexeUniteLegale`** - Gender (M/F)

### Status & Activity
- **`etatAdministratifUniteLegale`** - Administrative status
  - `'A'` = Active (Actif)
  - `'F'` = Closed (Fermé)
- **`activitePrincipaleUniteLegale`** - Main activity code (NAF code, e.g., "6201Z")
- **`activitePrincipaleNAF25UniteLegale`** - NAF Rev 2.5 activity code
- **`nomenclatureActivitePrincipaleUniteLegale`** - Activity nomenclature version
- **`activitePrincipaleRegistreMetiersEtablissement`** - Trade register activity

### Company Information
- **`denominationUsuelle1UniteLegale`** - Usual name 1
- **`denominationUsuelle2UniteLegale`** - Usual name 2
- **`denominationUsuelle3UniteLegale`** - Usual name 3
- **`categorieJuridiqueUniteLegale`** - Legal category code
- **`categorieEntreprise`** - Company category
- **`anneeCategorieEntreprise`** - Year of category
- **`trancheEffectifsUniteLegale`** - Employee size range
- **`anneeEffectifsUniteLegale`** - Year of employee count
- **`caractereEmployeurUniteLegale`** - Employer status
- **`economieSocialeSolidaireUniteLegale`** - Social economy indicator
- **`societeMissionUniteLegale`** - Mission-driven company indicator
- **`identifiantAssociationUniteLegale`** - Association identifier

### Dates
- **`dateCreationUniteLegale`** - Creation date
- **`dateDebut`** - Start date
- **`dateDernierTraitementUniteLegale`** - Last processing date

### Other Fields
- **`statutDiffusionUniteLegale`** - Diffusion status
- **`unitePurgeeUniteLegale`** - Purged unit flag
- **`nombrePeriodesUniteLegale`** - Number of periods
- **`nicSiegeUniteLegale`** - Head office NIC

## StockEtablissement Columns (Establishments)

**Total: 54 columns**

### Primary Identifiers
- **`siret`** (14 digits) - Unique establishment identifier (SIREN + 5-digit NIC)
- **`siren`** (9 digits) - Parent company identifier
- **`nic`** (5 digits) - Establishment number within company

### Address Fields (Primary Address)
- **`numeroVoieEtablissement`** - Street number
- **`indiceRepetitionEtablissement`** - Repetition index (bis, ter, etc.)
- **`dernierNumeroVoieEtablissement`** - Last street number
- **`indiceRepetitionDernierNumeroVoieEtablissement`** - Last number repetition index
- **`typeVoieEtablissement`** - Street type (RUE, AVENUE, BOULEVARD, etc.)
- **`libelleVoieEtablissement`** - Street name
- **`complementAdresseEtablissement`** - Address complement (building, floor, etc.)
- **`distributionSpecialeEtablissement`** - Special distribution (BP, CEDEX, etc.)
- **`codePostalEtablissement`** - Postal code (5 digits)
- **`libelleCommuneEtablissement`** - City name
- **`libelleCommuneEtrangerEtablissement`** - Foreign city name
- **`codeCommuneEtablissement`** - INSEE city code
- **`codeCedexEtablissement`** - CEDEX code
- **`libelleCedexEtablissement`** - CEDEX label
- **`codePaysEtrangerEtablissement`** - Foreign country code
- **`libellePaysEtrangerEtablissement`** - Foreign country name
- **`identifiantAdresseEtablissement`** - Address identifier

### Address Fields (Secondary Address - Address 2)
- **`complementAdresse2Etablissement`** - Secondary address complement
- **`numeroVoie2Etablissement`** - Secondary street number
- **`indiceRepetition2Etablissement`** - Secondary repetition index
- **`typeVoie2Etablissement`** - Secondary street type
- **`libelleVoie2Etablissement`** - Secondary street name
- **`codePostal2Etablissement`** - Secondary postal code
- **`libelleCommune2Etablissement`** - Secondary city name
- **`libelleCommuneEtranger2Etablissement`** - Secondary foreign city name
- **`distributionSpeciale2Etablissement`** - Secondary special distribution
- **`codeCommune2Etablissement`** - Secondary INSEE city code
- **`codeCedex2Etablissement`** - Secondary CEDEX code
- **`libelleCedex2Etablissement`** - Secondary CEDEX label
- **`codePaysEtranger2Etablissement`** - Secondary foreign country code
- **`libellePaysEtranger2Etablissement`** - Secondary foreign country name

### Geographic Coordinates
- **`coordonneeLambertAbscisseEtablissement`** - Lambert X coordinate
- **`coordonneeLambertOrdonneeEtablissement`** - Lambert Y coordinate

### Computed Address Field
In our code, we create a computed `address` field by concatenating:
```sql
upper(trim(
  coalesce(numeroVoieEtablissement::VARCHAR, '') || ' ' ||
  coalesce(typeVoieEtablissement, '') || ' ' ||
  coalesce(libelleVoieEtablissement, '') || ' ' ||
  coalesce(complementAdresseEtablissement, '') || ' ' ||
  coalesce(distributionSpecialeEtablissement, '')
)) AS address
```

### Status & Type
- **`etatAdministratifEtablissement`** - Administrative status
  - `'A'` = Active (Actif)
  - `'F'` = Closed (Fermé)
- **`etablissementSiege`** - Boolean, TRUE if this is the head office
- **`activitePrincipaleEtablissement`** - Main activity code (NAF code)

### Geographic Fields
- **`latitude`** - Latitude coordinate (if available)
- **`longitude`** - Longitude coordinate (if available)
- **`codePaysEtrangerEtablissement`** - Foreign country code
- **`libellePaysEtrangerEtablissement`** - Foreign country name

### Dates
- **`dateCreationEtablissement`** - Creation date
- **`dateDebutActivite`** - Activity start date
- **`dateDebut`** - Start date
- **`dateFin`** - End date (if closed)

## How We Use These Columns

### In `db_setup.py` (Partition Creation)

When creating partitions, we select:
```sql
SELECT
  siret,
  siren,
  upper(coalesce(libelleCommuneEtablissement, '')) AS libelleCommuneEtablissement,
  upper(coalesce(codePostalEtablissement::VARCHAR, '')) AS codePostalEtablissement,
  upper(trim(
    coalesce(numeroVoieEtablissement::VARCHAR, '') || ' ' ||
    coalesce(typeVoieEtablissement, '') || ' ' ||
    coalesce(libelleVoieEtablissement, '') || ' ' ||
    coalesce(complementAdresseEtablissement, '') || ' ' ||
    coalesce(distributionSpecialeEtablissement, '')
  )) AS address,
  (etablissementSiege = TRUE) AS is_siege,
  substr(codePostalEtablissement::VARCHAR, 1, 2) AS dept
FROM read_parquet(?)
WHERE etatAdministratifEtablissement = 'A'
  AND siret IS NOT NULL
  AND codePostalEtablissement IS NOT NULL
```

### In `matcher_logic.py` (Matching Queries)

#### Direct SIRET Lookup
```sql
SELECT
  e.siret AS siret,
  u.denominationUniteLegale AS official_name,
  upper(coalesce(e.libelleCommuneEtablissement, '')) AS city,
  upper(trim(
    coalesce(e.numeroVoieEtablissement::VARCHAR, '') || ' ' ||
    coalesce(e.typeVoieEtablissement, '') || ' ' ||
    coalesce(e.libelleVoieEtablissement, '') || ' ' ||
    coalesce(e.complementAdresseEtablissement, '') || ' ' ||
    coalesce(e.distributionSpecialeEtablissement, '')
  )) AS address,
  (e.etablissementSiege = TRUE) AS is_siege
FROM read_parquet(?) e
LEFT JOIN unite_legale_active u USING (siren)
WHERE e.etatAdministratifEtablissement = 'A'
  AND e.siret = ?
```

#### Strict Local Lookup (by Postal Code + Name)
```sql
SELECT
  e.siret,
  u.denominationUniteLegale AS official_name,
  e.libelleCommuneEtablissement AS city,
  e.address AS address,
  e.is_siege AS is_siege
FROM read_parquet(?) e
JOIN unite_legale_active u USING (siren)
WHERE e.codePostalEtablissement = ?
  AND levenshtein(u.denominationUniteLegale, ?) <= 3
```

#### FTS Search (Full-Text Search)
```sql
SELECT
  siren,
  denominationUniteLegale,
  fts_main_unite_legale_active.match_bm25(unite_legale_active, ?) AS score
FROM unite_legale_active
WHERE fts_main_unite_legale_active.match_bm25(unite_legale_active, ?) IS NOT NULL
ORDER BY score DESC
LIMIT 20
```

#### Fetch Establishments for SIRENs
```sql
SELECT
  e.siret,
  e.siren,
  u.denominationUniteLegale AS official_name,
  e.libelleCommuneEtablissement AS city,
  e.address AS address,
  e.is_siege AS is_siege
FROM read_parquet(?) e
JOIN unite_legale_active u USING (siren)
WHERE e.siren IN (...)
```

## Key Column Mappings

| Our Code Name | Parquet Column Name | Description |
|--------------|---------------------|-------------|
| `siret` | `siret` | 14-digit establishment ID |
| `siren` | `siren` | 9-digit company ID |
| `official_name` | `denominationUniteLegale` | Company name from UniteLegale |
| `city` | `libelleCommuneEtablissement` | City name |
| `postal_code` | `codePostalEtablissement` | 5-digit postal code |
| `address` | Computed from multiple fields | Full address string |
| `is_siege` | `etablissementSiege` | TRUE if head office |
| `dept` | `substr(codePostalEtablissement, 1, 2)` | Department (first 2 digits of CP) |

## Filtering Active Records

**Critical:** Always filter by `etatAdministratifEtablissement = 'A'` for establishments and `etatAdministratifUniteLegale = 'A'` for legal entities to get only active companies.

## Example: Querying All Columns

If you want to see all available columns in a Parquet file, you can use:

```python
import duckdb
import pyarrow.parquet as pq

# Read schema
pf = pq.ParquetFile("StockEtablissement_utf8.parquet")
print("Columns in StockEtablissement:")
for col in pf.schema:
    print(f"  - {col.name}: {col.physical_type}")

# Or query with DuckDB
con = duckdb.connect()
con.execute("DESCRIBE SELECT * FROM read_parquet('StockEtablissement_utf8.parquet') LIMIT 0")
print(con.fetchall())
```

## Common Queries

### Get all active establishments in a postal code
```sql
SELECT *
FROM read_parquet('StockEtablissement_utf8.parquet')
WHERE codePostalEtablissement = '75001'
  AND etatAdministratifEtablissement = 'A'
```

### Get company info by SIREN
```sql
SELECT *
FROM read_parquet('StockUniteLegale_utf8.parquet')
WHERE siren = '123456789'
  AND etatAdministratifUniteLegale = 'A'
```

### Get establishment by SIRET
```sql
SELECT *
FROM read_parquet('StockEtablissement_utf8.parquet')
WHERE siret = '12345678900012'
  AND etatAdministratifEtablissement = 'A'
```

### Join establishments with legal entities
```sql
SELECT
  e.siret,
  e.codePostalEtablissement,
  e.libelleCommuneEtablissement,
  u.denominationUniteLegale,
  u.activitePrincipaleUniteLegale
FROM read_parquet('StockEtablissement_utf8.parquet') e
JOIN read_parquet('StockUniteLegale_utf8.parquet') u USING (siren)
WHERE e.etatAdministratifEtablissement = 'A'
  AND u.etatAdministratifUniteLegale = 'A'
  AND e.codePostalEtablissement = '75001'
LIMIT 10
```
