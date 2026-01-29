from __future__ import annotations

import os
import pathlib
import time
from dataclasses import dataclass
from typing import Optional

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


@dataclass(frozen=True)
class Paths:
    supplier_xlsx: str = "Frs.xlsx"
    etab_parquet: str = "StockEtablissement_utf8.parquet"
    ul_parquet: str = "StockUniteLegale_utf8.parquet"
    duckdb_path: str = "sirene.duckdb"
    partitions_dir: str = "sirene_partitions"


def _ensure_dir(path: str) -> None:
    pathlib.Path(path).mkdir(parents=True, exist_ok=True)


def create_sample_parquet(
    input_parquet: str,
    output_parquet: str,
    *,
    max_row_groups: int = 2,
) -> None:
    """
    Create a small parquet by concatenating the first N row groups.
    This keeps tests fast while still using real data.
    """
    pf = pq.ParquetFile(input_parquet)
    n = min(max_row_groups, pf.num_row_groups)
    tables = [pf.read_row_group(i) for i in range(n)]
    table = pa.concat_tables(tables) if len(tables) > 1 else tables[0]
    _ensure_dir(os.path.dirname(output_parquet) or ".")
    pq.write_table(table, output_parquet, compression="zstd")


def init_duckdb(
    *,
    duckdb_path: str,
    ul_parquet: str,
    etab_parquet: str,
    partitions_dir: str,
    sample_row_groups: Optional[int] = None,
    force_rebuild: bool = False,
) -> None:
    """
    Creates:
    - `unite_legale_active` table + FTS index on `denominationUniteLegale`
    - partitions of etablissements by department (dept = first 2 digits of CP)

    For huge inputs, leave `sample_row_groups=None` (full init, slower).
    For tests/dev, set sample_row_groups (fast).
    """
    t0 = time.time()
    partitions_root = os.path.join(partitions_dir, "etablissements")
    _ensure_dir(partitions_root)

    # Sampling: create temp smaller parquets (optional)
    if sample_row_groups is not None:
        sample_dir = os.path.join(partitions_dir, "_samples")
        _ensure_dir(sample_dir)
        etab_sample = os.path.join(sample_dir, "StockEtablissement_sample.parquet")
        ul_sample = os.path.join(sample_dir, "StockUniteLegale_sample.parquet")
        if force_rebuild or not os.path.exists(etab_sample):
            create_sample_parquet(etab_parquet, etab_sample, max_row_groups=sample_row_groups)
        # UniteLegale must align with sampled etablissements (same sirens), otherwise joins/Direct-ID will miss.
        # So: build a filtered UL sample that contains only the sirens present in etab_sample.
        if force_rebuild or not os.path.exists(ul_sample):
            tmp_con = duckdb.connect()
            try:
                tmp_con.execute("CREATE TEMP TABLE sample_sirens AS SELECT DISTINCT siren FROM read_parquet(?) WHERE siren IS NOT NULL", [etab_sample])
                tmp_con.execute(
                    f"""
                    COPY (
                      SELECT ul.*
                      FROM read_parquet(?) ul
                      JOIN sample_sirens s USING (siren)
                    ) TO '{ul_sample}'
                    (FORMAT PARQUET, COMPRESSION ZSTD);
                    """,
                    [ul_parquet],
                )
            finally:
                tmp_con.close()
        etab_parquet = etab_sample
        ul_parquet = ul_sample

    con = duckdb.connect(duckdb_path)
    try:
        con.execute("INSTALL fts;")
        con.execute("LOAD fts;")
    except Exception:
        # Some installations ship with fts already available.
        pass

    # Build Unite Legale active table (name/NAF metadata), then FTS index
    con.execute("DROP TABLE IF EXISTS unite_legale_active;")
    con.execute(
        """
        CREATE TABLE unite_legale_active AS
        SELECT
          siren,
          upper(denominationUniteLegale) AS denominationUniteLegale,
          activitePrincipaleUniteLegale,
          etatAdministratifUniteLegale
        FROM read_parquet(?)
        WHERE etatAdministratifUniteLegale = 'A'
          AND denominationUniteLegale IS NOT NULL
          AND length(trim(denominationUniteLegale)) > 0
        """,
        [ul_parquet],
    )
    con.execute("DROP TABLE IF EXISTS __meta;")
    con.execute(
        """
        CREATE TABLE __meta(
          key VARCHAR,
          value VARCHAR
        )
        """
    )
    con.execute("INSERT INTO __meta VALUES ('ul_parquet', ?)", [os.path.abspath(ul_parquet)])
    con.execute("INSERT INTO __meta VALUES ('etab_parquet', ?)", [os.path.abspath(etab_parquet)])
    con.execute("INSERT INTO __meta VALUES ('created_at_epoch', ?)", [str(int(time.time()))])
    con.execute("INSERT INTO __meta VALUES ('sample_row_groups', ?)", [str(sample_row_groups or "")])

    # Create FTS index on denominationUniteLegale (fast broad search)
    # DuckDB 1.4.x signature: (table_name, index_name, col1, col2, ...)
    try:
        con.execute("PRAGMA drop_fts_index('unite_legale_active');")
    except Exception:
        pass  # Index might not exist
    con.execute("PRAGMA create_fts_index('unite_legale_active', 'unite_legale_active', 'denominationUniteLegale');")

    # Partition etablissements by dept (derived from CP)
    # Skip if already partitioned unless force_rebuild
    any_dept = next(pathlib.Path(partitions_root).glob("dept=*"), None)
    if force_rebuild or any_dept is None:
        # Clean partitions dir
        for p in pathlib.Path(partitions_root).glob("dept=*"):
            if p.is_dir():
                for fp in p.rglob("*"):
                    if fp.is_file():
                        fp.unlink()
                try:
                    p.rmdir()
                except OSError:
                    pass

        con.execute(
            f"""
            COPY (
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
                AND length(trim(codePostalEtablissement::VARCHAR)) >= 2
                AND regexp_matches(codePostalEtablissement::VARCHAR, '^[0-9]{{2}}')
            ) TO '{partitions_root}'
            (FORMAT PARQUET, PARTITION_BY (dept), COMPRESSION ZSTD);
            """
        , [etab_parquet])

    # Persist the effective parquet paths used (sample or full)
    con.execute("DROP TABLE IF EXISTS __paths;")
    con.execute(
        """
        CREATE TABLE __paths AS
        SELECT
          ?::VARCHAR AS ul_parquet,
          ?::VARCHAR AS etab_parquet,
          ?::VARCHAR AS partitions_root
        """,
        [os.path.abspath(ul_parquet), os.path.abspath(etab_parquet), os.path.abspath(partitions_root)],
    )

    con.close()
    dt = time.time() - t0
    print(f"[db_setup] init complete in {dt:.1f}s (duckdb={duckdb_path})")


def open_db(duckdb_path: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(duckdb_path, read_only=True)
    try:
        con.execute("LOAD fts;")
    except Exception:
        pass
    return con

