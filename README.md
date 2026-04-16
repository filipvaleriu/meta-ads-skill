# meta-ads-skill

Skill Cowork pentru extragere date din Meta Marketing API (Facebook/Instagram Ads): costuri campanii, perioade, status, si management token-uri.

## Structura

```
meta-ads-skill/
├── SKILL.md                                    # Instructiuni principale
├── README.md                                   # Acest fisier
├── .gitignore
├── config/
│   └── facebook_ads.template.ini               # Template config (placeholdere)
└── scripts/
    ├── config_loader.py                        # Loader centralizat configurari
    └── meta_ads_costs.py                       # Extragere costuri + token management
```

## Prerequisite

```bash
pip install requests
```

## Setup rapid

1. `cp config/facebook_ads.template.ini config/facebook_ads.ini`
2. Completeaza app_id, app_secret, ad_account_id
3. `python scripts/meta_ads_costs.py --refresh-token` (schimba short→long token)
4. `python scripts/meta_ads_costs.py`

## Changelog

- 2026-04-16: Creat ca repo separat din proiectul principal de marketing
