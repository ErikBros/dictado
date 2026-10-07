# Run Windows Python on this tree from WSL. Source me:  . tools/winpy.sh   then:  wtest "$APP_W\\tests" -q
# WINPY defaults to the python.org 3.12 install of the Windows user; override it before sourcing if needed.
_winlocal=$(wslpath "$(cmd.exe /c 'echo %LOCALAPPDATA%' 2>/dev/null | tr -d '\r')")
export WINPY=${WINPY:-$_winlocal/Programs/Python/Python312/python.exe}
export APP_W=$(wslpath -w "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)")
# Windows git refuses this \\wsl.localhost checkout ("dubious ownership"), which silently skipped the
# git-based privacy tests: trust it for these runs only, never in the PC's git config.
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0="*"
export WSLENV="${WSLENV:+$WSLENV:}GIT_CONFIG_COUNT:GIT_CONFIG_KEY_0:GIT_CONFIG_VALUE_0"
wpy() { (cd /mnt/c && "$WINPY" "$@"); }
wtest() { (cd /mnt/c && timeout "${WTIMEOUT:-900}" "$WINPY" -m pytest -p no:cacheprovider --rootdir "$APP_W" -c "$APP_W\\pytest.ini" "$@"); }
