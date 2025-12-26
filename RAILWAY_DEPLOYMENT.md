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

Railway will automatically:
- Detect Python from `requirements.txt`
- Use the `Procfile` for the start command
- Set the `$PORT` environment variable automatically

The service will start with:
```bash
uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers
```

### 4. Environment Variables

After deployment, configure these environment variables in Railway (Settings → Variables):

#### Required Variables

| Variable Name | Description | Example Value | Required |
|--------------|-------------|---------------|----------|
| `APP_SIGNING_SECRET` | Secret for signing tokens/cookies. Generate a strong random string (32+ characters). | `your-random-secret-string-here` | ✅ Yes (in production) |

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

#### SMTP Variables (for Magic Link Emails)

| Variable Name | Description | Example Value | Required |
|--------------|-------------|---------------|----------|
| `SMTP_HOST` | SMTP server hostname | `smtp.resend.com` | ✅ Yes (for email) |
| `SMTP_PORT` | SMTP server port | `587` | ✅ Yes (for email) |
| `SMTP_USER` | SMTP username | `resend` | ✅ Yes (for email) |
| `SMTP_PASS` | SMTP password/API key | `your-resend-api-key` | ✅ Yes (for email) |
| `SMTP_FROM` | From email address | `noreply@yourdomain.com` | ✅ Yes (for email) |

**Resend SMTP Example:**
- `SMTP_HOST=smtp.resend.com`
- `SMTP_PORT=587`
- `SMTP_USER=resend`
- `SMTP_PASS=re_xxxxxxxxxxxxx` (your Resend API key)
- `SMTP_FROM=noreply@yourdomain.com` (must be verified in Resend)

#### Public URL Variable

| Variable Name | Description | Example Value | Required |
|--------------|-------------|---------------|----------|
| `PUBLIC_BASE_URL` | Your Railway app's public URL (for magic links). Set this after Railway provides your URL. | `https://formfillai-production.up.railway.app` | ⚠️ Recommended |

**Important:** Set `PUBLIC_BASE_URL` to your Railway app URL to ensure magic links use HTTPS. If not set, the app will try to detect from request headers, but setting it explicitly is recommended.

#### Optional Variables

| Variable Name | Description | Example Value | Required |
|--------------|-------------|---------------|----------|
| `ENV` | Environment mode | `production` | ⚠️ Recommended |
| `DEBUG` | Debug mode (set to 0 in production) | `0` | ⚠️ Recommended |
| `STRIPE_SECRET_KEY` | Stripe secret key (for Pro subscriptions) | `sk_live_...` or `sk_test_...` | ❌ No |
| `STRIPE_PRICE_ID` | Stripe price ID for Pro plan | `price_xxxxxxxxxxxxx` | ❌ No |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret | `whsec_xxxxxxxxxxxxx` | ❌ No |
| `OPENAI_API_KEY` | OpenAI API key (for AI features) | `sk-xxxxxxxxxxxxx` | ❌ No |

### 5. Add PostgreSQL Database (Recommended)

1. In your Railway project, click **"+ New"**
2. Select **"Database"** → **"Add PostgreSQL"**
3. Railway will automatically set the `DATABASE_URL` environment variable
4. The app will automatically connect to Postgres on next deploy

### 6. Get Your App URL

1. After deployment, Railway will provide a URL like: `https://formfillai-production.up.railway.app`
2. Set `PUBLIC_BASE_URL` to this URL in your environment variables
3. Redeploy if needed

### 7. Verify Deployment

1. Visit your Railway app URL
2. Check logs in Railway dashboard for:
   - `DB backend: postgres` (if DATABASE_URL is set)
   - `SMTP configured: email delivery enabled` (if SMTP vars are set)
3. Test the magic link authentication flow

## Troubleshooting

### App won't start
- Check Railway logs for errors
- Verify all required environment variables are set
- Ensure `requirements.txt` is correct

### Database connection issues
- Verify `DATABASE_URL` is set correctly
- Check Postgres database is running in Railway
- Review connection logs in Railway dashboard

### Magic links not working
- Verify `PUBLIC_BASE_URL` is set to your Railway app URL
- Check SMTP configuration if email delivery is enabled
- Review logs for magic link creation/verification

## Files Added for Railway

- `Procfile` - Defines the web process with Railway's `$PORT` variable
- `railway.json` - Railway-specific configuration (optional, Procfile takes precedence)

