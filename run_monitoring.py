#!/usr/bin/env python3
"""
Convenience script to run the Polymarket monitoring system.

This script launches the monitoring service from the monitoring directory.
"""

import sys
import os

# Add monitoring directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'monitoring'))

# Import and run main
from main import main

if __name__ == "__main__":
    main()
