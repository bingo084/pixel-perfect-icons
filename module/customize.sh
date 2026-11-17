# KernelSU installation hook. Schedules one cache refresh after the reboot/unlock.
SKIPMOUNT=false

[ "$KSU" = true ] || abort "This build is for KernelSU."
[ "$(getprop ro.product.device)" = komodo ] || abort "This build is for Pixel 9 Pro XL (komodo)."
[ "$(getprop ro.build.version.sdk)" = 37 ] || abort "This build is for Android 17 / API 37."
[ ! -f /system_ext/overlay/config/config.xml ] || abort "Existing system_ext overlay configuration needs review."

ui_print "Pixel Perfect Icons: checking installed app versions..."
TAB=$(printf '\t')
while IFS="$TAB" read -r package expected overlay; do
    [ -n "$package" ] || continue
    actual=$(dumpsys package "$package" | sed -n 's/.*versionCode=\([0-9][0-9]*\).*/\1/p' | head -n 1)
    [ "$actual" = "$expected" ] || abort "$package changed or is missing (expected $expected, found $actual). Re-scan and rebuild."
done < "$MODPATH/targets.tsv"

if [ -s "$MODPATH/originals.tsv" ]; then
    sh "$MODPATH/capture-originals.sh" || ui_print "Some original previews were unavailable; icon replacement is still installed."
fi

# KernelSU owns webroot permissions and SELinux context; leave them untouched.
set_perm_recursive "$MODPATH/system" 0 0 0755 0644
for script in "$MODPATH"/*.sh; do
    set_perm "$script" 0 0 0755
done
# Remove the old ambiguous Action entry if an earlier staged install left it.
rm -f "$MODPATH/action.sh"
# Force PackageManager to reparse an updated system overlay instead of reusing its old cache.
for apk in "$MODPATH"/system/system_ext/overlay/*.apk; do
    [ -f "$apk" ] || continue
    touch "$apk" || abort "Could not update overlay timestamp: $apk"
done
printf 'install-or-update\n' > "$MODPATH/.refresh-pending" || abort "Could not schedule icon refresh."
ui_print "App versions match. Reboot to apply overlays."
ui_print "After unlock, icon cache refreshes once. Open WebUI for icons and cache clearing."
ui_print "Only Pixel Launcher icon cache is rebuilt. Desktop layout and app data stay intact."
