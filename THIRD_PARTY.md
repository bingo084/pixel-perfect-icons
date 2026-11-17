# 图标素材来源

当前全部替换图标来自 [完美图标补全计划](https://github.com/pzcn/Perfect-Icons-Completion-Project)。
固定上游提交及每张图片的 Git blob SHA 记录在 `targets.json`，构建时重新校验。
使用该项目 `icons/<应用包名>/0.png`（背景）及 `1.png`（前景），不修改图案或配色。

图标、商标及相关素材的权利归原作者和相应权利人所有；本项目的代码不改变素材授权。
上游包含其他主题作者的独立作品，本构建只使用上述默认分层素材，不导入 `themes/`。

## 闲鱼普通入口

0.3.7 使用该计划的 `icons/com.taobao.idlefish/0.png`（背景）与 `1.png`（前景），两者是正常的普通图标分层素材，没有会员皇冠。
本次固定提交中，两张图片的 Git blob SHA 分别为 `39c2db70bdbd5ee0aa76cda2e57daef10663a17f` 和 `97a1dbde2b9c17d643b63df321c7eed0f65c6616`，打包保持原始 PNG 字节。
运行时仍覆盖普通入口的 `drawable/idlefish_ic_launcher`（`0x7f0807a6`）。0.3.6 使用过 APK 自带普通图案；此前将补全计划素材说成会员图案的描述不准确，已纠正。

拼多多的“原图”对照在安装时从手机已安装的 APK 读取，仅存入模块自身的预览图片，不更改原应用。

## KernelSU JavaScript SDK

WebUI 使用官方 npm 包 `kernelsu@3.3.0` 的原始 `index.js`，声明的许可证为 Apache-2.0。
版本、下载地址和校验值见 `webui/vendor/README.md`，许可证正文随包分发。
所有脚本和图标均随模块提供，不从 CDN 加载。
