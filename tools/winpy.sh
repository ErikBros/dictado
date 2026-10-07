# Run Windows Python on this tree from WSL. Source me:  . tools/winpy.sh   then:  wtest "$APP_W\\tests" -q
# WINPY defaults to the python.org 3.12 install of the Windows user; override it before sourcing if needed.
_winlocal=$(wslpath "$(cmd.exe /c 'echo %LOCALAPPDATA%' 2>/dev/null | tr -d '\r')")
export WINPY=${WINPY:-$_winlocal/Programs/Python/Python312/python.exe}
export APP_W=$(wslpath -w "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)")
wpy() { (cd /mnt/c && "$WINPY" "$@"); }
wtest() { (cd /mnt/c && timeout "${WTIMEOUT:-900}" "$WINPY" -m pytest -p no:cacheprovider --rootdir "$APP_W" -c "$APP_W\\pytest.ini" "$@"); }
