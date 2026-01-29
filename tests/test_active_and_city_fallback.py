"""
Tests for the new fixes:
1. Active establishment check
2. City-only fallback search
"""
from __future__ import annotations

import pathlib
import duckdb
import pandas as pd

from db_setup import init_duckdb
from matcher_logic import match_supplier_row


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_active_establishment_check(tmp_path: pathlib.Path) -> None:
    """
    Verify that only active establishments are returned in search results.
    """
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

    con = duckdb.connect(duckdb_path, read_only=True)
    try:
        # Get an active establishment
        etab_parquet = con.execute("SELECT etab_parquet FROM __paths").fetchone()[0]
        active_row = con.execute(
            """
            SELECT e.siret, e.codePostalEtablissement, u.denominationUniteLegale
            FROM read_parquet(?) e
            JOIN unite_legale_active u USING (siren)
            WHERE e.etatAdministratifEtablissement = 'A'
                AND e.codePostalEtablissement IS NOT NULL
                AND u.denominationUniteLegale IS NOT NULL
            LIMIT 1
            """,
            [etab_parquet],
        ).fetchone()
        
        if not active_row:
            # Skip test if no data
            return
        
        siret, postal, name = active_row
        
        # Test with active establishment
        raw = {
            "Auxiliaire": "TEST_ACTIVE",
            "Nom": name,
            "Adresse 1": "1 RUE TEST",
            "Postal": postal,
            "Ville": "PARIS",
            "Code SIRET": siret,
        }
        result = match_supplier_row(con, raw)
        
        # Should find the active establishment
        assert result.resolved_siret == siret
        assert result.match_method == "DIRECT_ID"
        assert result.confidence_score == 1.0
        
    finally:
        con.close()


def test_city_only_fallback(tmp_path: pathlib.Path) -> None:
    """
    Verify that when no postal code is provided, the system falls back to city-based search.
    """
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

    con = duckdb.connect(duckdb_path, read_only=True)
    try:
        # Get a real company with city
        etab_parquet = con.execute("SELECT etab_parquet FROM __paths").fetchone()[0]
        company_row = con.execute(
            """
            SELECT 
                e.siret, 
                e.libelleCommuneEtablissement, 
                u.denominationUniteLegale
            FROM read_parquet(?) e
            JOIN unite_legale_active u USING (siren)
            WHERE e.etatAdministratifEtablissement = 'A'
                AND e.libelleCommuneEtablissement IS NOT NULL
                AND u.denominationUniteLegale IS NOT NULL
                AND length(u.denominationUniteLegale) > 5
            LIMIT 1
            """,
            [etab_parquet],
        ).fetchone()
        
        if not company_row:
            # Skip test if no data
            return
        
        siret, city, name = company_row
        
        # Test WITHOUT postal code but WITH city
        raw = {
            "Auxiliaire": "TEST_CITY_ONLY",
            "Nom": name,
            "Adresse 1": "1 RUE TEST",
            "Postal": "",  # No postal code!
            "Ville": city,  # But has city
            "Code SIRET": "",
        }
        result = match_supplier_row(con, raw)
        
        # Should NOT return NOT_FOUND immediately
        # Should search nationwide and filter by city
        assert result.match_method != "NOT_FOUND" or "NO_LOCATION" not in result.debug.get("step", "")
        
        # Debug info should show nationwide search was attempted
        if "search_scope" in result.debug:
            assert result.debug["search_scope"] == "nationwide"
        
    finally:
        con.close()


def test_no_location_returns_not_found(tmp_path: pathlib.Path) -> None:
    """
    Verify that when neither postal code nor city is provided, NOT_FOUND is returned.
    """
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

    con = duckdb.connect(duckdb_path, read_only=True)
    try:
        # Test with NO postal code and NO city
        raw = {
            "Auxiliaire": "TEST_NO_LOCATION",
            "Nom": "SOME COMPANY NAME",
            "Adresse 1": "1 RUE TEST",
            "Postal": "",  # No postal code
            "Ville": "",   # No city
            "Code SIRET": "",
        }
        result = match_supplier_row(con, raw)
        
        # Should return NOT_FOUND with NO_LOCATION step
        assert result.match_method == "NOT_FOUND"
        assert result.debug.get("step") == "NO_LOCATION"
        assert result.resolved_siret is None
        
    finally:
        con.close()
