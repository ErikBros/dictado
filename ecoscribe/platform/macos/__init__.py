"""macOS implementations of Ecoscribe's Windows-only pieces (uat.2).

The shared module (ecoscribe/deliver.py, ipc.py, ...) imports the names from here when
sys.platform == "darwin" and from ecoscribe/platform/windows otherwise (dictado-gkt). Same names,
same behavior contract; nothing here is imported on Windows.
"""
