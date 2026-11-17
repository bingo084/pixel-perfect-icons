# 前景大小微调

0.3.11 的选定比例为 BOSS 直聘 90%、闲鱼 85%。其余应用保持原比例。

对前景显得拥挤的应用，在 `icon-overrides.json` 中设置 `foreground_scale`。例如 `0.9` 表示前景宽、高各为原来的 90%；背景保持原来的大小。未设置时为 `1`，沿用补全计划原有比例。各应用可以分别设置。

参数经过 `review.py` 校验后写入 `targets.json`，只接受大于 0、且不超过 1 的数值，并限于已有前后景分层素材。构建使用 Android 的 `InsetDrawable` 居中收进前景，原始 PNG、素材 SHA 和背景均保持不变。它不改变启动入口、资源映射或缓存清理逻辑。实现依据见 [Android InsetDrawable](https://developer.android.com/reference/android/graphics/drawable/InsetDrawable)。

WebUI 的替换后图片和 `preview.py` 共用同一套前景缩放预览，保持与构建参数一致。界面继续显示原有修改原因及“补全计划”来源；当前参数由项目适配配置管理，重新构建后生效，没有新增界面设置按钮。

图标使用系统的自适应形状，桌面缩放及动画也可能影响视觉效果。离线对照用于选择比例，正式显示仍以手机桌面为准。
