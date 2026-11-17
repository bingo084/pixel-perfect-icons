#!/system/bin/sh
# Read PNG previews from the installed APK. Does not load code or modify the app.
MODDIR=${0%/*}
[ -s "$MODDIR/originals.tsv" ] || exit 0
TAB=$(printf '\t')
failed=0
capture() (
    package=$1
    apk_name=$2
    entry=$3
    printf '%s\n' "$package" | grep -Eq '^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$' || exit 1
    case "$apk_name" in base.apk|split_config.*.apk) ;; *) exit 1 ;; esac
    case "$entry" in ''|/*|*..*) exit 1 ;; esac
    printf '%s\n' "$entry" | grep -Eq '^[A-Za-z0-9_./-]+\.png$' || exit 1
    base=$(pm path "$package" | while IFS= read -r line; do
        path=${line#package:}
        if [ "${path##*/}" = "$apk_name" ]; then printf '%s\n' "$path"; break; fi
    done)
    [ -f "$base" ] || exit 1
    destination="$MODDIR/webroot/assets/$package.before.png"
    [ -f "$destination" ] && [ ! -L "$destination" ] || exit 1
    temporary=$(mktemp "$MODDIR/.original-preview.XXXXXX") || exit 1
    trap 'rm -f "$temporary"' 0
    unzip -p "$base" "$entry" > "$temporary" 2>/dev/null || exit 1
    [ "$(od -An -N8 -tx1 "$temporary" | tr -d ' \n')" = 89504e470d0a1a0a ] || exit 1
    # Overwrite the pre-created placeholder inode, retaining KernelSU's context.
    cat "$temporary" > "$destination" || exit 1
    printf 'Original preview captured: %s\n' "$package"
)
while IFS="$TAB" read -r package apk_name entry; do
    [ -n "$package" ] || continue
    if ! capture "$package" "$apk_name" "$entry"; then
        printf 'Original preview unavailable: %s (placeholder retained)\n' "$package"
        failed=$((failed + 1))
    fi
done < "$MODDIR/originals.tsv"
[ "$failed" -eq 0 ]
