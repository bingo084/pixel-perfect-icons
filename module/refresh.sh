#!/system/bin/sh
# Delete only regenerable icon-cache files. Never clear launcher app data.
exec 2>&1
MODDIR=${0%/*}
MODE=${1:-manual}
LAUNCHER=com.google.android.apps.nexuslauncher
DBDIR=/data/user/0/com.google.android.apps.nexuslauncher/databases
STATEDIR=/data/adb/pixel-clean-icons

case "$MODE" in manual|auto) ;; *) echo 'Usage: refresh.sh manual|auto'; exit 1 ;; esac
if [ "$MODE" = auto ] && [ ! -f "$MODDIR/.refresh-pending" ]; then
    exit 0
fi
if [ "$MODE" = auto ] && { [ -f "$MODDIR/disable" ] || [ -f "$MODDIR/remove" ]; }; then
    exit 0
fi
[ "$(id -u)" = 0 ] || { echo 'Root is required.'; exit 1; }
[ "$(getprop ro.product.device)" = komodo ] && [ "$(getprop ro.build.version.sdk)" = 37 ] || {
    echo 'This build requires komodo / API 37.'; exit 1;
}

# This is a one-time job after installation/update, not a permanent watcher.
# Leave the pending flag intact if unlock takes more than 30 minutes.
attempt=0
while [ "$(am get-started-user-state 0 2>/dev/null)" != RUNNING_UNLOCKED ]; do
    [ "$MODE" = auto ] || { echo 'Unlock the owner user before refreshing.'; exit 1; }
    [ -f "$MODDIR/.refresh-pending" ] || exit 0
    [ ! -f "$MODDIR/disable" ] && [ ! -f "$MODDIR/remove" ] || exit 0
    [ "$attempt" -lt 180 ] || { echo 'Unlock wait expired; refresh remains pending.'; exit 1; }
    attempt=$((attempt + 1))
    sleep 10
done
[ "$(am get-current-user 2>/dev/null)" = 0 ] || { echo 'Switch to the owner user before refreshing.'; exit 1; }
home=$(cmd package resolve-activity --brief --user 0 -a android.intent.action.MAIN -c android.intent.category.HOME 2>/dev/null)
printf '%s\n' "$home" | grep -Fq "$LAUNCHER/" || { echo 'Pixel Launcher is not the default home.'; exit 1; }

umask 077
[ ! -L "$STATEDIR" ] || { echo 'Refusing a symlink state directory.'; exit 1; }
mkdir -p "$STATEDIR" || exit 1
chmod 700 "$STATEDIR" || exit 1
for name in refresh.lock last-refresh.log last-check.log; do
    [ ! -L "$STATEDIR/$name" ] || { echo 'Refusing a symlink state file.'; exit 1; }
done
exec 9>"$STATEDIR/refresh.lock"
# Android mksh closes extra descriptors in child processes. Pass the shared open
# file description through stdin so the parent continues to hold the lock.
flock -n 0 <&9 || { echo 'A refresh is already running.'; exit 1; }
if [ "$MODE" = auto ] && [ ! -f "$MODDIR/.refresh-pending" ]; then
    exit 0
fi
if [ "$MODE" = auto ] && { [ -f "$MODDIR/disable" ] || [ -f "$MODDIR/remove" ]; }; then
    exit 0
fi
: > "$STATEDIR/last-refresh.log"
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$STATEDIR/last-refresh.log"; }
log "Starting icon cache refresh: $MODE"
if [ -s "$MODDIR/numeric-targets.tsv" ] && ! sh "$MODDIR/numeric.sh" apply; then
    log 'Numeric mappings are not ready. Cache unchanged; refresh remains pending.'
    exit 1
fi
if check=$(sh "$MODDIR/check.sh" 2>&1); then
    check_ok=true
else
    check_ok=false
fi
printf '%s\n' "$check" | tail -c 32768 > "$STATEDIR/last-check.log"
if [ "$check_ok" != true ]; then
    printf '%s\n' "$check"
    log 'Overlays are not ready. Cache unchanged; refresh remains pending.'
    exit 1
fi

# Fixed allowlist: none of the launcher*.db layout databases can match.
[ ! -L "$DBDIR" ] || { log 'Refusing a symlink database directory.'; exit 1; }
has_cache=false
for name in app_icons.db app_icons.db-journal app_icons.db-wal app_icons.db-shm; do
    [ ! -L "$DBDIR/$name" ] || { log 'Refusing a symlink cache file.'; exit 1; }
    if [ -e "$DBDIR/$name" ]; then
        [ -f "$DBDIR/$name" ] || { log 'Unexpected cache file type.'; exit 1; }
        has_cache=true
    fi
done
if [ "$has_cache" = true ]; then
    was_home=false
    if dumpsys activity activities | grep -E '(topResumedActivity|mResumedActivity)' | grep -Fq "$LAUNCHER/"; then
        was_home=true
    fi
    log 'Stopping Pixel Launcher to close its icon cache.'
    am force-stop --user 0 "$LAUNCHER" || { log 'Launcher stop failed; cache unchanged.'; exit 1; }
    if pidof "$LAUNCHER" >/dev/null 2>&1; then
        log 'Launcher is still running; cache unchanged.'
        exit 1
    fi
    # Recheck after stopping the process before removing the cache and sidecars.
    for name in app_icons.db app_icons.db-journal app_icons.db-wal app_icons.db-shm; do
        [ ! -L "$DBDIR/$name" ] || { log 'Cache path changed; refresh stopped.'; exit 1; }
    done
    rm -f "$DBDIR/app_icons.db" "$DBDIR/app_icons.db-journal" "$DBDIR/app_icons.db-wal" "$DBDIR/app_icons.db-shm" || {
        log 'Cache removal failed; refresh remains pending.'; exit 1;
    }
    if [ "$was_home" = true ]; then
        am start --user 0 -a android.intent.action.MAIN -c android.intent.category.HOME >/dev/null 2>&1 || {
            log 'Cache cleared. Return home to rebuild; automatic refresh remains pending.'; exit 1;
        }
    fi
fi
rm -f "$MODDIR/.refresh-pending" || { log 'Could not clear pending flag.'; exit 1; }
log 'SUCCESS: icon cache invalidated. Return home to rebuild. Layout and app data preserved.'
