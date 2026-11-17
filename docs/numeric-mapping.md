# 数值 ID 映射

0.3.6 开始对拼多多和闲鱼启用，0.3.9 增加招商银行和高德地图。平台限制仍是 komodo / API 37，并且只接受 Android 17 的 idmap v11。

| 应用 | 系统建立初始映射的资源 | 实际覆盖目标 |
|---|---|---|
| 拼多多 8.27.0 / 82700 | `drawable/logo` / `0x7f070570` | 普通入口 `mipmap/pdd` / `0x7f0d0009` |
| 闲鱼 7.28.86.1 / 529 | `drawable/appicon_skin_default_badge` / `0x7f08021e` | 普通入口 `drawable/idlefish_ic_launcher` / `0x7f0807a6` |
| 招商银行 13.2.0 / 1320 | `drawable/aboutbank_version_cmb_logo` / `0x7f080058`，保留原图 | `drawable/common_ic_cmb_logo` / `0x7f0802e2` |
| 高德地图 17.02.2.2014 / 170105 | `drawable/auth_logo` / `0x7f0800e1`，保留原图 | `drawable/v3_icon` / `0x7f080e8a` |

扫描时固定的主包元数据 CRC 分别为拼多多 `32fbffb9`、闲鱼 `c7590760`，写入前必须与其一致。同版本但资源不同的渠道包也会停止处理，不能只凭 versionCode 相同就套用数值 ID。

招行与高德对应的主包 CRC 为 `6049bfb8`、`03774ed9`。两者主包中没有可直接复用的桌面备用图标，因此初始映射指向该主包资源的原始图片副本 `clean_seed`，保持原始字节及密度配置；不先把应用内部图片替换成桌面图案。校准时同步更新目标 ID、覆盖值 ID 及其反向映射，使最终映射为实际桌面 ID → `clean_icon`，初始资源恢复原有读取路径。写入仅接受完整的初始或最终资源对，拒绝混合状态。原图 SHA256 记录在 `targets.json` 的 `bootstrap_artwork`，扫描时从已安装主包只读提取；构建前再次核对。

拼多多在解析应用信息时已把别名换成真实图标 ID。该真实资源与其它 12 项同名，普通按名查找却会得到 `0x7f0d0005`。闲鱼普通图标仅存在于密度拆分包，建立映射时读取主包找不到它。两者均不能以“声明别名的命名映射通过”证明桌面已经生效。

静态 RRO 先让系统建立一对一的初始映射。`numeric.sh` 调用一次性 `NumericIcons` helper，只校准本模块以下四个缓存文件中的正反向资源对：

```text
/data/resource-cache/system_ext@overlay@local.pixelcleanicons.com_xunmeng_pinduoduo.apk@idmap
/data/resource-cache/system_ext@overlay@local.pixelcleanicons.com_taobao_idlefish.apk@idmap
/data/resource-cache/system_ext@overlay@local.pixelcleanicons.cmb_pb.apk@idmap
/data/resource-cache/system_ext@overlay@local.pixelcleanicons.com_autonavi_minimap.apk@idmap
```

不修改应用 APK、不重签名、不安装管理应用、不注册新的动态覆盖、不加入常驻服务或 SELinux 策略。资源表、图案和代码仍来自各自的构建输入。

写入前核对应用 versionCode、目标和覆盖 APK 的路径及元数据 CRC、idmap 魔数和版本、策略、条目数量、原目标 ID、正反映射一致性及所有读取边界。仅支持一对一映射；不认识的格式直接停止。先在临时文件中准备，保持原文件的属主、权限及 SELinux 文件上下文；加载成功并确认目标 ID 选中了本模块的自适应图标后，才在同一目录原子替换缓存文件。没有缓存备份；临时文件在退出时移除，下次处理时只清理本模块对应前缀的遗留临时文件。

开机完成后维护一次；手动或首次解锁清缓存前也会维护。若映射已经正确则不重写。版本、CRC 或格式不匹配时，保留原映射，不清图标缓存；用户更新应用后应重新扫描构建。停用或卸载模块后重启，系统不再加载本模块覆盖包，恢复应用原资源。

只读检查同时验证当前桌面入口 ID、加载主包及拆分包后的资源实际归属，以及图标可被解析为 `AdaptiveIconDrawable`。Java helper 不调用应用代码，运行时限制 64MB Java 堆及 20 秒；每次执行后退出。

已在手机的专用临时目录用真实 `idmap2`、真实主包及拆分包验证两个普通图标，生产脚本副本的校准、读取和重复执行均通过；真实系统缓存哈希未变。图像与证据见 `build/device-validation/idmap-probe/`，它们不是已部署桌面的截图。正式版本仍需刷入后确认开机阶段和桌面效果。

0.3.9 的独立验证覆盖四项数值映射。招行、高德初始映射的渲染与原图完全一致；校准后实际桌面资源选中补全计划自适应图标，初始资源继续保持原样。高德的启动 Activity 图标为 0 时按 ApplicationInfo 图标检查。生产脚本副本通过重复执行、错误 CRC 保留映射、权限保留及临时文件清理验证；真实系统 idmap 的哈希或缺失状态均未变。证据在 `build/device-validation/numeric-0.3.9/results.json`，尚未安装新模块。

实现依据：[AOSP ResourceMapping](https://github.com/aosp-mirror/platform_frameworks_base/blob/main/cmds/idmap2/libidmap2/ResourceMapping.cpp)、[AOSP AssetManager2](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/libs/androidfw/AssetManager2.cpp)、[ApkAssets](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/java/android/content/res/ApkAssets.java)。读取映射使用 `ApkAssets.loadOverlayFromPath` 和独立 `AssetManager.Builder`，不通过会再次按路径查找映射的旧接口。
