"""
Polymarket monitoring package.

Core monitoring components for tracking geopolitical prediction markets.
"""

# CRITICAL: Single instance check at import time
# BUT ONLY when actually running monitoring (not when importing for System Observer)
import os
import sys
from pathlib import Path

# Detect if we're actually starting monitoring vs just importing the package
_is_monitoring_run = False

# Check if we're being run as the monitoring module
if 'monitoring.__main__' in sys.modules or __name__ == '__main__':
    _is_monitoring_run = True
elif len(sys.argv) > 0:
    # Check command line arguments
    _cmd = ' '.join(sys.argv).lower()
    # We're starting monitoring if:
    # - Command contains 'monitoring' AND
    # - Command does NOT contain 'observer'
    if 'monitoring' in _cmd and 'observer' not in _cmd:
        _is_monitoring_run = True

# Only enforce single instance if we're actually starting monitoring
if _is_monitoring_run:
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
                            # Check if it's actually monitoring (not observer)
                            _cmdline = ' '.join(_proc.cmdline()).lower()
                            if 'monitoring' in _cmdline and 'observer' not in _cmdline:
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
if '_pid_file' in locals():
    del _pid_file
del Path, _is_monitoring_run
if '_old_pid' in locals():
    del _old_pid
if '_cmd' in locals():
    del _cmd
if '_cmdline' in locals():
    del _cmdline

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
