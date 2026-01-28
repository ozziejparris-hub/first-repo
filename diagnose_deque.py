"""
Comprehensive diagnostic to find why deque optimization isn't working.
"""
import sys
import inspect
import os
from monitoring.position_tracker import PositionTracker

print("=" * 70)
print("  DEQUE OPTIMIZATION DIAGNOSTIC")
print("=" * 70)

# Step 1: Find which file is being imported
file_path = inspect.getfile(PositionTracker)
abs_path = os.path.abspath(file_path)
print(f"\n[1] Position tracker file being used:")
print(f"    {abs_path}")

# Step 2: Check if file exists
if os.path.exists(abs_path):
    print(f"    ✅ File exists")

    # Step 3: Read the file
    with open(abs_path, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.split('\n')

    print(f"    ✅ File readable ({len(lines)} lines)")

    # Step 4: Check for deque optimization markers
    print(f"\n[2] Checking for deque optimization:")

    has_deque_import = 'from collections import deque' in content
    has_deque_init = 'deque()' in content
    has_popleft = 'popleft()' in content
    has_old_pop = 'pop(0)' in content

    print(f"    Import 'from collections import deque': {'✅ YES' if has_deque_import else '❌ NO'}")
    print(f"    Initialize with 'deque()': {'✅ YES' if has_deque_init else '❌ NO'}")
    print(f"    Use 'popleft()': {'✅ YES' if has_popleft else '❌ NO'}")
    print(f"    Still has 'pop(0)' (OLD): {'❌ YES - BAD!' if has_old_pop else '✅ NO - GOOD'}")

    # Step 5: Show critical lines
    print(f"\n[3] Critical lines inspection:")

    # Find import section (first 50 lines)
    print(f"\n    === IMPORTS (lines 1-50) ===")
    for i, line in enumerate(lines[:50], 1):
        if 'import' in line.lower() and ('deque' in line or 'collections' in line):
            print(f"    Line {i:3d}: {line}")

    if not any('deque' in line for line in lines[:50]):
        print(f"    ❌ NO deque import found in first 50 lines")

    # Find _match_group method
    print(f"\n    === _match_group METHOD ===")
    in_match_group = False
    method_start = -1

    for i, line in enumerate(lines):
        if 'def _match_group' in line:
            in_match_group = True
            method_start = i
            print(f"    Found at line {i+1}")
            break

    if in_match_group:
        # Show lines 210-250 (typical location)
        print(f"\n    === Lines around queue initialization ===")
        for i in range(method_start, min(method_start + 50, len(lines))):
            line = lines[i]
            line_num = i + 1

            # Highlight important lines
            if 'open_buy_queue' in line and '=' in line:
                marker = "  👉 " if 'deque' in line else "  ⚠️  "
                print(f"{marker}Line {line_num:3d}: {line}")
            elif 'pop(0)' in line:
                print(f"  ⚠️  Line {line_num:3d}: {line}  ← PROBLEM: Should be popleft()")
            elif 'popleft' in line:
                print(f"  ✅ Line {line_num:3d}: {line}")

    # Step 6: Search for ALL pop(0) occurrences
    print(f"\n[4] Searching for ALL pop(0) occurrences:")
    pop_zero_lines = []
    for i, line in enumerate(lines, 1):
        if 'pop(0)' in line and not line.strip().startswith('#'):
            pop_zero_lines.append((i, line.strip()))

    if pop_zero_lines:
        print(f"    ❌ Found {len(pop_zero_lines)} instances of pop(0):")
        for line_num, line in pop_zero_lines:
            print(f"       Line {line_num:4d}: {line}")
    else:
        print(f"    ✅ No pop(0) found (good)")

    # Step 7: Count popleft occurrences
    print(f"\n[5] Searching for popleft() occurrences:")
    popleft_count = content.count('popleft()')
    print(f"    Found {popleft_count} instances of popleft()")

    if popleft_count == 0:
        print(f"    ❌ CRITICAL: No popleft() found - deque optimization NOT applied!")
    elif popleft_count == 1:
        print(f"    ✅ Expected: 1 instance found")
    else:
        print(f"    ⚠️  Unexpected: Multiple instances found")

    # Step 8: Show the exact queue operations
    print(f"\n[6] Queue operation summary:")
    print(f"    Append operations: {content.count('open_buy_queue.append(')}")
    print(f"    Pop operations (old): {content.count('open_buy_queue.pop(0)')}")
    print(f"    Popleft operations (new): {content.count('open_buy_queue.popleft(')}")

else:
    print(f"    ❌ File NOT found!")

# Step 9: Search for ALL position_tracker.py files
print(f"\n[7] Searching for ALL position_tracker.py files:")
search_root = os.path.abspath('.')
print(f"    Searching in: {search_root}")

found_files = []
for root, dirs, files in os.walk(search_root):
    if 'position_tracker.py' in files:
        full_path = os.path.join(root, 'position_tracker.py')
        found_files.append(full_path)

if len(found_files) > 1:
    print(f"    ⚠️  WARNING: Found {len(found_files)} position_tracker.py files:")
    for f in found_files:
        is_active = "  ← ACTIVE" if os.path.abspath(f) == abs_path else ""
        print(f"       {f}{is_active}")
else:
    print(f"    ✅ Only 1 file found (good)")

# Step 10: Final diagnosis
print(f"\n" + "=" * 70)
print(f"  DIAGNOSIS")
print(f"=" * 70)

if has_popleft and not has_old_pop:
    print(f"✅ Deque optimization IS applied to the file")
    print(f"❓ But performance is still slow - different issue")
    print(f"\n   Next steps:")
    print(f"   1. Check if there's a different code path")
    print(f"   2. Verify match_trades_for_trader() calls _match_group()")
    print(f"   3. Look for position matching bypass logic")
elif has_old_pop and not has_popleft:
    print(f"❌ Deque optimization NOT applied")
    print(f"   File still uses pop(0) instead of popleft()")
    print(f"\n   FIX: Apply deque optimization to this file:")
    print(f"   {abs_path}")
elif not has_deque_import:
    print(f"❌ Deque not imported")
    print(f"   Missing: from collections import deque")
    print(f"\n   FIX: Add import and apply optimization")
else:
    print(f"❓ Ambiguous state - both pop(0) and popleft() found")
    print(f"   Need manual inspection")

print(f"\n" + "=" * 70)
