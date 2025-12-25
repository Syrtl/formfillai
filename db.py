"""Database module for users, sessions, and profiles.
Supports both PostgreSQL (via DATABASE_URL) and SQLite (fallback).
"""
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger("formfillai.db")

# Postgres connection pool (initialized on startup)
_pg_pool: Optional[Any] = None
_USE_POSTGRES = False
DB_PATH: Optional[Path] = None

# Import aiosqlite at module level (will be used if Postgres not available)
import aiosqlite

# Canonical field mappings
CANONICAL_FIELDS = {
    "full_name": ["name", "fullname", "full_name", "fullName", "fullName1", "applicant_name", "name_full"],
    "first_name": ["firstname", "first_name", "firstName", "fname", "given_name"],
    "last_name": ["lastname", "last_name", "lastName", "lname", "surname", "family_name"],
    "email": ["email", "email_address", "emailAddress", "e_mail", "e-mail", "mail"],
    "phone": ["phone", "phone_number", "phoneNumber", "telephone", "tel", "mobile", "cell"],
    "address": ["address", "street_address", "streetAddress", "street", "address_line_1", "address1"],
    "address_line_2": ["address_line_2", "address2", "address_line2", "apt", "apartment", "unit"],
    "city": ["city", "town"],
    "state": ["state", "province", "region"],
    "zip": ["zip", "zip_code", "zipCode", "postal_code", "postalCode", "postcode"],
    "country": ["country", "nation"],
    "date_of_birth": ["dob", "date_of_birth", "dateOfBirth", "birth_date", "birthdate"],
    "ssn": ["ssn", "social_security_number", "socialSecurityNumber", "tax_id"],
}


async def init_db() -> None:
    """Initialize database tables and connection pool.
    Reads DATABASE_URL at runtime (not import time) to support Fly.io secrets.
    """
    global _pg_pool, _USE_POSTGRES, DB_PATH
    
    # Read DATABASE_URL at runtime (not import time)
    database_url = os.getenv("DATABASE_URL")
    
    if database_url:
        # Try to use Postgres
        try:
            import asyncpg
        except ImportError:
            logger.warning("DATABASE_URL set but asyncpg not installed. Falling back to SQLite.")
            database_url = None
        
        if database_url:
            # Parse DATABASE_URL (format: postgres://user:pass@host:port/dbname?sslmode=disable)
            parsed = urlparse(database_url)
            
            # Parse query parameters for SSL mode
            sslmode_str = None
            if parsed.query:
                # Parse query string properly (handle URL encoding, multiple params)
                from urllib.parse import parse_qs
                query_params = parse_qs(parsed.query)
                sslmode_list = query_params.get('sslmode', [])
                if sslmode_list:
                    sslmode_str = sslmode_list[0].lower()
                # Also try simple parsing as fallback
                if not sslmode_str:
                    simple_params = dict(param.split('=') for param in parsed.query.split('&') if '=' in param)
                    sslmode_str = simple_params.get('sslmode', '').lower() or None
            
            db_config = {
                "host": parsed.hostname,
                "port": parsed.port or 5432,
                "user": parsed.username,
                "password": parsed.password,
                "database": parsed.path.lstrip("/"),
            }
            
            # Set SSL mode explicitly based on sslmode parameter
            # asyncpg: ssl=False completely disables SSL (no TLS handshake attempt, no start_tls call)
            #         ssl=None may still attempt TLS in some cases
            #         ssl=True or SSLContext enables SSL
            if sslmode_str == 'disable':
                db_config["ssl"] = False  # Explicitly disable SSL (no TLS handshake) - False prevents start_tls
                logger.info("Postgres SSL disabled (sslmode=disable)")
            elif sslmode_str in ('require', 'verify-full', 'verify-ca'):
                # For require/verify modes, use default SSL context
                import ssl
                db_config["ssl"] = ssl.create_default_context()
                logger.info("Postgres SSL enabled (sslmode=%s)", sslmode_str)
            else:
                # No sslmode specified - explicitly set ssl=False to avoid TLS attempts
                # This ensures we don't accidentally try TLS when not configured
                db_config["ssl"] = False
                logger.info("Postgres SSL mode not specified, disabling SSL (ssl=False)")
            
            # Prepare kwargs for create_pool (only pass what asyncpg expects)
            pool_kwargs = {
                "host": db_config["host"],
                "port": db_config["port"],
                "user": db_config["user"],
                "password": db_config["password"],
                "database": db_config["database"],
                "ssl": db_config["ssl"],  # Explicitly set: False for disable, SSLContext for require
                "min_size": 1,
                "max_size": 10,
            }
            
            # Log pool_kwargs (without password) to verify SSL setting
            log_kwargs = pool_kwargs.copy()
            log_kwargs['password'] = '***'
            logger.info("asyncpg.create_pool kwargs: %s", log_kwargs)
            
            try:
                _pg_pool = await asyncpg.create_pool(**pool_kwargs)
                _USE_POSTGRES = True
                sslmode_log = f"sslmode={sslmode_str}" if sslmode_str else "default SSL"
                logger.info("Using Postgres (%s)", sslmode_log)
                logger.info("DB backend: postgres")
                
                # Initialize tables
                async with _pg_pool.acquire() as conn:
                    await _init_postgres_tables(conn)
                return
            except Exception as e:
                # Log full exception details with stack trace
                logger.exception("Failed to connect to Postgres, falling back to SQLite")
                logger.error("Postgres connection error details: %s", repr(e))
                _USE_POSTGRES = False
                # Continue to SQLite fallback below
    
    # Fallback to SQLite (only if Postgres not available or connection failed)
    if not _USE_POSTGRES:
        DB_PATH = Path(__file__).resolve().parent / "data" / "app.db"
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Using SQLite (no DATABASE_URL or Postgres connection failed)")
        logger.info("DB backend: sqlite")
        await _init_sqlite_tables()
    else:
        # Postgres succeeded, do not initialize SQLite
        logger.debug("Postgres connection successful, skipping SQLite initialization")


async def _init_postgres_tables(conn) -> None:
    """Initialize PostgreSQL tables."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            created_at BIGINT NOT NULL,
            is_pro INTEGER DEFAULT 0,
            stripe_customer_id TEXT
        )
    """)
    
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            expires_at BIGINT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS magic_tokens (
            token TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            expires_at BIGINT NOT NULL,
            used INTEGER DEFAULT 0
        )
    """)
    
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            data TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            updated_at BIGINT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS pdf_mappings (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            pdf_hash TEXT NOT NULL,
            mappings TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            updated_at BIGINT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, pdf_hash)
        )
    """)
    
    # Create indexes
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_magic_tokens_email ON magic_tokens(email)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_profiles_user_id ON profiles(user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_pdf_mappings_user_hash ON pdf_mappings(user_id, pdf_hash)")
    
    logger.info("Postgres tables initialized")


async def _init_sqlite_tables() -> None:
    """Initialize SQLite tables."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                created_at INTEGER NOT NULL,
                is_pro INTEGER DEFAULT 0,
                stripe_customer_id TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS magic_tokens (
                token TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                used INTEGER DEFAULT 0
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pdf_mappings (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                pdf_hash TEXT NOT NULL,
                mappings TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, pdf_hash)
            )
        """)
        
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_magic_tokens_email ON magic_tokens(email)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_profiles_user_id ON profiles(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_pdf_mappings_user_hash ON pdf_mappings(user_id, pdf_hash)")
        
        await db.commit()
        logger.info("Using SQLite: %s", DB_PATH)


async def create_user(email: str) -> str:
    """Create a new user and return user_id."""
    user_id = secrets.token_urlsafe(16)
    now = int(time.time())
    email_lower = email.lower()
    
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO users (id, email, created_at) VALUES ($1, $2, $3)",
                    user_id, email_lower, now
                )
                logger.info("Created user: %s", email)
                return user_id
            except Exception as e:
                # Check if it's a unique violation (Postgres)
                error_type = type(e).__name__
                if error_type == "UniqueViolationError":
                    # User already exists, get existing ID
                    row = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email_lower)
                    if row:
                        return row["id"]
                raise
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            try:
                await db.execute(
                    "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
                    (user_id, email_lower, now)
                )
                await db.commit()
                logger.info("Created user: %s", email)
                return user_id
            except aiosqlite.IntegrityError:
                async with db.execute("SELECT id FROM users WHERE email = ?", (email_lower,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return row[0]
                raise


async def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Get user by email."""
    email_lower = email.lower()
    
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, email, created_at, is_pro, stripe_customer_id FROM users WHERE email = $1",
                email_lower
            )
            if row:
                return {
                    "id": row["id"],
                    "email": row["email"],
                    "created_at": row["created_at"],
                    "is_pro": bool(row["is_pro"]),
                    "stripe_customer_id": row["stripe_customer_id"],
                }
            return None
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, email, created_at, is_pro, stripe_customer_id FROM users WHERE email = ?",
                (email_lower,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "id": row[0],
                        "email": row[1],
                        "created_at": row[2],
                        "is_pro": bool(row[3]),
                        "stripe_customer_id": row[4],
                    }
                return None


async def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Get user by ID."""
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, email, created_at, is_pro, stripe_customer_id FROM users WHERE id = $1",
                user_id
            )
            if row:
                return {
                    "id": row["id"],
                    "email": row["email"],
                    "created_at": row["created_at"],
                    "is_pro": bool(row["is_pro"]),
                    "stripe_customer_id": row["stripe_customer_id"],
                }
            return None
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, email, created_at, is_pro, stripe_customer_id FROM users WHERE id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "id": row[0],
                        "email": row[1],
                        "created_at": row[2],
                        "is_pro": bool(row[3]),
                        "stripe_customer_id": row[4],
                    }
                return None


async def create_session(user_id: str, expires_in_seconds: int = 30 * 24 * 60 * 60) -> str:
    """Create a session and return session_id."""
    session_id = secrets.token_urlsafe(32)
    now = int(time.time())
    expires_at = now + expires_in_seconds
    
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES ($1, $2, $3, $4)",
                session_id, user_id, now, expires_at
            )
            return session_id
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (session_id, user_id, now, expires_at)
            )
            await db.commit()
            return session_id


async def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get session by ID if valid and not expired."""
    now = int(time.time())
    
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, user_id, expires_at FROM sessions WHERE id = $1 AND expires_at > $2",
                session_id, now
            )
            if row:
                return {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "expires_at": row["expires_at"],
                }
            return None
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, user_id, expires_at FROM sessions WHERE id = ? AND expires_at > ?",
                (session_id, now)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "id": row[0],
                        "user_id": row[1],
                        "expires_at": row[2],
                    }
                return None


async def delete_session(session_id: str) -> None:
    """Delete a session."""
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute("DELETE FROM sessions WHERE id = $1", session_id)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            await db.commit()


async def create_magic_token(email: str, expires_in_seconds: int = 15 * 60) -> str:
    """Create a magic link token."""
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    expires_at = now + expires_in_seconds
    email_lower = email.lower()
    
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                "UPDATE magic_tokens SET used = 1 WHERE email = $1 AND used = 0",
                email_lower
            )
            await conn.execute(
                "INSERT INTO magic_tokens (token, email, created_at, expires_at) VALUES ($1, $2, $3, $4)",
                token, email_lower, now, expires_at
            )
            return token
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE magic_tokens SET used = 1 WHERE email = ? AND used = 0",
                (email_lower,)
            )
            await db.execute(
                "INSERT INTO magic_tokens (token, email, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token, email_lower, now, expires_at)
            )
            await db.commit()
            return token


async def verify_magic_token(token: str) -> Optional[str]:
    """Verify magic token and return email if valid. Marks token as used."""
    now = int(time.time())
    
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT email FROM magic_tokens WHERE token = $1 AND expires_at > $2 AND used = 0",
                token, now
            )
            if row:
                email = row["email"]
                await conn.execute("UPDATE magic_tokens SET used = 1 WHERE token = $1", token)
                return email
            return None
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT email FROM magic_tokens WHERE token = ? AND expires_at > ? AND used = 0",
                (token, now)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    email = row[0]
                    await db.execute("UPDATE magic_tokens SET used = 1 WHERE token = ?", (token,))
                    await db.commit()
                    return email
                return None


async def create_profile(user_id: str, name: str, data: Dict[str, Any]) -> str:
    """Create a profile and return profile_id."""
    profile_id = secrets.token_urlsafe(16)
    now = int(time.time())
    data_json = json.dumps(data)
    
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO profiles (id, user_id, name, data, created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6)",
                profile_id, user_id, name, data_json, now, now
            )
            logger.info("Created profile %s for user %s", profile_id, user_id)
            return profile_id
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO profiles (id, user_id, name, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (profile_id, user_id, name, data_json, now, now)
            )
            await db.commit()
            logger.info("Created profile %s for user %s", profile_id, user_id)
            return profile_id


async def get_user_profiles(user_id: str) -> List[Dict[str, Any]]:
    """Get all profiles for a user."""
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, data, created_at, updated_at FROM profiles WHERE user_id = $1 ORDER BY updated_at DESC",
                user_id
            )
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "data": json.loads(row["data"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, name, data, created_at, updated_at FROM profiles WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "id": row[0],
                        "name": row[1],
                        "data": json.loads(row[2]),
                        "created_at": row[3],
                        "updated_at": row[4],
                    }
                    for row in rows
                ]


async def get_profile(profile_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Get a profile by ID (with user check for security)."""
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name, data, created_at, updated_at FROM profiles WHERE id = $1 AND user_id = $2",
                profile_id, user_id
            )
            if row:
                return {
                    "id": row["id"],
                    "name": row["name"],
                    "data": json.loads(row["data"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            return None
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, name, data, created_at, updated_at FROM profiles WHERE id = ? AND user_id = ?",
                (profile_id, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "id": row[0],
                        "name": row[1],
                        "data": json.loads(row[2]),
                        "created_at": row[3],
                        "updated_at": row[4],
                    }
                return None


async def update_profile(profile_id: str, user_id: str, name: Optional[str], data: Optional[Dict[str, Any]]) -> bool:
    """Update a profile."""
    now = int(time.time())
    updates = []
    params = []
    
    if name is not None:
        updates.append("name = $1" if _USE_POSTGRES else "name = ?")
        params.append(name)
    if data is not None:
        updates.append("data = $2" if _USE_POSTGRES else "data = ?")
        params.append(json.dumps(data))
    
    if not updates:
        return False
    
    updates.append("updated_at = $3" if _USE_POSTGRES else "updated_at = ?")
    params.append(now)
    params.extend([profile_id, user_id])
    
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE profiles SET {', '.join(updates)} WHERE id = ${len(params)-1} AND user_id = ${len(params)}",
                *params
            )
            return result == "UPDATE 1"
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                f"UPDATE profiles SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
                params
            )
            await db.commit()
            return cursor.rowcount > 0


async def delete_profile(profile_id: str, user_id: str) -> bool:
    """Delete a profile."""
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM profiles WHERE id = $1 AND user_id = $2",
                profile_id, user_id
            )
            return result == "DELETE 1"
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "DELETE FROM profiles WHERE id = ? AND user_id = ?",
                (profile_id, user_id)
            )
            await db.commit()
            return cursor.rowcount > 0


async def delete_user_data(user_id: str) -> None:
    """Delete all user data (profiles, mappings, sessions)."""
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute("DELETE FROM profiles WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM pdf_mappings WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM sessions WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM users WHERE id = $1", user_id)
            logger.info("Deleted all data for user %s", user_id)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))
            await db.execute("DELETE FROM pdf_mappings WHERE user_id = ?", (user_id,))
            await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            await db.commit()
            logger.info("Deleted all data for user %s", user_id)


async def save_pdf_mapping(user_id: str, pdf_hash: str, mappings: Dict[str, str]) -> None:
    """Save PDF field mappings for a user."""
    now = int(time.time())
    mappings_json = json.dumps(mappings)
    mapping_id = secrets.token_urlsafe(16)
    
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO pdf_mappings (id, user_id, pdf_hash, mappings, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT(user_id, pdf_hash) DO UPDATE SET mappings = $4, updated_at = $6""",
                mapping_id, user_id, pdf_hash, mappings_json, now, now
            )
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO pdf_mappings (id, user_id, pdf_hash, mappings, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, pdf_hash) DO UPDATE SET mappings = ?, updated_at = ?""",
                (mapping_id, user_id, pdf_hash, mappings_json, now, now, mappings_json, now)
            )
            await db.commit()


async def get_pdf_mapping(user_id: str, pdf_hash: str) -> Optional[Dict[str, str]]:
    """Get PDF field mappings for a user."""
    if _USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT mappings FROM pdf_mappings WHERE user_id = $1 AND pdf_hash = $2",
                user_id, pdf_hash
            )
            if row:
                return json.loads(row["mappings"])
            return None
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT mappings FROM pdf_mappings WHERE user_id = ? AND pdf_hash = ?",
                (user_id, pdf_hash)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return json.loads(row[0])
                return None


def map_canonical_to_pdf_fields(canonical_data: Dict[str, Any], pdf_field_names: List[str]) -> Dict[str, Any]:
    """Map canonical field names to actual PDF field names."""
    result = {}
    pdf_fields_lower = {f.lower(): f for f in pdf_field_names}
    
    for canonical_key, canonical_value in canonical_data.items():
        if canonical_key not in CANONICAL_FIELDS:
            continue
        
        # Try to find matching PDF field
        for possible_name in CANONICAL_FIELDS[canonical_key]:
            if possible_name.lower() in pdf_fields_lower:
                result[pdf_fields_lower[possible_name.lower()]] = canonical_value
                break
    
    return result


def compute_pdf_hash(pdf_bytes: bytes) -> str:
    """Compute a hash of PDF content for caching mappings."""
    import hashlib
    return hashlib.sha256(pdf_bytes).hexdigest()[:16]
