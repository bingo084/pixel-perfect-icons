# Pixel 完美图标（Pixel Perfect Icons）

给 Pixel 原生系统使用的彩色图标修复 KernelSU 模块：保留官方品牌图案和配色，去掉营销横幅，将旧式图标转换为标准的前景、背景自适应图标。

当前构建为 **0.3.10**，面向 Pixel 9 Pro XL（komodo）、Android 17 / API 37。上次已知安装版本为 0.3.6。当前版本增加 QQ 普通图标的自适应适配，并包含 0.3.9 的招商银行、高德地图适配及此前的闲鱼素材修正、清缓存等待反馈；尚未刷入。
当前选择 21 个应用、28 个启动图标资源。拼多多 8.27.0（versionCode 82700）按真实 ID 覆盖默认图标、去掉营销装饰；闲鱼 7.28.86.1（versionCode 529）按真实 ID 覆盖普通入口，使用补全计划的普通分层图标，活动和会员等备用入口不在当前目标内。招商银行 13.2.0（1320）、高德地图 17.02.2.2014（170105）也按真实 ID 处理拆分包中的桌面图标。QQ 9.3.75（16580）通过普通名称映射将主包中的单张 PNG 换为补全计划分层图标。WebUI 展示前后对照和全部桌面应用，并支持清除图标缓存。已有资源验证及本轮检查范围见 `docs/validation.md`。
安装及实际显示验证进展见 `docs/validation.md`。

## 范围

- 当前全部替换图标直接来自 [完美图标补全计划](https://github.com/pzcn/Perfect-Icons-Completion-Project)，固定提交与 PNG 的 Git blob SHA 都有记录。
- 使用原始 `0.png` 背景、`1.png` 前景，不重绘图案；来源及校验值见 `THIRD_PARTY.md`。
- 每个应用一个无代码 RRO APK，使用 `resourcesMap` 明确映射实际扫描到的启动图标资源。
- 拼多多、闲鱼、招商银行和高德使用一次性 Java helper 校准本模块自己的四个 idmap 缓存。它检查版本、APK CRC、路径和格式，再原子替换对应映射；覆盖 APK 仍无 DEX。招行和高德的初始映射保留原始图片及密度，校准后只覆盖实际桌面图标。实现及边界见 [数值 ID 映射](docs/numeric-mapping.md)。
- 同时处理应用图标、圆形入口和选中应用的营销启动别名。不会凭 `ic_launcher` 这样的通用名称猜资源。
- 覆盖包挂载到 `/system_ext/overlay`，与 PUI 的 `/product/overlay` 覆盖包并存；已在当前手机确认选中的资源来自本模块，PUI 保持启用。
- 没有后台常驻服务、SELinux 规则、系统属性修改，也不更换应用 APK；包含一次性开机刷新入口。
- WebUI 内的“清除图标缓存”按钮负责手动清理，移除旧的直接执行 Action 入口；安装、更新后重启并解锁仍自动清理一次。
- 默认查看已替换图标，支持“未替换／全部”、应用名称或包名搜索；显示修改原因、图标来源和生效状态。全部应用从手机实时查询，只包含机主用户有桌面入口的应用。
- 清缓存按钮立即显示等待动画和用时，优先异步执行，完成或失败结果保留在按钮下方。打开页面、切换列表不会清缓存。
- 此阶段不制作主题单色层、通知图标或自定义导入；不改变主题图标开关。

已有规范且干净的图标不默认替换。QQ 普通入口的方形位图已纳入自适应适配，保留经典企鹅和红围巾。QQ 构建时直接读取位图资源表，避开 AAPT2 全表导出超时；运行时仍是普通名称 RRO，不增加数值 ID 处理。抖音尚未确认实际图标问题，资源名混淆不作为默认替换理由。拼多多的同名引用已按二进制资源表的真实 ID 解析。岚图汽车按用户选择保留原图。
未纳入条目的说明集中在 [未纳入替换的已知情况](docs/unsupported-apps.md)，界面不为这些应用显示原因。

## 查看结果

- `selection.json`：首批应用及替换理由。
- `targets.json`：经核实的应用版本、资源名、配置、素材来源及校验值。
- `build/preview-selected/index.html` / `sheet-1.png`：对照预览。左侧是应用 APK 的位图回退素材，**不是当前已受 PUI 影响的桌面截图**；右侧是替换图标的圆形预览。拼多多左侧在离线预览中标为“待提取”，安装时才从已安装 APK 读取。
- `dist/pixel-perfect-icons-0.3.10.zip`：本地构建生成的 KSU 安装包，不随源码提交。
- `dist/webui-preview.html`：可直接用电脑浏览器打开的离线界面预览。明确标注预览模式，使用此前扫描的 36 个样本应用和模拟接口，不访问手机，按钮也不清理真实缓存。
- `dist/manifest.json`、`dist/SHA256SUMS`：构建清单及校验值。

## 安装和验证

安装器核对机型、API 和各应用版本；如果应用已更新或缺失，会停止安装并提示重新扫描。安装时不停止应用、清理缓存或自动重启，只登记首次开机刷新。

1. 先检查对照预览。
2. 在 KernelSU 中手动选择 `dist/pixel-perfect-icons-0.3.10.zip`。内部模块 ID 仍为 `pixel-clean-icons`，可直接更新旧版，不会安装重复模块。
3. 方便时手动重启；这依赖手机已有的模块挂载能力，PUI 能正常生效的挂载环境可作为基线。
4. 首次解锁后自动检查覆盖图标并刷新一次。打开模块的 WebUI 查看清单及前后对照；需要手动清理时点击“清除图标缓存”。只读资源检查入口仍为模块内的 `check.sh`。
5. 在关闭主题图标的彩色显示下，确认桌面、抽屉和应用信息页；主题开关由用户自己选择。

刷新仅处理 Pixel Launcher 的 `app_icons.db` 及三个附属文件；默认桌面、用户、解锁状态或资源校验不满足时不清理。操作和固定大小诊断日志见 [缓存刷新说明](docs/cache-refresh.md)。界面和数据含义见 [WebUI 说明](docs/webui.md)。本次新增覆盖及闲鱼白底改善效果尚未进行真机验证。

安装器还会读取拼多多 APK 中的原图，用于 WebUI 前后对照。读取失败时保留“待提取”占位并提示，不影响图标覆盖，也不保存 APK 备份。

需要回退时，在 KernelSU 停用或卸载这个独立模块并重启。PUI 本身不会被停用或修改。
应用以后更新，资源名可能改变；显示原图或出现映射失败时应重新扫描，不能将“模块已安装”视为已生效。

## 本地构建

需要 Linux x86_64、Python 3、JDK（含 `javac`、`keytool`）、ImageMagick；扫描时需要已配对的 ADB。一次性 helper 由固定版本官方 D8 编译。
没有 Gradle 或第三方 Python 依赖。构建工具只放入项目缓存，不安装系统软件。

公开仓库只包含源码及适配定义，不包含签名密钥、手机扫描数据、构建缓存和安装包。首次克隆后，需要连接目标手机生成自己的扫描缓存；设备、系统或应用版本不符时应先重新适配。这是针对上述设备和版本的个人模块。

```sh
python bootstrap.py
adb pull /system/framework/framework-res.apk .cache/framework-res.apk
python scan.py --aapt2 .cache/toolchain/aapt2 --upstream-commit fb8b5c9224510fedb653a7dceafdcb364b4e2263
# 根据实际扫描结果确认 selection.json、icon-overrides.json 后：
python review.py
python fetch_assets.py
python build.py
python -m unittest discover -s tests -v
npm test
python preview_ui.py
```

重新扫描当前手机及复查选择：

```sh
python scan.py --aapt2 .cache/toolchain/aapt2 --upstream-commit fb8b5c9224510fedb653a7dceafdcb364b4e2263
python preview.py
# 检查预览并编辑 selection.json 后：
python review.py
python preview.py --selected
python build.py
```

多个 ADB 传输时，为扫描增加 `--serial <设备传输标识>`，或设置 `ANDROID_SERIAL`。
完整上游索引第一次从 GitHub 获取；遇到匿名 API 频率限制时，可等待恢复，或将对应提交的 Git Tree JSON 保存为 `.cache/upstream-tree.json`，并添加 `commit` 字段标明固定提交。

本机签名密钥在 `keys/`，不会进入 Git 或模块 ZIP；后续更新应保留该目录并沿用签名。
`build.py` 只构建和校验，不执行任何 ADB 安装、刷入或重启操作。
文档里的 `build/device-validation/` 路径是本机诊断证据，不随公开源码上传。

## 后续

后续考虑自定义导入、主题单色层和通知小图标。自定义图标更新与应用资源映射更新会分开管理。
