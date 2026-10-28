"""
Admin code: the numeric code that unlocks admin-only actions. Kept here so
every screen checks the same one (Settings' Admin button, the Z report's
"continue without a backup"). Stored in the `admin_code` setting, changed
by an admin from Settings; DEFAULT_ADMIN_CODE until then.
"""
import hmac
import logging

from app.core.database import get_session
from app.core.settings_service import SettingsService

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_CODE = "2060"
ADMIN_CODE_KEY = "admin_code"
ADMIN_CODE_MIN_LENGTH = 4


def _current_code() -> str:
    with get_session() as session:
        return SettingsService.get(session, ADMIN_CODE_KEY) or DEFAULT_ADMIN_CODE


def check_admin_code(code: str | None) -> bool:
    """Whether `code` is the admin code (constant-time comparison)."""
    return code is not None and hmac.compare_digest(code.encode("utf-8"), _current_code().encode("utf-8"))


def admin_code_problem(code: str) -> str | None:
    """Why `code` can't be the new admin code, or None if it can."""
    if not code.isdigit():
        return "The admin code can only contain digits."
    if len(code) < ADMIN_CODE_MIN_LENGTH:
        return f"The admin code needs at least {ADMIN_CODE_MIN_LENGTH} digits."
    return None


def set_admin_code(code: str):
    """Saves a new admin code; check admin_code_problem() first."""
    problem = admin_code_problem(code)
    if problem:
        raise ValueError(problem)
    with get_session() as session:
        SettingsService.set(session, ADMIN_CODE_KEY, code)
    logger.info("Admin code changed")
