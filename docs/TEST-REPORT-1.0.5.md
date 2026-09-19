# 1.0.5 测试报告（开发实例实测）

**被测对象**：DeepSeek Harness for Windows 1.0.5（源码 + `dist\DeepSeek Harness` 开发实例）
**测试日期**：2026-09-20
**测试机**：Windows（Edge/WebView2 153.0.4234，Node v24.16.0，pnpm 11.7.0）

本报告记录 1.0.5 三类修复的**可复现验证**：外壳 UI 全屏缺陷用真实浏览器内核量测，
内核升级/降级用启动器自身的更新管线在开发实例里真机跑通。

---

## 一、外壳 UI：退出全屏后的 iframe 塌陷

**方法**：`tools/immersive-check/`
真实 Edge（与随应用分发的 WebView2 同内核）无头启动 → CDP 驱动 → 真点按钮
（`#btn-start` / `#btn-immersive` / `#btn-exit-immersive` / `#btn-stop`），
量测 iframe、`.frame-wrap`、`.page`、`.content` 的几何与滚动尺寸，并断言
iframe 高度、宽度、容器高度、是否出现双滚动条、iframe 内部页面自报的视口尺寸。

复现（修复前，`app/ui/style.css` 原始版本）：

| 场景 | body class | iframe | 容器 | 判定 |
| --- | --- | --- | --- | --- |
| 启动后（自动全屏） | `immersive` | 1250×725 | 1250×725 | 通过 |
| **退出全屏** | — | **980×150** | 982×624 | **失败：iframe 塌陷** |
| 反复切换全屏 | — | **980×150** | 982×624 | **失败** |
| 切换页面再返回 | — | **980×150** | 982×624 | **失败** |
| 启动→退出全屏 | — | **980×150** | 982×571 | **失败** |
| 窄窗口 1000×640 | — | **730×150** | 732×486 | **失败** |

修复后（同机同场景，`app/ui` 与 `dist\DeepSeek Harness\ui` 各跑一遍）：

| 场景 | iframe | 容器 | 内部页面自报 | 判定 |
| --- | --- | --- | --- | --- |
| 启动后（自动全屏） | 1250×725 | 1250×725 | 1250×725 | 通过 |
| 退出全屏 | 980×622 | 982×624 | 980×622 | 通过 |
| 反复切换全屏 | 980×622 | 982×624 | 980×622 | 通过 |
| 切换页面再返回 | 980×622 | 982×624 | 980×622 | 通过 |
| 启动→退出全屏 | 980×569 | 982×571 | 980×569 | 通过 |
| 窄窗口 1000×640 | 730×484 | 732×486 | 730×484 | 通过 |
| 停止服务器（空状态） | 隐藏 | 982×571 | 空状态 980×569 铺满 | 通过 |

结论：**8/8 场景通过**，控制台无异常，无外层/内层双滚动条；退出全屏后 iframe 高度从
150px 恢复为容器满高（622px）。

同一套断言还在**真实内核**的 iframe 上跑通（`--real-core-url` 指向正在运行的
dsh 0.1.6-alpha.2 / 0.1.1-rc.2），8/8 通过，并额外校验 iframe 内部页面真实挂载：

```
# dsh 0.1.6-alpha.2（带 token 地址）
real core inner page: {"title":"DSH 本地构建","rootChildren":1,"textLen":190,
  "head":"DSH 本地构建\n0.1.6-alpha.2-a849f1e\n新会话\n插件\n工作区\n…",
  "authError":false}

# dsh 0.1.1-rc.2（裸地址）
real core inner page: {"title":"DSH Local Build","rootChildren":1,"textLen":157,
  "head":"DSH Local Build\n187d5f6\n新会话\n…"}
```

复跑命令：

```powershell
# 1) 起测试用外壳服务（同时提供伪内核页面）
python tools\immersive-check\stub_server.py --port 0 --json-port-file .tmp-ui-test\ports.json
#    针对开发实例已装 UI：
python tools\immersive-check\stub_server.py --port 0 --json-port-file .tmp-ui-test\ports-dist.json `
       --ui-root "dist\DeepSeek Harness\ui"
# 2) 无头驱动量测（退出码 0 = 全通过）
node tools\immersive-check\cdp_probe.mjs --shell-port <shell> --core-port <core> `
     --out .tmp-ui-test\report.json --shots .tmp-ui-test\shots
```

---

## 二、Python 回归测试

`tools\test-1.0.5.py`（自包含，仅标准库）：

```
1.0.5 regression tests: 98/98 passed
ALL PASS
```

覆盖：

- 超 MAX_PATH（>260 字符）目录树删除（旧 `shutil.rmtree` 失败的同一目录）；
- 只读文件（git pack 属性）删除；
- junction（目录联接）不被跟随——目标内容必须存活；
- CLI 入口解析 5 种布局（`bin` 字符串 / 字典 / 未知键 / 声明但缺失 / 无清单）；
- 启动候选梯度顺序与记忆（`core_launch_mode`，越界值忽略）；
- 内核打印地址解析（token 地址 / 裸地址 / 无输出回退）、`status().url` 的运行/停止语义、
  停止后清除 token；
- usage 错误识别（unknown option/command/argument、unrecognized、invalid option、
  `Usage:`）与真实故障（模块缺失、profile 启动失败）不误判；
- 控制台输出解码（构造非法 UTF-8 的 OEM 字节，验证不再抛异常；`relink.create_junction`
  可用）；
- 健康检查三态：成功 / 不认识 `--dump-config`（记为不支持）/ 真故障；
- 换核：成功换核 + 元数据 + 清空启动记忆 + 备份回收；
- 换核前校验半成品（拒绝且不动旧核心）、换核后校验失败自动回滚；
- 陈旧备份删不掉时不阻塞换核（改用时间戳备份名）；
- `cleanup_stale_core_backups()`（含长路径、`keep=` 保护）；
- `shellui.sync_shell_ui()`（陈旧 UI 刷新 + 备份 + 二次运行无操作 + 缺失/开发布局 +
  绝不把比随包更新版本的在装 UI 降级）；
- `post-update.bat` 规则（不再只看标记是否存在）；
- 外壳 CSS 不变式（`.frame` 绝对定位四边、沉浸模式不得 `position: static`）。

---

## 三、内核升级 / 降级实测（开发实例）

**方法**：`tools/core-update-test/run_core_update.py` —— 直接用启动器自身的
`updater.CoreUpdater`（也就是「核心更新」页调用的同一份代码），对
`dist\DeepSeek Harness` 实例执行：下载源码 zip → `pnpm install` → `pnpm build`
→ 原子换核 → 元数据 → 健康检查 → 启动服务器并 HTTP 校验。

| 动作 | 起始内核 | 目标内核 | 换核前 | 换核后 | 旧核心备份 | 健康检查 | 启动地址 | HTTP |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 升级 | dsh 0.1.1-rc.2 | dsh 0.1.6-alpha.2 | 0.1.1-rc.2 | 0.1.6-alpha.2 | 已回收（`backups: []`） | exit 0（`--profile web --dump-config`） | 带 token 的地址 | 200（带 token） |
| 降级 | dsh 0.1.6-alpha.2 | dsh 0.1.1-rc.2 | 0.1.6-alpha.2 | 0.1.1-rc.2 | 已回收 | exit 0 | 裸地址（旧内核不打印 token） | 200 |
| 再升级 | dsh 0.1.1-rc.2 | dsh 0.1.6-alpha.2 | 0.1.1-rc.2 | 0.1.6-alpha.2 | 已回收 | exit 0 | 带 token 的地址 | 200 |

补充：

- 换核全程异常堆栈数量：修复前 **2287+**（旧代码）、修复后 **0**；
- 换核后 pnpm workspace junction 重建（`relink.rebase_junctions`）在真实核心树上完成；
- 历史遗留的 `core.backup`（前一次失败更新留下、`shutil.rmtree` 与 `cmd rmdir` 均无法删除的
  >300 字符 pnpm 路径）由新实现 **0.0 秒删除**，随后每一次换核都能正常完成；
- 下载/构建中断后重跑、以及 `.update` 残留（含部分安装的 pnpm 树）的清理均正常。

### 3.1 最新内核的鉴权地址（1.0.4 在此处完全不可用）

| 加载地址 | 内核 | iframe 内部页面（CDP 实测） |
| --- | --- | --- |
| 裸地址 `http://127.0.0.1:3080/` | 0.1.6-alpha.2 | 401：`dsh web authentication required; reopen the URL printed by dsh web`；`#root` 不存在（`rootChildren=-1`） |
| 内核打印的 token 地址 | 0.1.6-alpha.2 | 标题「DSH 本地构建」，版本 `0.1.6-alpha.2-9f209c3`，`#root` 已挂载，正文含会话列表与输入框，`authError=false` |
| 裸地址 `http://127.0.0.1:3080/` | 0.1.1-rc.2 | 标题「DSH Local Build」，`#root` 已挂载（旧内核无需 token） |

内核启动输出（`logs\core.log`）对照：

```
--- start 2026-09-14 13:46:32 ---      # 0.1.1-rc.2
dsh web: http://127.0.0.1:3080

--- start 2026-09-20 00:56:39 ---      # 0.1.6-alpha.2
dsh web: http://127.0.0.1:3080/?token=zHUtLpCMQ5Z5yFHuV8lWxMu0sVdZ_1ymDpGD3_Mn1Jw
```

---

## 四、启动参数梯度实测（真实 dsh CLI）

**方法**：`tools/core-update-test/test_launch_ladder.py` —— 把“坏参数”候选放在梯度最前面
（模拟未来内核改名/删除某个 flag 的情形），验证启动器自动跳到可用组合、打开端口、
记住可用索引，并在下一次启动直接使用该索引。

实测（内核 0.1.1-rc.2，10/10 通过）：

```
PASS  real core starts with the preferred flags        -- 服务已启动: http://127.0.0.1:3080
PASS  web UI answers over HTTP                          -- status=200
PASS  launch mode remembered                            -- 0
PASS  core still starts when the first candidates are rejected
                                                        -- 服务已启动 (elapsed 9.1s)
PASS  fallback candidate really served the UI           -- status=200
PASS  working candidate index (2) remembered            -- 2
PASS  rejection observed in the core log
      -- error: unknown option '--definitely-not-a-flag'
         error: unknown option '--no-such-option'
         dsh web: http://127.0.0.1:3080
PASS  remembered mode starts without re-probing
```

---

## 五、插件路径实测（真实内核）

**方法**：`tools/core-update-test/test_plugin_on_core.py` —— 用启动器自身的
`plugins.PluginManager`（即 `dsh plugin --profile web add/remove …` 转发路径 +
profile store 自愈）在真实实例上安装 / 列出 / 卸载随包 dshmarket，完成后恢复原状。

| 内核 | 结果 |
| --- | --- |
| dsh 0.1.1-rc.2 | **8/8 通过**：安装 dshmarket（`✔ Done in 634ms using pnpm v11.7.0`）→ 列表可见 → 卸载 → 列表恢复原状 |
| dsh 0.1.6-alpha.2 | **8/8 通过**：安装 / 列出 / 卸载同样正常（`✔ Lockfile passes supply-chain policies`） |

## 六、启动参数梯度实测（最新内核）

`test_launch_ladder.py` 在 dsh **0.1.6-alpha.2** 上同样 10/10 通过，包括：

- 首选参数直接启动并返回带 token 的地址（HTTP 200，cookie 会话）；
- 把两个坏参数候选放在最前面时，自动降级到第 3 个候选（用时 9.0s）并成功服务 UI；
- 内核日志实证：`error: unknown option '--definitely-not-a-flag'` →
  `error: unknown option '--no-such-option'` → `dsh web: http://127.0.0.1:3080/?token=…`。

> 说明：dsh ≥ 0.1.6 的 token 地址会先 303 跳转再用 Cookie 建立会话，因此测试助手
> 使用带 Cookie 的请求（与浏览器/WebView 行为一致）；不带 Cookie 直接请求会得到 401。

## 七、结论与遗留

- 三类缺陷（全屏塌陷、换核失败、界面不刷新）与两项内核适配缺陷（最新内核 401 鉴权地址、
  非英文 Windows 子进程解码崩溃）均已修复，并有可复现的量化证据；
- 全版本内核适配已通过“随包旧内核 ↔ 最新上游内核”**双向实测**（升级 + 降级 + 再升级），
  且新内核在该实例上完成了真实的浏览器渲染校验；
- 未在本机执行的部分：PyInstaller 重新打包 exe（本机无 PyInstaller/pywebview 环境）、
  自解压安装包（SFX）制作与 `smoke-release.ps1` 全流程——这些需要在带完整 Python 工具链
  的构建机上执行；相关代码路径已按同一规则调整，并有单元测试覆盖
  （CLI 入口解析式、UI 按版本刷新、`post-update.bat` 规则）。
