#!/system/bin/sh
# Restore the reviewed numeric mappings after PackageManager prepares its idmaps.
# Icon-cache clearing still happens only after installation/update.
MODDIR=${0%/*}
[ ! -f "$MODDIR/disable" ] && [ ! -f "$MODDIR/remove" ] || exit 0
if [ -s "$MODDIR/numeric-targets.tsv" ]; then
    sh "$MODDIR/numeric.sh" apply || exit 1
fi
[ -f "$MODDIR/.refresh-pending" ] || exit 0
exec sh "$MODDIR/refresh.sh" auto
