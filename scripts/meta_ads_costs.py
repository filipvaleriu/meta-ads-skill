"""
Meta Ads Costs Fetcher — FGO Marketing
======================================
Preia costurile campaniilor Meta Ads (Facebook/Instagram) via Graph API.
Genereaza output compatibil cu sp_Import_Costuri_Campanii (INSERT-uri T-SQL).

Versiune: 2.0 — Adauga perioade campanie (start_time, stop_time, effective_status)
             si prima/ultima luna cu spend per campanie.

Folosire:
  python meta_ads_costs.py                    # preia costuri (ultimele 6 luni)
  python meta_ads_costs.py --months 12        # ultimele 12 luni
  python meta_ads_costs.py --refresh-token    # reface long-lived token din short-lived
  python meta_ads_costs.py --start 2024-11-01 --end 2026-03-31   # interval custom

Config: config/facebook_ads.ini, sectiunea [meta_ads] (prin config_loader.load_facebook_ads)
Output: meta_ads_costs_output.sql + meta_ads_costs_output.csv + meta_ads_campaigns_output.csv
"""

import requests
import configparser
import csv
import getpass
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import load_facebook_ads, ConfigError  # noqa: E402

# Fisierul real (NU template) - scris de --refresh-token cand actualizam token-ul.
CONFIG_FILE = ROOT / "config" / "facebook_ads.ini"

OUTPUT_SQL = SCRIPT_DIR / "meta_ads_costs_output.sql"
OUTPUT_CSV = SCRIPT_DIR / "meta_ads_costs_output.csv"
OUTPUT_CAMPAIGNS_CSV = SCRIPT_DIR / "meta_ads_campaigns_output.csv"

# Versiunea Graph API curenta (2026) - poate fi suprascrisa din config [meta_ads].api_version
DEFAULT_API_VERSION = "v25.0"
BASE_URL = ""  # populat in main() pe baza versiunii din config


def _is_placeholder(value: str) -> bool:
    if not value:
        return True
    v = value.strip()
    if not v:
        return True
    for marker in ("YOUR_", "PASTE_", "PUNE", "0000000000"):
        if marker in v:
            return True
    return False


def load_config():
    """Incarca sectiunea [meta_ads] din config/facebook_ads.ini via config_loader."""
    try:
        cp = load_facebook_ads()
    except ConfigError as e:
        print(f"EROARE: {e}")
        sys.exit(1)
    if not cp.has_section("meta_ads"):
        print(f"EROARE: Nu gasesc sectiunea [meta_ads] in {CONFIG_FILE}")
        print("  Verifica ca ai copiat template-ul in config/facebook_ads.ini")
        sys.exit(1)
    return cp["meta_ads"]


def _write_token(token: str, expires_at: str | None):
    """Scrie access_token (si optional token_expires_at) in config/facebook_ads.ini.

    Preserveaza restul sectiunilor si comentariilor (config nu are comentarii
    persistente in ConfigParser, deci rescriem doar campurile necesare).
    """
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(str(CONFIG_FILE), encoding="utf-8")
    if not cfg.has_section("meta_ads"):
        cfg.add_section("meta_ads")
    cfg["meta_ads"]["access_token"] = token
    if expires_at:
        cfg["meta_ads"]["token_expires_at"] = expires_at
    with open(str(CONFIG_FILE), "w", encoding="utf-8") as f:
        cfg.write(f)
    print(f"  access_token salvat in {CONFIG_FILE}")
    if expires_at:
        print(f"  token_expires_at = {expires_at}")


def refresh_token(config):
    """Transforma short-lived token (cerut interactiv) in long-lived (~60 zile)."""
    print("\n=== Refresh Token: short -> long-lived ===")
    app_id = config.get("app_id", "").strip()
    app_secret = config.get("app_secret", "").strip()
    if _is_placeholder(app_id) or _is_placeholder(app_secret):
        print("EROARE: app_id / app_secret lipsesc in [meta_ads] (config/facebook_ads.ini).")
        sys.exit(1)

    # Short-lived NU se salveaza - cerut interactiv (getpass, nu apare pe ecran)
    print("  Genereaza un short-lived token din Graph API Explorer:")
    print("  https://developers.facebook.com/tools/explorer/")
    try:
        short_token = getpass.getpass("  Paste short-lived token (nu apare pe ecran): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Anulat.")
        sys.exit(1)
    if not short_token:
        print("EROARE: token gol.")
        sys.exit(1)

    r = requests.get(f"{BASE_URL}/oauth/access_token", params={
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    })
    data = r.json()

    if "access_token" in data:
        token = data["access_token"]
        expires_in = data.get("expires_in", 0)
        days = expires_in // 86400 if isinstance(expires_in, int) else "?"
        expires_at = None
        if isinstance(expires_in, int) and expires_in > 0:
            expires_at = (datetime.now() + timedelta(seconds=expires_in)).strftime("%Y-%m-%d")
        print(f"  Token obtinut! Expira in ~{days} zile ({expires_at or 'permanent?'})")
        _write_token(token, expires_at)
        return token
    else:
        print(f"  EROARE: {data.get('error', {}).get('message', data)}")
        sys.exit(1)


def get_token(config):
    """Returneaza access_token-ul (long-lived) din config."""
    token = config.get("access_token", "").strip()
    if _is_placeholder(token):
        print("EROARE: access_token lipseste sau e placeholder in [meta_ads].")
        print("  Ruleaza: python meta_ads_costs.py --refresh-token")
        sys.exit(1)
    return token


def check_token_validity(token):
    """Verifica daca token-ul e valid si cand expira"""
    r = requests.get(f"{BASE_URL}/debug_token", params={
        "input_token": token,
        "access_token": token,
    })
    data = r.json().get("data", {})
    if data.get("is_valid"):
        expires = data.get("expires_at", 0)
        if expires > 0:
            exp_date = datetime.fromtimestamp(expires)
            days_left = (exp_date - datetime.now()).days
            print(f"  Token valid. Expira: {exp_date.strftime('%Y-%m-%d')} ({days_left} zile ramase)")
            if days_left < 7:
                print("  ⚠ TOKEN EXPIRA CURAND! Regenereaza din Graph API Explorer + --refresh-token")
        else:
            print("  Token valid (fara data expirare — posibil permanent)")
    else:
        print(f"  TOKEN INVALID sau EXPIRAT!")
        print(f"  Regenereaza din https://developers.facebook.com/tools/explorer/")
        print(f"  Apoi ruleaza: python meta_ads_costs.py --refresh-token")
        sys.exit(1)


def fetch_campaigns(token, ad_account):
    """
    Preia lista de campanii din contul de ads, inclusiv:
    - start_time: data cand campania a fost creata/pornita
    - stop_time: data cand campania a fost oprita (None daca e activa)
    - effective_status: statusul real curent (ACTIVE, PAUSED, ARCHIVED, etc.)
    - daily_budget / lifetime_budget: bugetul configurat
    """
    print("\n=== Preluare campanii (cu perioade) ===")
    campaigns = []
    url = f"{BASE_URL}/{ad_account}/campaigns"
    params = {
        "fields": "id,name,status,effective_status,objective,start_time,stop_time,"
                  "daily_budget,lifetime_budget,created_time,updated_time",
        "limit": 100,
        "access_token": token,
    }

    while url:
        r = requests.get(url, params=params)
        data = r.json()
        if "error" in data:
            print(f"  EROARE API: {data['error']['message']}")
            sys.exit(1)
        campaigns.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = {}  # next URL contine deja parametrii

    # Filtram campaniile vechi (inainte de 2024)
    MIN_DATE = "2024-01-01"
    all_count = len(campaigns)
    filtered = []
    skipped = 0
    for c in campaigns:
        # Folosim start_time sau created_time ca referinta
        ref_date = c.get("start_time", c.get("created_time", ""))[:10] if c.get("start_time") or c.get("created_time") else ""
        if ref_date and ref_date < MIN_DATE:
            skipped += 1
            continue
        filtered.append(c)

    campaigns = filtered
    print(f"  Gasit {all_count} campanii, pastram {len(campaigns)} (de la {MIN_DATE}), excluse {skipped} vechi")
    for c in campaigns:
        status = c.get("effective_status", c.get("status", "?"))[:6]
        start = c.get("start_time", "")[:10] if c.get("start_time") else "N/A"
        stop = c.get("stop_time", "")[:10] if c.get("stop_time") else "activa"
        print(f"    [{status:6s}] {start} → {stop}  {c['name']}")
    return campaigns


def fetch_campaign_costs(token, ad_account, start_date, end_date):
    """
    Preia costurile per campanie per luna.
    Returneaza lista de dict-uri cu: campaign_id, campaign_name, month, spend, impressions, clicks
    """
    print(f"\n=== Preluare costuri: {start_date} → {end_date} ===")
    results = []
    url = f"{BASE_URL}/{ad_account}/insights"
    params = {
        "fields": "campaign_id,campaign_name,spend,impressions,clicks,actions,cost_per_action_type",
        "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
        "time_increment": "monthly",
        "level": "campaign",
        "limit": 500,
        "access_token": token,
    }

    page = 0
    while url:
        page += 1
        r = requests.get(url, params=params)
        data = r.json()
        if "error" in data:
            print(f"  EROARE API: {data['error']['message']}")
            sys.exit(1)

        rows = data.get("data", [])
        print(f"  Pagina {page}: {len(rows)} randuri")

        for row in rows:
            spend = float(row.get("spend", 0))
            if spend == 0:
                continue

            # Extrage luna din date_start (format YYYY-MM-DD)
            month = row["date_start"][:7]  # YYYY-MM

            results.append({
                "campaign_id": row["campaign_id"],
                "campaign_name": row["campaign_name"],
                "month": month,
                "spend": spend,
                "impressions": int(row.get("impressions", 0)),
                "clicks": int(row.get("clicks", 0)),
            })

        url = data.get("paging", {}).get("next")
        params = {}

    print(f"  Total: {len(results)} randuri cu cost > 0")
    total_spend = sum(r["spend"] for r in results)
    print(f"  Spend total: {total_spend:,.2f}")
    return results


def generate_sql_inserts(results, output_file):
    """Genereaza fisier SQL cu INSERT-uri compatibile cu sp_Import_Costuri_Campanii"""
    print(f"\n=== Generare SQL: {output_file} ===")

    lines = []
    lines.append("-- =====================================================")
    lines.append("-- Meta Ads Costs — generat automat de meta_ads_costs.py")
    lines.append(f"-- Data generare: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"-- Randuri: {len(results)}")
    lines.append(f"-- Spend total: {sum(r['spend'] for r in results):,.2f}")
    lines.append("-- =====================================================")
    lines.append("")
    lines.append("-- Format: (NumeCampanie, Sursa, CampaignID, Luna, Cost_RON)")
    lines.append("-- NOTA: Costurile Meta sunt in RON daca contul e setat pe RON,")
    lines.append("--       altfel sunt in valuta contului (verifica in Ads Manager)")
    lines.append("")

    # Sorteaza: campanie, luna
    results.sort(key=lambda r: (r["campaign_name"], r["month"]))

    for r in results:
        name = r["campaign_name"].replace("'", "''")  # escape single quotes
        lines.append(
            f"INSERT INTO #tmpCosturiRaw (NumeCampanie, Sursa, CampaignID, Luna, Cost_RON) "
            f"VALUES (N'{name}', 'Meta Ads', '{r['campaign_id']}', "
            f"'{r['month']}', {r['spend']:.2f});"
        )

    lines.append("")
    lines.append(f"-- Total: {len(results)} INSERT-uri")
    lines.append(f"-- Spend: {sum(r['spend'] for r in results):,.2f}")

    with open(str(output_file), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"  Salvat: {len(results)} INSERT-uri")


def generate_csv(results, output_file):
    """Genereaza CSV cu costurile (pentru verificare/import Excel)"""
    print(f"\n=== Generare CSV costuri: {output_file} ===")
    with open(str(output_file), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["CampaignID", "NumeCampanie", "Sursa", "Luna", "Cost_RON", "Impressions", "Clicks"])
        for r in results:
            w.writerow([
                r["campaign_id"], r["campaign_name"], "Meta Ads",
                r["month"], f"{r['spend']:.2f}",
                r["impressions"], r["clicks"],
            ])
    print(f"  Salvat: {len(results)} randuri")


def generate_campaigns_sql(campaigns, cost_results, output_file):
    """
    Adauga INSERT-uri pentru perioadele campaniilor la finalul fisierului SQL existent.
    Populeaza #tmpPerioadeRaw cu: CampaignID, NumeCampanie, Sursa, Status,
    StartDate, StopDate, PrimaLunaSpend, UltimaLunaSpend, NrLuniSpend, TotalSpend.
    """
    print(f"\n=== Adaugare perioade campanii in SQL: {output_file} ===")

    # Calculeaza prima/ultima luna spend per campaign
    spend_by_campaign = {}
    for r in cost_results:
        cid = r["campaign_id"]
        if cid not in spend_by_campaign:
            spend_by_campaign[cid] = {"total_spend": 0, "months": []}
        spend_by_campaign[cid]["total_spend"] += r["spend"]
        spend_by_campaign[cid]["months"].append(r["month"])

    lines = []
    lines.append("")
    lines.append("")
    lines.append("-- =====================================================")
    lines.append("-- PERIOADE CAMPANII META — generat automat")
    lines.append(f"-- Data generare: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"-- Campanii: {len(campaigns)}")
    lines.append("-- =====================================================")
    lines.append("")
    lines.append("-- Tabel temporar pentru perioade (creat in scriptul apelant)")
    lines.append("-- CREATE TABLE #tmpPerioadeRaw (")
    lines.append("--     CampaignID NVARCHAR(50),")
    lines.append("--     NumeCampanie NVARCHAR(500),")
    lines.append("--     Sursa NVARCHAR(50),")
    lines.append("--     StatusCampanie NVARCHAR(50),")
    lines.append("--     StartDate DATE NULL,")
    lines.append("--     StopDate DATE NULL,")
    lines.append("--     PrimaLunaSpend NVARCHAR(7) NULL,")
    lines.append("--     UltimaLunaSpend NVARCHAR(7) NULL,")
    lines.append("--     NrLuniSpend INT,")
    lines.append("--     TotalSpend DECIMAL(12,2)")
    lines.append("-- )")
    lines.append("")

    count = 0
    for c in campaigns:
        cid = c["id"]
        name = c.get("name", "").replace("'", "''")
        status = c.get("effective_status", c.get("status", ""))
        start = c.get("start_time", "")[:10] if c.get("start_time") else ""
        stop = c.get("stop_time", "")[:10] if c.get("stop_time") else ""

        spend_info = spend_by_campaign.get(cid, {})
        months = sorted(spend_info.get("months", []))
        total_spend = spend_info.get("total_spend", 0)

        start_sql = f"'{start}'" if start else "NULL"
        stop_sql = f"'{stop}'" if stop else "NULL"
        prima = f"'{months[0]}'" if months else "NULL"
        ultima = f"'{months[-1]}'" if months else "NULL"

        lines.append(
            f"INSERT INTO #tmpPerioadeRaw (CampaignID, NumeCampanie, Sursa, StatusCampanie, "
            f"StartDate, StopDate, PrimaLunaSpend, UltimaLunaSpend, NrLuniSpend, TotalSpend) "
            f"VALUES ('{cid}', N'{name}', 'Meta Ads', '{status}', "
            f"{start_sql}, {stop_sql}, {prima}, {ultima}, {len(months)}, {total_spend:.2f});"
        )
        count += 1

    lines.append("")
    lines.append(f"-- Total: {count} campanii Meta cu perioade")

    # Append la fisierul SQL existent
    with open(str(output_file), "a", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"  Adaugat: {count} INSERT-uri perioade campanii")


def generate_campaigns_csv(campaigns, cost_results, output_file):
    """
    Genereaza CSV cu datele campaniilor: perioada, status, prima/ultima luna cu spend.
    Combina informatiile din campaigns API (start/stop) cu insights (spend per luna).
    """
    print(f"\n=== Generare CSV campanii (perioade): {output_file} ===")

    # Calculeaza prima si ultima luna cu spend per campaign_id
    spend_by_campaign = {}
    for r in cost_results:
        cid = r["campaign_id"]
        if cid not in spend_by_campaign:
            spend_by_campaign[cid] = {
                "total_spend": 0,
                "months": [],
                "total_impressions": 0,
                "total_clicks": 0,
            }
        spend_by_campaign[cid]["total_spend"] += r["spend"]
        spend_by_campaign[cid]["months"].append(r["month"])
        spend_by_campaign[cid]["total_impressions"] += r["impressions"]
        spend_by_campaign[cid]["total_clicks"] += r["clicks"]

    with open(str(output_file), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "CampaignID", "NumeCampanie", "Sursa",
            "EffectiveStatus", "Objective",
            "StartTime", "StopTime", "CreatedTime",
            "PrimaLunaSpend", "UltimaLunaSpend", "NrLuniActive",
            "TotalSpend", "TotalImpressions", "TotalClicks",
            "DailyBudget", "LifetimeBudget",
        ])

        for c in campaigns:
            cid = c["id"]
            spend_info = spend_by_campaign.get(cid, {})
            months = sorted(spend_info.get("months", []))

            # Formatare date (Meta returneaza ISO 8601: 2025-01-15T12:00:00+0200)
            start_time = c.get("start_time", "")[:10] if c.get("start_time") else ""
            stop_time = c.get("stop_time", "")[:10] if c.get("stop_time") else ""
            created_time = c.get("created_time", "")[:10] if c.get("created_time") else ""

            w.writerow([
                cid,
                c.get("name", ""),
                "Meta Ads",
                c.get("effective_status", c.get("status", "")),
                c.get("objective", ""),
                start_time,
                stop_time,
                created_time,
                months[0] if months else "",
                months[-1] if months else "",
                len(months),
                f"{spend_info.get('total_spend', 0):.2f}",
                spend_info.get("total_impressions", 0),
                spend_info.get("total_clicks", 0),
                c.get("daily_budget", ""),
                c.get("lifetime_budget", ""),
            ])

    # Sumar
    with_spend = sum(1 for c in campaigns if c["id"] in spend_by_campaign)
    without_spend = len(campaigns) - with_spend
    print(f"  Salvat: {len(campaigns)} campanii ({with_spend} cu spend, {without_spend} fara)")
    print(f"  Coloane noi: StartTime, StopTime, PrimaLunaSpend, UltimaLunaSpend")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Meta Ads Costs Fetcher — FGO")
    parser.add_argument("--refresh-token", action="store_true", help="Reface long-lived token din short-lived")
    parser.add_argument("--months", type=int, default=24, help="Cate luni in urma (default: 24)")
    parser.add_argument("--start", type=str, help="Data start (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="Data end (YYYY-MM-DD)")
    parser.add_argument("--list-campaigns", action="store_true", help="Listeaza doar campaniile")
    parser.add_argument("--check-token", action="store_true", help="Verifica validitatea token-ului")
    args = parser.parse_args()

    print("=" * 60)
    print("  Meta Ads Costs Fetcher — FGO Marketing")
    print("=" * 60)

    config = load_config()
    ad_account = config["ad_account_id"]
    api_version = config.get("api_version", DEFAULT_API_VERSION).strip() or DEFAULT_API_VERSION
    global BASE_URL
    BASE_URL = f"https://graph.facebook.com/{api_version}"
    print(f"  Ad Account: {ad_account}")
    print(f"  Graph API:  {api_version}")

    # Refresh token
    if args.refresh_token:
        token = refresh_token(config)
    else:
        token = get_token(config)

    # Check token
    if args.check_token:
        check_token_validity(token)
        return

    # Verificare rapida token
    check_token_validity(token)

    # Preia campanii (cu perioade) — necesar si pentru list si pentru export complet
    campaigns = fetch_campaigns(token, ad_account)

    # List campaigns only
    if args.list_campaigns:
        return

    # Calculeaza interval date
    if args.start and args.end:
        start_date = args.start
        end_date = args.end
    else:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=args.months * 30)).strftime("%Y-%m-%d")

    # Preia costuri
    results = fetch_campaign_costs(token, ad_account, start_date, end_date)

    if not results:
        print("\n  Niciun cost gasit in intervalul specificat.")
        return

    # Genereaza output
    generate_sql_inserts(results, OUTPUT_SQL)
    generate_campaigns_sql(campaigns, results, OUTPUT_SQL)  # append perioade la acelasi SQL
    generate_csv(results, OUTPUT_CSV)
    generate_campaigns_csv(campaigns, results, OUTPUT_CAMPAIGNS_CSV)

    # Sumar
    print("\n" + "=" * 60)
    print("  SUMAR")
    print("=" * 60)
    campaign_names = set(r["campaign_name"] for r in results)
    months = sorted(set(r["month"] for r in results))
    total = sum(r["spend"] for r in results)

    # Campanii incheiate vs active
    active = [c for c in campaigns if c.get("effective_status") in ("ACTIVE", "CAMPAIGN_PAUSED")]
    archived = [c for c in campaigns if c.get("effective_status") not in ("ACTIVE", "CAMPAIGN_PAUSED")]

    print(f"  Campanii cu spend: {len(campaign_names)}")
    print(f"  Campanii active/paused: {len(active)}")
    print(f"  Campanii incheiate/archived: {len(archived)}")
    print(f"  Luni: {months[0]} -> {months[-1]} ({len(months)} luni)")
    print(f"  Spend total: {total:,.2f} RON")
    print(f"  Output SQL:       {OUTPUT_SQL}")
    print(f"  Output CSV cost:  {OUTPUT_CSV}")
    print(f"  Output CSV camp:  {OUTPUT_CAMPAIGNS_CSV}")
    print()
    print("  Fisierul meta_ads_campaigns_output.csv contine pentru fiecare campanie:")
    print("    - StartTime / StopTime (din API)")
    print("    - PrimaLunaSpend / UltimaLunaSpend (din insights)")
    print("    - EffectiveStatus, Objective, buget")


if __name__ == "__main__":
    main()
