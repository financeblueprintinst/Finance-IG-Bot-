# Finance Instagram Bot

Fully automated Instagram finance page. Every day at ~20:00 it:

1. Pulls live market data (indices, stocks, commodities, forex) via `yfinance`
2. Parses finance news from free RSS feeds
3. Renders a branded 1080×1350 PNG with `matplotlib`
4. Generates an English caption with Google Gemini (free tier)
5. Publishes the post via the Instagram Graph API

Runs on GitHub Actions (free cron). No server, no paid APIs.

## Weekly rotation

| Day | Post type              |
| --- | ---------------------- |
| Mon | Market recap (indices) |
| Tue | Top gainers & losers   |
| Wed | Market recap (indices) |
| Thu | Commodities & FX       |
| Fri | Market recap (indices) |
| Sat | Weekly recap           |
| Sun | News digest            |

Override in `src/config.py → ROTATION` or force a type from the Actions UI.

---

## Prerequisites (do these once, in order)

### 1. Instagram Business or Creator account
- Open the Instagram app → Settings → Account → *Switch to professional account*.
- Pick **Business** or **Creator**. Either works for the API.
- Link it to a Facebook Page you own (Settings → Account Center). The API
  requires this link — a standalone Instagram account cannot post via API.

### 2. Meta Developer app
- Go to https://developers.facebook.com, create an app of type **Business**.
- In the app dashboard, add the **Instagram Graph API** product.
- In *App Roles → Roles*, add yourself as a Tester if prompted.

### 3. Get a long-lived access token
- Open https://developers.facebook.com/tools/explorer
- Select your app. Click *Generate Access Token*.
- Required permissions:
  - `instagram_basic`
  - `instagram_content_publish`
  - `pages_show_list`
  - `pages_read_engagement`
  - `business_management`
- Copy the short-lived token, then exchange it for a long-lived one:
  ```
  https://graph.facebook.com/v20.0/oauth/access_token
    ?grant_type=fb_exchange_token
    &client_id={APP_ID}
    &client_secret={APP_SECRET}
    &fb_exchange_token={SHORT_LIVED_TOKEN}
  ```
- You now have a **60-day token**. Write a calendar reminder to rotate it.

### 4. Find your Instagram Business Account ID
In Graph Explorer run:
```
GET /me/accounts                                → grab your Facebook Page ID
GET /{page-id}?fields=instagram_business_account
```
The returned `id` is your `IG_BUSINESS_ACCOUNT_ID`.

### 5. Google Gemini API key (free)
- https://aistudio.google.com/apikey → create key.
- Free tier: 15 requests/min, 1M tokens/day. More than enough.

---

## Local setup & smoke test

```bash
git clone https://github.com/<you>/finance-ig-bot.git
cd finance-ig-bot
python -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # fill in your values
# on Linux/macOS:
export $(cat .env | xargs)
# render an image without posting:
python src/main.py --dry-run
# force a specific post type:
python src/main.py --dry-run --type gainers_losers
```
Check the generated PNG in `output/`.

---

## Deploy on GitHub

1. Push the repo to GitHub (public is fine; private also works with Actions quota).
2. In *Settings → Secrets and variables → Actions*, add **repository secrets**:
   - `IG_ACCESS_TOKEN`
   - `IG_BUSINESS_ACCOUNT_ID`
   - `GEMINI_API_KEY`
3. In the same UI, add **repository variables** (public, not secret):
   - `BRAND_NAME` — shown in the header, e.g. `Daily Market Pulse`
   - `BRAND_HANDLE` — shown in the footer, e.g. `@yourhandle`
4. Ensure *Settings → Actions → General → Workflow permissions* is set to
   **Read and write**. The workflow commits the generated PNG so Instagram
   can fetch it via `raw.githubusercontent.com`.
5. First run: *Actions → Daily Instagram Post → Run workflow*. Tick
   **Render only** to verify before a live post.

The schedule (`cron: "55 18 * * *"` = 18:55 UTC ≈ 20:55 CEST) posts daily.
Adjust in `.github/workflows/daily-post.yml` if you need a different time.

---

## File map

```
finance-ig-bot/
├── src/
│   ├── main.py                 # entry point + weekday dispatch
│   ├── config.py               # branding, tickers, rotation
│   ├── data_fetcher.py         # yfinance + RSS
│   ├── chart_generator.py      # matplotlib → 1080×1350 PNGs
│   ├── caption_generator.py    # Gemini + fallback captions
│   └── instagram_publisher.py  # Graph API media container + publish
├── .github/workflows/daily-post.yml
├── output/                     # generated images committed here by CI
├── requirements.txt
├── .env.example
└── README.md
```

---

## Gotchas & tips

- **Token expiry**: long-lived tokens last ~60 days. Regenerate before then,
  or swap to a *system user token* in the Meta Business Suite for non-expiring.
- **Image fetch**: Meta fetches the image from the URL you pass. The repo must
  be **public** for `raw.githubusercontent.com` to serve it. If you prefer a
  private repo, swap `instagram_publisher.build_public_url` to upload to imgbb,
  Cloudflare R2, or GitHub Pages instead.
- **Rate limits**: IG Graph API allows 50 posts per 24h, 200 API calls/hour.
  One post per day is well inside.
- **Finance disclaimer**: captions end with "Not financial advice." Keep it.
  Especially if you ever target an EU/DACH audience, BaFin/ESMA-style rules
  on investment recommendations can apply to creators.
- **yfinance reliability**: it scrapes Yahoo. If a ticker breaks, the script
  logs and continues with the others. For more resilience, add Finnhub
  (free 60 calls/min) as a fallback in `data_fetcher.py`.
- **Content quality**: fully automated finance content can get repetitive.
  Review the first 2 weeks of posts by hand and tune `config.py` colors,
  `caption_generator.py` prompts, and the ticker lists to your taste.
