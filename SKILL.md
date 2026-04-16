---
name: meta-ads
description: |
  Skill for pulling campaign costs and performance data from Meta (Facebook/Instagram) Marketing API.
  Use this skill whenever the user asks about Meta Ads, Facebook Ads, Instagram Ads campaign costs,
  ad spend, ROAS, token refresh, or wants to extract data from their Meta ad account. Also trigger
  when the user mentions Graph API for ads, Meta access tokens, or ad_account_id.
---

# Meta Ads API Skill

This skill provides everything needed to connect to the Meta Marketing API (Graph API), extract
campaign cost data, manage access tokens, and generate output compatible with SQL import procedures.

## Quick Start

1. Ensure `config/facebook_ads.ini` exists (copy from `config/facebook_ads.template.ini`)
2. If no long-lived token yet, run `python scripts/meta_ads_costs.py --refresh-token`
3. Pull campaign costs: `python scripts/meta_ads_costs.py`

## Prerequisites

```bash
pip install requests
```

## Authentication Setup

Meta Marketing API requires:

1. **App ID + App Secret** — from Meta for Developers > App > Settings > Basic
2. **Long-lived Access Token** (~60 days validity) — obtained by exchanging a short-lived token
3. **Ad Account ID** — format `act_XXXXXXXXX` (from Meta Ads Manager URL)

All credentials go in `config/facebook_ads.ini` (gitignored). See `config/facebook_ads.template.ini` for the format.

### Token Management

Meta tokens come in two flavors:

- **Short-lived** (~1 hour) — generated from Graph API Explorer. **Never save** this in config.
- **Long-lived** (~60 days) — obtained by exchanging the short-lived token.

To exchange:
```bash
python scripts/meta_ads_costs.py --refresh-token
```

The script asks for the short-lived token interactively, exchanges it via the API, and writes the long-lived token back to `config/facebook_ads.ini` with an expiration date.

### Checking Token Status

```bash
python scripts/meta_ads_costs.py --check-token
```

Shows token validity and days remaining. Regenerate when under 7 days.

### Getting a Short-lived Token

1. Go to https://developers.facebook.com/tools/explorer/
2. Select your app
3. Add permission: `ads_read`
4. Generate User Access Token
5. Immediately exchange it for long-lived via `--refresh-token`

## Available Scripts

### `meta_ads_costs.py` — Campaign Cost Extraction

Primary script for pulling Meta campaign spend data.

```bash
python scripts/meta_ads_costs.py                    # last 6 months
python scripts/meta_ads_costs.py --months 12        # last 12 months
python scripts/meta_ads_costs.py --start 2024-11-01 --end 2026-03-31  # custom range
python scripts/meta_ads_costs.py --refresh-token    # exchange short→long token
python scripts/meta_ads_costs.py --check-token      # check token validity
```

**Output files**:
- `meta_ads_costs_output.sql` — SQL INSERT statements for `sp_Import_Costuri_Campanii`
- `meta_ads_costs_output.csv` — CSV with monthly costs per campaign
- `meta_ads_campaigns_output.csv` — Campaign metadata (start/end dates, status, spend periods)

### Campaign Data Fields

The script extracts per campaign per month:
- Campaign name, ID, status
- Total spend (RON or account currency)
- Impressions, clicks, CTR, CPC
- Start/stop time, effective_status
- First and last month with spend

## Config Loader

All scripts use `config_loader.py` (included in `scripts/`) which provides:

- `load_facebook_ads()` — reads `config/facebook_ads.ini`, validates non-placeholder values
- Placeholder detection: `YOUR_`, `INSERT_`, `PASTE_`, `PUNE`, `0000000000`
- Clear error messages for missing/incomplete config

## Graph API Version

Configured in `facebook_ads.ini` (`api_version`). Current as of April 2026: `v25.0`

Meta deprecates API versions on a rolling 2-year window. Update periodically.

## Common Issues

| Error | Cause | Fix |
|-------|-------|-----|
| `OAuthException: Error validating access token` | Token expired or revoked | Run `--refresh-token` with a fresh short-lived token |
| `(#100) Missing permissions` | Token lacks `ads_read` scope | Regenerate token with correct permissions |
| `Invalid ad_account_id` | Missing `act_` prefix or wrong ID | Check Ads Manager URL; include `act_` prefix |
| `Application request limit reached` | Rate limiting | Wait 15 min, reduce date range, or use smaller batches |

## Credential Security

- `config/facebook_ads.ini` is gitignored — never commit credentials
- `config/facebook_ads.template.ini` is the committed template with `YOUR_*` placeholders
- Short-lived tokens are never written to files — only long-lived tokens after exchange
- If a token leaks, revoke it immediately from Meta for Developers
- The `token_expires_at` field in config helps track when to refresh
