# Railway Deployment Guide

## Quick Setup Steps

### 1. Create Railway Project from GitHub

1. Go to [Railway.app](https://railway.app) and sign in with GitHub
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. If you see **"No repositories found"**, follow the steps below to fix permissions

### 2. Fix GitHub Repository Access (if needed)

If Railway shows "No repositories found":

1. Go to **GitHub.com** → Your Profile → **Settings**
2. Click **"Applications"** in the left sidebar
3. Find **"Railway"** in the list and click **"Configure"**
4. Under **"Repository access"**:
   - Select **"Only select repositories"**
   - Check the box for **"formfillai"** (or select **"All repositories"**)
5. Click **"Save"**
6. Go back to Railway and **refresh the page**
7. You should now see **"formfillai"** in the repository list
8. Select **"formfillai"** and click **"Deploy"**

### 3. Railway Configuration

**IMPORTANT: Start Command is Auto-Configured**

The repository uses a single source of truth for the start command:
- `Procfile` - Contains the web process command (primary)
- `nixpacks.toml` - Hard-pins the start command as backup (prevents Railway from overriding)
- `railway.json` - Railway-specific configuration (NO startCommand field to avoid conflicts)

**Start Command:**
```
sh -c 'uvicorn main:app --host 0.0.0.0 --port "$PORT" --proxy-headers'
```

**Why this works:**
- Railway provides `PORT` as an environment variable
- The `sh -c` wrapper expands `$PORT` to the actual port number before passing it to uvicorn
- This ensures uvicorn receives an integer, not the literal string `$PORT`

**Railway UI Note:**
- Railway's UI may show an auto-generated uvicorn command in the Start Command field
- **DO NOT** manually set or override the Start Command in Railway UI
- The repository configuration files (`Procfile`, `nixpacks.toml`) ensure the correct command is used
- If you see a different command in Railway UI, it's just a display issue - the pinned command will be used

**Repository Cleanup:**
- Fly.io files (`fly.toml`, `FLY_DEPLOYMENT.md`) have been removed to avoid conflicts
- Only Railway deployment files are present

**What Railway does automatically:**
- Detects Python from `requirements.txt`
- Sets the `PORT` environment variable automatically
- Uses the start command from `nixpacks.toml` or `Procfile`

### 4. Add PostgreSQL Database (REQUIRED for Production)

**IMPORTANT:** Production requires PostgreSQL. SQLite is not allowed in production.

1. In your Railway project, click **"+ New"**
2. Select **"Database"** → **"Add PostgreSQL"**
3. Railway will automatically set the `DATABASE_URL` environment variable
4. The app will automatically connect to Postgres on next deploy
5. **Verify:** Check startup logs to confirm `DB backend: postgres`

**If DATABASE_URL is missing in production:**
- The app will refuse to start with error: "DATABASE_URL is required in production"
- Add a PostgreSQL database via Railway dashboard

### 5. Environment Variables

After deployment, configure these environment variables in Railway (Settings → Variables):

#### Required Variables (Production)

| Variable Name | Description | Example Value | Required |
|--------------|-------------|---------------|----------|
| `ENV` | Environment mode. Set to `production` for production. | `production` | ✅ Yes |
| `DEBUG` | Debug mode. Set to `0` in production. | `0` | ✅ Yes |
| `APP_SIGNING_SECRET` | Secret for signing tokens/cookies. Generate a strong random string (32+ characters). | `your-random-secret-string-here` | ✅ Yes |
| `DATABASE_URL` | PostgreSQL connection string. **Auto-set by Railway when you add Postgres database.** | `postgresql://user:pass@host:port/dbname` | ✅ Yes (auto-set) |
| `PUBLIC_BASE_URL` | Your Railway app's public URL (for magic links). Set this after Railway provides your URL. | `https://formfillai-production.up.railway.app` | ✅ Yes |

**Generate APP_SIGNING_SECRET:**
```bash
# On Linux/Mac:
openssl rand -hex 32

# Or use Python:
python -c "import secrets; print(secrets.token_hex(32))"
```

#### Database Variables

| Variable Name | Description | Example Value | Required |
|--------------|-------------|---------------|----------|
| `DATABASE_URL` | PostgreSQL connection string. Railway auto-sets this when you add a Postgres database. | `postgresql://user:pass@host:port/dbname` | ✅ Yes (recommended) |

**Note:** If `DATABASE_URL` is not set, the app will use SQLite (only in dev mode). In production, Postgres is required.

#### Email Delivery Variables

**Recommended: Resend API (Primary Method)**

| Variable Name | Description | Example Value | Required |
|--------------|-------------|---------------|----------|
| `RESEND_API_KEY` | Resend API key for HTTP API email delivery. **Recommended on Railway** (avoids SMTP port blocking). | `re_xxxxxxxxxxxxx` | ✅ Recommended |
| `EMAIL_FROM` or `SMTP_FROM` | Sender email address. Supports "Name <email>" format. Must be verified in Resend. | `FormFillAI <[email protected]>` | ✅ Required if using Resend |

**Optional: SMTP Fallback**

| Variable Name | Description | Example Value | Required |
|--------------|-------------|---------------|----------|
| `SMTP_HOST` | SMTP server hostname. Only needed if not using Resend API. | `smtp.resend.com` | ❌ Optional |
| `SMTP_PORT` | SMTP server port. Defaults to 587 if not set. | `587` | ❌ Optional |
| `SMTP_USER` or `SMTP_USERNAME` | SMTP username. | `resend` | ❌ Optional |
| `SMTP_PASS` or `SMTP_PASSWORD` | SMTP password. | `your-smtp-password` | ❌ Optional |

**Note:** The app will use Resend API if `RESEND_API_KEY` is set, and fall back to SMTP if Resend is not configured. On Railway, Resend API is recommended because SMTP port 587 may be blocked or unreliable.

**⚠️ Important: Resend Domain Verification**

Resend has two modes:

1. **Sandbox Mode (Unverified Domain):**
   - If `SMTP_FROM` domain is `resend.dev` or not verified, Resend operates in sandbox mode
   - In sandbox mode, emails can **only** be delivered to:
     - Your Resend account owner email
     - `delivered@resend.dev` (test email)
   - Emails to other recipients will **not be delivered** (but won't error)
   - The app will detect this and log a warning: `"Resend sandbox detected: SMTP_FROM domain is 'resend.dev'"`
   - **Magic links will always be logged in server logs** when SMTP fails, so you can manually use them

2. **Production Mode (Verified Domain):**
   - Verify your custom domain in Resend dashboard
   - Use `SMTP_FROM` with your verified domain (e.g., `noreply@yourdomain.com`)
   - All emails will be delivered normally
   - No sandbox limitations

**Testing in Sandbox Mode:**
- Use `delivered@resend.dev` as the recipient email for testing
- Or use your Resend account owner email
- Check server logs for magic links if email delivery fails
- The app will log: `"Magic link (for manual use): https://..."` when SMTP fails

**To Enable Production Email Delivery:**
1. Go to Resend dashboard → Domains
2. Add and verify your domain (add DNS records)
3. Update `SMTP_FROM` to use your verified domain
4. Redeploy your app


**Important:** Set `PUBLIC_BASE_URL` to your Railway app URL to ensure magic links use HTTPS. If not set, the app will try to detect from request headers, but setting it explicitly is recommended.

#### Debug Variables (Optional)

| Variable Name | Description | Example Value | Required |
|--------------|-------------|---------------|----------|
| `DEBUG_KEY` | Secret key for accessing debug endpoints when email delivery fails. Set this to enable `/debug/last-magic-link` and `/debug/email/send-test`. | `your-secret-debug-key` | ❌ Optional |

**Debug Endpoints:**
- `GET /debug/last-magic-link?email=...` - Get the latest magic link for an email (requires `DEBUG=1` OR `X-Debug-Key` header)
- `GET /debug/email/send-test?to=...` - Test email delivery via Resend API and/or SMTP (requires `DEBUG=1` OR `X-Debug-Key` header)

**Usage:**
```bash
# With DEBUG_KEY set:
curl -H "X-Debug-Key: your-secret-debug-key" "https://your-app.railway.app/debug/last-magic-link?email=user@example.com"

# Or with DEBUG=1 (no header needed):
curl "https://your-app.railway.app/debug/last-magic-link?email=user@example.com"
```

#### Optional Variables

| Variable Name | Description | Example Value | Required |
|--------------|-------------|---------------|----------|
| `ENV` | Environment mode | `production` | ⚠️ Recommended |
| `DEBUG` | Debug mode (set to 0 in production) | `0` | ⚠️ Recommended |
| `STRIPE_SECRET_KEY` | Stripe secret key (for Pro subscriptions) | `sk_live_...` or `sk_test_...` | ❌ No |
| `STRIPE_PRICE_ID` | Stripe price ID for Pro plan | `price_xxxxxxxxxxxxx` | ❌ No |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret | `whsec_xxxxxxxxxxxxx` | ❌ No |
| `OPENAI_API_KEY` | OpenAI API key (for AI features) | `sk-xxxxxxxxxxxxx` | ❌ No |

### 6. Get Your App URL

1. After deployment, Railway will provide a URL like: `https://formfillai-production.up.railway.app`
2. Set `PUBLIC_BASE_URL` to this URL in your environment variables
3. Redeploy if needed

### 7. Verify Deployment

1. Visit your Railway app URL
2. Check startup logs in Railway dashboard for:
   - `Environment: ENV=production DEBUG=False IS_PRODUCTION=True`
   - `DATABASE_URL: set`
   - `Selected DB backend: postgres` (must be postgres in production)
   - `SMTP configuration: HOST=True PORT=True USER=True PASS=True FROM=True`
   - `SMTP configured: email delivery enabled`
3. Check `/health` endpoint - should return `"backend": "postgres"`
4. Test the magic link authentication flow

**Production Requirements Checklist:**
- ✅ `ENV=production` or `DEBUG=0`
- ✅ `DATABASE_URL` is set (auto-set by Railway Postgres)
- ✅ `DB backend: postgres` in logs (not sqlite)
- ✅ `PUBLIC_BASE_URL` is set to your Railway app URL
- ✅ All SMTP variables are set for sign-in

## Troubleshooting

### App won't start / "Invalid value for '--port': '$PORT' is not a valid integer"

**This error means Railway is using a start command that doesn't expand $PORT.**

**Solution:**
1. Ensure your repository has the latest code (with `nixpacks.toml` and updated `Procfile`)
2. Redeploy on Railway - the pinned start command will be used
3. **DO NOT** manually set a Start Command in Railway UI (it may override the pinned command)

**Why this happens:**
- Railway may auto-generate a start command that doesn't expand `$PORT`
- The uvicorn CLI receives the literal string `$PORT` instead of the port number
- The repository now pins the correct command via `nixpacks.toml` and `Procfile` using `sh -c` to expand `$PORT`

**If the error persists:**
- Check that `nixpacks.toml` exists in your repository
- Verify `Procfile` contains: `web: sh -c 'uvicorn main:app --host 0.0.0.0 --port "$PORT" --proxy-headers'`
- Clear any manually set Start Command in Railway UI (Settings → Service → Start Command)

### App won't start (other issues)
- Check Railway logs for errors
- Verify all required environment variables are set
- Ensure `requirements.txt` is correct

### Database connection issues / "DATABASE_URL is required in production"
- **Production requires PostgreSQL** - SQLite is not allowed
- Add a PostgreSQL database via Railway dashboard (Settings → "+ New" → "Database" → "Add PostgreSQL")
- Railway will automatically set `DATABASE_URL` when you add the database
- Verify `DATABASE_URL` is set in Railway environment variables
- Check Postgres database is running in Railway
- Review connection logs in Railway dashboard
- Ensure startup logs show `Selected DB backend: postgres` (not sqlite)

### Health check shows backend=sqlite in production
- This is not allowed in production
- Verify `ENV=production` or `DEBUG=0` is set
- Verify `DATABASE_URL` is set (add Postgres database if missing)
- Check startup logs for Postgres connection errors
- The app should refuse to start if Postgres is not available in production

### Magic links not working
- Verify `PUBLIC_BASE_URL` is set to your Railway app URL
- Check SMTP configuration if email delivery is enabled
- Review logs for magic link creation/verification

### Testing Authentication Without Browser DevTools

You can test the authentication flow using curl commands:

**A) Request magic link:**
- Use the app UI or POST to `/auth/send-magic-link`
- Check server logs for the magic link token (or use `/debug/last-magic-link` endpoint)

**B) Test session via curl (no browser):**

1. **Verify token and capture cookie:**
   ```bash
   curl -i -c cookies.txt -X POST https://<APP>/auth/verify \
     -H "Content-Type: application/json" \
     -d '{"token":"<TOKEN>"}'
   ```
   This should return `{"ok":true,"authenticated":true,"email":"...","plan":"free|pro"}` and set a `session` cookie.

2. **Confirm cookie is being sent back:**
   ```bash
   curl -s -b cookies.txt https://<APP>/debug/cookies
   ```
   Should show `"session_present": true` and `"session_prefix": "..."` (first 8 chars).

3. **Confirm authenticated:**
   ```bash
   curl -s -b cookies.txt https://<APP>/api/me
   ```
   Should return `{"authenticated": true, "email": "...", "plan": "..."}`.

4. **Test fields endpoint:**
   ```bash
   curl -i -b cookies.txt -X POST https://<APP>/fields \
     -F "pdf_file=@<PATH_TO_PDF>"
   ```
   Should return 200 with fields JSON (not 401).

**Debug Endpoints:**
- `GET /debug/cookies` - Shows which cookies are present (no secrets)
- `GET /debug/auth` - Shows authentication status and session lookup
- `POST /auth/verify` - Verify token via POST (returns JSON, sets cookie)

## Files Added for Railway

- `Procfile` - Defines the web process with Railway's `$PORT` variable
- `railway.json` - Railway-specific configuration (optional, Procfile takes precedence)

