"""
Admin code: the numeric code that unlocks admin-only actions. Kept here so
every screen checks the same one (Settings' Admin button, the Z report's
"continue without a backup").
"""
import hmac

ADMIN_CODE = "2060"


def check_admin_code(code: str | None) -> bool:
    """Whether `code` is the admin code (constant-time comparison)."""
    return code is not None and hmac.compare_digest(code.encode("utf-8"), ADMIN_CODE.encode("utf-8"))
