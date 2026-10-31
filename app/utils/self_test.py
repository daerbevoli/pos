"""
Build self-test: `SuperPOS.exe --self-test` (or `python main.py --self-test`).

The PyInstaller build only bundles what it can see imported. Libraries that
load modules or data files dynamically (reportlab's barcodes, escpos's
capabilities.json, libusb's pkg_about/metadata/DLLs) start fine and then crash
the first time that feature is used, e.g. at the first receipt. This exercises
each of those code paths once, without touching the database or opening any
device, so a broken build fails here instead of at the till. Results go to the
log; the exit code is 0 only if every check passed. The release workflow runs
it on every build.
"""
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


def _usb_backend():
    from app.core.receipt_service import _get_backend
    if _get_backend() is None:
        raise RuntimeError("libusb backend could not be loaded")


def _usb_enumerate():
    # Lists attached devices (none on a build server); never opens one.
    import usb.core
    from app.core.receipt_service import _get_backend
    list(usb.core.find(find_all=True, backend=_get_backend()))


def _escpos():
    from escpos.exceptions import Error  # noqa: F401
    from escpos.printer import Usb  # noqa: F401  (loads capabilities.json)


def _label_sheet_pdf():
    from app.core.label_sheet_service import LABEL_LAYOUTS, build_label_sheet_pdf
    layout = next(iter(LABEL_LAYOUTS))
    with tempfile.TemporaryDirectory() as tmp:
        # One GTIN and one Code 128 code: each symbology is a separate module.
        for barcode in ("5400000000003", "SELFTEST-1"):
            path = os.path.join(tmp, f"{barcode}.pdf")
            build_label_sheet_pdf(path, layout, barcode, name="Self-test")
            if os.path.getsize(path) == 0:
                raise RuntimeError(f"empty PDF for {barcode}")


def _backup_crypto():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    box = AESGCM(key)
    if box.decrypt(nonce, box.encrypt(nonce, b"self-test", None), None) != b"self-test":
        raise RuntimeError("AES-GCM round trip failed")


def _erp_http():
    import requests  # noqa: F401
    import certifi  # noqa: F401  (CA bundle requests uses for HTTPS)
    if not os.path.exists(requests.certs.where()):
        raise RuntimeError("CA certificate bundle missing")


CHECKS = [
    ("USB backend (libusb DLL)", _usb_backend),
    ("USB device enumeration", _usb_enumerate),
    ("Receipt printer driver (escpos)", _escpos),
    ("Label sheet PDF (reportlab barcodes)", _label_sheet_pdf),
    ("Backup encryption (cryptography)", _backup_crypto),
    ("ERP HTTPS (requests, CA bundle)", _erp_http),
]


def run_self_test() -> int:
    """Run every check, log each result; return the process exit code."""
    failed = 0
    for name, check in CHECKS:
        try:
            check()
            logger.info("SELF-TEST ok:   %s", name)
        except Exception:
            failed += 1
            logger.exception("SELF-TEST FAIL: %s", name)
    logger.info("SELF-TEST %s: %d/%d checks passed",
                "PASSED" if not failed else "FAILED", len(CHECKS) - failed, len(CHECKS))
    return 1 if failed else 0
