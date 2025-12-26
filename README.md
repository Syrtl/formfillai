# FormFillAI

Minimal FastAPI micro-SaaS that fills PDF forms using JSON data. Upload a fillable PDF and a JSON payload; receive a filled PDF in response. Files are stored locally in `tmp/` and cleaned after 30 minutes.

Free mode limits: 1 filled document per day per browser/token and adds a small footer watermark. Pro mode (via Stripe subscription) removes limits and watermark.

## Stack
- Python 3.11
- FastAPI
- pypdf
- Jinja2 for the upload page
- Stripe Checkout (subscriptions, local-only for now)

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
uvicorn main:app --reload
```

Then open http://127.0.0.1:8000 to use the upload page.

## API
- `GET /` — Minimal HTML form to upload a PDF and JSON file.
- `POST /fill` — Accepts `pdf_file` (fillable PDF) and `json_file` (JSON). Returns a filled PDF download.
- `GET /health` — Health probe.

## Behavior
- Validates file type and max size (10MB each).
- Ignores JSON keys that do not match form fields.
- If the PDF has no form fields, responds with a clear error message.
- Uploaded/filled files live in `tmp/` and are auto-deleted after 30 minutes (background cleaner).
- Appearance streams are regenerated with `/NeedAppearances` to ensure filled values show in Acrobat, Chrome, and Preview.
- Frontend shows clear errors and a loading state during processing.

## Free vs Pro mode
- **Free (default)**: 1 fill per day per browser token, adds watermark `Filled with FormFillAI (Free)`.
- **Pro**: Unlimited fills, watermark removed, no per-day limits.

### Usage limits (free mode)
- The app sets a signed cookie (`ffai_token`). Counts are kept in memory and reset daily.
- Exceeding the limit returns HTTP 429 with a clear error message.

### Pro access model
- When Stripe subscription checkout completes successfully, the app sets a signed cookie (`ffai_pro`) containing an expiry timestamp (e.g. now + 30 days).
- The cookie is HMAC-signed with `APP_SIGNING_SECRET` and cannot be forged without that secret.
- When `ffai_pro` is active and not expired, `/fill` treats the user as Pro (no watermark, no limits).

## Stripe setup (local test)

### 1. Create product and price in Stripe
- In the Stripe Dashboard, create a **Product** called “FormFillAI Pro”.
- Add a **Recurring price** for **$19/month**.
- Copy the generated **Price ID** (e.g. `price_123...`).

### 2. Set environment variables
Set these environment variables before running the app:
```bash
export APP_SIGNING_SECRET="a-long-random-string"          # REQUIRED: HMAC secret for cookies/tokens (do NOT auto-generate in prod)
export STRIPE_SECRET_KEY="sk_live_or_test_..."            # Stripe secret key
export STRIPE_PRICE_ID="price_123..."                     # Recurring price for the $19/month Pro plan
export STRIPE_WEBHOOK_SECRET="whsec_..."                  # Webhook signing secret from Stripe dashboard
# Optional, not required for core flow:
export STRIPE_PUBLISHABLE_KEY="pk_live_or_test_..."
# Magic link authentication:
export PUBLIC_BASE_URL="http://127.0.0.1:8000"           # Public base URL for magic links (local dev)
# For production (e.g., Fly.io):
# export PUBLIC_BASE_URL="https://formfillai.fly.dev"
```

> The app will refuse to start if `APP_SIGNING_SECRET` is missing.  
> For **local development only**, you can allow auto-generation by setting `ENV=dev` or `DEBUG=1`:

```bash
export ENV=dev   # or: export DEBUG=1
uvicorn main:app --reload
```

In production, always set a stable, strong `APP_SIGNING_SECRET` so Pro cookies remain valid across restarts.

### 3. Run and test checkout locally
- Start the app:
```bash
uvicorn main:app --reload
```
- Open `http://127.0.0.1:8000` in your browser.
- Scroll to the pricing section and click **Upgrade to Pro**:
  - This sends `POST /create-checkout-session`, which creates a Stripe Checkout Session (mode=subscription) using `STRIPE_PRICE_ID` and redirects to Stripe Checkout.
  - On successful payment, Stripe redirects back to `http://127.0.0.1:8000/stripe/success?session_id=...`, which verifies the session and sets the `ffai_pro` cookie (30‑day rolling expiry), then redirects to `/?upgraded=1`.
  - If you cancel, Stripe redirects to `http://127.0.0.1:8000/stripe/cancel`, which redirects to `/?canceled=1`.

- When `ffai_pro` is set and valid, uploads via `/fill` run in Pro mode (no limits, no watermark). Otherwise, the free limits apply.

### 4. Webhooks and subscription stability
- Start Stripe CLI to forward webhooks to your local app:
```bash
stripe listen --forward-to 127.0.0.1:8000/stripe/webhook
```
- The app handles:
  - `checkout.session.completed` (subscription mode)
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.payment_succeeded`
  - `invoice.payment_failed`
- When a subscription is canceled/expired or payments fail, the app adds the subscription id to a small in-memory denylist for 24h so `/stripe/refresh` can quickly reject inactive subs.
- You can manually hit `GET /stripe/refresh` in the browser to refresh the Pro cookie based on the latest subscription status from Stripe.

## Magic Link Authentication

The app supports email-based authentication via magic links. Configure SMTP settings to enable email delivery:

```bash
export SMTP_HOST="smtp.resend.com"        # SMTP server hostname
export SMTP_PORT="587"                     # SMTP port (default: 587)
export SMTP_USER="resend"                  # SMTP username
export SMTP_PASS="your_resend_api_key"     # SMTP password/API key
export SMTP_FROM="noreply@yourdomain.com"  # From email address
```

**Important:** Set `PUBLIC_BASE_URL` to ensure magic links use the correct scheme (https) and domain:
- **Local development:** `PUBLIC_BASE_URL=http://127.0.0.1:8000`
- **Production (Fly.io):** `PUBLIC_BASE_URL=https://formfillai.fly.dev`

If `PUBLIC_BASE_URL` is not set, the app falls back to `request.base_url`, which may be incorrect behind proxies (e.g., returning `http://` instead of `https://`), causing cookie/session issues.

## Notes
- Ensure your PDF is a fillable AcroForm. Static PDFs without fields will be rejected.
- JSON root must be an object; nested values are stringified when written to the PDF.

