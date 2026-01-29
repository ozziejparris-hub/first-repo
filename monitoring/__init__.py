"""
Polymarket monitoring package.

Core monitoring components for tracking geopolitical prediction markets.
"""

# CRITICAL: Single instance check at import time
# This prevents duplicate monitoring processes from even starting
import os
import sys
from pathlib import Path

_pid_file = Path('data/.monitoring.pid')

if _pid_file.exists():
    try:
        _old_pid = int(_pid_file.read_text().strip())

        # Check if process is running (lightweight check, no psutil yet)
        try:
            import psutil
            if psutil.pid_exists(_old_pid):
                try:
                    _proc = psutil.Process(_old_pid)
                    if _proc.is_running():
                        # Check if it's actually monitoring
                        _cmdline = ' '.join(_proc.cmdline())
                        if 'monitoring' in _cmdline and __name__ in _cmdline:
                            print(f"\n[ERROR] Monitoring already running (PID {_old_pid})")
                            print(f"[ERROR] Stop it first:")
                            print(f"[ERROR]   python scripts/kill_all.py")
                            print(f"[ERROR]   OR: taskkill /PID {_old_pid} /F\n")
                            sys.exit(1)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except ImportError:
            # psutil not available, skip check
            pass
    except (ValueError, FileNotFoundError):
        pass  # Corrupt PID file, will be handled later

# Clean up import-time variables
del _pid_file, Path
if '_old_pid' in locals():
    del _old_pid

from .database import Database
from .polymarket_client import PolymarketClient
from .trader_analyzer import TraderAnalyzer

# Import components with external dependencies conditionally
__all__ = [
    'Database',
    'PolymarketClient',
    'TraderAnalyzer',
]

try:
    from .telegram_bot import TelegramNotifier
    __all__.append('TelegramNotifier')
except ImportError:
    pass

try:
    from .monitor import PolymarketMonitor
    __all__.append('PolymarketMonitor')
except ImportError:
    pass
