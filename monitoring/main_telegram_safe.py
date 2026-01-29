#!/usr/bin/env python3
"""
Polymarket Monitoring System - Telegram Rate Limit Safe Version

This version:
- NO Telegram messages from monitoring (observer handles all notifications)
- Position tracking ALWAYS enabled
- Enhanced logging for system observer
- Activity timestamp updates for health checks
- No rate limit hangs

Usage:
    python monitoring/main_telegram_safe.py
"""

import asyncio
import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/monitoring.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


async def main():
    """
    Main entry point for Telegram-safe monitoring.

    This version NEVER sends Telegram messages - all notifications
    are handled by the system observer.
    """

    print("\n" + "="*70)
    print("  TELEGRAM-SAFE POLYMARKET MONITORING")
    print("  NO Telegram messages from monitoring")
    print("  Position tracking: ENABLED")
    print("  All notifications via System Observer")
    print("="*70 + "\n")

    # Single instance enforcement - check if monitoring already running
    pid_file = Path('data/.monitoring.pid')
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())

            # Check if process is actually running
            import psutil
            if psutil.pid_exists(old_pid):
                try:
                    proc = psutil.Process(old_pid)
                    if proc.is_running():
                        print(f"\n[ERROR] Monitoring already running (PID {old_pid})")
                        print(f"[ERROR] Stop existing instance first:")
                        print(f"[ERROR]   Windows: taskkill /PID {old_pid} /F")
                        print(f"[ERROR]   Linux:   kill {old_pid}")
                        print(f"[ERROR] Or use: python scripts/kill_all.py")
                        sys.exit(1)
                except psutil.NoSuchProcess:
                    pass  # Process died, will remove stale PID file below
        except (ValueError, FileNotFoundError):
            pass  # Corrupt PID file, will overwrite

        # Remove stale PID file
        print(f"[CLEANUP] Removing stale PID file")
        pid_file.unlink()

    # Get API keys
    polymarket_api_key = os.getenv('POLYMARKET_API_KEY')
    if not polymarket_api_key:
        logger.error("POLYMARKET_API_KEY not found in environment")
        sys.exit(1)

    # Import here to avoid circular imports
    from monitoring.monitor import PolymarketMonitor

    # Create monitor - Telegram completely disabled (no parameters needed)
    # All notifications handled by System Observer
    monitor = PolymarketMonitor(
        polymarket_api_key=polymarket_api_key,
        check_interval=900,  # 15 minutes
        ai_agent=None
    )

    # Telegram is always disabled (hardcoded in Monitor class)
    print("[OK] Monitoring initialized - Telegram disabled by design")

    logger.info("Starting monitoring (Telegram-safe mode)")
    logger.info("Position tracking: ENABLED")
    logger.info("Check interval: 15 minutes")

    # Write PID file for System Observer to find this process
    pid_file.parent.mkdir(exist_ok=True)
    pid_file.write_text(str(os.getpid()))
    print(f"[OK] PID file created: {pid_file} (PID: {os.getpid()})")
    logger.info(f"PID file created: {pid_file}")

    try:
        # Start monitoring loop
        await monitor.start()

    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user")
        print("\n[SHUTDOWN] Monitoring stopped by user")

    except Exception as e:
        logger.error(f"Monitoring error: {e}", exc_info=True)
        print(f"\n[ERROR] Monitoring failed: {e}")
        raise

    finally:
        await monitor.stop()

        # Clean up PID file
        if pid_file.exists():
            pid_file.unlink()
            logger.info("PID file cleaned up")


if __name__ == '__main__':
    asyncio.run(main())
