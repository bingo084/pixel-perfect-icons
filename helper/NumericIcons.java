import java.io.File;
import java.lang.reflect.Array;
import java.lang.reflect.InvocationTargetException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Android 17 idmap v11 helper. No app code is loaded and no overlay is registered. */
public final class NumericIcons {
    private static final class Mapping {
        byte[] bytes;
        int targetOffset;
        int reverseOffset;
        int overlayOffset;
        int reverseOverlayOffset;
        int target;
        int overlay;
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new IllegalArgumentException(message);
    }

    private static int word(ByteBuffer data) {
        require(data.remaining() >= 4, "Truncated idmap");
        return data.getInt();
    }

    private static String string(ByteBuffer data) {
        int length = word(data);
        require(length >= 0 && length <= 32768, "Invalid idmap string length");
        int padded = (length + 3) & ~3;
        require(data.remaining() >= padded, "Truncated idmap string");
        byte[] content = new byte[length];
        data.get(content);
        data.position(data.position() + padded - length);
        return new String(content, StandardCharsets.UTF_8);
    }

    private static int apkCrc(String path) throws Exception {
        try (ZipFile apk = new ZipFile(path)) {
            ZipEntry manifest = apk.getEntry("AndroidManifest.xml");
            ZipEntry resources = apk.getEntry("resources.arsc");
            require(manifest != null && resources != null, "APK metadata missing");
            return (int)(manifest.getCrc() ^ resources.getCrc());
        }
    }

    private static Mapping read(String path, int seed, int target, String base, String overlay, String expectedCrc,
                                int seedOverlay, int targetOverlay) throws Exception {
        require((seedOverlay >>> 24) == 0x7f && (targetOverlay >>> 24) == 0x7f, "Invalid reviewed overlay IDs");
        File file = new File(path);
        require(file.isFile() && file.length() >= 64 && file.length() <= 1048576, "Invalid idmap file size");
        Mapping result = new Mapping();
        result.bytes = Files.readAllBytes(file.toPath());
        ByteBuffer data = ByteBuffer.wrap(result.bytes).order(ByteOrder.LITTLE_ENDIAN);
        require(word(data) == 0x504d4449 && word(data) == 11, "Unsupported idmap format; Android 17 v11 required");
        int baseCrc = apkCrc(base);
        require(expectedCrc.matches("[0-9a-f]{8}") && Integer.parseUnsignedInt(expectedCrc, 16) == baseCrc,
                "Target APK differs from the reviewed scan");
        require(word(data) == baseCrc, "Target APK CRC changed");
        require(word(data) == apkCrc(overlay), "Overlay APK CRC changed");
        require(word(data) == 3 && word(data) == 1, "Unexpected idmap policies");
        require(string(data).equals(base), "Target APK path differs");
        require(string(data).equals(overlay), "Overlay APK path differs");
        require(string(data).isEmpty(), "Named overlays are unsupported");
        string(data); // diagnostic information
        require(word(data) == 0, "Constrained idmap is unsupported");
        require(word(data) == 1 && word(data) == 0 && word(data) == 0 && word(data) == 0 && word(data) == 1,
                "Only a single resource mapping is supported");
        require(word(data) >= 0, "Invalid string pool index");
        result.targetOffset = data.position();
        result.target = word(data);
        result.overlayOffset = data.position();
        result.overlay = word(data);
        result.reverseOverlayOffset = data.position();
        require(word(data) == result.overlay, "Invalid reverse mapping");
        result.reverseOffset = data.position();
        require(word(data) == result.target, "Forward and reverse targets differ");
        require((result.target == seed && result.overlay == seedOverlay) ||
                (result.target == target && result.overlay == targetOverlay), "Unexpected resource ID pair");
        int poolLength = word(data);
        require(poolLength >= 0 && poolLength == data.remaining(), "Invalid string pool bounds");
        return result;
    }

    private static void checkResource(String idmap, int target, String base, String overlay, String[] args, int splitStart)
            throws Exception {
        Class<?> apkClass = Class.forName("android.content.res.ApkAssets");
        Class<?> builderClass = Class.forName("android.content.res.AssetManager$Builder");
        Class<?> assetsClass = Class.forName("android.content.res.AssetManager");
        Class<?> resourcesClass = Class.forName("android.content.res.Resources");
        Class<?> metricsClass = Class.forName("android.util.DisplayMetrics");
        Class<?> configClass = Class.forName("android.content.res.Configuration");
        Class<?> valueClass = Class.forName("android.util.TypedValue");
        Object builder = builderClass.getConstructor().newInstance();
        java.lang.reflect.Method add = builderClass.getMethod("addApkAssets", apkClass);
        java.lang.reflect.Method load = apkClass.getMethod("loadFromPath", String.class);
        add.invoke(builder, load.invoke(null, base));
        for (int i = splitStart; i < args.length; i++) add.invoke(builder, load.invoke(null, args[i]));
        add.invoke(builder, apkClass.getMethod("loadOverlayFromPath", String.class, int.class).invoke(null, idmap, 0));
        Object assets = builderClass.getMethod("build").invoke(builder);
        try {
            Object system = resourcesClass.getMethod("getSystem").invoke(null);
            Object metrics = resourcesClass.getMethod("getDisplayMetrics").invoke(system);
            Object config = resourcesClass.getMethod("getConfiguration").invoke(system);
            Object resources = resourcesClass.getConstructor(assetsClass, metricsClass, configClass)
                    .newInstance(assets, metrics, config);
            Object value = valueClass.getConstructor().newInstance();
            resourcesClass.getMethod("getValue", int.class, valueClass, boolean.class).invoke(resources, target, value, true);
            Object selected = valueClass.getField("string").get(value);
            require(selected != null && selected.toString().endsWith("/clean_icon.xml"), "Original icon is still selected");
            int cookie = valueClass.getField("assetCookie").getInt(value);
            Object loaded = assetsClass.getMethod("getApkAssets").invoke(assets);
            require(cookie > 0 && cookie <= Array.getLength(loaded), "Invalid selected asset cookie");
            String selectedApk = (String)apkClass.getMethod("getAssetPath").invoke(Array.get(loaded, cookie - 1));
            require(overlay.equals(selectedApk), "Icon is not from this overlay");
            Object drawable = resourcesClass.getMethod("getDrawable", int.class).invoke(resources, target);
            require(drawable.getClass().getName().equals("android.graphics.drawable.AdaptiveIconDrawable"),
                    "Selected icon is not adaptive");
        } finally {
            assetsClass.getMethod("close").invoke(assets);
        }
    }

    public static void main(String[] args) {
        try {
            require(args.length >= 9, "Invalid helper arguments");
            if (args[0].equals("patch")) {
                require(args.length == 10, "Invalid patch arguments");
                int seed = Integer.decode(args[3]);
                int target = Integer.decode(args[4]);
                int seedOverlay = Integer.decode(args[8]);
                int targetOverlay = Integer.decode(args[9]);
                Mapping mapping = read(args[1], seed, target, args[5], args[6], args[7], seedOverlay, targetOverlay);
                ByteBuffer data = ByteBuffer.wrap(mapping.bytes).order(ByteOrder.LITTLE_ENDIAN);
                data.putInt(mapping.targetOffset, target);
                data.putInt(mapping.reverseOffset, target);
                data.putInt(mapping.overlayOffset, targetOverlay);
                data.putInt(mapping.reverseOverlayOffset, targetOverlay);
                Files.write(new File(args[2]).toPath(), mapping.bytes);
                read(args[2], seed, target, args[5], args[6], args[7], seedOverlay, targetOverlay);
                System.out.println("Mapping prepared for " + args[4]);
            } else if (args[0].equals("check")) {
                int seed = Integer.decode(args[2]);
                int target = Integer.decode(args[3]);
                int seedOverlay = Integer.decode(args[7]);
                int targetOverlay = Integer.decode(args[8]);
                Mapping mapping = read(args[1], seed, target, args[4], args[5], args[6], seedOverlay, targetOverlay);
                require(mapping.target == target && mapping.overlay == targetOverlay, "Launcher resource ID is not mapped");
                checkResource(args[1], target, args[4], args[5], args, 9);
                System.out.println("Selected adaptive icon for " + args[3]);
            } else {
                throw new IllegalArgumentException("Unknown helper operation");
            }
        } catch (Throwable error) {
            while (error instanceof InvocationTargetException && error.getCause() != null) error = error.getCause();
            System.err.println("Numeric icon mapping: " + error.getClass().getSimpleName() + ": " + error.getMessage());
            System.exit(error instanceof IllegalArgumentException ? 1 : 2);
        }
    }
}
