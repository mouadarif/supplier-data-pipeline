from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import duckdb
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from llm_providers import CleanedSupplier, LLMClient, OfflineHeuristicLLM


def _as_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, float) and math.isnan(x):
        return ""
    return str(x)


def _digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _normalize_city(s: str) -> str:
    s = _as_str(s).strip().upper()
    s = re.sub(r"\s+", " ", s)
    return s


def _normalize_addr(parts: List[Any]) -> str:
    s = " ".join(_as_str(p) for p in parts if _as_str(p).strip())
    s = s.strip().upper()
    s = re.sub(r"\s+", " ", s)
    return s


def _extract_siret(raw: Any) -> Optional[str]:
    # Excel often turns long IDs into numbers; preserve leading zeros.
    if isinstance(raw, int):
        s = f"{raw:014d}"
        return s if len(s) == 14 else None
    if isinstance(raw, float) and not math.isnan(raw):
        try:
            s = f"{int(raw):014d}"
            return s if len(s) == 14 else None
        except Exception:
            pass

    s = _digits_only(_as_str(raw))
    if len(s) == 14:
        return s
    return None


def _extract_siren_from_nif(raw: Any) -> Optional[str]:
    s = _as_str(raw).strip().upper()
    # Typical FR VAT: FRkk + 9-digit siren
    m = re.search(r"\bFR\s*\d{2}\s*(\d{9})\b", s.replace(" ", ""))
    if m:
        return m.group(1)
    digits = _digits_only(s)
    if len(digits) >= 9 and s.startswith("FR"):
        return digits[-9:]
    return None


@dataclass
class MatchResult:
    input_id: str
    resolved_siret: Optional[str]
    official_name: Optional[str]
    confidence_score: float  # 0..1
    match_method: str
    alternatives: List[str]
    debug: Dict[str, Any]

    def to_row(self) -> Dict[str, Any]:
        return {
            "input_id": self.input_id,
            "resolved_siret": self.resolved_siret,
            "official_name": self.official_name,
            "confidence_score": self.confidence_score,
            "match_method": self.match_method,
            "alternatives": json.dumps(self.alternatives, ensure_ascii=False, default=str),
        }


def _get_paths(con: duckdb.DuckDBPyConnection) -> Tuple[str, str, str]:
    ul_parquet, etab_parquet, partitions_root = con.execute(
        "SELECT ul_parquet, etab_parquet, partitions_root FROM __paths"
    ).fetchone()
    return ul_parquet, etab_parquet, partitions_root


def _direct_id_lookup(
    con: duckdb.DuckDBPyConnection,
    *,
    etab_parquet: str,
    siret: str,
) -> Optional[Dict[str, Any]]:
    row = con.execute(
        """
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
        LIMIT 1
        """,
        [etab_parquet, siret],
    ).fetchone()
    if not row:
        return None
    return {"siret": row[0], "official_name": row[1], "city": row[2], "address": row[3], "is_siege": row[4]}


def _strict_local_lookup(
    con: duckdb.DuckDBPyConnection,
    *,
    partitions_root: str,
    clean_cp: str,
    clean_name: str,
) -> List[Dict[str, Any]]:
    """
    Strict local search in partitioned data.
    Note: Partitions already contain only active establishments (filtered during db_setup),
    so no need to filter by etatAdministratifEtablissement here.
    """
    dept = clean_cp[:2]
    glob = os.path.join(partitions_root, f"dept={dept}", "*.parquet")
    rows = con.execute(
        """
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
        """,
        [glob, clean_cp, clean_name],
    ).fetchall()
    return [
        {"siret": r[0], "official_name": r[1], "city": r[2], "address": r[3], "is_siege": r[4]} for r in rows
    ]


def _fts_candidates(
    con: duckdb.DuckDBPyConnection,
    *,
    search_token: str,
    limit: int = 20,
) -> List[Tuple[str, str, float]]:
    rows = con.execute(
        """
        SELECT
          siren,
          denominationUniteLegale,
          fts_main_unite_legale_active.match_bm25(unite_legale_active, ?) AS score
        FROM unite_legale_active
        WHERE fts_main_unite_legale_active.match_bm25(unite_legale_active, ?) IS NOT NULL
        ORDER BY score
        LIMIT ?
        """,
        [search_token, search_token, limit],
    ).fetchall()
    return [(r[0], r[1], float(r[2])) for r in rows]


def _fetch_establishments_for_sirens(
    con: duckdb.DuckDBPyConnection,
    *,
    partitions_root: str,
    dept: str,
    sirens: List[str],
) -> List[Dict[str, Any]]:
    """
    Fetch establishments from partitioned data for given SIRENs.
    Note: Partitions already contain only active establishments (filtered during db_setup),
    so no need to filter by etatAdministratifEtablissement here.
    """
    if not sirens:
        return []
    glob = os.path.join(partitions_root, f"dept={dept}", "*.parquet")
    placeholders = ",".join(["?"] * len(sirens))
    sql = f"""
      SELECT
        e.siret,
        e.siren,
        u.denominationUniteLegale AS official_name,
        e.libelleCommuneEtablissement AS city,
        e.address AS address,
        e.is_siege AS is_siege
      FROM read_parquet(?) e
      JOIN unite_legale_active u USING (siren)
      WHERE e.siren IN ({placeholders})
    """
    rows = con.execute(sql, [glob, *sirens]).fetchall()
    return [
        {
            "siret": r[0],
            "siren": r[1],
            "official_name": r[2],
            "city": r[3],
            "address": r[4],
            "is_siege": bool(r[5]),
        }
        for r in rows
    ]


def _fetch_establishments_for_sirens_nationwide(
    con: duckdb.DuckDBPyConnection,
    *,
    etab_parquet: str,
    sirens: List[str],
) -> List[Dict[str, Any]]:
    """
    Fetch establishments from entire database when no postal code is available.
    Performance: Uses single parquet file read instead of partitions.
    """
    if not sirens:
        return []
    placeholders = ",".join(["?"] * len(sirens))
    sql = f"""
      SELECT
        e.siret,
        e.siren,
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
      JOIN unite_legale_active u USING (siren)
      WHERE e.etatAdministratifEtablissement = 'A'
        AND e.siren IN ({placeholders})
    """
    rows = con.execute(sql, [etab_parquet, *sirens]).fetchall()
    return [
        {
            "siret": r[0],
            "siren": r[1],
            "official_name": r[2],
            "city": r[3],
            "address": r[4],
            "is_siege": bool(r[5]),
        }
        for r in rows
    ]


def _score_candidates(
    *,
    supplier_clean_name: str,
    supplier_city: Optional[str],
    supplier_address: str,
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    scored: List[Dict[str, Any]] = []
    for c in candidates:
        name_sim = fuzz.token_sort_ratio(supplier_clean_name, _as_str(c.get("official_name"))) / 100.0
        city_match = (supplier_city or "") == _as_str(c.get("city") or "").upper()
        addr_sim = fuzz.token_set_ratio(supplier_address, _as_str(c.get("address"))) / 100.0

        score = 0.0
        if name_sim > 0.9:
            score += 40
        if city_match:
            score += 30
        if addr_sim > 0.8:
            score += 20
        if bool(c.get("is_siege")):
            score += 10
        c2 = dict(c)
        c2["_name_sim"] = name_sim
        c2["_addr_sim"] = addr_sim
        c2["_score_100"] = score
        scored.append(c2)
    scored.sort(key=lambda x: x["_score_100"], reverse=True)
    return scored


def match_supplier_row(
    con: duckdb.DuckDBPyConnection,
    raw: Dict[str, Any],
    *,
    llm: Optional[LLMClient] = None,
) -> MatchResult:
    ul_parquet, etab_parquet, partitions_root = _get_paths(con)
    _ = ul_parquet  # kept for debugging symmetry
    llm = llm or OfflineHeuristicLLM()

    input_id = _as_str(raw.get("Auxiliaire") or raw.get("input_id") or raw.get("Code tiers") or raw.get("index"))

    debug: Dict[str, Any] = {"input_id": input_id}

    # STEP 1: strict ID verification
    siret = _extract_siret(raw.get("Code SIRET"))
    if siret:
        hit = _direct_id_lookup(con, etab_parquet=etab_parquet, siret=siret)
        if hit:
            return MatchResult(
                input_id=input_id,
                resolved_siret=hit["siret"],
                official_name=hit["official_name"],
                confidence_score=1.0,
                match_method="DIRECT_ID",
                alternatives=[],
                debug={"step": "DIRECT_ID", **debug, "hit": hit},
            )

    # If NIF provides a siren, we still proceed with search (not guaranteed to be unique for an establishment)
    siren_from_nif = _extract_siren_from_nif(raw.get("Code NIF"))
    debug["siren_from_nif"] = siren_from_nif

    # STEP 2: cleaning/tokenization (LLM or offline heuristic)
    cleaned: CleanedSupplier = llm.clean_supplier(raw)
    debug["cleaned"] = cleaned.to_json()

    supplier_city = cleaned.clean_city or _normalize_city(raw.get("Ville"))
    supplier_address = _normalize_addr([raw.get("Adresse 1"), raw.get("Adresse 2"), raw.get("Adresse 3")])

    # STEP 3-A: strict local (CP + tiny levenshtein threshold on name)
    if cleaned.clean_cp:
        strict_hits = _strict_local_lookup(
            con,
            partitions_root=partitions_root,
            clean_cp=cleaned.clean_cp,
            clean_name=cleaned.clean_name,
        )
        debug["strict_hits_n"] = len(strict_hits)
        if len(strict_hits) == 1:
            h = strict_hits[0]
            return MatchResult(
                input_id=input_id,
                resolved_siret=h["siret"],
                official_name=h["official_name"],
                confidence_score=0.95,
                match_method="STRICT_LOCAL",
                alternatives=[],
                debug={"step": "STRICT_LOCAL", **debug, "hit": h},
            )

    # STEP 3-B: FTS broad search (with city fallback if no postal code)
    if not cleaned.clean_cp and not supplier_city:
        # No location data at all - cannot reliably match
        return MatchResult(
            input_id=input_id,
            resolved_siret=None,
            official_name=None,
            confidence_score=0.0,
            match_method="NOT_FOUND",
            alternatives=[],
            debug={"step": "NO_LOCATION", **debug},
        )
    
    # FTS search for company name
    fts = _fts_candidates(con, search_token=cleaned.search_token, limit=20)
    debug["fts_n"] = len(fts)
    sirens = [s for (s, _name, _score) in fts]
    
    # Fetch establishments (department-filtered if postal code available, nationwide if only city)
    if cleaned.clean_cp:
        dept = cleaned.clean_cp[:2]
        estabs = _fetch_establishments_for_sirens(con, partitions_root=partitions_root, dept=dept, sirens=sirens)
        debug["search_scope"] = f"department_{dept}"
    else:
        # No postal code but has city - search nationwide (slower but necessary)
        estabs = _fetch_establishments_for_sirens_nationwide(con, etab_parquet=etab_parquet, sirens=sirens)
        debug["search_scope"] = "nationwide"
    debug["estabs_n"] = len(estabs)

    # Secondary filtering (approximate the spec thresholds with true Levenshtein distance)
    filtered: List[Dict[str, Any]] = []
    for c in estabs:
        c_city = _normalize_city(c.get("city"))
        c_addr = _normalize_city(c.get("address"))
        if supplier_city:
            if Levenshtein.distance(c_city, supplier_city) >= 3:
                continue
        if supplier_address:
            if Levenshtein.distance(c_addr, supplier_address) >= 10:
                continue
        filtered.append(c)
    debug["filtered_n"] = len(filtered)

    if not filtered:
        return MatchResult(
            input_id=input_id,
            resolved_siret=None,
            official_name=None,
            confidence_score=0.0,
            match_method="NOT_FOUND",
            alternatives=[],
            debug={"step": "NOT_FOUND", **debug},
        )

    scored = _score_candidates(
        supplier_clean_name=cleaned.clean_name,
        supplier_city=supplier_city,
        supplier_address=supplier_address,
        candidates=filtered,
    )
    debug["top_scores"] = [c["_score_100"] for c in scored[:5]]

    top = scored[0]
    alternatives = [c["siret"] for c in scored[1:6]]

    if top["_score_100"] > 80:
        return MatchResult(
            input_id=input_id,
            resolved_siret=top["siret"],
            official_name=top["official_name"],
            confidence_score=min(1.0, top["_score_100"] / 100.0),
            match_method="CALCULATED",
            alternatives=alternatives,
            debug={"step": "CALCULATED", **debug, "top": top},
        )

    if top["_score_100"] < 50:
        return MatchResult(
            input_id=input_id,
            resolved_siret=None,
            official_name=None,
            confidence_score=0.0,
            match_method="NOT_FOUND",
            alternatives=alternatives,
            debug={"step": "LOW_SCORE", **debug, "top": top},
        )

    # Close scores → arbiter
    if len(scored) >= 2 and abs(scored[0]["_score_100"] - scored[1]["_score_100"]) <= 2:
        a = scored[0]
        b = scored[1]
        question = f"Which address best matches '{supplier_address}'?"
        choice = llm.arbitrate(question, a, b)
        pick = a if choice == "A" else b
        return MatchResult(
            input_id=input_id,
            resolved_siret=pick["siret"],
            official_name=pick["official_name"],
            confidence_score=min(1.0, pick["_score_100"] / 100.0),
            match_method="GEMINI_ARBITER",
            alternatives=alternatives,
            debug={
                "step": "GEMINI_ARBITER",
                **debug,
                "choice": choice,
                "a": {k: v for k, v in a.items() if not k.startswith("_")},
                "b": {k: v for k, v in b.items() if not k.startswith("_")},
            },
        )

    # Otherwise return best-effort calculated
    return MatchResult(
        input_id=input_id,
        resolved_siret=top["siret"],
        official_name=top["official_name"],
        confidence_score=min(1.0, top["_score_100"] / 100.0),
        match_method="CALCULATED",
        alternatives=alternatives,
        debug={"step": "CALCULATED_FALLBACK", **debug, "top": top},
    )

