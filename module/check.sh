#!/system/bin/sh
# Read-only verification of the overlays and the resources actually selected.
exec 2>&1
MODDIR=${0%/*}
FORMAT=${1:-text}
case "$FORMAT" in text|--tsv) ;; *) echo 'Usage: check.sh [--tsv]'; exit 1 ;; esac
report() { [ "$FORMAT" = --tsv ] || printf '%s\n' "$*"; }
TAB=$(printf '\t')
failed=0
while IFS="$TAB" read -r package expected overlay; do
    [ -n "$package" ] || continue
    package_failed=0
    unknown=false
    issue=-
    if ! state=$(cmd overlay dump --user 0 "$overlay" 2>&1); then
        unknown=true
    fi
    if [ "$unknown" = false ] && printf '%s\n' "$state" | grep -Eq 'mState.*: STATE_ENABLED(_IMMUTABLE)?$'; then
        report "OK $package"
        if [ -s "$MODDIR/numeric-targets.tsv" ] && awk -F '\t' -v pkg="$package" '$1 == pkg {found=1} END {exit !found}' "$MODDIR/numeric-targets.tsv"; then
            if value=$(sh "$MODDIR/numeric.sh" check "$package" 2>&1); then
                :
            else
                code=$?
                report "NOT SELECTED $package: $value"
                failed=$((failed + 1))
                package_failed=$((package_failed + 1))
                issue=resource-not-selected
                if [ "$code" -eq 2 ]; then unknown=true; issue=check-unavailable; fi
            fi
        else
        while IFS="$TAB" read -r map_overlay resource; do
            [ "$map_overlay" = "$overlay" ] || continue
            if ! printf '%s\n' "$state" | grep -Fq "($resource ->"; then
                report "MISSING MAP $package $resource"
                failed=$((failed + 1))
                package_failed=$((package_failed + 1))
                [ "$issue" != - ] || issue=mapping-missing
                continue
            fi
            if ! value=$(cmd overlay lookup --user 0 "$package" "$package:$resource" 2>&1); then
                report "LOOKUP FAILED $package $resource: $value"
                failed=$((failed + 1))
                package_failed=$((package_failed + 1))
                unknown=true
            elif ! printf '%s\n' "$value" | grep -Fq 'clean_icon.xml'; then
                report "NOT SELECTED $package $resource: $value"
                failed=$((failed + 1))
                package_failed=$((package_failed + 1))
                [ "$issue" != - ] || issue=resource-not-selected
            fi
        done < "$MODDIR/maps.tsv"
        fi
    else
        report "NOT ACTIVE $package
$state"
        failed=$((failed + 1))
        package_failed=$((package_failed + 1))
        issue=overlay-not-active
        if printf '%s\n' "$state" | grep -Fq 'STATE_NO_IDMAP'; then
            issue=mapping-missing
        elif printf '%s\n' "$state" | grep -Fq 'STATE_DISABLED'; then
            issue=disabled
        fi
    fi
    if [ "$FORMAT" = --tsv ]; then
        status=active
        [ "$package_failed" -eq 0 ] || status=inactive
        if [ "$unknown" = true ]; then
            status=unknown
            issue=check-unavailable
        fi
        printf '%s\t%s\t%s\n' "$package" "$status" "$issue"
    fi
done < "$MODDIR/targets.tsv"
[ "$FORMAT" = --tsv ] || printf '\nFailed overlay/resource checks: %s\n' "$failed"
[ "$failed" -eq 0 ]
