#!/system/bin/sh
# Fixed WebUI operations; never accepts package names or shell text from the page.
MODDIR=${0%/*}
case "${1:-}" in
    snapshot)
        [ "$(id -u)" = 0 ] || { echo 'Root is required.' >&2; exit 1; }
        [ "$(am get-current-user 2>/dev/null)" = 0 ] || { echo 'Owner user is required.' >&2; exit 1; }
        activities=$(cmd package query-activities --brief --components --user 0 \
            -a android.intent.action.MAIN -c android.intent.category.LAUNCHER 2>&1) || {
            printf '%s\n' "$activities" >&2; exit 1;
        }
        printf 'PIXEL_CLEAN_ICONS_V1\n'
        printf '%s\n' "$activities" | sed -n 's@^\([A-Za-z][A-Za-z0-9_]*\(\.[A-Za-z0-9_][A-Za-z0-9_]*\)*\)/[^ ][^ ]*$@\1@p' | sort -u
        printf '__OVERLAY_STATES__\n'
        sh "$MODDIR/check.sh" --tsv || :
        ;;
    clear-cache)
        exec sh "$MODDIR/refresh.sh" manual
        ;;
    *)
        echo 'Usage: ui.sh snapshot|clear-cache' >&2
        exit 1
        ;;
esac
