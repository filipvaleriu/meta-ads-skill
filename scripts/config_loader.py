"""
config_loader.py
----------------
Loader centralizat pentru configurari non-DB (Google Ads + GA4 + Facebook/Meta).

Pentru DB, logica traieste in skill-ul `fgo-db-analytics` (scripts/fgo_connect.py).
Acest loader il importa si il re-exporta ca sa fie un singur punct de intrare:

    from config_loader import load_db_config, load_google_ads, load_facebook_ads

Conventie fisiere:
  - Template-urile (*.template.ini) sunt in radacina repo-ului si SE commit-eaza.
  - Fisierele reale (cu credentiale) sunt in config/ si NU se commit-eaza.
  - Daca un fisier lipseste, loader-ul afiseaza instructiuni clare.
"""

from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"

# ---- Import skill DB (fgo-db-analytics) ----
# Adaugam skill-ul la sys.path ca sa putem importa fgo_connect.
# Cautam in mai multe locatii: ROOT/fgo-db-analytics/scripts (standalone),
# sau ROOT/.claude/skills/fgo-db-analytics/scripts (Claude project layout).
_SKILL_CANDIDATES = [
    ROOT / "fgo-db-analytics" / "scripts",
    ROOT / ".claude" / "skills" / "fgo-db-analytics" / "scripts",
]
_SKILL_SCRIPTS = next((p for p in _SKILL_CANDIDATES if p.exists()), None)
if _SKILL_SCRIPTS and str(_SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SKILL_SCRIPTS))

try:
    from fgo_connect import DbConfig, ConfigError  # noqa: F401
    _HAS_DB_SKILL = True
except ImportError:
    _HAS_DB_SKILL = False

    class ConfigError(Exception):  # type: ignore
        pass


# ============================================================================
# DB - delegat catre skill
# ============================================================================

def load_db_config(path: str | None = None):
    """Incarca config DB prin skill-ul fgo-db-analytics.

    Cautare config:
      1. parametrul explicit `path`
      2. variabila de mediu FGO_DB_CONFIG
      3. config/db_config.ini relativ la cwd sau la scriptul caller
    """
    if not _HAS_DB_SKILL:
        raise ConfigError(
            "Skill-ul fgo-db-analytics nu e disponibil (lipseste fgo-db-analytics/scripts/fgo_connect.py).\n"
            "Instaleaza skill-ul sau foloseste direct fgo_connect."
        )
    return DbConfig.load(path)


# ============================================================================
# Helpers
# ============================================================================

def _require(file_name: str, template_name: str) -> Path:
    """Verifica existenta unui config real; daca nu exista, arunca eroare explicativa."""
    real = CONFIG_DIR / file_name
    # Template-urile traiesc tot in config/ (se commit-eaza), instantele (cu date) nu.
    template = CONFIG_DIR / template_name

    if not real.exists():
        msg = [
            "",
            "=" * 60,
            f"  Lipseste fisierul de configurare: {real}",
            "=" * 60,
            "",
            "  Cum rezolvi:",
            f"    1. Creeaza folderul:   {CONFIG_DIR}",
            f"    2. Copiaza template-ul: {template}",
            f"                  ->      {real}",
            "    3. Completeaza valorile reale.",
            "",
            "  Folderul config/ este in .gitignore - NU se commit-eaza.",
            "=" * 60,
            "",
        ]
        raise ConfigError("\n".join(msg))
    return real


def _load_ini(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path, encoding="utf-8")
    return cp


# ============================================================================
# Google Ads / GA4
# ============================================================================

def load_google_ads() -> configparser.ConfigParser:
    path = _require("google_ads.ini", "google_ads.template.ini")
    return _load_ini(path)


# ============================================================================
# GA4
# ============================================================================

def load_ga4() -> configparser.ConfigParser:
    path = _require("ga4.ini", "ga4.template.ini")
    return _load_ini(path)


# ============================================================================
# Settings aplicatie (non-sensitive)
# ============================================================================

def load_settings() -> configparser.ConfigParser:
    path = _require("settings.ini", "settings.template.ini")
    return _load_ini(path)


# ============================================================================
# Facebook / Meta Ads
# ============================================================================

def load_facebook_ads() -> configparser.ConfigParser:
    path = _require("facebook_ads.ini", "facebook_ads.template.ini")
    return _load_ini(path)


# ============================================================================
# Loader agregat - merge mai multe config-uri intr-un singur ConfigParser
# ============================================================================

def load_apis(require_google_ads: bool = True) -> configparser.ConfigParser:
    """Incarca toate config-urile API disponibile intr-un singur ConfigParser.

    Util pentru scripturile care au nevoie de mai multe sectiuni (google_ads,
    ga4, meta_ads, settings). Fisierele optionale care lipsesc sunt ignorate
    silentios; pentru cele lipsa scripturile vor primi KeyError la
    `cp.get(section, ...)` cand incearca sa citeasca o sectiune absenta.

    Args:
        require_google_ads: daca True si google_ads.ini lipseste, arunca ConfigError.
    """
    cp = configparser.ConfigParser(interpolation=None)
    # google_ads este singurul obligatoriu - fara el nu poti face mai nimic util
    if require_google_ads:
        cp.read(_require("google_ads.ini", "google_ads.template.ini"), encoding="utf-8")
    else:
        p = CONFIG_DIR / "google_ads.ini"
        if p.exists():
            cp.read(p, encoding="utf-8")

    for name in ("ga4.ini", "facebook_ads.ini", "settings.ini"):
        p = CONFIG_DIR / name
        if p.exists():
            cp.read(p, encoding="utf-8")
    return cp


# ============================================================================
# Verificare completitudine config (CLI)
# ============================================================================

def _is_placeholder(v: str) -> bool:
    if not v:
        return True
    v = v.strip()
    if v in ("", ".apps.googleusercontent.com", "0000000000", "act_0000000000"):
        return True
    for marker in ("YOUR_", "PASTE_", "SERVER_NAME_HERE", "DATABASE_NAME_HERE", "TODO", "CHANGE_ME"):
        if marker in v:
            return True
    return False


def _status(v: str, required: bool = True) -> str:
    if _is_placeholder(v):
        return "[LIPSA]" if required else "[opt]"
    masked = (v[:4] + "***" + v[-4:]) if len(v) > 12 else "***"
    return f"[OK]   {masked}"


def _check_db() -> int:
    errors = 0
    print("SQL Database:")
    if not _HAS_DB_SKILL:
        print("  [!] skill fgo-db-analytics indisponibil - nu pot verifica configul DB")
        return 1
    try:
        db = load_db_config()
    except ConfigError as e:
        print(f"  [LIPSA CONFIG]\n{e}")
        return 1

    print(f"  server                    {_status(db.server)}")
    print(f"  database                  {_status(db.database)}")
    print(f"  port                      [OK]   {db.port}")
    print(f"  auth_type                 [OK]   {db.auth_type}")

    if db.auth_type == "sql":
        print(f"  credentials_source        [OK]   {db.credentials_source}")
        if db.credentials_source == "prompt":
            print("    -> user si parola se cer la runtime (nu se salveaza)")
        elif db.credentials_source == "keyring":
            try:
                import keyring  # type: ignore
                stored = keyring.get_password("fgo-db-analytics", db.keyring_key)
                print("    -> credentiale " + ("gasite in Credential Manager" if stored else "nu exista inca (se cer la prima rulare)"))
            except ImportError:
                print("    [!] pip install keyring")
                errors += 1
        elif db.credentials_source == "env":
            env_ok = bool(os.environ.get("DB_USERNAME") and os.environ.get("DB_PASSWORD"))
            print(f"    -> DB_USERNAME / DB_PASSWORD in env: {'DA' if env_ok else 'NU (lipsesc!)'}")
            if not env_ok:
                errors += 1
    return errors


def _check_google() -> int:
    errors = 0
    print("Google Ads:")
    try:
        ga = load_google_ads()
    except ConfigError as e:
        print(f"  [LIPSA CONFIG]\n{e}")
        return 1

    for key in ["developer_token", "login_customer_id", "customer_id",
                "client_id", "client_secret", "refresh_token"]:
        v = ga["google_ads"].get(key, "")
        s = _status(v)
        if s.startswith("[LIPSA]"):
            errors += 1
        print(f"  {key:25s} {s}")

    if ga.has_section("google_analytics"):
        print("  [google_analytics]")
        for key in ["property_id", "measurement_id", "api_secret"]:
            v = ga["google_analytics"].get(key, "")
            print(f"    {key:23s} {_status(v, required=False)}")
    return errors


def _check_facebook() -> int:
    errors = 0
    print("Meta Ads (Facebook/Instagram):")
    try:
        fb = load_facebook_ads()
    except ConfigError as e:
        print(f"  [LIPSA CONFIG]\n{e}")
        return 1

    if not fb.has_section("meta_ads"):
        print("  [LIPSA] sectiunea [meta_ads] nu exista in config/facebook_ads.ini")
        return 1

    for key in ["app_id", "app_secret", "access_token", "ad_account_id"]:
        v = fb["meta_ads"].get(key, "")
        s = _status(v)
        if s.startswith("[LIPSA]"):
            errors += 1
        print(f"  {key:25s} {s}")
    # Reminder expirare token (opt)
    exp = fb["meta_ads"].get("token_expires_at", "").strip()
    if exp:
        try:
            from datetime import date as _d
            days = (_d.fromisoformat(exp) - _d.today()).days
            tag = "[OK]  " if days >= 7 else "[WARN]"
            print(f"  token_expires_at          {tag} {exp} ({days} zile ramase)")
        except ValueError:
            print(f"  token_expires_at          [opt]  {exp}")
    return errors


def _check_all() -> int:
    print(f"Root proiect: {ROOT}")
    print(f"Folder config: {CONFIG_DIR}")
    print(f"Skill DB disponibil: {'DA' if _HAS_DB_SKILL else 'NU'}")
    print()

    errors = _check_db()
    print()
    errors += _check_google()
    print()
    errors += _check_facebook()
    print()
    if errors:
        print(f"TOTAL: {errors} campuri lipsa/incomplete.")
    else:
        print("TOTAL: toate configurarile complete.")
    return errors


if __name__ == "__main__":
    sys.exit(1 if _check_all() else 0)
