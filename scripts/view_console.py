#!/usr/bin/env python3
"""
View monitoring console output in real-time.

Usage:
    py scripts/view_console.py               # Show last 50 lines
    py scripts/view_console.py --tail 100    # Show last 100 lines
    py scripts/view_console.py --follow      # Follow in real-time (like tail -f)
    py scripts/view_console.py -f            # Short form of --follow
"""

import sys
import time
from pathlib import Path

def tail_file(filepath, lines=50, follow=False):
    """Tail a file like Unix tail command."""

    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            # Get last N lines
            content = f.readlines()
            for line in content[-lines:]:
                print(line, end='')

            if follow:
                # Follow mode - watch for new lines
                print("\n" + "="*70)
                print("Following log file in real-time (Ctrl+C to stop)")
                print("="*70 + "\n")
                f.seek(0, 2)  # Seek to end

                try:
                    while True:
                        line = f.readline()
                        if line:
                            print(line, end='')
                            sys.stdout.flush()
                        else:
                            time.sleep(0.1)
                except KeyboardInterrupt:
                    print("\n\n[Stopped following log file]")

    except FileNotFoundError:
        print(f"ERROR: Log file not found: {filepath}")
        print("\nMonitoring may not have started yet, or console redirect is disabled.")
        print("\nTo start monitoring:")
        print("  py -m monitoring.main")
        sys.exit(1)

    except Exception as e:
        print(f"ERROR: Failed to read log file: {e}")
        sys.exit(1)

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='View monitoring console output',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  py scripts/view_console.py              # Show last 50 lines
  py scripts/view_console.py --tail 100   # Show last 100 lines
  py scripts/view_console.py --follow     # Follow in real-time
  py scripts/view_console.py -f           # Short form
        """
    )

    parser.add_argument('--tail', type=int, default=50,
                       help='Number of lines to show (default: 50)')
    parser.add_argument('--follow', '-f', action='store_true',
                       help='Follow log file in real-time (like tail -f)')

    args = parser.parse_args()

    # Console log path
    log_path = Path('logs/monitoring_console.log')

    print(f"Reading: {log_path}")
    print("="*70 + "\n")

    tail_file(log_path, lines=args.tail, follow=args.follow)
