#!/system/bin/sh
# Maintain only this module's two reviewed idmaps. Never changes application APKs.
exec 2>&1
MODDIR=${0%/*}
MODE=${1:-check}
REQUESTED=${2:-}
STATEDIR=/data/adb/pixel-clean-icons
case "$MODE" in apply|check) ;; *) exit 2 ;; esac
[ -s "$MODDIR/numeric-targets.tsv" ] || exit 0
[ "$(id -u)" = 0 ] || exit 2
[ "$(getprop ro.product.device)" = komodo ] && [ "$(getprop ro.build.version.sdk)" = 37 ] || exit 2
[ -f "$MODDIR/numeric-icons.jar" ] || exit 2
TAB=$(printf '\t')

helper() {
    CLASSPATH="$MODDIR/numeric-icons.jar" timeout 20s app_process -Xmx64m /system/bin NumericIcons "$@"
}

one() (
    package=$1 expected=$2 overlay=$3 seed=$4 target=$5 crc=$6
    printf '%s\n' "$package" | grep -Eq '^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$' || exit 2
    [ "$overlay" = "local.pixelcleanicons.$(printf '%s' "$package" | tr '[:upper:].' '[:lower:]_')" ] || exit 2
    for resource in "$seed" "$target"; do
        printf '%s\n' "$resource" | grep -Eq '^0x7f[0-9a-f]{6}$' || exit 2
    done
    printf '%s\n' "$crc" | grep -Eq '^[0-9a-f]{8}$' || exit 2
    version=$(dumpsys package "$package" | sed -n 's/.*versionCode=\([0-9][0-9]*\).*/\1/p' | head -n 1)
    [ "$version" = "$expected" ] || { echo "Version changed: $package"; exit 1; }
    paths=$(pm path "$package") || exit 2
    base=
    for line in $paths; do
        path=${line#package:}
        case "$path" in /data/app/*/base.apk) base=$path ;; esac
    done
    [ -n "$base" ] && [ -f "$base" ] || exit 2
    idmap="/data/resource-cache/system_ext@overlay@$overlay.apk@idmap"
    overlay_apk="/system_ext/overlay/$overlay.apk"
    [ -f "$idmap" ] && [ ! -L "$idmap" ] && [ -f "$overlay_apk" ] || exit 2
    set -- "$idmap" "$seed" "$target" "$base" "$overlay_apk" "$crc"
    for line in $paths; do
        path=${line#package:}
        case "$path" in /data/app/*/split_*.apk) set -- "$@" "$path" ;; esac
    done
    if [ "$MODE" = check ]; then
        current=$(cmd package resolve-activity --user 0 -a android.intent.action.MAIN -c android.intent.category.LAUNCHER "$package" |
            sed -n 's/.* icon=\(0x[0-9a-fA-F]*\) .*/\1/p' | head -n 1 | tr '[:upper:]' '[:lower:]')
        [ "$current" = "$target" ] || { echo "Launcher entry is not covered: $package ($current)"; exit 1; }
        helper check "$@"
        exit $?
    fi
    # The ordinary boot case is a no-op if the verified mapping is already correct.
    if helper check "$@" >/dev/null 2>&1; then
        echo "Mapping already correct: $package"
        exit 0
    fi
    # Remove only abandoned temporaries in this module's reserved per-overlay prefix.
    for stale in "/data/resource-cache/.pixel-clean-icons-map-$overlay."*; do
        [ -f "$stale" ] && [ ! -L "$stale" ] || continue
        rm -f "$stale" || exit 1
    done
    temporary=$(mktemp "/data/resource-cache/.pixel-clean-icons-map-$overlay.XXXXXX") || exit 1
    trap 'rm -f "$temporary"' 0
    cp -p "$idmap" "$temporary" || exit 1
    helper patch "$idmap" "$temporary" "$seed" "$target" "$base" "$overlay_apk" "$crc" || exit 1
    context=$(ls -Zd "$idmap") || exit 1
    context=${context%% *}
    case "$context" in u:object_r:*:s0) ;; *) echo 'Unexpected idmap context'; exit 1 ;; esac
    chcon "$context" "$temporary" || exit 1
    # Check the complete new mapping before atomically replacing the owned cache file.
    shift
    helper check "$temporary" "$@" || exit 1
    mv -f "$temporary" "$idmap" || exit 1
    echo "Mapped ordinary launcher icon: $package"
)

process() {
    failed=0 found=false
    while IFS="$TAB" read -r package expected overlay seed target crc extra; do
        [ -n "$package" ] || continue
        [ -z "$REQUESTED" ] || [ "$package" = "$REQUESTED" ] || continue
        found=true
        if [ -n "$extra" ]; then
            failed=2
            continue
        fi
        one "$package" "$expected" "$overlay" "$seed" "$target" "$crc"
        code=$?
        if [ "$code" -eq 2 ]; then failed=2
        elif [ "$code" -ne 0 ] && [ "$failed" -eq 0 ]; then failed=1
        fi
    done < "$MODDIR/numeric-targets.tsv"
    [ "$found" = true ] || return 2
    return "$failed"
}

if [ "$MODE" = check ]; then
    process
    exit $?
fi
[ ! -f "$MODDIR/disable" ] && [ ! -f "$MODDIR/remove" ] || exit 0
umask 077
[ ! -L "$STATEDIR" ] || exit 1
mkdir -p "$STATEDIR" || exit 1
for name in mapping.lock last-mapping.log; do
    [ ! -L "$STATEDIR/$name" ] || exit 1
done
exec 8>"$STATEDIR/mapping.lock"
flock -n 0 <&8 || { echo 'Numeric mapping update is already running.'; exit 1; }
output=$(process)
status=$?
printf '%s\n' "$output" | tail -c 16384 > "$STATEDIR/last-mapping.log"
printf '%s\n' "$output"
exit "$status"
