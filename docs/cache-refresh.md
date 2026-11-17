# 图标缓存刷新

## 手动刷新

在 KernelSU 中打开 Pixel Perfect Icons 的 WebUI，点击“清除图标缓存”。按钮立即显示“正在清除…”、等待动画和用时；完成或失败的结果保留在按钮下方。执行中防止重复提交，列表和搜索仍可使用。模块先核对全部覆盖图标是否已经生效，再停止 Pixel Launcher 并删除可重建的图标缓存。若桌面原本在前台，会重新打开桌面；若正在其他应用中，则保留当前应用，返回桌面时重建图标。

优先通过 KernelSU 异步 `spawn` 执行，避免同步原生接口阻塞网页。旧管理器使用兼容回退，但先绘制等待提示。长时间未收到完成回调时显示“暂未收到清除结果”，不冒充成功，也不自动重试或宣称已取消后台操作。

模块不备份图标缓存，不清除 Pixel Launcher 应用数据。仅允许删除以下四个文件：

```text
/data/user/0/com.google.android.apps.nexuslauncher/databases/app_icons.db
/data/user/0/com.google.android.apps.nexuslauncher/databases/app_icons.db-journal
/data/user/0/com.google.android.apps.nexuslauncher/databases/app_icons.db-wal
/data/user/0/com.google.android.apps.nexuslauncher/databases/app_icons.db-shm
```

`launcher.db`、`launcher_*.db`、小组件预览、桌面布局、壁纸及偏好设置均不属于删除范围。前后景图标仍来自固定上游素材，不保存在这个缓存中。

## 自动刷新

安装或更新模块时，安装器写入 `.refresh-pending` 标记。重启挂载覆盖包后，由 KernelSU 的 `boot-completed.sh` 执行一次刷新；这个时机由 [KernelSU 官方模块文档](https://kernelsu.org/guide/module.html#shell-scripts) 定义。

开机脚本先维护数值 ID 映射，正确时不重写。0.3.6 包含拼多多和闲鱼，0.3.9 增加招商银行和高德，共四项。只有存在 `.refresh-pending` 标记才继续清理缓存；普通开机不重复清理。

自动清理任务等机主用户解锁，最长等待 30 分钟。数值映射、覆盖层及真实桌面资源校验通过，默认桌面为 Pixel Launcher 且当前用户为机主时才执行。成功后删除待刷新标记。手动清理前也会先检查并维护数值映射。

如果解锁超时或资源尚未生效，保留待刷新标记和缓存，在下次开机重试，也可解锁后在 WebUI 清理。停用或标记卸载的模块不会继续自动刷新。应用本身的常规更新由桌面原有的包更新机制处理，本模块不另外监听所有应用更新。

## 日志与并发

模块使用系统 `flock` 避免手动和自动任务同时清理。运行状态放在 `/data/adb/pixel-clean-icons/`：

- `last-refresh.log`：最近一次刷新结果，每次覆盖，无历史堆积。
- `last-check.log`：最近一次覆盖层校验，最多 32 KiB。
- `refresh.lock`：进程锁文件，进程退出自动释放锁，不依赖删除文件解锁。
- `last-mapping.log`：最近一次数值映射维护，最多 16 KiB。
- `mapping.lock`：数值映射维护的进程锁。

没有缓存备份或持续增长的历史记录。状态目录只允许 root 访问，更新模块时保留；卸载后留下这几个诊断文件，避免擅自删除用户查看结果所需的记录。

只读排查可运行模块内的 `check.sh`，它不会清理缓存或重启桌面。当前实现只面向机主用户、Pixel 9 Pro XL / API 37 和 Pixel Launcher。
