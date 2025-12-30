import asyncio
import json
import logging
import hmac
import os
import secrets
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    Depends,
    Security,
)
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import stripe
import uvicorn
from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject, DictionaryObject
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
import db
import re

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("formfillai")

if not OPENAI_AVAILABLE:
    logger.warning("OpenAI not available. AI extraction will be disabled.")

BASE_DIR = Path(__file__).resolve().parent
TMP_DIR = BASE_DIR / "tmp"
PREVIEW_DIR = BASE_DIR / "tmp" / "previews"
STATIC_DIR = BASE_DIR / "static"
LOCALES_DIR = STATIC_DIR / "i18n"
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
TEMP_TTL_SECONDS = 30 * 60  # 30 minutes
PREVIEW_TTL_SECONDS = 60 * 60  # 1 hour for previews
CLEAN_INTERVAL_SECONDS = 5 * 60  # clean every 5 minutes

# Supported languages (ordered by popularity after English)
SUPPORTED_LANGUAGES = [
    "en", "de", "fr", "it", "es", "pl", "ro", "nl", "cs", "el", 
    "hu", "pt", "sv", "da", "fi", "sk", "bg", "hr", "sl", "lt", 
    "lv", "et", "ga", "mt", "ru", "uk"
]
DEFAULT_LANGUAGE = "en"

ENV = os.getenv("ENV", "").lower()
DEBUG_RAW = os.getenv("DEBUG", "0")
DEBUG = DEBUG_RAW == "1"
# Production detection: (ENV == "production") OR (DEBUG is explicitly 0/False AND ENV is set)
# If ENV is missing/empty, default to dev (not production)
IS_PRODUCTION = (ENV == "production") or (DEBUG_RAW in ["0", "false", "False"] and bool(ENV))

_app_signing_secret_raw = os.getenv("APP_SIGNING_SECRET")
if not _app_signing_secret_raw:
    if ENV == "dev" or DEBUG:
        _app_signing_secret_raw = secrets.token_hex(32)
        logging.warning(
            "APP_SIGNING_SECRET is not set; generating a temporary secret for development. "
            "Do NOT use this in production."
        )
    else:
        raise RuntimeError(
            "APP_SIGNING_SECRET environment variable is required in production. "
            "Set a strong random string before starting the app."
        )

APP_SIGNING_SECRET = _app_signing_secret_raw.encode("utf-8")
FREE_DAILY_LIMIT = 1

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = None
if OPENAI_AVAILABLE and OPENAI_API_KEY:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Helper function to normalize environment variables
def get_env(name: str) -> Optional[str]:
    """Get and normalize environment variable.
    
    Normalization:
    - Reads os.getenv(name)
    - Strips whitespace
    - Removes outer single/double quotes if present
    - Returns None if empty after stripping
    """
    value = os.getenv(name)
    if not value:
        return None
    
    # Strip whitespace
    value = value.strip()
    
    # Remove outer quotes if present
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    
    # Treat empty strings as missing
    if not value:
        return None
    
    return value


# Extract email from "Name <email>" format if needed
def extract_email_from_string(email_str: Optional[str]) -> Optional[str]:
    """Extract email address from string, handling 'Name <email>' format."""
    if not email_str:
        return None
    # Use email.utils.parseaddr to extract email from "Name <email>" format
    name, email = parseaddr(email_str)
    # If parseaddr found an email, use it; otherwise use the original string
    return email if email else email_str


def get_email_config() -> Dict[str, Any]:
    """Get unified email configuration (Resend API + SMTP).
    
    Returns dict with:
    - resend_configured (RESEND_API_KEY present)
    - smtp_configured (SMTP_HOST/PORT/USER/PASS/FROM present)
    - from_raw (display name), from_email (parsed email)
    - resend_api_key, smtp_config (nested)
    """
    # Check Resend API key
    resend_api_key = get_env("RESEND_API_KEY")
    resend_configured = bool(resend_api_key)
    
    # Get SMTP config
    smtp_config = get_smtp_config()
    
    # Get FROM address (supports both SMTP_FROM and EMAIL_FROM)
    from_raw = get_env("SMTP_FROM") or get_env("EMAIL_FROM")
    from_email = extract_email_from_string(from_raw)
    
    return {
        "resend_configured": resend_configured,
        "resend_api_key": resend_api_key,
        "smtp_configured": smtp_config["configured"],
        "smtp_config": smtp_config,
        "from_raw": from_raw,
        "from_email": from_email
    }


def get_smtp_config() -> Dict[str, Any]:
    """Get SMTP configuration with normalized env vars.
    
    Returns dict with:
    - host, user, pass, from_raw, from (extracted), port
    - host_present, user_present, pass_present, from_present
    - configured (bool)
    - missing_keys (list of missing required keys)
    """
    # Support multiple naming variants with normalization
    host = get_env("SMTP_HOST")
    user = get_env("SMTP_USER") or get_env("SMTP_USERNAME")
    pass_val = get_env("SMTP_PASS") or get_env("SMTP_PASSWORD")
    from_raw = get_env("SMTP_FROM") or get_env("EMAIL_FROM")
    
    # SMTP_PORT is OPTIONAL - default to 587 if missing or invalid
    port_raw = get_env("SMTP_PORT")
    port = 587  # Default
    if port_raw:
        try:
            port = int(port_raw)
        except (ValueError, TypeError):
            logger.warning("SMTP_PORT could not be parsed as integer: %s. Using default 587.", port_raw)
            port = 587
    
    # Extract email from "Name <email>" format
    from_email = extract_email_from_string(from_raw)
    
    # Check which required keys are present
    host_present = bool(host)
    user_present = bool(user)
    pass_present = bool(pass_val)
    from_present = bool(from_email)
    
    # Determine configuration status
    configured = all([host_present, user_present, pass_present, from_present])
    
    # List missing keys
    missing_keys = []
    if not host_present:
        missing_keys.append("SMTP_HOST")
    if not user_present:
        missing_keys.append("SMTP_USER or SMTP_USERNAME")
    if not pass_present:
        missing_keys.append("SMTP_PASS or SMTP_PASSWORD")
    if not from_present:
        missing_keys.append("SMTP_FROM or EMAIL_FROM")
    
    return {
        "host": host,
        "user": user,
        "pass": pass_val,
        "from_raw": from_raw,
        "from": from_email,
        "port": port,
        "host_present": host_present,
        "user_present": user_present,
        "pass_present": pass_present,
        "from_present": from_present,
        "configured": configured,
        "missing_keys": missing_keys
    }


# Initialize SMTP config at module level
_smtp_config = get_smtp_config()
SMTP_HOST = _smtp_config["host"]
SMTP_USER = _smtp_config["user"]
SMTP_PASS = _smtp_config["pass"]
SMTP_FROM_RAW = _smtp_config["from_raw"]
SMTP_FROM = _smtp_config["from"]
SMTP_PORT = _smtp_config["port"]

# Thread pool for SMTP (smtplib is synchronous)
_smtp_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="smtp")

# Store last magic link for dev mode debugging
_last_magic_link: Optional[str] = None

ALLOWED_PDF_TYPES = {"application/pdf"}
ALLOWED_JSON_TYPES = {"application/json", "text/json"}

app = FastAPI(title="FormFillAI", version="0.1.0")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def ensure_tmp_dir() -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)


def normalize_language(lang: Optional[str]) -> str:
    """Normalize language code (e.g., 'de-DE' -> 'de')."""
    if not lang:
        return DEFAULT_LANGUAGE
    lang = lang.lower().strip()
    # Extract base language (before hyphen/underscore)
    base_lang = lang.split("-")[0].split("_")[0]
    return base_lang if base_lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def detect_language(request: Request) -> str:
    """Detect user language from cookie (client-side detection is primary)."""
    # Check cookie (set by client-side)
    lang_cookie = request.cookies.get("lang")
    if lang_cookie:
        normalized = normalize_language(lang_cookie)
        if normalized in SUPPORTED_LANGUAGES:
            return normalized
    
    # Fallback to Accept-Language header if no cookie
    accept_lang = request.headers.get("accept-language", "")
    if accept_lang:
        languages = []
        for part in accept_lang.split(","):
            lang_part = part.split(";")[0].strip()
            languages.append(lang_part)
        
        for lang in languages:
            normalized = normalize_language(lang)
            if normalized in SUPPORTED_LANGUAGES:
                return normalized
    
    return DEFAULT_LANGUAGE


def _sign_token(raw: str) -> str:
    sig = hmac.new(APP_SIGNING_SECRET, raw.encode("utf-8"), sha256).hexdigest()
    return f"{raw}.{sig}"


def _verify_token(token: Optional[str]) -> Optional[str]:
    if not token or "." not in token:
        return None
    raw, sig = token.rsplit(".", 1)
    expected = hmac.new(APP_SIGNING_SECRET, raw.encode("utf-8"), sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    return raw


class UsageLimiter:
    def __init__(self) -> None:
        self._counts: Dict[str, Tuple[str, int]] = {}

    def check_and_increment(self, token: str, limit: int = FREE_DAILY_LIMIT) -> None:
        today = time.strftime("%Y-%m-%d")
        day, count = self._counts.get(token, (today, 0))
        if day != today:
            day, count = today, 0
        if count >= limit:
            raise HTTPException(
                status_code=429,
                detail="Daily free limit reached. Upgrade to continue filling forms today.",
            )
        self._counts[token] = (day, count + 1)


usage_limiter = UsageLimiter()


def create_entitlement_token(expiry_ts: int, sub_id: str, customer_id: Optional[str]) -> str:
    """Create a signed Pro entitlement token with subscription metadata."""
    payload = {
        "exp": expiry_ts,
        "sub_id": sub_id,
        "customer_id": customer_id,
        "nonce": secrets.token_urlsafe(8),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return _sign_token(raw)


def parse_entitlement_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a signed Pro entitlement token without enforcing expiry."""
    raw = _verify_token(token)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


class SubscriptionDenylist:
    """In-memory cache for recently inactive subscriptions."""

    def __init__(self) -> None:
        self._entries: Dict[str, float] = {}

    def mark_inactive(self, sub_id: str) -> None:
        self._entries[sub_id] = time.time()

    def is_inactive(self, sub_id: str, ttl_seconds: int = 24 * 60 * 60) -> bool:
        ts = self._entries.get(sub_id)
        if ts is None:
            return False
        if time.time() - ts > ttl_seconds:
            self._entries.pop(sub_id, None)
            return False
        return True


subscription_denylist = SubscriptionDenylist()


def get_pro_entitlement_active(cookie_value: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return entitlement only if token is valid, not expired, and not denylisted."""
    data = parse_entitlement_token(cookie_value)
    if not data:
        return None
    exp = data.get("exp")
    if not isinstance(exp, int) or exp <= int(time.time()):
        return None
    sub_id = data.get("sub_id")
    if isinstance(sub_id, str) and subscription_denylist.is_inactive(sub_id):
        return None
    return data


def get_pro_entitlement_any(cookie_value: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return entitlement even if expired, but still respect denylist."""
    data = parse_entitlement_token(cookie_value)
    if not data:
        return None
    sub_id = data.get("sub_id")
    if isinstance(sub_id, str) and subscription_denylist.is_inactive(sub_id):
        return None
    return data


def validate_file_type(upload_file: UploadFile, allowed_types: Iterable[str], extensions: Iterable[str]) -> None:
    content_type_ok = upload_file.content_type in allowed_types
    extension_ok = any(upload_file.filename.lower().endswith(ext) for ext in extensions if upload_file.filename)
    if not (content_type_ok or extension_ok):
        raise HTTPException(status_code=400, detail=f"Invalid file type for {upload_file.filename}.")


async def read_upload_file(upload_file: UploadFile, max_size: int = MAX_UPLOAD_SIZE) -> bytes:
    content = await upload_file.read()
    if len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File {upload_file.filename} exceeds max size of {max_size // (1024 * 1024)}MB.",
        )
    return content


def parse_json_payload(payload: bytes) -> Dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("Failed to parse JSON payload: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid JSON file.")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON root must be an object.")
    return data


def ensure_form_fields(reader: PdfReader) -> Dict[str, Any]:
    fields = reader.get_fields()
    if not fields:
        raise HTTPException(
            status_code=400,
            detail="This PDF does not contain fillable form fields. Please upload a PDF with interactive form fields (AcroForm)."
        )
    return fields


def extract_field_metadata(reader: PdfReader) -> list[Dict[str, Any]]:
    """Extract form field metadata for UI rendering."""
    fields = ensure_form_fields(reader)
    result = []
    
    for field_name, field_obj in fields.items():
        field_info: Dict[str, Any] = {"name": field_name, "value": ""}
        
        # Get existing value if any
        try:
            if hasattr(field_obj, "get"):
                val = field_obj.get("/V")
                if val is not None:
                    if hasattr(val, "get_object"):
                        val = val.get_object()
                    if isinstance(val, bool):
                        field_info["value"] = val
                    elif isinstance(val, (str, int, float)):
                        field_info["value"] = str(val)
                    elif isinstance(val, list) and len(val) > 0:
                        first = val[0]
                        if hasattr(first, "get_object"):
                            first = first.get_object()
                        field_info["value"] = str(first)
        except Exception:
            pass  # Use default empty value
        
        # Infer field type from /FT (field type)
        try:
            ft = field_obj.get("/FT") if hasattr(field_obj, "get") else None
            if ft:
                if hasattr(ft, "get_object"):
                    ft = ft.get_object()
                ft_str = str(ft) if ft else ""
                if "/Btn" in ft_str or "Btn" in ft_str:
                    # Check if it's a checkbox or radio
                    ff = field_obj.get("/Ff") if hasattr(field_obj, "get") else None
                    if ff is not None:
                        if hasattr(ff, "get_object"):
                            ff = ff.get_object()
                        if isinstance(ff, int) and (ff & 0x8000):  # Radio button flag
                            field_info["type"] = "choice"
                            field_info["options"] = []
                        else:
                            field_info["type"] = "checkbox"
                    else:
                        field_info["type"] = "checkbox"
                elif "/Ch" in ft_str or "Ch" in ft_str:
                    field_info["type"] = "choice"
                    # Try to extract options
                    opt = field_obj.get("/Opt") if hasattr(field_obj, "get") else None
                    if opt is not None:
                        if hasattr(opt, "get_object"):
                            opt = opt.get_object()
                        if isinstance(opt, list):
                            options = []
                            for item in opt:
                                if hasattr(item, "get_object"):
                                    item = item.get_object()
                                if isinstance(item, (str, int, float)):
                                    options.append(str(item))
                                elif isinstance(item, list) and len(item) > 0:
                                    options.append(str(item[0]))
                            if options:
                                field_info["options"] = options
                else:
                    field_info["type"] = "text"
            else:
                field_info["type"] = "text"
        except Exception:
            field_info["type"] = "text"  # Default to text on error
        
        result.append(field_info)
    
    return result


def copy_acroform_and_set_appearances(writer: PdfWriter, reader: PdfReader) -> None:
    """Copy /AcroForm from reader to writer and set /NeedAppearances = true."""
    try:
        root = writer._root_object  # type: ignore[attr-defined]
        if not root:
            raise ValueError("Writer root object not found")
        
        reader_root = reader.trailer.get("/Root")
        if not reader_root:
            raise ValueError("Reader root not found")
        
        acro_form_ref = reader_root.get("/AcroForm")
        if not acro_form_ref:
            raise ValueError("No /AcroForm found in PDF")
        
        # Get the actual AcroForm dictionary object
        if hasattr(acro_form_ref, "get_object"):
            acro_form_obj = acro_form_ref.get_object()
        else:
            acro_form_obj = acro_form_ref
        
        # Create a new dictionary object for the writer by copying fields manually
        new_acro_form = DictionaryObject()
        
        # Copy all fields from the original AcroForm
        if isinstance(acro_form_obj, dict):
            for key, value in acro_form_obj.items():
                if key != "/NeedAppearances":  # We'll set this explicitly
                    new_acro_form[NameObject(key)] = value
        elif hasattr(acro_form_obj, "keys"):
            for key in acro_form_obj.keys():
                if key != "/NeedAppearances":
                    new_acro_form[NameObject(key)] = acro_form_obj[key]
        
        # Set /NeedAppearances = true
        new_acro_form[NameObject("/NeedAppearances")] = BooleanObject(True)
        
        # Add to writer's root using update method
        root.update({NameObject("/AcroForm"): new_acro_form})
        
        logger.info("Successfully copied AcroForm and set NeedAppearances")
    except ValueError as exc:
        logger.error("AcroForm error: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="This PDF does not contain interactive form fields (AcroForm). Please upload a fillable PDF form."
        )
    except Exception as exc:
        logger.error("Failed to copy AcroForm: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="This PDF does not contain interactive form fields (AcroForm). Please upload a fillable PDF form."
        )


def add_free_watermark(writer: PdfWriter, text: str = "Filled with FormFillAI (Free)") -> None:
    """Add a small footer watermark text by overlaying a PDF onto each page."""
    for i, page in enumerate(writer.pages):
        media_box = page.mediabox
        page_width = float(media_box.width)
        page_height = float(media_box.height)

        # Create a single-page PDF overlay in memory with ReportLab.
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=(page_width, page_height))
        c.setFillColorRGB(0.35, 0.4, 0.45)
        c.setFont("Helvetica", 8)
        margin_x = 15 * mm
        margin_y = 10 * mm
        c.drawString(margin_x, margin_y, text)
        c.save()
        buffer.seek(0)

        overlay_reader = PdfReader(buffer)
        overlay_page = overlay_reader.pages[0]
        page.merge_page(overlay_page)


def fill_pdf_form(pdf_bytes: bytes, data: Dict[str, Any], add_watermark: bool, output_path: Optional[Path] = None) -> Path:
    """Fill PDF form with data. If output_path is provided, save there; otherwise create temp file."""
    reader = PdfReader(BytesIO(pdf_bytes))
    fields = ensure_form_fields(reader)
    field_names = set(fields.keys())
    # Convert values to appropriate types: keep bools as bool, convert others to str
    filtered_data = {}
    for k, v in data.items():
        if k in field_names:
            if isinstance(v, bool):
                filtered_data[k] = v
            else:
                filtered_data[k] = str(v) if v is not None else ""

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    
    # Copy /AcroForm from reader to writer BEFORE updating fields
    copy_acroform_and_set_appearances(writer, reader)
    
    # Update form field values
    for page in writer.pages:
        writer.update_page_form_field_values(page, filtered_data)

    if add_watermark:
        add_free_watermark(writer)

    ensure_tmp_dir()
    if output_path:
        tmp_file = output_path
    else:
        tmp_file = TMP_DIR / f"filled_{int(time.time() * 1000)}.pdf"
    with tmp_file.open("wb") as fh:
        writer.write(fh)
    return tmp_file


def cleanup_tmp_directory(ttl_seconds: int = TEMP_TTL_SECONDS) -> None:
    now = time.time()
    for path in TMP_DIR.glob("*"):
        try:
            if path.is_file() and now - path.stat().st_mtime > ttl_seconds:
                path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to cleanup %s: %s", path, exc)
    
    # Cleanup preview directory (including original PDFs and metadata)
    if PREVIEW_DIR.exists():
        for path in PREVIEW_DIR.glob("*"):
            try:
                if path.is_file() and now - path.stat().st_mtime > PREVIEW_TTL_SECONDS:
                    path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to cleanup preview %s: %s", path, exc)


async def periodic_cleanup() -> None:
    ensure_tmp_dir()
    while True:
        cleanup_tmp_directory()
        await asyncio.sleep(CLEAN_INTERVAL_SECONDS)


@app.on_event("startup")
async def startup_event() -> None:
    ensure_tmp_dir()
    
    # Log app version/commit for deployment verification
    try:
        import subprocess
        commit_hash = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        commit_hash = "unknown"
    
    logger.info("=== FormFillAI Startup ===")
    logger.info("App version: commit=%s", commit_hash)
    
    # Log environment and required variables BEFORE any initialization
    database_url_set = bool(os.getenv("DATABASE_URL"))
    app_signing_secret_set = bool(os.getenv("APP_SIGNING_SECRET"))
    
    logger.info("Startup config: ENV=%s DEBUG=%s DATABASE_URL=%s APP_SIGNING_SECRET=%s",
                ENV or "not set", DEBUG, database_url_set, app_signing_secret_set)
    
    # Initialize database (this will log DATABASE_URL status and backend)
    await db.init_db()
    
    # Log database backend (after init_db which sets it)
    db_backend = db.get_db_backend_name()
    database_url_set = bool(os.getenv("DATABASE_URL"))
    if db_backend:
        logger.info("DB backend consistency: backend=%s DATABASE_URL=%s ENV=%s DEBUG=%s IS_PRODUCTION=%s",
                    db_backend, database_url_set, ENV or "not set", DEBUG, IS_PRODUCTION)
        if IS_PRODUCTION and db_backend != "postgres":
            logger.error("CRITICAL: Production requires Postgres but backend is %s", db_backend)
            raise RuntimeError(f"Production requires Postgres backend, but {db_backend} is active")
    else:
        logger.error("Database backend not initialized")
        raise RuntimeError("Database backend initialization failed")
    
    # Log email configuration (Resend API + SMTP)
    email_config = get_email_config()
    resend_api_key_present = email_config["resend_configured"]
    smtp_configured = email_config["smtp_configured"]
    public_base_url_present = bool(os.getenv("PUBLIC_BASE_URL"))
    
    logger.info("Email configuration: RESEND_API_KEY=%s SMTP_configured=%s PUBLIC_BASE_URL=%s DB_backend=%s",
                resend_api_key_present, smtp_configured, public_base_url_present, db_backend)
    
    asyncio.create_task(periodic_cleanup())
    if STRIPE_SECRET_KEY:
        stripe.api_key = STRIPE_SECRET_KEY
        logger.info("Stripe API key configured.")
    else:
        logger.info("Stripe not configured; upgrade-to-pro will be disabled.")
    
    logger.info("FormFillAI startup complete; temp dir: %s", TMP_DIR)


async def get_current_user_async(request: Request) -> Optional[Dict[str, Any]]:
    """Get current user from session cookie (async)."""
    session_id = request.cookies.get("session")
    db_backend = db.get_db_backend_name()
    database_url_set = bool(os.getenv("DATABASE_URL"))
    
    if not session_id:
        logger.debug("get_current_user_async: no session cookie, backend=%s DATABASE_URL=%s", 
                     db_backend, database_url_set)
        return None
    
    session = await db.get_session(session_id)
    if not session:
        logger.debug("get_current_user_async: session not found, session_id_prefix=%s backend=%s DATABASE_URL=%s",
                     session_id[:8] if len(session_id) >= 8 else "short", db_backend, database_url_set)
        return None
    
    user = await db.get_user_by_id(session["user_id"])
    if user:
        logger.debug("get_current_user_async: authenticated user_id=%s email=%s backend=%s",
                     session["user_id"], user.get("email"), db_backend)
    return user


async def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """FastAPI dependency to get current user."""
    return await get_current_user_async(request)


async def require_user(
    user: Optional[Dict[str, Any]] = Depends(get_current_user)
) -> Dict[str, Any]:
    """FastAPI dependency that requires authentication."""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def require_pro(user: Dict[str, Any] = Depends(require_user), request: Request = None) -> Dict[str, Any]:
    """Require Pro subscription."""
    if request:
        is_pro = get_pro_entitlement_active(request.cookies.get("ffai_pro")) is not None
        if not is_pro and not user.get("is_pro"):
            raise HTTPException(status_code=403, detail="Pro subscription required.")
    return user


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    is_pro = get_pro_entitlement_active(request.cookies.get("ffai_pro")) is not None
    lang = detect_language(request)  # Fallback detection, client-side is primary
    user = await get_current_user_async(request)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "is_pro": is_pro,
            "default_lang": lang,  # Server-side fallback only
            "user": user,
        }
    )


@app.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request) -> HTMLResponse:
    is_pro = get_pro_entitlement_active(request.cookies.get("ffai_pro")) is not None
    lang = detect_language(request)
    user = await get_current_user_async(request)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "is_pro": is_pro,
            "default_lang": lang,
            "user": user,
        }
    )


@app.post("/set-language")
async def set_language(request: Request, lang: str = Form(...)) -> JSONResponse:
    """Set language preference in cookie."""
    normalized = normalize_language(lang)
    if normalized not in SUPPORTED_LANGUAGES:
        normalized = DEFAULT_LANGUAGE
    
    response = JSONResponse({"success": True, "lang": normalized})
    response.set_cookie(
        key="lang",
        value=normalized,
        httponly=False,  # Allow JS access
        secure=False,
        samesite="lax",
        max_age=60 * 60 * 24 * 365,  # 1 year
    )
    return response


@app.get("/fields")
async def extract_fields_get() -> JSONResponse:
    """GET handler for /fields - returns friendly message instead of Method Not Allowed."""
    return JSONResponse(
        status_code=200,
        content={"ok": False, "detail": "Use POST with multipart/form-data containing a PDF file (field name: 'pdf_file')"}
    )


@app.post("/fields")
async def extract_fields(
    request: Request,
    pdf_file: UploadFile = File(...)
) -> JSONResponse:
    """Extract form fields from a fillable PDF."""
    # Log cookie presence for debugging
    cookie_keys = list(request.cookies.keys())
    session_cookie = request.cookies.get("session")
    session_present = bool(session_cookie)
    session_prefix = session_cookie[:8] if session_cookie and len(session_cookie) >= 8 else None
    
    # Check authentication - return 401 if not authenticated
    user = await get_current_user_async(request)
    if not user:
        logger.warning("POST /fields: unauthenticated request cookie_keys=%s session_present=%s session_prefix=%s",
                      cookie_keys, session_present, session_prefix)
        raise HTTPException(
            status_code=401,
            detail="Please sign in to analyze PDFs."
        )
    
    user_id = user.get("id")
    user_email = user.get("email")
    is_authenticated = True
    
    # Log analyze request with content-type
    filename = pdf_file.filename or "unknown"
    content_type = pdf_file.content_type or "unknown"
    
    logger.info("POST /fields: cookie_keys=%s session_present=%s session_prefix=%s",
                cookie_keys, session_present, session_prefix)
    
    # Get file size if possible (before reading)
    file_size = 0
    try:
        if hasattr(pdf_file, 'size'):
            file_size = pdf_file.size
        elif hasattr(pdf_file, 'file'):
            pdf_file.file.seek(0, 2)  # Seek to end
            file_size = pdf_file.file.tell()
            pdf_file.file.seek(0)  # Reset
    except:
        pass
    
    logger.info("POST /fields: filename=%s content_type=%s size=%d authenticated=%s user_id=%s user_email=%s",
                filename, content_type, file_size, is_authenticated, user_id, user_email)
    
    try:
        validate_file_type(pdf_file, ALLOWED_PDF_TYPES, extensions=(".pdf",))
    except HTTPException as e:
        logger.warning("POST /fields failed: invalid file type filename=%s user_id=%s error=%s",
                      filename, user_id, e.detail)
        raise
    
    try:
        pdf_bytes = await read_upload_file(pdf_file)
        file_size = len(pdf_bytes)
        logger.info("POST /fields: filename=%s size=%d bytes content_type=%s authenticated=%s user_id=%s user_email=%s", 
                    filename, file_size, content_type, is_authenticated, user_id, user_email)
        
        # Check file size (10MB limit)
        if file_size > MAX_UPLOAD_SIZE:
            logger.warning("POST /fields failed: file too large filename=%s size=%d user_id=%s",
                          filename, file_size, user_id)
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 * 1024)}MB."
            )
        
        # Compute PDF hash for mapping cache
        pdf_hash = db.compute_pdf_hash(pdf_bytes)
        
        try:
            reader = PdfReader(BytesIO(pdf_bytes))
            fields_metadata = extract_field_metadata(reader)
            field_count = len(fields_metadata)
            logger.info("POST /fields success: filename=%s size=%d fields=%d authenticated=%s user_id=%s",
                       filename, file_size, field_count, is_authenticated, user_id)
            
            if field_count == 0:
                logger.warning("POST /fields: no fields found filename=%s size=%d authenticated=%s user_id=%s",
                             filename, file_size, is_authenticated, user_id)
                raise HTTPException(
                    status_code=422,
                    detail="This PDF does not contain fillable form fields. Please upload a PDF with interactive form fields (AcroForm)."
                )
            
            # Return stable JSON shape that frontend expects
            return JSONResponse({
                "ok": True,
                "fields": fields_metadata,
                "pdf_hash": pdf_hash,
                "meta": {
                    "field_count": field_count,
                    "filename": filename,
                    "size": file_size
                }
            })
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("POST /fields failed: invalid PDF filename=%s size=%d authenticated=%s user_id=%s error=%s",
                          filename, file_size, is_authenticated, user_id, str(exc))
            raise HTTPException(
                status_code=422,
                detail="This PDF does not contain fillable form fields. Please upload a PDF with interactive form fields (AcroForm)."
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("POST /fields error: filename=%s user_id=%s error=%s",
                    filename, user_id, str(exc), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An error occurred while analyzing the PDF. Please try again."
        )


@app.post("/analyze")
async def analyze_pdf(pdf_file: UploadFile = File(...)) -> JSONResponse:
    """Alias for /fields - extract form fields from a fillable PDF."""
    return await extract_fields(pdf_file)


@app.post("/ai-extract")
async def ai_extract_fields(
    fields_json: str = Form(...),
    user_text: str = Form(...),
    current_values: Optional[str] = Form(None),
) -> JSONResponse:
    """Use AI to extract field values from user text. Only fills empty/missing fields."""
    if not openai_client:
        raise HTTPException(status_code=503, detail="AI extraction is not available. Set OPENAI_API_KEY to enable.")
    
    if not user_text or not user_text.strip():
        return JSONResponse({"extracted": {}})
    
    try:
        fields = json.loads(fields_json)
        if not isinstance(fields, list):
            raise ValueError("fields_json must be a list")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid fields_json format.")
    
    # Parse current values (already filled by user)
    current_data: Dict[str, Any] = {}
    if current_values and current_values.strip():
        try:
            current_data = json.loads(current_values.strip())
            if not isinstance(current_data, dict):
                current_data = {}
        except json.JSONDecodeError:
            current_data = {}
    
    # Build field names list for the prompt, excluding already-filled fields
    field_names = []
    empty_field_names = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = field.get("name")
        if not name:
            continue
        field_names.append(name)
        # Track fields that are empty or not yet filled
        if name not in current_data or not current_data.get(name):
            empty_field_names.append(name)
    
    if not field_names:
        return JSONResponse({"extracted": {}})
    
    # Only extract values for empty fields
    if not empty_field_names:
        return JSONResponse({"extracted": {}})
    
    # Create structured output schema only for empty fields
    properties = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = field.get("name")
        if not name or name not in empty_field_names:
            continue  # Skip already-filled fields
        field_type = field.get("type", "text")
        
        if field_type == "checkbox":
            properties[name] = {
                "type": "boolean",
                "description": f"Value for field '{name}' (true/false)"
            }
        else:
            properties[name] = {
                "type": "string",
                "description": f"Value for field '{name}'"
            }
    
    schema = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False
    }
    
    # Build prompt emphasizing not to overwrite existing values
    filled_fields_desc = ", ".join([f"{k}: {v}" for k, v in current_data.items() if v]) if current_data else "none"
    
    try:
        response = openai_client.beta.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that extracts structured information from user text. Only extract values you are confident about. Only fill fields that are currently empty. Never overwrite fields that already have values. Leave fields empty if you cannot determine the value from the text."
                },
                {
                    "role": "user",
                    "content": f"Extract information from this text and fill ONLY the empty fields listed below. Do NOT fill fields that already have values.\n\nUser text: {user_text}\n\nAlready filled fields (DO NOT change these): {filled_fields_desc}\n\nEmpty fields to fill: {', '.join(empty_field_names)}\n\nReturn only the empty fields you can confidently identify from the text."
                }
            ],
            response_format={"type": "json_schema", "json_schema": {"name": "extracted_fields", "strict": True, "schema": schema}},
            temperature=0.1,
        )
        
        result_text = response.choices[0].message.content
        if result_text:
            extracted = json.loads(result_text)
            if isinstance(extracted, dict):
                # Filter out empty values and ensure we don't overwrite existing values
                extracted = {
                    k: v for k, v in extracted.items() 
                    if v not in (None, "", False) and k in empty_field_names
                }
                return JSONResponse({"extracted": extracted})
        
        return JSONResponse({"extracted": {}})
    except Exception as exc:
        logger.warning("AI extraction error: %s", exc)
        raise HTTPException(status_code=500, detail="AI extraction failed. Please fill fields manually.")


@app.post("/fill")
async def fill(
    request: Request,
    background_tasks: BackgroundTasks,
    pdf_file: UploadFile = File(...),
    fields_json: Optional[str] = Form(None),
    # JSON inputs kept for API/debug use only, not exposed in UI
    json_file: Optional[UploadFile] = File(None),
    json_text: Optional[str] = Form(None),
):
    # Determine access tier based on signed cookie.
    is_pro = get_pro_entitlement_active(request.cookies.get("ffai_pro")) is not None

    # Handle free-tier usage limits.
    token_cookie = request.cookies.get("ffai_token")
    token_raw = _verify_token(token_cookie)
    new_token_raw: Optional[str] = None
    if token_raw is None:
        new_token_raw = secrets.token_urlsafe(16)
        token_raw = new_token_raw
    if not is_pro:
        usage_limiter.check_and_increment(token_raw)

    validate_file_type(pdf_file, ALLOWED_PDF_TYPES, extensions=(".pdf",))
    
    # Primary data source: fields_json from UI form
    data: Dict[str, Any] = {}
    
    # 1. fields_json (from generated UI form) - primary method
    if fields_json and fields_json.strip():
        try:
            fields_data = json.loads(fields_json.strip())
            if isinstance(fields_data, dict):
                data.update(fields_data)
                logger.info("Received fill request: pdf=%s fields_json=provided", pdf_file.filename)
        except json.JSONDecodeError:
            logger.warning("Invalid fields_json: %s", fields_json[:100])
            raise HTTPException(status_code=400, detail="Invalid form data. Please try again.")
    
    # 2. json_file (API/debug only - not in UI)
    if json_file is not None and json_file.filename and json_file.filename.strip():
        validate_file_type(json_file, ALLOWED_JSON_TYPES, extensions=(".json",))
        json_bytes = await read_upload_file(json_file)
        file_data = parse_json_payload(json_bytes)
        data.update(file_data)  # fields_json takes precedence
        logger.info("Received fill request: pdf=%s json_file=%s (API)", pdf_file.filename, json_file.filename)
    
    # 3. json_text (API/debug only - not in UI)
    if json_text and json_text.strip():
        try:
            text_data = json.loads(json_text.strip())
            if isinstance(text_data, dict):
                data.update(text_data)  # fields_json and json_file take precedence
                logger.info("Received fill request: pdf=%s json_text=provided (API)", pdf_file.filename)
        except json.JSONDecodeError:
            logger.warning("Invalid json_text")
    
    if not data:
        raise HTTPException(status_code=400, detail="No form field values provided. Please fill the form fields.")

    pdf_bytes = await read_upload_file(pdf_file)
    
    # Compute PDF hash for mapping cache
    pdf_hash = db.compute_pdf_hash(pdf_bytes)
    
    # Generate unique file ID for preview
    file_id = secrets.token_urlsafe(16)
    ensure_tmp_dir()
    preview_path = PREVIEW_DIR / f"{file_id}.pdf"
    original_pdf_path = PREVIEW_DIR / f"{file_id}_original.pdf"
    
    # Save original PDF for AI fix loop
    with original_pdf_path.open("wb") as fh:
        fh.write(pdf_bytes)
    
    # Fill PDF and save to preview directory
    filled_pdf_path = fill_pdf_form(pdf_bytes, data, add_watermark=not is_pro, output_path=preview_path)
    
    file_size = preview_path.stat().st_size
    logger.info("Generated filled PDF: file_id=%s, path=%s, size=%d bytes, watermark=%s", 
                file_id, preview_path, file_size, not is_pro)
    
    # Store metadata (watermark status) in a simple JSON file
    metadata_path = PREVIEW_DIR / f"{file_id}_meta.json"
    with metadata_path.open("w") as fh:
        json.dump({"is_pro": is_pro, "add_watermark": not is_pro}, fh)

    response = JSONResponse({
        "preview_url": f"/preview/{file_id}",
        "download_url": f"/download/{file_id}",
        "file_id": file_id,
        "pdf_hash": pdf_hash
    })
    
    if new_token_raw:
        response.set_cookie(
            key="ffai_token",
            value=_sign_token(new_token_raw),
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
        )
    
    return response


@app.get("/api/debug/env")
async def debug_env() -> JSONResponse:
    """Debug endpoint to check environment variables (dev only)."""
    if IS_PRODUCTION:
        raise HTTPException(status_code=404, detail="Not found")
    
    database_url = os.getenv("DATABASE_URL")
    return JSONResponse({
        "hasDatabaseUrl": bool(database_url),
        "env": "prod" if IS_PRODUCTION else "dev",
        "databaseUrlPresent": bool(database_url)
    })


@app.get("/api/config")
async def get_config() -> JSONResponse:
    """Get application configuration (feature flags, environment)."""
    stripe_enabled = bool(STRIPE_SECRET_KEY and STRIPE_PRICE_ID)
    openai_enabled = bool(OPENAI_AVAILABLE and OPENAI_API_KEY)
    env_name = "prod" if IS_PRODUCTION else "dev"
    
    return JSONResponse({
        "stripeEnabled": stripe_enabled,
        "openaiEnabled": openai_enabled,
        "env": env_name
    })


@app.get("/api/me")
async def get_me(request: Request) -> JSONResponse:
    """Get current user information including email and plan (free/pro)."""
    # Log cookie presence for debugging
    cookie_keys = list(request.cookies.keys())
    session_cookie = request.cookies.get("session")
    session_present = bool(session_cookie)
    session_prefix = session_cookie[:8] if session_cookie and len(session_cookie) >= 8 else None
    
    # Log backend consistency
    db_backend = db.get_db_backend_name()
    database_url_set = bool(os.getenv("DATABASE_URL"))
    logger.info("GET /api/me: cookie_keys=%s session_present=%s session_prefix=%s backend=%s DATABASE_URL=%s ENV=%s DEBUG=%s IS_PRODUCTION=%s",
                cookie_keys, session_present, session_prefix, db_backend, database_url_set, ENV or "not set", DEBUG, IS_PRODUCTION)
    
    user = await get_current_user_async(request)
    if not user:
        logger.info("api/me: not authenticated (no user found)")
        return JSONResponse({
            "authenticated": False
        })
    
    # Check if user is Pro (from Stripe cookie or database)
    is_pro_cookie = get_pro_entitlement_active(request.cookies.get("ffai_pro")) is not None
    is_pro_db = user.get("is_pro", False)
    is_pro = is_pro_cookie or is_pro_db
    
    # Determine plan string
    plan = "pro" if is_pro else "free"
    
    logger.info("api/me: authenticated user_id=%s email=%s plan=%s backend=%s",
                user.get("id"), user.get("email"), plan, db_backend)
    
    return JSONResponse({
        "authenticated": True,
        "email": user["email"],
        "plan": plan,
        "is_pro": is_pro
    })


@app.post("/create-checkout-session")
async def create_checkout_session(request: Request):
    if not (STRIPE_SECRET_KEY and STRIPE_PRICE_ID):
        logger.info("Checkout session requested but Stripe is not configured.")
        raise HTTPException(
            status_code=503,
            detail="Payments are not configured in this environment."
        )

    # Ensure we have a stable browser token to associate with the checkout session.
    token_cookie = request.cookies.get("ffai_token")
    token_raw = _verify_token(token_cookie)
    new_token_raw: Optional[str] = None
    if token_raw is None:
        new_token_raw = secrets.token_urlsafe(16)
        token_raw = new_token_raw

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            client_reference_id=token_raw,
            success_url="http://127.0.0.1:8000/stripe/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="http://127.0.0.1:8000/stripe/cancel",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error creating Stripe Checkout session: %s", exc)
        raise HTTPException(status_code=500, detail="Unable to start checkout.")

    response = RedirectResponse(url=session.url, status_code=303)
    if new_token_raw:
        response.set_cookie(
            key="ffai_token",
            value=_sign_token(new_token_raw),
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
        )
    return response


@app.get("/stripe/success")
async def stripe_success(request: Request):
    if not STRIPE_SECRET_KEY:
        logger.info("Stripe success callback but Stripe is not configured.")
        raise HTTPException(status_code=503, detail="Stripe is not configured.")

    session_id = request.query_params.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id.")

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error retrieving Stripe session: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid session.")

    if session.get("status") != "complete":
        raise HTTPException(status_code=400, detail="Checkout session not complete.")
    if session.get("mode") != "subscription":
        raise HTTPException(status_code=400, detail="Not a subscription session.")

    sub_id = session.get("subscription")
    if not sub_id:
        raise HTTPException(status_code=400, detail="No subscription found for session.")

    try:
        subscription = stripe.Subscription.retrieve(sub_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error retrieving Stripe subscription: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid subscription.")

    if subscription.get("status") not in {"active", "trialing"}:
        raise HTTPException(status_code=400, detail="Subscription is not active.")

    customer_id = subscription.get("customer")
    exp = int(time.time()) + 30 * 24 * 60 * 60
    response = RedirectResponse(url="/?upgraded=1", status_code=303)
    response.set_cookie(
        key="ffai_pro",
        value=create_entitlement_token(expiry_ts=exp, sub_id=str(subscription.get("id")), customer_id=str(customer_id) if customer_id else None),
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return response


@app.get("/stripe/cancel")
async def stripe_cancel() -> RedirectResponse:
    return RedirectResponse(url="/?canceled=1", status_code=303)


@app.get("/stripe/refresh")
async def stripe_refresh(request: Request) -> RedirectResponse:
    if not STRIPE_SECRET_KEY:
        logger.info("Stripe refresh requested but Stripe is not configured.")
        raise HTTPException(status_code=503, detail="Stripe is not configured.")

    ent = get_pro_entitlement_any(request.cookies.get("ffai_pro"))
    if not ent:
        return RedirectResponse(url="/?pro_refresh=missing", status_code=303)

    sub_id = ent.get("sub_id")
    if not isinstance(sub_id, str):
        return RedirectResponse(url="/?pro_refresh=invalid", status_code=303)

    if subscription_denylist.is_inactive(sub_id):
        resp = RedirectResponse(url="/?pro_refresh=inactive", status_code=303)
        resp.delete_cookie("ffai_pro")
        return resp

    try:
        subscription = stripe.Subscription.retrieve(sub_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error retrieving Stripe subscription during refresh: %s", exc)
        return RedirectResponse(url="/?pro_refresh=error", status_code=303)

    if subscription.get("status") not in {"active", "trialing"}:
        subscription_denylist.mark_inactive(sub_id)
        resp = RedirectResponse(url="/?pro_refresh=inactive", status_code=303)
        resp.delete_cookie("ffai_pro")
        return resp

    # Subscription is active; extend Pro cookie.
    customer_id = subscription.get("customer")
    exp = int(time.time()) + 30 * 24 * 60 * 60
    token = create_entitlement_token(
        expiry_ts=exp,
        sub_id=sub_id,
        customer_id=str(customer_id) if customer_id else None,
    )
    resp = RedirectResponse(url="/?pro_refresh=ok", status_code=303)
    resp.set_cookie(
        key="ffai_pro",
        value=token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return resp


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret not configured.")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    if sig_header is None:
        raise HTTPException(status_code=400, detail="Missing Stripe signature header.")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError:
        logger.warning("Invalid Stripe webhook signature.")
        raise HTTPException(status_code=400, detail="Invalid signature.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error parsing Stripe webhook: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid payload.")

    event_type = event.get("type")
    obj = event.get("data", {}).get("object", {}) or {}

    sub_id: Optional[str] = None
    customer_id: Optional[str] = None

    if event_type == "checkout.session.completed":
        if obj.get("mode") == "subscription":
            sub_id = obj.get("subscription")
            customer_id = obj.get("customer")
    elif event_type in {"customer.subscription.updated", "customer.subscription.deleted"}:
        sub_id = obj.get("id")
        customer_id = obj.get("customer")
    elif event_type in {"invoice.payment_succeeded", "invoice.payment_failed"}:
        sub_id = obj.get("subscription")
        customer_id = obj.get("customer")

    if sub_id:
        logger.info("Stripe webhook %s for subscription %s", event_type, sub_id)

    if event_type in {"customer.subscription.updated", "customer.subscription.deleted"}:
        status = obj.get("status")
        if status not in {"active", "trialing"} and sub_id:
            subscription_denylist.mark_inactive(sub_id)
    elif event_type == "invoice.payment_failed":
        if sub_id:
            subscription_denylist.mark_inactive(sub_id)

    return JSONResponse({"received": True})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # For API requests return JSON; the frontend relies on default behavior (FastAPI will render JSON).
    logger.warning("HTTP error on %s: %s", request.url.path, exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/preview/{file_id}")
async def preview_pdf(file_id: str, request: Request) -> FileResponse:
    """Return PDF for inline preview with proper headers."""
    ensure_tmp_dir()
    preview_path = PREVIEW_DIR / f"{file_id}.pdf"
    
    if not preview_path.exists():
        logger.warning("Preview not found: file_id=%s", file_id)
        raise HTTPException(status_code=404, detail="Preview not found or expired.")
    
    file_size = preview_path.stat().st_size
    logger.info("Serving preview: file_id=%s, size=%d bytes", file_id, file_size)
    
    # Use FileResponse with inline disposition for iframe rendering
    response = FileResponse(
        path=preview_path,
        media_type="application/pdf",
        filename="preview.pdf",
        headers={
            "Content-Disposition": 'inline; filename="preview.pdf"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            # Allow same-origin framing (not DENY)
            "X-Frame-Options": "SAMEORIGIN"
        }
    )
    
    logger.debug("Preview response headers: Content-Type=%s, Content-Disposition=%s, X-Frame-Options=%s", 
                 response.headers.get("Content-Type"), 
                 response.headers.get("Content-Disposition"),
                 response.headers.get("X-Frame-Options"))
    
    return response


@app.get("/download/{file_id}")
async def download_pdf(file_id: str) -> FileResponse:
    """Return PDF with download disposition."""
    ensure_tmp_dir()
    preview_path = PREVIEW_DIR / f"{file_id}.pdf"
    
    if not preview_path.exists():
        logger.warning("Download requested for non-existent file: file_id=%s", file_id)
        raise HTTPException(status_code=404, detail="File not found or expired.")
    
    file_size = preview_path.stat().st_size
    logger.info("Serving download: file_id=%s, size=%d bytes", file_id, file_size)
    
    response = FileResponse(
        path=preview_path,
        media_type="application/pdf",
        filename="filled_form.pdf",
    )
    response.headers["Content-Disposition"] = 'attachment; filename="filled_form.pdf"'
    return response


@app.post("/ai-fix")
async def ai_fix_pdf(
    file_id: str = Form(...),
    fields_json: str = Form(...),
    current_values: str = Form(...),
    feedback: str = Form(...),
) -> JSONResponse:
    """Apply AI corrections to a preview PDF based on user feedback."""
    if not openai_client:
        raise HTTPException(status_code=503, detail="AI correction is not available. Set OPENAI_API_KEY to enable.")
    
    if not feedback or not feedback.strip():
        raise HTTPException(status_code=400, detail="Please provide feedback on what to fix.")
    
    ensure_tmp_dir()
    preview_path = PREVIEW_DIR / f"{file_id}.pdf"
    original_pdf_path = PREVIEW_DIR / f"{file_id}_original.pdf"
    metadata_path = PREVIEW_DIR / f"{file_id}_meta.json"
    
    if not preview_path.exists() or not original_pdf_path.exists():
        raise HTTPException(status_code=404, detail="Preview not found or expired.")
    
    try:
        fields = json.loads(fields_json)
        current_data = json.loads(current_values)
        if not isinstance(fields, list) or not isinstance(current_data, dict):
            raise ValueError("Invalid data format")
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid form data.")
    
    # Read original PDF
    with original_pdf_path.open("rb") as fh:
        pdf_bytes = fh.read()
    
    # Read metadata
    add_watermark = True  # Default
    if metadata_path.exists():
        try:
            with metadata_path.open("r") as fh:
                meta = json.load(fh)
                add_watermark = meta.get("add_watermark", True)
        except Exception:
            pass
    
    # Build AI prompt with exact system message
    field_list = []
    for field in fields:
        if isinstance(field, dict):
            name = field.get("name", "")
            current_val = current_data.get(name, "")
            field_list.append(f"- {name}: {current_val}")
    
    field_list_str = "\n".join(field_list)
    
    try:
        response = openai_client.beta.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are editing values in a PDF form.\nYou are given:\n- A list of form fields with their current values\n- A user instruction describing what to fix\n\nRules:\n- Only change fields that the user explicitly or implicitly refers to\n- Do not invent new data\n- Do not remove data unless asked\n- Return ONLY valid JSON with updated fields\n- Preserve all untouched fields exactly as-is"
                },
                {
                    "role": "user",
                    "content": f"Current form field values:\n{field_list_str}\n\nUser instruction: {feedback}\n\nReturn a JSON object with ONLY the fields that need to be changed. Preserve all other fields exactly as they are."
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        
        result_text = response.choices[0].message.content
        if not result_text:
            raise ValueError("Empty AI response")
        
        corrections = json.loads(result_text)
        if not isinstance(corrections, dict):
            raise ValueError("Invalid AI response format")
        
        # Merge corrections with current values (corrections take precedence)
        updated_data = current_data.copy()
        updated_data.update(corrections)
        
        # Regenerate PDF with corrections
        fill_pdf_form(pdf_bytes, updated_data, add_watermark=add_watermark, output_path=preview_path)
        
        file_size = preview_path.stat().st_size
        logger.info("AI fix applied: file_id=%s, updated_fields=%s, size=%d bytes", 
                    file_id, list(corrections.keys()), file_size)
        
        return JSONResponse({
            "success": True,
            "preview_url": f"/preview/{file_id}",
            "file_id": file_id,
            "updated_fields": list(corrections.keys())
        })
        
    except json.JSONDecodeError:
        logger.warning("AI returned invalid JSON")
        raise HTTPException(status_code=500, detail="AI returned invalid response. Please try again.")
    except Exception as exc:
        logger.warning("AI fix error: %s", exc)
        raise HTTPException(status_code=500, detail="AI correction failed. Please try again.")


async def send_email_via_resend_api(to_email: str, subject: str, html: str, from_email: str, from_raw: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Send email via Resend HTTP API.
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        html: Email body (HTML)
        from_email: From email address (parsed)
        from_raw: Optional raw FROM string (supports "Name <email>")
    
    Returns:
        Tuple[bool, Optional[str]]: (success, error_message)
        - If successful: (True, None)
        - If failed: (False, safe_error_message)
    """
    import httpx
    
    resend_api_key = get_env("RESEND_API_KEY")
    if not resend_api_key:
        return (False, "RESEND_API_KEY not configured")
    
    # Use from_raw if available (supports "Name <email>"), otherwise use from_email
    from_address = from_raw if from_raw else from_email
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "from": from_address,
                    "to": to_email,
                    "subject": subject,
                    "html": html
                }
            )
            
            if response.status_code == 200:
                logger.info("Email sent via Resend API to %s", to_email)
                return (True, None)
            else:
                # Log status code only (no secrets)
                error_detail = f"Resend API error: status {response.status_code}"
                try:
                    error_data = response.json()
                    if "message" in error_data:
                        error_detail = f"Resend API error: {error_data['message'][:100]}"
                except:
                    pass
                logger.error("Resend API send failed: status=%d", response.status_code)
                return (False, error_detail)
                
    except httpx.TimeoutException:
        logger.error("Resend API timeout")
        return (False, "Resend API timeout")
    except Exception as e:
        logger.error("Resend API error: %s", e)
        return (False, f"Resend API error: {str(e)[:100]}")


async def send_email_via_smtp(to_email: str, subject: str, body: str, smtp_config: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str]]:
    """Send email via SMTP with retry logic. 
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Email body (HTML)
        smtp_config: Optional SMTP config dict from get_smtp_config(). If None, calls get_smtp_config().
    
    Returns:
        Tuple[bool, Optional[str]]: (success, error_message)
        - If successful: (True, None)
        - If failed: (False, safe_error_message)
    
    Uses connection timeout (10s) and handles all SMTP errors robustly.
    """
    # Get fresh SMTP config if not provided
    if smtp_config is None:
        smtp_config = get_smtp_config()
    
    # Check if SMTP is configured
    if not smtp_config["configured"]:
        missing_keys_str = ", ".join(smtp_config["missing_keys"])
        logger.warning("SMTP not configured: missing keys=%s", missing_keys_str)
        return (False, f"SMTP not configured: missing {missing_keys_str}")
    
    # Extract config values
    host = smtp_config["host"]
    user = smtp_config["user"]
    pass_val = smtp_config["pass"]
    from_raw = smtp_config["from_raw"]
    from_email = smtp_config["from"]
    port = smtp_config["port"]
    
    def _send_sync():
        """Synchronous SMTP send function to run in thread pool."""
        try:
            # Create message
            msg = MIMEMultipart()
            # Use raw FROM if available (supports "Name <email>"), otherwise use extracted email
            msg['From'] = from_raw if from_raw else from_email
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Add body
            msg.attach(MIMEText(body, 'html'))
            
            # Connect with timeout (10 seconds for connection)
            # Note: send_message may take additional time, but connection is established within timeout
            with smtplib.SMTP(host, port, timeout=10) as server:
                # Enable TLS with timeout
                server.starttls()
                # Login with timeout handling
                server.login(user, pass_val)
                # Send message - use extracted email for from_addr
                server.send_message(msg, from_addr=from_email, to_addrs=[to_email])
            
            return (True, None)
        except (smtplib.SMTPException, smtplib.SMTPAuthenticationError, 
                smtplib.SMTPConnectError, smtplib.SMTPDataError,
                smtplib.SMTPHeloError, smtplib.SMTPRecipientsRefused,
                smtplib.SMTPSenderRefused, smtplib.SMTPServerDisconnected) as e:
            # Re-raise SMTP-specific exceptions to be caught by retry logic
            raise
        except (ConnectionError, TimeoutError, OSError) as e:
            # Network/connection errors - will be retried
            raise
        except Exception as e:
            # Unexpected errors - log and re-raise for retry logic
            logger.error("Unexpected error in SMTP send function: %s", e, exc_info=True)
            raise
    
    # Retry logic: up to 3 attempts (initial + 2 retries)
    max_attempts = 3
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            # Run SMTP send in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(_smtp_executor, _send_sync)
            if result[0]:  # result is now a tuple (bool, Optional[str])
                if attempt > 1:
                    logger.info("SMTP email sent successfully to %s on attempt %d", to_email, attempt)
                else:
                    logger.info("Email sent via SMTP to %s", to_email)
                return (True, None)
        except (smtplib.SMTPException, smtplib.SMTPAuthenticationError,
                smtplib.SMTPConnectError, smtplib.SMTPDataError,
                smtplib.SMTPHeloError, smtplib.SMTPRecipientsRefused,
                smtplib.SMTPSenderRefused, smtplib.SMTPServerDisconnected) as e:
            # Create safe error message (no sensitive data)
            error_msg = f"SMTP error: {type(e).__name__}"
            if hasattr(e, 'smtp_code') and e.smtp_code:
                error_msg += f" (code {e.smtp_code})"
            if hasattr(e, 'smtp_error') and e.smtp_error:
                # Only include first line of error, sanitized
                error_line = str(e.smtp_error).split('\n')[0][:100]
                error_msg += f": {error_line}"
            last_error = error_msg
            logger.error("SMTP error sending email to %s (attempt %d/%d): %s", to_email, attempt, max_attempts, e)
        except (ConnectionError, TimeoutError, OSError) as e:
            error_msg = f"Connection error: {type(e).__name__}"
            if str(e):
                error_msg += f": {str(e)[:100]}"
            last_error = error_msg
            logger.error("Connection error sending email to %s (attempt %d/%d): %s", to_email, attempt, max_attempts, e)
        except Exception as e:
            error_msg = f"Unexpected error: {type(e).__name__}"
            last_error = error_msg
            logger.error("Unexpected error sending email to %s (attempt %d/%d): %s", to_email, attempt, max_attempts, e, exc_info=True)
        
        # If not the last attempt, wait before retrying
        if attempt < max_attempts:
            logger.info("Retrying SMTP send to %s in 2 seconds (attempt %d/%d)", to_email, attempt + 1, max_attempts)
            await asyncio.sleep(2)
    
    # All attempts failed - return the last error message
    logger.error("SMTP send failed to %s after %d attempts: %s", to_email, max_attempts, last_error)
    return (False, last_error or "Failed to send email after multiple attempts")


def get_public_base_url(request: Request) -> str:
    """Get the public base URL for generating magic links.
    
    In production, prefers PUBLIC_BASE_URL env var.
    Falls back to request.base_url if PUBLIC_BASE_URL is not set.
    Ensures proper URL formatting (no double slashes, proper scheme).
    """
    base_url = get_env("PUBLIC_BASE_URL")
    if base_url:
        # Use env var, ensure it's properly formatted
        base_url = base_url.rstrip('/')
    else:
        # Fallback to request.base_url (check X-Forwarded-Proto for Railway/proxy)
        base_url = str(request.base_url).rstrip('/')
        # Check X-Forwarded-Proto header for HTTPS behind proxy
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").lower()
        if forwarded_proto == "https" and base_url.startswith("http://"):
            base_url = base_url.replace("http://", "https://", 1)
    
    # Ensure no double slashes (except after scheme)
    if '://' in base_url:
        scheme, rest = base_url.split('://', 1)
        rest = rest.lstrip('/')
        base_url = f"{scheme}://{rest}"
    else:
        # If no scheme, assume https in production, http in dev
        if IS_PRODUCTION:
            base_url = f"https://{base_url.lstrip('/')}"
        else:
            base_url = f"http://{base_url.lstrip('/')}"
    
    return base_url


# Authentication endpoints
@app.get("/auth/send-magic-link")
async def send_magic_link_get() -> JSONResponse:
    """GET handler for send-magic-link - returns friendly message instead of Method Not Allowed."""
    return JSONResponse(
        status_code=200,
        content={"ok": False, "detail": "Use POST with JSON body {email: ...} or FormData with email field"}
    )


@app.post("/auth/send-magic-link")
async def send_magic_link(request: Request) -> JSONResponse:
    """Send magic link email for authentication.
    
    Accepts either JSON body with {"email": "..."} or FormData with email field.
    """
    try:
        # Check database availability
        if not db.is_db_available():
            logger.error("Database not available for magic link creation")
            return JSONResponse(
                status_code=503,
                content={"detail": "Database temporarily unavailable. Please try again later."}
            )
        
        # Extract email from request (supports both JSON and FormData)
        content_type = request.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            try:
                body = await request.json()
                email = body.get("email", "").strip()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON body. Expected {email: ...}")
        else:
            # FormData
            form_data = await request.form()
            email = form_data.get("email", "").strip()
        
        # Get unified email configuration
        email_config = get_email_config()
        resend_configured = email_config["resend_configured"]
        smtp_configured = email_config["smtp_configured"]
        from_raw = email_config["from_raw"]
        from_email = email_config["from_email"]
        smtp_config = email_config["smtp_config"]
        
        # Log email configuration (unambiguous, no secrets)
        logger.info("Email config: resend_configured=%s smtp_configured=%s from_present=%s",
                    resend_configured, smtp_configured, bool(from_email))
        
        # Validate email format
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not email or not re.match(email_pattern, email):
            raise HTTPException(status_code=400, detail="Invalid email address.")
        
        # Create or get user
        user = await db.get_user_by_email(email)
        if not user:
            user_id = await db.create_user(email)
        else:
            user_id = user["id"]
        
        # Create magic token (always generate, even if SMTP fails)
        token = await db.create_magic_token(email)
        
        # Build magic link URL using PUBLIC_BASE_URL if available
        base_url = get_public_base_url(request)
        magic_link = f"{base_url}/auth/verify?token={token}"
        
        # Store magic link in memory for dev mode /debug/last-magic-link endpoint
        if DEBUG or ENV == "dev":
            global _last_magic_link
            _last_magic_link = magic_link
        
        # Prepare email content
        email_subject = "Sign in to FormFillAI"
        email_body = f"""<html><body><p>Click the link below to sign in to your FormFillAI account:</p><p><a href="{magic_link}">{magic_link}</a></p><p>This link will expire in 15 minutes.</p><p>If you didn't request this link, you can safely ignore this email.</p></body></html>"""
        
        # Try Resend API first (primary method)
        email_sent = False
        error_msg = None
        method_used = "none"
        
        if resend_configured:
            method_used = "resend_api"
            email_sent, error_msg = await send_email_via_resend_api(
                to_email=email,
                subject=email_subject,
                html=email_body,
                from_email=from_email,
                from_raw=from_raw
            )
            if email_sent:
                logger.info("POST /auth/send-magic-link: method=resend_api success email=%s", email)
                return JSONResponse({
                    "ok": True,
                    "success": True,
                    "message": "Magic link sent to your email."
                })
            else:
                # Extract safe error type
                error_type = "unknown"
                if error_msg:
                    if "timeout" in error_msg.lower():
                        error_type = "timeout"
                    elif "status" in error_msg.lower():
                        error_type = "api_error"
                    else:
                        error_type = "connection_error"
                logger.warning("POST /auth/send-magic-link: method=resend_api failed email=%s error_type=%s", email, error_type)
                # Fall through to SMTP fallback
        
        # Fallback to SMTP if Resend failed or not configured
        if not email_sent and smtp_configured:
            method_used = "smtp"
            email_sent, error_msg = await send_email_via_smtp(
                to_email=email,
                subject=email_subject,
                body=email_body,
                smtp_config=smtp_config
            )
            if email_sent:
                logger.info("POST /auth/send-magic-link: method=smtp success email=%s", email)
                return JSONResponse({
                    "ok": True,
                    "success": True,
                    "message": "Magic link sent to your email."
                })
            else:
                # Extract safe error type
                error_type = "unknown"
                if error_msg:
                    if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                        error_type = "timeout"
                    elif "connection" in error_msg.lower():
                        error_type = "connection_error"
                    else:
                        error_type = "smtp_error"
                logger.warning("POST /auth/send-magic-link: method=smtp failed email=%s error_type=%s", email, error_type)
        
        # Both methods failed or not configured
        # Always log full magic link when email send fails (for Railway logs debugging)
        logger.info("MAGIC_LINK: %s", magic_link)
        
        # Store token for debug endpoint (when sending fails)
        # The token is already in the database, so we just need to ensure it's accessible
        
        if not resend_configured and not smtp_configured:
            # No email service configured
            logger.warning("POST /auth/send-magic-link: method=none email=%s reason=not_configured", email)
            return JSONResponse(
                status_code=503,
                content={"ok": False, "detail": "Email service is not configured. Please configure RESEND_API_KEY or SMTP settings."}
            )
        else:
            # Email service configured but sending failed
            safe_error = error_msg[:200] if error_msg else "Failed to send email"
            logger.error("POST /auth/send-magic-link: method=%s failed email=%s detail=%s", method_used, email, safe_error)
            return JSONResponse(
                status_code=503,
                content={"ok": False, "detail": safe_error}
            )
    except HTTPException:
        # Re-raise HTTP exceptions (400, etc.)
        raise
    except Exception as e:
        # Catch any unexpected errors and return 500 with generic message
        logger.error("Unexpected error in send_magic_link: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again later."
        )


@app.get("/auth/verify")
async def verify_magic_link(request: Request, token: str) -> RedirectResponse:
    """Verify magic link token and create session.
    
    Validates token, marks it as used, creates session, and sets secure cookie.
    """
    # Log backend consistency
    db_backend = db.get_db_backend_name()
    database_url_set = bool(os.getenv("DATABASE_URL"))
    logger.info("auth/verify: backend=%s DATABASE_URL=%s ENV=%s DEBUG=%s IS_PRODUCTION=%s",
                db_backend, database_url_set, ENV or "not set", DEBUG, IS_PRODUCTION)
    
    # Log token prefix (first 6 chars) for debugging
    token_prefix = token[:6] if token and len(token) >= 6 else "none"
    logger.info("Magic link verification request: token_prefix=%s", token_prefix)
    
    # Check database availability
    if not db.is_db_available():
        logger.error("Database not available for magic link verification")
        return RedirectResponse(url="/?auth_error=db_unavailable", status_code=303)
    
    # Verify token (this marks it as used atomically)
    email = await db.verify_magic_token(token)
    if not email:
        logger.warning("Magic link verification failed: token_prefix=%s reason=invalid/expired/used backend=%s", 
                       token_prefix, db_backend)
        return RedirectResponse(url="/?auth_error=invalid_token", status_code=303)
    
    logger.info("Magic link verified successfully: token_prefix=%s email=%s backend=%s", 
                token_prefix, email, db_backend)
    
    # Get or create user
    user = await db.get_user_by_email(email)
    if not user:
        user_id = await db.create_user(email)
        logger.info("Created new user for email: %s", email)
    else:
        user_id = user["id"]
    
    # Create session (uses active backend - postgres or sqlite)
    session_id = await db.create_session(user_id)
    logger.info("Session created: user_id=%s session_id_prefix=%s backend=%s", 
                user_id, session_id[:8] if len(session_id) >= 8 else "short", db_backend)
    
    # Determine if request is HTTPS (check X-Forwarded-Proto for Railway/proxy)
    scheme = request.url.scheme
    x_forwarded_proto = request.headers.get("X-Forwarded-Proto", "").lower()
    host = request.headers.get("host", "unknown")
    
    # Detect HTTPS: prioritize X-Forwarded-Proto (set by Railway/proxy)
    is_https = (x_forwarded_proto == "https") or (scheme == "https")
    
    # Build redirect URL - use PUBLIC_BASE_URL if set, otherwise relative
    redirect_url = "/?auth_success=1"
    public_base_url = get_public_base_url(request)
    if public_base_url and public_base_url != str(request.base_url).rstrip("/"):
        redirect_url = f"{public_base_url}/?auth_success=1"
    
    # Log verification details (no secrets)
    session_id_prefix = session_id[:8] if len(session_id) >= 8 else "short"
    logger.info("auth/verify: token_prefix=%s user_id=%s session_id_prefix=%s secure=%s scheme=%s x_forwarded_proto=%s host=%s redirect_url=%s",
                token_prefix, user_id, session_id_prefix, is_https, scheme, x_forwarded_proto, host, redirect_url)
    
    # Create a single RedirectResponse object and set cookie on it
    # This ensures the cookie is set on the response that's actually returned
    response = RedirectResponse(url=redirect_url, status_code=303)
    response.set_cookie(
        key="session",
        value=session_id,
        httponly=True,
        secure=is_https,  # Secure only when HTTPS detected
        samesite="lax",
        path="/",
        max_age=60 * 60 * 24 * 30,  # 30 days
        # Do NOT set domain explicitly - let browser use current host
    )
    logger.info("Set-cookie issued: secure=%s samesite=lax path=/ httponly=True max_age=2592000 backend=%s", 
                is_https, db_backend)
    return response


@app.post("/auth/logout")
async def logout(request: Request) -> JSONResponse:
    """Logout user by deleting session."""
    session_id = request.cookies.get("session")
    if session_id:
        await db.delete_session(session_id)
    
    response = JSONResponse({"success": True})
    response.delete_cookie("session", httponly=True, secure=IS_PRODUCTION, samesite="lax", path="/")
    return response


# Profile endpoints
@app.get("/api/profiles")
async def list_profiles(user: Dict[str, Any] = Depends(require_user)) -> JSONResponse:
    """List all profiles for current user."""
    profiles = await db.get_user_profiles(user["id"])
    return JSONResponse({"profiles": profiles})


@app.post("/api/profiles")
async def create_profile(
    request: Request,
    name: str = Form(...),
    data: str = Form(...),
    user: Dict[str, Any] = Depends(require_user),
) -> JSONResponse:
    """Create a new profile (paid-only)."""
    # Check if user is Pro
    is_pro = get_pro_entitlement_active(request.cookies.get("ffai_pro")) is not None
    if not is_pro and not user.get("is_pro"):
        raise HTTPException(
            status_code=403,
            detail="Saving profiles requires a Pro subscription. Please upgrade."
        )
    
    try:
        profile_data = json.loads(data)
        if not isinstance(profile_data, dict):
            raise ValueError("Data must be a JSON object")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON data.")
    
    profile_id = await db.create_profile(user["id"], name, profile_data)
    return JSONResponse({"success": True, "profile_id": profile_id})


@app.get("/api/profiles/{profile_id}")
async def get_profile(profile_id: str, user: Dict[str, Any] = Depends(require_user)) -> JSONResponse:
    """Get a specific profile."""
    profile = await db.get_profile(profile_id, user["id"])
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
    
    return JSONResponse(profile)


@app.put("/api/profiles/{profile_id}")
async def update_profile_endpoint(
    request: Request,
    profile_id: str,
    name: Optional[str] = Form(None),
    data: Optional[str] = Form(None),
    user: Dict[str, Any] = Depends(require_user),
) -> JSONResponse:
    """Update a profile (paid-only)."""
    is_pro = get_pro_entitlement_active(request.cookies.get("ffai_pro")) is not None
    if not is_pro and not user.get("is_pro"):
        raise HTTPException(
            status_code=403,
            detail="Updating profiles requires a Pro subscription."
        )
    
    profile_data = None
    if data:
        try:
            profile_data = json.loads(data)
            if not isinstance(profile_data, dict):
                raise ValueError("Data must be a JSON object")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON data.")
    
    success = await db.update_profile(profile_id, user["id"], name, profile_data)
    if not success:
        raise HTTPException(status_code=404, detail="Profile not found.")
    
    return JSONResponse({"success": True})


@app.delete("/api/profiles/{profile_id}")
async def delete_profile_endpoint(
    profile_id: str,
    user: Dict[str, Any] = Depends(require_user),
) -> JSONResponse:
    """Delete a profile."""
    success = await db.delete_profile(profile_id, user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="Profile not found.")
    
    return JSONResponse({"success": True})


@app.post("/api/profiles/apply")
async def apply_profile(
    request: Request,
    profile_id: str = Form(...),
    pdf_hash: Optional[str] = Form(None),
    fields_json: str = Form(...),
    user: Dict[str, Any] = Depends(require_user),
) -> JSONResponse:
    """Apply a profile to PDF fields using mapping."""
    
    profile = await db.get_profile(profile_id, user["id"])
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
    
    try:
        fields = json.loads(fields_json)
        if not isinstance(fields, list):
            raise ValueError("fields_json must be a list")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid fields_json format.")
    
    pdf_field_names = [f.get("name", "") for f in fields if isinstance(f, dict) and f.get("name")]
    
    # Try to get cached mapping
    mappings = None
    if pdf_hash:
        mappings = await db.get_pdf_mapping(user["id"], pdf_hash)
    
    # Map canonical fields to PDF fields
    if mappings:
        # Use cached mappings
        mapped_data = {}
        for pdf_field, canonical_key in mappings.items():
            if canonical_key in profile["data"] and pdf_field in pdf_field_names:
                mapped_data[pdf_field] = profile["data"][canonical_key]
        result = mapped_data
    else:
        # Use automatic mapping
        result = db.map_canonical_to_pdf_fields(profile["data"], pdf_field_names)
        
        # Save mapping for future use
        if pdf_hash and result:
            reverse_mappings = {v: k for k, v in result.items()}
            await db.save_pdf_mapping(user["id"], pdf_hash, reverse_mappings)
    
    return JSONResponse({"mapped_data": result})


@app.post("/api/user/delete-data")
async def delete_user_data(
    request: Request,
    user: Dict[str, Any] = Depends(require_user),
) -> JSONResponse:
    """Delete all user data (profiles, mappings, etc)."""
    await db.delete_user_data(user["id"])
    
    response = JSONResponse({"success": True, "message": "All data deleted."})
    response.delete_cookie("session_id", httponly=True, secure=IS_PRODUCTION, samesite="lax")
    return response


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Health check endpoint with database connectivity status."""
    db_available = db.is_db_available()
    db_connected = False
    db_backend = db.get_db_backend_name() or "unknown"
    
    if db_available:
        try:
            db_connected = await db.check_db_connectivity()
        except Exception as e:
            logger.warning("Health check DB connectivity error: %s", e)
    
    # In production, verify Postgres is being used
    if IS_PRODUCTION and db_backend != "postgres":
        logger.error("Health check: Production requires Postgres but backend is %s", db_backend)
    
    return {
        "ok": True,
        "status": "ok",
        "database": {
            "available": db_available,
            "connected": db_connected,
            "backend": db_backend
        }
    }


@app.get("/debug/email")
async def debug_email(request: Request) -> JSONResponse:
    """Debug endpoint for email configuration (production-safe).
    
    Returns Resend API and SMTP configuration status, PUBLIC_BASE_URL, and environment info.
    Does NOT leak secrets - only shows booleans and parsed port.
    """
    # Get unified email config
    email_config = get_email_config()
    
    # Check if FROM is in angle bracket format (e.g., "Name <email@domain.com>")
    from_is_angle_format = False
    if email_config["from_raw"] and "<" in email_config["from_raw"] and ">" in email_config["from_raw"]:
        from_is_angle_format = True
    
    # Get PUBLIC_BASE_URL
    public_base_url_value = get_env("PUBLIC_BASE_URL")
    public_base_url_present = bool(public_base_url_value)
    
    smtp_config = email_config["smtp_config"]
    
    return JSONResponse({
        "resend": {
            "present": email_config["resend_configured"]
        },
        "smtp": {
            "present": email_config["smtp_configured"],
            "host_present": smtp_config["host_present"],
            "user_present": smtp_config["user_present"],
            "pass_present": smtp_config["pass_present"],
            "from_present": smtp_config["from_present"],
            "port_value": smtp_config["port"],
            "missing_keys": smtp_config["missing_keys"]
        },
        "from": {
            "is_angle_format": from_is_angle_format,
            "present": bool(email_config["from_email"])
        },
        "public_base_url_present": public_base_url_present,
        "public_base_url_value": public_base_url_value,
        "env": {
            "ENV": ENV or "not set",
            "DEBUG": str(DEBUG),
            "IS_PRODUCTION": IS_PRODUCTION
        }
    })


@app.get("/debug/last-magic-link")
async def debug_last_magic_link(request: Request, email: Optional[str] = None) -> JSONResponse:
    """Secure debug endpoint to get last generated magic link for an email.
    
    Enabled when DEBUG=1 OR when X-Debug-Key header matches DEBUG_KEY environment variable.
    
    Args:
        email: Email address to look up the latest unexpired magic token for.
    
    Returns:
        {ok:true, magic_link:"https://.../auth/verify?token=..."} for most recent unexpired token
        {ok:false, detail:"not found"} if none
    """
    # Check if enabled: DEBUG=1 OR DEBUG_KEY is set
    debug_key = get_env("DEBUG_KEY")
    is_debug_mode = DEBUG or bool(debug_key)
    
    if not is_debug_mode:
        raise HTTPException(status_code=404, detail="Not found")
    
    # If DEBUG_KEY is set, require X-Debug-Key header
    if debug_key:
        provided_key = request.headers.get("X-Debug-Key", "")
        if not provided_key or provided_key != debug_key:
            raise HTTPException(status_code=403, detail="Invalid debug key")
    
    # Email is required
    if not email:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "detail": "Email parameter is required"}
        )
    
    email = email.strip().lower()
    if not email:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "detail": "Email parameter is required"}
        )
    
    # Get latest unexpired token from database
    token = await db.get_latest_magic_token_for_email(email)
    if token:
        # Verify token is not expired by checking expires_at
        now = int(time.time())
        token_valid = await db.check_magic_token_valid(token, now)
        if token_valid:
            # Build magic link URL
            base_url = get_public_base_url(request)
            magic_link = f"{base_url}/auth/verify?token={token}"
            return JSONResponse({
                "ok": True,
                "magic_link": magic_link
            })
    
    return JSONResponse(
        status_code=404,
        content={"ok": False, "detail": "not found"}
    )


@app.get("/debug/send-test-email")
async def debug_send_test_email(request: Request, to: str) -> JSONResponse:
    """Test email endpoint - sends a simple test email (dev mode only, no secrets in logs).
    
    In production, returns 404.
    """
    if IS_PRODUCTION:
        raise HTTPException(status_code=404, detail="Not found")
    
    # Get SMTP config
    smtp_config = get_smtp_config()
    if not smtp_config["configured"]:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "detail": f"SMTP not configured. Missing: {', '.join(smtp_config['missing_keys'])}"}
        )
    
    # Send test email
    email_sent, error_msg = await send_email_via_smtp(
        to_email=to,
        subject="FormFillAI Test Email",
        body="<html><body><p>This is a test email from FormFillAI.</p><p>If you received this, SMTP is working correctly.</p></body></html>"
    )
    
    if email_sent:
        logger.info("Test email sent to %s", to)
        return JSONResponse({
            "ok": True,
            "message": f"Test email sent to {to}"
        })
    else:
        logger.error("Test email failed to %s: %s", to, error_msg)
        safe_error = error_msg[:200] if error_msg else "Failed to send test email"
        return JSONResponse(
            status_code=503,
            content={"ok": False, "detail": safe_error}
        )


@app.get("/debug/send-test-email")
async def debug_send_test_email(request: Request, to: str) -> JSONResponse:
    """Test email endpoint - sends a simple test email (dev mode only, no secrets in logs).
    
    In production, returns 404.
    """
    if IS_PRODUCTION:
        raise HTTPException(status_code=404, detail="Not found")
    
    # Get SMTP config
    smtp_config = get_smtp_config()
    if not smtp_config["configured"]:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "detail": f"SMTP not configured. Missing: {', '.join(smtp_config['missing_keys'])}"}
        )
    
    # Send test email
    email_sent, error_msg = await send_email_via_smtp(
        to_email=to,
        subject="FormFillAI Test Email",
        body="<html><body><p>This is a test email from FormFillAI.</p><p>If you received this, SMTP is working correctly.</p></body></html>"
    )
    
    if email_sent:
        logger.info("Test email sent to %s", to)
        return JSONResponse({
            "ok": True,
            "message": f"Test email sent to {to}"
        })
    else:
        logger.error("Test email failed to %s: %s", to, error_msg)
        safe_error = error_msg[:200] if error_msg else "Failed to send test email"
        return JSONResponse(
            status_code=503,
            content={"ok": False, "detail": safe_error}
        )


@app.get("/debug/auth")
async def debug_auth(request: Request) -> JSONResponse:
    """Debug endpoint for authentication issues (production-safe).
    
    Returns request info, cookie status, and database backend info.
    Does NOT leak full tokens/cookies - only shows truncated values.
    """
    # Get request info
    host = request.headers.get("host", "unknown")
    scheme = request.url.scheme
    x_forwarded_proto = request.headers.get("X-Forwarded-Proto", "not set")
    
    # Check session cookie
    session_cookie = request.cookies.get("session")
    session_present = bool(session_cookie)
    session_prefix = session_cookie[:8] if session_cookie and len(session_cookie) >= 8 else None
    
    # Get database backend info
    db_backend = db.get_db_backend_name() or "unknown"
    database_url_set = bool(os.getenv("DATABASE_URL"))
    
    # Try to look up session if present
    session_found = False
    if session_cookie:
        try:
            session = await db.get_session(session_cookie)
            session_found = session is not None
        except Exception as e:
            logger.warning("debug_auth: error looking up session: %s", e)
    
    return JSONResponse({
        "request": {
            "host": host,
            "scheme": scheme,
            "x_forwarded_proto": x_forwarded_proto
        },
        "cookie": {
            "session_present": session_present,
            "session_prefix": session_prefix  # Only first 8 chars, safe to log
        },
        "database": {
            "backend": db_backend,
            "database_url_set": database_url_set,
            "session_found": session_found
        },
        "environment": {
            "ENV": ENV or "not set",
            "DEBUG": DEBUG,
            "IS_PRODUCTION": IS_PRODUCTION
        }
    })


@app.get("/debug/set-test-cookie")
async def debug_set_test_cookie(request: Request) -> RedirectResponse:
    """Debug endpoint to test cookie setting (no DevTools needed).
    
    Sets a simple non-httponly cookie "cookie_test=1" and redirects to "/".
    This lets us verify cookies are working in the browser.
    """
    # Detect HTTPS via X-Forwarded-Proto (Railway/proxy)
    scheme = request.url.scheme
    x_forwarded_proto = request.headers.get("X-Forwarded-Proto", "").lower()
    is_https = (x_forwarded_proto == "https") or (scheme == "https")
    
    # Create redirect response
    response = RedirectResponse(url="/", status_code=303)
    
    # Set test cookie (non-httponly so we can see it in browser)
    response.set_cookie(
        key="cookie_test",
        value="1",
        httponly=False,  # Non-httponly so visible in browser
        secure=is_https,
        samesite="lax",
        path="/",
        max_age=60 * 60 * 24,  # 1 day
    )
    
    logger.info("debug/set-test-cookie: secure=%s scheme=%s x_forwarded_proto=%s", 
                is_https, scheme, x_forwarded_proto)
    
    return response


@app.get("/debug/auth-status")
async def debug_auth_status(request: Request) -> JSONResponse:
    """Simplified debug endpoint for authentication status (dev mode only).
    
    Enabled only when ENV!=production OR DEBUG=1.
    In production, returns 404.
    
    Returns:
        {
            "authenticated": bool,
            "cookie_present": bool,
            "db_session_found": bool,
            "backend": str
        }
    """
    if IS_PRODUCTION:
        raise HTTPException(status_code=404, detail="Not found")
    
    # Check session cookie
    session_cookie = request.cookies.get("session")
    cookie_present = bool(session_cookie)
    
    # Get database backend
    db_backend = db.get_db_backend_name() or "unknown"
    
    # Try to look up session if present
    db_session_found = False
    authenticated = False
    if session_cookie:
        try:
            session = await db.get_session(session_cookie)
            db_session_found = session is not None
            authenticated = db_session_found
        except Exception as e:
            logger.warning("debug_auth_status: error looking up session: %s", e)
    
    return JSONResponse({
        "authenticated": authenticated,
        "cookie_present": cookie_present,
        "db_session_found": db_session_found,
        "backend": db_backend
    })


if __name__ == "__main__":
    # Read PORT from environment (Railway provides this as an environment variable)
    # Default to 8000 for local development
    # NOTE: Railway sets PORT as an env var, not a shell variable
    # This is why we read it here in Python, not via uvicorn CLI --port $PORT
    port = int(os.environ.get("PORT", 8000))
    
    # Start uvicorn programmatically
    # This ensures PORT is read as an integer, not a string
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        proxy_headers=True
    )

