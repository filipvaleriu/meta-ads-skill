"""
secret_store.py
---------------
Stocare secrete API in Windows Credential Manager (prin libraria `keyring`),
in loc de valori in clar in fisierele config/*.ini.

Model:
  - Secretele (client_secret, refresh_token, developer_token, ...) traiesc in
    Credential Manager-ul FIECAREI statii. Nu ajung niciodata in git sau zip.
  - .ini ramane pentru ne-secrete (property_id, customer_id, api_version).
  - Codul e identic pe toate statiile si se sincronizeaza prin git.

Integrare (in config_loader.py):
    from secret_store import overlay_secrets
    cp = _load_ini(path)
    overlay_secrets(cp, "ga4")   # umple secretele din keyring daca exista
    return cp

Provisioning (o singura data per statie):
    python secret_store.py migrate ga4 config/ga4.ini      # ini -> keyring + goleste in ini
    python secret_store.py set ga4 refresh_token           # introducere manuala (ascuns)
    python secret_store.py status ga4                      # ce e in keyring (fara valori)
"""

from __future__ import annotations

import configparser
import getpass
import re
import sys
from pathlib import Path

try:
    import keyring
except ImportError:  # pragma: no cover
    keyring = None  # type: ignore

# Prefix sub care grupam credentialele in Credential Manager: "FGO:<service>".
SERVICE_PREFIX = "FGO"

# Campurile considerate SECRETE per serviciu (restul raman in .ini).
SECRET_FIELDS: dict[str, tuple[str, ...]] = {
    "google_ads": ("developer_token", "client_secret", "refresh_token"),
    "ga4": ("client_secret", "refresh_token"),
    "meta_ads": ("app_secret", "access_token"),
    "facebook_ads": ("app_secret", "access_token"),
}

# Valori care nu sunt secrete reale (template-uri / goale) - se ignora la migrare.
_PLACEHOLDER = re.compile(r"^\s*(your_|xxx|<.*>|change_me|placeholder|0+)?\s*$", re.IGNORECASE)


class SecretsUnavailable(RuntimeError):
    """keyring nu e instalat / backend indisponibil."""


def _kr():
    if keyring is None:
        raise SecretsUnavailable(
            "Libraria 'keyring' nu e instalata. Ruleaza: pip install keyring"
        )
    return keyring


def _service(service: str) -> str:
    return f"{SERVICE_PREFIX}:{service}"


def is_placeholder(value: str | None) -> bool:
    """True daca valoarea e goala sau un template (nu un secret real)."""
    return value is None or bool(_PLACEHOLDER.match(value))


# ---------------------------------------------------------------------------
# API de baza
# ---------------------------------------------------------------------------

def get_secret(service: str, field: str) -> str | None:
    """Citeste un secret din Credential Manager (None daca lipseste)."""
    return _kr().get_password(_service(service), field)


def set_secret(service: str, field: str, value: str) -> None:
    """Scrie un secret in Credential Manager."""
    _kr().set_password(_service(service), field, value)


def delete_secret(service: str, field: str) -> None:
    """Sterge un secret (ignora daca nu exista)."""
    try:
        _kr().delete_password(_service(service), field)
    except Exception:  # keyring arunca daca lipseste - tratat ca no-op
        pass


def overlay_secrets(cp: configparser.ConfigParser, service: str) -> list[str]:
    """Suprascrie in `cp` campurile secrete cu valorile din keyring (daca exista).

    Backward-compatible: daca un secret nu e in keyring, ramane valoarea din .ini.
    Returneaza lista campurilor preluate din keyring.
    """
    applied: list[str] = []
    for field in SECRET_FIELDS.get(service, ()):  # serviciu necunoscut -> nimic
        value = get_secret(service, field)
        if value:
            if not cp.has_section(service):
                cp.add_section(service)
            cp.set(service, field, value)
            applied.append(field)
    return applied


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------

def migrate_ini(service: str, ini_path: str | Path, blank: bool = True) -> list[str]:
    """Muta secretele din .ini in keyring; optional le goleste in .ini.

    Pastreaza comentariile si campurile ne-secrete din .ini (editare pe linii,
    nu rescriere cu configparser care ar pierde comentariile).
    """
    path = Path(ini_path)
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path, encoding="utf-8")

    moved: list[str] = []
    for field in SECRET_FIELDS.get(service, ()):
        if not cp.has_option(service, field):
            continue
        value = cp.get(service, field)
        if is_placeholder(value):
            continue
        set_secret(service, field, value)
        moved.append(field)

    if blank and moved:
        _blank_fields_in_file(path, moved)
    return moved


def _blank_fields_in_file(path: Path, fields: list[str]) -> None:
    """Goleste `field = ...` -> `field =` pastrand restul fisierului intact."""
    text = path.read_text(encoding="utf-8")
    for field in fields:
        text = re.sub(
            rf"(?im)^(\s*{re.escape(field)}\s*=).*$",
            r"\1",
            text,
        )
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd, *rest = argv
    if cmd == "migrate" and len(rest) == 2:
        service, ini = rest
        moved = migrate_ini(service, ini)
        print(f"Mutate in Credential Manager ({_service(service)}): {moved or 'nimic (placeholder/lipsa)'}")
        if moved:
            print(f"Golite in {ini}. Secretele sunt acum DOAR in Credential Manager.")
        return 0
    if cmd == "set" and len(rest) == 2:
        service, field = rest
        value = getpass.getpass(f"Valoare pentru {_service(service)}/{field} (ascuns): ")
        set_secret(service, field, value)
        print("Salvat.")
        return 0
    if cmd == "status" and len(rest) == 1:
        service = rest[0]
        for field in SECRET_FIELDS.get(service, ()):
            present = get_secret(service, field) is not None
            print(f"  {field:18} {'OK (in keyring)' if present else '-- lipseste'}")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
