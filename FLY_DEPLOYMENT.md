# Fly.io Deployment Guide

## Database Configuration

The app now supports both PostgreSQL (via `DATABASE_URL`) and SQLite (fallback).

### PostgreSQL Setup (Recommended for Production)

1. Create a Postgres database on Fly.io:
   ```bash
   fly postgres create --name formfillai-db
   fly postgres attach formfillai-db
   ```

2. The `DATABASE_URL` environment variable will be automatically set by Fly.io.

3. On startup, the app will:
   - Detect `DATABASE_URL` and use Postgres
   - Initialize all tables automatically
   - Log: "Using Postgres (DATABASE_URL)"

### SQLite (Fallback)

If `DATABASE_URL` is not set, the app falls back to SQLite:
- Database file: `/app/data/app.db`
- Logs: "Using SQLite: /app/data/app.db"

## SMTP Configuration

### Development Mode

- Magic links are returned in the API response (`dev_link` or `magicLink` field)
- Frontend displays a copyable link for testing
- No SMTP required

### Production Mode

- If `SMTP_HOST` is not configured:
  - Returns HTTP 503 (Service Unavailable)
  - Frontend shows: "Email delivery is not configured yet. Please contact support."
  - Token is still generated and stored (can be retrieved from logs if needed)
- If `SMTP_HOST` is configured:
  - Email sending will be implemented (TODO)

## Environment Variables

### Required
- `APP_SIGNING_SECRET` - Secret for signing tokens (auto-generated in dev)

### Optional
- `DATABASE_URL` - Postgres connection string (e.g., `postgresql://user:pass@host:port/dbname`)
- `SMTP_HOST` - SMTP server hostname
- `SMTP_PORT` - SMTP server port (default: 587)
- `SMTP_USER` - SMTP username
- `SMTP_PASSWORD` - SMTP password
- `ENV` - Environment name (`dev` or `production`)
- `DEBUG` - Debug mode (`1` or `0`)

## Fly.io Trial Limitations

**Note:** Fly.io trial accounts stop machines after ~5 minutes of inactivity with the message:
"Trial machine stopping... add a credit card"

This is expected behavior. To avoid this:
1. Add a credit card to your Fly.io account
2. Or use a paid plan

The app will continue to work normally once the machine restarts.

## Smoke Test Checklist

### Database
- [ ] App starts without errors
- [ ] Logs show "Using Postgres (DATABASE_URL)" or "Using SQLite: ..."
- [ ] Tables are created automatically
- [ ] Can create a user via sign-in flow
- [ ] User data persists after restart

### Authentication
- [ ] `/auth/send-magic-link` returns 200 in dev mode
- [ ] Dev mode shows magic link in response
- [ ] Production without SMTP returns 503 (not 500)
- [ ] Frontend handles 503 gracefully
- [ ] Magic link verification works (`/auth/verify?token=...`)
- [ ] Session cookie is set after verification
- [ ] `/api/me` returns user info when logged in

### Frontend
- [ ] Sign-in modal opens
- [ ] Email validation works
- [ ] Dev mode shows copyable magic link
- [ ] Production shows error message for 503
- [ ] User dropdown appears after login
- [ ] Logout clears session

### Profiles (Pro Feature)
- [ ] `/api/profiles` requires authentication
- [ ] Non-Pro users cannot create profiles (returns 403)
- [ ] Pro users can create/update/delete profiles
- [ ] Profile selector appears when logged in

### Error Handling
- [ ] No 500 errors in logs
- [ ] All errors return proper HTTP status codes
- [ ] Frontend displays error messages clearly

## Deployment Steps

1. **Set up Postgres (recommended):**
   ```bash
   fly postgres create --name formfillai-db
   fly postgres attach formfillai-db
   ```

2. **Set environment variables:**
   ```bash
   fly secrets set APP_SIGNING_SECRET=$(openssl rand -hex 32)
   fly secrets set ENV=production
   ```

3. **Deploy:**
   ```bash
   fly deploy
   ```

4. **Check logs:**
   ```bash
   fly logs
   ```

5. **Verify database:**
   - Check logs for "Using Postgres" or "Using SQLite"
   - Verify no database errors

6. **Test authentication:**
   - Try sign-in flow
   - Verify magic link works
   - Check session persistence

## Troubleshooting

### Database Connection Issues

If you see "Failed to connect to Postgres":
1. Check `DATABASE_URL` is set: `fly secrets list`
2. Verify Postgres is running: `fly status`
3. Check network connectivity
4. App will fall back to SQLite automatically

### SMTP Errors

If you see 503 errors for `/auth/send-magic-link`:
- This is expected if `SMTP_HOST` is not set
- In dev mode, magic link is returned in response
- In production, configure SMTP or contact support

### Trial Machine Stopping

If you see "Trial machine stopping...":
- This is normal for Fly.io trial accounts
- Add a credit card to prevent this
- Machine will restart automatically when accessed

