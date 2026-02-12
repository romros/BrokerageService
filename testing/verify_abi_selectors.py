#!/usr/bin/env python3


from pathlib import Path
import sys


"""
Verify ABI Selectors - Standalone script to verify official selectors
Verifies that computed selectors match official SDK ABI.
"""

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.venues.gtrade.abi_encoder import verify_selectors

def main():
    print("\n" + "="*60)
    print("Verifying ABI Selectors")
    print("="*60 + "\n")

    success = verify_selectors()

    print("\n" + "="*60)
    if success:
        print("✅ All selectors verified successfully!")
        print("="*60 + "\n")
        return 0
    else:
        print("❌ Selector verification failed!")
        print("="*60 + "\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())
