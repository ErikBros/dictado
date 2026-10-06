"""macOS implementations of Dictado's Windows-only pieces (uat.2).

Each Windows module keeps its code and, at the bottom, swaps in the names from here when
sys.platform == "darwin". Same names, same behavior contract; nothing here is imported on Windows.
"""
