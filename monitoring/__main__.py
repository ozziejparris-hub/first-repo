#!/usr/bin/env python3
"""
Polymarket Monitoring System - Standard Entry Point

Run with: python -m monitoring

This is the standard, official way to start the monitoring system.
It runs in telegram-safe mode (no messages from monitoring, only from observer).
"""

import asyncio
import sys
from pathlib import Path

# Ensure project root in path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the telegram-safe main
from monitoring.main_telegram_safe import main

if __name__ == '__main__':
    asyncio.run(main())
