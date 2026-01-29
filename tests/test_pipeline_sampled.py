from __future__ import annotations

import csv
import pathlib

import duckdb
import pandas as pd

from db_setup import init_duckdb
from matcher_logic import match_supplier_row
from pipeline_manager import PipelineConfig, run_pipeline


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _get_sample_siret(duckdb_path: str) -> str:
    con = duckdb.connect(duckdb_path, read_only=True)
    try:
        etab_parquet = con.execute("SELECT etab_parquet FROM __paths").fetchone()[0]
        row = con.execute(
            """
            SELECT siret
            FROM read_parquet(?)
            WHERE etatAdministratifEtablissement = 'A'
              AND siret IS NOT NULL
            LIMIT 1
            """,
            [etab_parquet],
        ).fetchone()
        assert row and row[0]
        return str(row[0])
    finally:
        con.close()


def test_match_direct_id_with_sample_index(tmp_path: pathlib.Path) -> None:
    duckdb_path = str(tmp_path / "sirene.duckdb")
    partitions_dir = str(tmp_path / "sirene_partitions")

    init_duckdb(
        duckdb_path=duckdb_path,
        ul_parquet=str(ROOT / "StockUniteLegale_utf8.parquet"),
        etab_parquet=str(ROOT / "StockEtablissement_utf8.parquet"),
        partitions_dir=partitions_dir,
        sample_row_groups=1,
        force_rebuild=True,
    )

    siret = _get_sample_siret(duckdb_path)
    con = duckdb.connect(duckdb_path, read_only=True)
    try:
        raw = {
            "Auxiliaire": "TEST001",
            "Nom": "TEST SUPPLIER",
            "Adresse 1": "1 RUE DE TEST",
            "Postal": "75001",
            "Ville": "PARIS",
            "Code SIRET": siret,
        }
        r = match_supplier_row(con, raw)
        assert r.match_method == "DIRECT_ID"
        assert r.resolved_siret == siret
        assert r.confidence_score == 1.0
    finally:
        con.close()


def test_run_pipeline_end_to_end_sampled(tmp_path: pathlib.Path) -> None:
    duckdb_path = str(tmp_path / "sirene.duckdb")
    partitions_dir = str(tmp_path / "sirene_partitions")
    xlsx_path = str(tmp_path / "suppliers.xlsx")
    checkpoint = str(tmp_path / "state.sqlite")
    output_csv = str(tmp_path / "results_enriched.csv")

    init_duckdb(
        duckdb_path=duckdb_path,
        ul_parquet=str(ROOT / "StockUniteLegale_utf8.parquet"),
        etab_parquet=str(ROOT / "StockEtablissement_utf8.parquet"),
        partitions_dir=partitions_dir,
        sample_row_groups=1,
        force_rebuild=True,
    )

    siret = _get_sample_siret(duckdb_path)

    df = pd.DataFrame(
        [
            {
                "Auxiliaire": "TEST001",
                "Nom": "TEST SUPPLIER",
                "Adresse 1": "1 RUE DE TEST",
                "Adresse 2": "",
                "Adresse 3": "",
                "Postal": "75001",
                "Ville": "PARIS",
                "Code SIRET": siret,
                "Code NIF": "",
                "Code NAF": "",
            },
            {
                "Auxiliaire": "TEST002",
                "Nom": "SOCIETE INEXISTANTE XYZ",
                "Adresse 1": "99 RUE NULLE",
                "Adresse 2": "",
                "Adresse 3": "",
                "Postal": "75001",
                "Ville": "PARIS",
                "Code SIRET": "",
                "Code NIF": "",
                "Code NAF": "",
            },
        ]
    )
    df.to_excel(xlsx_path, index=False)

    cfg = PipelineConfig(
        supplier_xlsx=xlsx_path,
        duckdb_path=duckdb_path,
        checkpoint_sqlite=checkpoint,
        output_csv=output_csv,
        batch_size=1,
        limit_rows=None,
    )
    run_pipeline(cfg)

    assert pathlib.Path(output_csv).exists()
    with open(output_csv, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 1
    row1 = next(r for r in rows if r["input_id"] == "TEST001")
    assert row1["resolved_siret"] == siret
    assert row1["match_method"] == "DIRECT_ID"

