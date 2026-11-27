"""Alias: python scripts/inspect_dataset.py --data ... --belt-depth-mm 350 --out ..."""
import sys
from potato3d.cli import main

if __name__ == "__main__":
    sys.argv.insert(1, "inspect")
    main()
