"""
Preprocessing module for supplier data:
1. Identifies columns (Nom, Postal, Ville, Pays)
2. Infers country from postal code or city if Pays is empty
3. Filters suppliers with "Date dern. Mouvt" = null
4. Splits into French (SIRENE) and non-French (Google) groups
"""
from __future__ import annotations

import pandas as pd
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# French postal code patterns (5 digits, starting with 0-9)
FRENCH_POSTAL_PATTERN = re.compile(r'^[0-9]{5}$')
# French overseas territories postal codes (3 digits starting with 97 or 98)
FRENCH_OVERSEAS_PATTERN = re.compile(r'^9[78][0-9]{3}$')

# Common French city names (uppercase)
FRENCH_CITIES = {
    'PARIS', 'LYON', 'MARSEILLE', 'TOULOUSE', 'NICE', 'NANTES', 'STRASBOURG',
    'MONTPELLIER', 'BORDEAUX', 'LILLE', 'RENNES', 'REIMS', 'SAINT-ETIENNE',
    'TOULON', 'LE HAVRE', 'GRENOBLE', 'DIJON', 'ANGERS', 'NIMES', 'VILLEURBANNE',
    'SAINT-DENIS', 'LE MANS', 'AIX-EN-PROVENCE', 'CLERMONT-FERRAND', 'BREST',
    'LIMOGES', 'TOURS', 'AMIENS', 'PERPIGNAN', 'METZ', 'BESANCON', 'BOULOGNE-BILLANCOURT',
    'ORLEANS', 'MULHOUSE', 'ROUEN', 'CAEN', 'NANCY', 'SAINT-DENIS', 'ARGENTEUIL',
    'MONTPELLIER', 'ROUBAIX', 'TOURCOING', 'NANTERRE', 'AVIGNON', 'CRETEIL',
    'DUNKERQUE', 'POITIERS', 'ASNIERES-SUR-SEINE', 'COURBEVOIE', 'VERSAILLES',
    'VITRY-SUR-SEINE', 'COLOMBES', 'AULNAY-SOUS-BOIS', 'LA COURNEUVE', 'RUEIL-MALMAISON',
    'ANTIBES', 'SAINT-MAUR-DES-FOSSES', 'CANNES', 'BOURGES', 'MERIGNAC', 'SAINT-NAZAIRE',
    'COLOMBES', 'ISSY-LES-MOULINEAUX', 'NOISY-LE-GRAND', 'EVRY', 'CHAMPIGNY-SUR-MARNE',
    'LEVALLOIS-PERRET', 'ANTONY', 'CLICHY', 'IVRY-SUR-SEINE', 'NEUILLY-SUR-SEINE',
    'SARCELLES', 'PANTIN', 'NOISY-LE-SEC', 'LA ROCHELLE', 'SAINT-OUEN', 'CHAMBERY',
    'AUXERRE', 'SETE', 'BAYONNE', 'BRIVE-LA-GAILLARDE', 'FRECHES', 'CHALON-SUR-SAONE',
    'MONTBELIARD', 'CHARTRES', 'VALENCE', 'ARRAS', 'BOULOGNE-SUR-MER', 'CALAIS',
    'SAINT-BRIEUC', 'ALBI', 'MEAUX', 'CHARTRES', 'RODEZ', 'AGEN', 'TARBES', 'PAU',
    'PERIGUEUX', 'BRIVE', 'TULLE', 'GUERET', 'MONTLUCON', 'VIERZON', 'CHATEAUROUX',
    'BLOIS', 'ORLEANS', 'CHARTRES', 'DREUX', 'VENDOME', 'ROMORANTIN-LANTHENAY',
    'NOGENT-LE-ROTROU', 'CHATEAUDUN', 'GIEN', 'MONTARGIS', 'PITHIVIERS', 'ETAMPES',
    'CORBEIL-ESSONNES', 'MELUN', 'FONTAINEBLEAU', 'PROVINS', 'COULOMMIERS', 'MEAUX',
    'TORCY', 'MARNE-LA-VALLEE', 'NOISY-LE-GRAND', 'BRY-SUR-MARNE', 'CHAMPIGNY-SUR-MARNE',
    'SAINT-MAUR-DES-FOSSES', 'CRETEIL', 'VINCENNES', 'SAINT-MANDE', 'FONTENAY-SOUS-BOIS',
    'NOGENT-SUR-MARNE', 'LE PERREUX-SUR-MARNE', 'BRY-SUR-MARNE', 'NEUILLY-SUR-MARNE',
    'JOINVILLE-LE-PONT', 'SAINT-MAURICE', 'CHAMPIGNY-SUR-MARNE', 'SUCY-EN-BRIE',
    'BOISSY-SAINT-LEGER', 'LIMEIL-BREVANNES', 'VALENTON', 'BONNEUIL-SUR-MARNE',
    'SAINT-MAUR-DES-FOSSES', 'LA VARENNE-SAINT-HILAIRE', 'ORMESSON-SUR-MARNE',
    'SAINT-MAURICE', 'CHAMPIGNY-SUR-MARNE', 'BRY-SUR-MARNE', 'NEUILLY-SUR-MARNE',
    'JOINVILLE-LE-PONT', 'SAINT-MAURICE', 'CHAMPIGNY-SUR-MARNE', 'SUCY-EN-BRIE',
    'BOISSY-SAINT-LEGER', 'LIMEIL-BREVANNES', 'VALENTON', 'BONNEUIL-SUR-MARNE',
    'SAINT-MAUR-DES-FOSSES', 'LA VARENNE-SAINT-HILAIRE', 'ORMESSON-SUR-MARNE',
}

# French country names in various languages
FRENCH_COUNTRY_NAMES = {
    'FRANCE', 'FR', 'FRA', 'FRANCAIS', 'FRANCAISE', 'FRANÇAIS', 'FRANÇAISE',
    'FRENCH', 'FRANCE METROPOLITAINE', 'METROPOLE', 'METROPOLITAIN',
}


def _normalize_string(value: any) -> str:
    """Normalize string value: strip, uppercase, handle NaN."""
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def _is_french_postal_code(postal: str) -> bool:
    """
    Check if postal code matches French pattern.
    Handles edge cases: float values, missing leading zeros, whitespace.
    """
    if not postal:
        return False
    # Convert to string and strip whitespace
    postal = str(postal).strip()
    # Handle float values (e.g., "75001.0" -> "75001")
    if '.' in postal:
        postal = postal.split('.')[0].strip()
    # Handle missing leading zeros (e.g., "6000" -> "06000" for Nice)
    if len(postal) < 5 and postal.isdigit():
        postal = postal.zfill(5)
    # Standard 5-digit French postal codes
    if FRENCH_POSTAL_PATTERN.match(postal):
        return True
    # French overseas territories (97xxx, 98xxx)
    if FRENCH_OVERSEAS_PATTERN.match(postal):
        return True
    return False


def _is_french_city(city: str) -> str:
    """
    Check if city name is likely French.
    Returns True only if:
    1. City is in known French cities list, OR
    2. City matches French patterns AND is not a known non-French city
    """
    if not city:
        return False
    city = city.strip().upper()
    
    # Direct match in known French cities
    if city in FRENCH_CITIES:
        return True
    
    # Known non-French cities that might match patterns (false positive prevention)
    non_french_cities = {
        'LA PAZ', 'LAS VEGAS', 'LOS ANGELES', 'LA HABANA', 'LA PLATA',
        'SANTA FE', 'SANTA CRUZ', 'SAN JOSE', 'SAN FRANCISCO',
    }
    if city in non_french_cities:
        return False
    
    # Check for French city patterns (more specific patterns to reduce false positives)
    # Only use patterns if city is not obviously non-French
    french_indicators = [
        'SAINT-', 'SAINTE-', 'LES ', 'DU ', 'DE LA ', 'DES ',
        'SUR ', 'SOUS ', 'EN ', 'ET ', 'L\'', 'D\'', 'AUX ', 'AU ',
        # More specific patterns for "LE" and "LA" to reduce false positives
        'LE HAVRE', 'LE MANS', 'LA ROCHELLE', 'LA COURNEUVE',
    ]
    for indicator in french_indicators:
        if indicator in city:
            return True
    
    # Generic "LE " and "LA " patterns (less reliable, use with caution)
    # Only if city doesn't look obviously non-French
    if city.startswith('LE ') and len(city) > 5:
        return True
    if city.startswith('LA ') and len(city) > 5 and 'PAZ' not in city and 'VEGAS' not in city:
        return True
    
    return False


def _infer_country(row: Dict[str, any], col_pays: str, col_postal: str, col_ville: str, col_siret: Optional[str] = None) -> str:
    """
    Infer country from row data.
    Priority:
    0. Code SIRET: If exists and valid (>=9 digits) → FRANCE (most reliable!)
    1. Pays column: If "FRA" → FRANCE, if other country → that country, if empty → continue
    2. If Pays empty: Check Ville (city) - if French city → FRANCE
    3. If Ville not French/empty: Check Postal code - if 5 digits → FRANCE
    4. Otherwise → UNKNOWN
    """
    # Step 0: Check Code SIRET first (most reliable indicator of French company)
    if col_siret:
        siret = _normalize_string(row.get(col_siret))
        if siret and len(siret) >= 9:  # SIRET is 14 digits, SIREN is 9 digits
            return 'FRANCE'
    
    # Step 1: Check Pays column
    pays = _normalize_string(row.get(col_pays))
    if pays:
        # If Pays = "FRA" → FRANCE
        if pays == 'FRA' or pays in FRENCH_COUNTRY_NAMES or pays.startswith('FR'):
            return 'FRANCE'
        # If Pays = other country → return that country
        return pays if len(pays) > 1 else 'UNKNOWN'
    
    # Step 2: Pays is empty → Check Ville (city)
    ville = _normalize_string(row.get(col_ville))
    if ville and _is_french_city(ville):
        return 'FRANCE'
    
    # Step 3: Ville not French/empty → Check Postal code (5 digits)
    postal = _normalize_string(row.get(col_postal))
    if postal and _is_french_postal_code(postal):
        return 'FRANCE'
    
    # Step 4: Cannot infer - return UNKNOWN
    return 'UNKNOWN'


def identify_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """
    Identify column names for Nom, Postal, Ville, Pays, Date dern. Mouvt, Code SIRET.
    Returns dict mapping standard names to actual column names.
    """
    columns_upper = {col.upper(): col for col in df.columns}
    
    # Try various possible column names
    col_mapping = {}
    
    # Nom / Name
    for possible in ['NOM', 'NAME', 'NOM FOURNISSEUR', 'SUPPLIER NAME', 'COMPANY NAME', 'RAISON SOCIALE']:
        if possible in columns_upper:
            col_mapping['Nom'] = columns_upper[possible]
            break
    
    # Postal / Code Postal
    for possible in ['POSTAL', 'CODE POSTAL', 'CP', 'ZIP', 'ZIP CODE', 'POSTCODE', 'POSTAL CODE']:
        if possible in columns_upper:
            col_mapping['Postal'] = columns_upper[possible]
            break
    
    # Ville / City
    for possible in ['VILLE', 'CITY', 'COMMUNE', 'LOCALITE']:
        if possible in columns_upper:
            col_mapping['Ville'] = columns_upper[possible]
            break
    
    # Pays / Country
    for possible in ['PAYS', 'COUNTRY', 'PAYS FOURNISSEUR', 'COUNTRY CODE']:
        if possible in columns_upper:
            col_mapping['Pays'] = columns_upper[possible]
            break
    
    # Code SIRET (critical for French identification)
    for possible in ['CODE SIRET', 'SIRET', 'SIREN', 'CODE SIREN']:
        if possible in columns_upper:
            col_mapping['Code SIRET'] = columns_upper[possible]
            break
    
    # Date dern. Mouvt / Last Movement Date
    for possible in ['DATE DERN. MOUVT', 'DATE DERNIER MOUVEMENT', 'LAST MOVEMENT DATE', 
                     'DATE DERN MOUVT', 'DERNIER MOUVEMENT', 'LAST MOVEMENT']:
        if possible in columns_upper:
            col_mapping['Date dern. Mouvt'] = columns_upper[possible]
            break
    
    return col_mapping


def preprocess_suppliers(
    input_xlsx: str,
    output_dir: str = "preprocessed",
    *,
    filter_inactive: bool = True,
    limit_rows: Optional[int] = None,
) -> Tuple[str, str, Dict[str, int]]:
    """
    Preprocess supplier data:
    1. Load Excel file
    2. Identify columns
    3. Infer countries
    4. Filter inactive suppliers (Date dern. Mouvt = null)
    5. Split into French (SIRENE) and non-French (Google) groups
    
    Returns:
        Tuple of (french_xlsx_path, non_french_xlsx_path, statistics_dict)
    """
    print(f"[preprocess] Loading {input_xlsx}...")
    # Detect file format and load accordingly
    input_path = Path(input_xlsx)
    if input_path.suffix.lower() == '.csv':
        # Read CSV with string types to preserve leading zeros and prevent float conversion
        # Try UTF-8 first, fallback to latin1 if needed
        try:
            df = pd.read_csv(
                input_xlsx,
                dtype={
                    'Postal': str,
                    'Code SIRET': str,
                    'Code SIREN': str,
                    'SIRET': str,
                    'SIREN': str,
                    'Auxiliaire': str,
                },
                encoding='utf-8',
                na_values=['', ' ', 'NaN', 'nan', 'NULL', 'null'],
                keep_default_na=True,
            )
        except UnicodeDecodeError:
            print("[preprocess] UTF-8 failed, trying latin1 encoding...")
            df = pd.read_csv(
                input_xlsx,
                dtype={
                    'Postal': str,
                    'Code SIRET': str,
                    'Code SIREN': str,
                    'SIRET': str,
                    'SIREN': str,
                    'Auxiliaire': str,
                },
                encoding='latin1',
                na_values=['', ' ', 'NaN', 'nan', 'NULL', 'null'],
                keep_default_na=True,
            )
    else:
        # Read Excel file
        df = pd.read_excel(
            input_xlsx,
            dtype={
                'Postal': str,
                'Code SIRET': str,
                'Auxiliaire': str,
            },
        )
    
    if limit_rows is not None:
        df = df.head(limit_rows)
        print(f"[preprocess] Limited to {limit_rows} rows")
    
    original_count = len(df)
    print(f"[preprocess] Loaded {original_count} suppliers")
    
    # Identify columns
    col_mapping = identify_columns(df)
    print(f"[preprocess] Column mapping: {col_mapping}")
    
    # Verify required columns exist
    required = ['Nom', 'Postal', 'Ville']
    missing = [col for col in required if col not in col_mapping]
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Found columns: {list(df.columns)}")
    
    # Add inferred country column
    print("[preprocess] Inferring countries...")
    df['_inferred_country'] = df.apply(
        lambda row: _infer_country(
            row.to_dict(),
            col_mapping.get('Pays', ''),
            col_mapping.get('Postal', ''),
            col_mapping.get('Ville', ''),
            col_mapping.get('Code SIRET', '')
        ),
        axis=1
    )
    
    # If Pays column exists, use it (fill empty with inferred)
    if 'Pays' in col_mapping:
        pays_col = col_mapping['Pays']
        df['_pays_value'] = df[pays_col].fillna('').astype(str).str.strip().str.upper()
        # If Pays has value, use it (normalize FRA to FRANCE)
        # If Pays is empty, use inferred country
        df['_final_country'] = df.apply(
            lambda row: (
                'FRANCE' if row['_pays_value'] == 'FRA' or row['_pays_value'] in FRENCH_COUNTRY_NAMES or row['_pays_value'].startswith('FR')
                else row['_pays_value'] if row['_pays_value']
                else row['_inferred_country']
            ),
            axis=1
        )
        df = df.drop(columns=['_pays_value'], errors='ignore')
    else:
        df['_final_country'] = df['_inferred_country']
    
    # Filter inactive suppliers (Date dern. Mouvt = null or empty)
    if filter_inactive and 'Date dern. Mouvt' in col_mapping:
        date_col = col_mapping['Date dern. Mouvt']
        before_filter = len(df)
        # Filter out NaN, empty strings, and whitespace-only values
        # Use more lenient filtering - only filter true NaN, not string representations
        mask = (
            df[date_col].notna() & 
            (df[date_col].astype(str).str.strip() != '') &
            (df[date_col].astype(str).str.strip().str.lower() != 'nan') &
            (df[date_col].astype(str).str.strip().str.lower() != 'null') &
            (df[date_col].astype(str).str.strip() != 'None')
        )
        df = df[mask]
        filtered_count = before_filter - len(df)
        print(f"[preprocess] Filtered {filtered_count} inactive suppliers (Date dern. Mouvt = null/empty)")
        print(f"[preprocess] Remaining after filter: {len(df)} suppliers")
    else:
        filtered_count = 0
        if not filter_inactive:
            print("[preprocess] Skipping inactive filter (filter_inactive=False)")
        else:
            print("[preprocess] No 'Date dern. Mouvt' column found, skipping inactive filter")
    
    # Split by country
    df_french = df[df['_final_country'] == 'FRANCE'].copy()
    df_non_french = df[df['_final_country'] != 'FRANCE'].copy()
    
    # Remove helper columns
    df_french = df_french.drop(columns=['_inferred_country', '_final_country'], errors='ignore')
    df_non_french = df_non_french.drop(columns=['_inferred_country', '_final_country'], errors='ignore')
    
    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # Save split files
    french_path = str(output_path / "suppliers_french.xlsx")
    non_french_path = str(output_path / "suppliers_non_french.xlsx")
    
    print(f"[preprocess] Saving French suppliers ({len(df_french)} rows) to {french_path}...")
    df_french.to_excel(french_path, index=False)
    
    print(f"[preprocess] Saving non-French suppliers ({len(df_non_french)} rows) to {non_french_path}...")
    df_non_french.to_excel(non_french_path, index=False)
    
    # Statistics
    stats = {
        'total_original': original_count,
        'filtered_inactive': filtered_count,
        'french_suppliers': len(df_french),
        'non_french_suppliers': len(df_non_french),
        'total_processed': len(df_french) + len(df_non_french),
    }
    
    print()
    print("=" * 80)
    print("PREPROCESSING SUMMARY")
    print("=" * 80)
    print(f"Original suppliers:        {stats['total_original']}")
    print(f"Filtered (inactive):       {stats['filtered_inactive']}")
    print(f"French suppliers:          {stats['french_suppliers']} -> SIRENE matching")
    print(f"Non-French suppliers:      {stats['non_french_suppliers']} -> Google search")
    print(f"Total to process:          {stats['total_processed']}")
    print("=" * 80)
    
    return french_path, non_french_path, stats
