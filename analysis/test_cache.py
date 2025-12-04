#!/usr/bin/env python3
"""
Quick test script to verify correlation caching is working.

Usage:
    python analysis/test_cache.py
"""

import os
import json
from datetime import datetime

def check_cache_status():
    """Check status of correlation cache."""

    print("\n" + "="*70)
    print("  CORRELATION CACHE STATUS CHECK")
    print("="*70 + "\n")

    cache_file = os.path.join('reports', 'correlation_cache.json')

    # Check if cache exists
    if not os.path.exists(cache_file):
        print("❌ Cache file does NOT exist")
        print(f"   Expected location: {cache_file}")
        print("\n💡 Run this to create cache:")
        print("   python analysis/correlation_matrix.py")
        return

    print(f"✅ Cache file exists: {cache_file}")

    # Check file size
    file_size = os.path.getsize(cache_file)
    print(f"   File size: {file_size:,} bytes ({file_size/1024:.1f} KB)")

    # Check file age
    file_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
    file_age = datetime.now() - file_time
    hours = file_age.seconds // 3600
    minutes = (file_age.seconds // 60) % 60
    print(f"   Created: {file_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Age: {file_age.days} days, {hours}h {minutes}m")

    # Check if expired (default 24 hours)
    if file_age.total_seconds() > 24 * 3600:
        print(f"   ⚠️  Cache is EXPIRED (older than 24 hours)")
        print(f"      Will be recalculated on next run")
    else:
        print(f"   ✅ Cache is VALID (younger than 24 hours)")

    # Try to load and validate JSON
    print("\n📊 Cache contents:")
    try:
        with open(cache_file, 'r') as f:
            data = json.load(f)

        print(f"   ✅ Valid JSON format")
        print(f"   - High correlation pairs: {len(data.get('high_correlation_pairs', []))}")
        print(f"   - Correlation clusters: {len(data.get('correlation_clusters', []))}")
        print(f"   - Independence scores: {len(data.get('independence_scores', {}))}")
        print(f"   - Total traders: {data.get('total_traders', 'N/A')}")
        print(f"   - Total pairs calculated: {data.get('total_pairs_calculated', 'N/A')}")
        print(f"   - Timestamp: {data.get('timestamp', 'N/A')}")

        # Check for required fields
        required_fields = ['high_correlation_pairs', 'timestamp']
        missing_fields = [f for f in required_fields if f not in data]

        if missing_fields:
            print(f"\n   ⚠️  Missing required fields: {missing_fields}")
        else:
            print(f"\n   ✅ All required fields present")

    except json.JSONDecodeError as e:
        print(f"   ❌ Invalid JSON format: {e}")
    except Exception as e:
        print(f"   ❌ Error loading cache: {e}")

    # Recommendations
    print("\n💡 Next steps:")
    if file_age.total_seconds() > 24 * 3600:
        print("   1. Cache is expired - run correlation_matrix.py to refresh")
        print("      python analysis/correlation_matrix.py")
    else:
        print("   1. Cache is valid - copy_trade_detector.py will use it")
        print("      python analysis/copy_trade_detector.py")

    print("   2. To force recalculation (ignore cache):")
    print("      python analysis/copy_trade_detector.py --force-recalc")

    print("   3. To set custom cache expiration (e.g., 48 hours):")
    print("      python analysis/copy_trade_detector.py --max-cache-age 48")

    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    check_cache_status()
