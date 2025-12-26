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

After deployment, configure these environment variables in Railway:

**Required:**
- `APP_SIGNING_SECRET` - Secret for signing tokens (generate a strong random string)

**Database (choose one):**
- `DATABASE_URL` - PostgreSQL connection string (Railway can provision a Postgres database)
  - Or leave unset to use SQLite (not recommended for production)

**SMTP (for magic link emails):**
- `SMTP_HOST` - e.g., `smtp.resend.com`
- `SMTP_PORT` - e.g., `587`
- `SMTP_USER` - SMTP username
- `SMTP_PASS` - SMTP password/API key
- `SMTP_FROM` - From email address

**Public URL (for magic links):**
- `PUBLIC_BASE_URL` - Your Railway app URL (e.g., `https://formfillai-production.up.railway.app`)

**Optional:**
- `STRIPE_SECRET_KEY` - Stripe secret key
- `STRIPE_PRICE_ID` - Stripe price ID
- `STRIPE_WEBHOOK_SECRET` - Stripe webhook secret
- `OPENAI_API_KEY` - OpenAI API key
- `ENV` - Set to `production` for production mode
- `DEBUG` - Set to `0` for production

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

