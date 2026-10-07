"""PyInstaller entry point: Ecoscribe.exe"""
import multiprocessing
import sys

from ecoscribe.__main__ import main

if __name__ == "__main__":
    # a frozen app re-runs itself for multiprocessing helpers (the resource tracker on macOS):
    # those must not reach Ecoscribe's argument parser
    multiprocessing.freeze_support()
    sys.exit(main())
