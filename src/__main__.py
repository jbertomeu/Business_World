"""Allow running as: python -m src <command>"""
# Wave ν+4: force UTF-8 on stdout/stderr so non-cp1252 unicode (arrows,
# checkmarks, em-dash variants, etc.) doesn't crash the run on Windows
# consoles. Without this, a single stray '→' in a print() will
# UnicodeEncodeError out of an 88-minute Q1.
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    # Older Python or non-text stream — best-effort
    pass

from .cli import main
main()
