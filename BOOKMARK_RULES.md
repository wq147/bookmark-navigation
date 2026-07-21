# 个人书签维护与分类规则

> 适用对象：需要长期维护的 Chrome / Edge 书签体系
> 当前基准版本：V5
> 核心目标：**收藏快、找到快、长期维护成本低。**

---

## 1. 核心原则

### 1.1 按“以后会去哪里找”分类

不要优先问：

> 这个网站技术上属于什么？

应该问：

> **以后我要找它时，第一反应会进入哪个目录？**

例如：

- Wireshark → `03_网络工程与安全 / 05_网络工具与测试`
- Docker Hub → `04_Linux、服务器与云 / 02_容器与 Docker`
- Codex 文档 → `02_AI 与智能开发 / 02_Codex、OpenCode 与 AI 编程`
- OpenWrt 固件 → `09_设备、玩机与实验室 / 02_路由与刷机 / 01_OpenWrt`

### 1.2 一个 URL 只保留一个主位置

同一个 URL 不重复保存到多个目录。

例外：高频入口优先保留在 `01_常用`，其他目录中的重复副本删除。

### 1.3 新书签先进入 `00_待整理`

平时收藏时不要被分类打断：

```text
Ctrl/Cmd + D
    ↓
00_待整理
```

建议每两周集中整理一次。

### 1.4 分类体系不是写死的

一级目录尽量保持稳定；二级及更深目录允许根据实际积累变化。

目录定义、优先顺序和自动分类规则集中保存在：

```text
bookmark_policy.json
```

以后需要新增、删除、重命名或调整优先级，优先修改 JSON，不改 Python 代码。

---

## 2. 当前一级目录

```text
00_待整理
01_常用
02_AI 与智能开发
03_网络工程与安全
04_Linux、服务器与云
05_开发、自动化与 DevOps
06_工具与在线服务
07_软件、系统与桌面工具
08_学习、资料与社区
09_设备、玩机与实验室
10_影音、阅读与娱乐
11_工作与项目
90_历史归档
```

一级目录已经比较稳定，除非长期工作方向发生明显变化，否则不建议频繁调整。

---

## 3. 子目录编号规则

### 3.1 所有子目录都编号

一级目录保持固定编号；二级、三级、四级目录在各自父目录内从 `01_` 开始独立编号。

示例：

```text
03_网络工程与安全
├── 01_H3C
│   ├── 01_官方文档、社区与工具
│   ├── 02_案例与配置
│   ├── 03_产品与解决方案
│   └── 04_学习与认证
├── 02_华为
└── 03_网络基础与学习
```

### 3.2 编号要求

同级目录必须满足：

- 从 `01` 开始；
- 连续编号；
- 不重复；
- 不缺号；
- 显示顺序与编号顺序一致。

新增或删除目录后，不手工逐个改编号，运行：

```bash
python3 bookmark_numbering.py bookmarks.html \
  --policy bookmark_policy.json \
  -o bookmarks_numbered.html
```

---

## 4. 建目录规则

一般建议：

```text
1～2 个书签  → 通常不单独建目录
3～5 个      → 视长期积累价值决定
6 个以上     → 可以独立建目录
20 个以上    → 检查是否需要继续拆分
```

长期主线可以提前保留，即使当前数量较少，例如：

- H3C
- 华为
- Codex、OpenCode 与 AI 编程
- 模型与本地部署
- OpenWrt
- 软路由与虚拟化
- 5G、MIFI 与随身 WiFi
- PCDN
- macOS 与 Homebrew
- 串流与远程

---

## 5. 禁止形成“大杂项桶”

尽量避免以下目录名：

```text
其他
杂项
综合
常用工具
实用工具
软件
玩机
资料
教程
```

因为这类目录容易无限膨胀，最终失去定位价值。

确实需要临时放置时，用：

```text
00_待整理
```

已失效但不想删除时，用：

```text
90_历史归档
```

---

## 6. 标题命名规则

网站默认标题过长时，建议改为：

```text
产品或项目名 - 简短用途
```

例如：

```text
Wireshark - 抓包分析
LinuxMirrors - Linux 一键换源
Ventoy - 多系统启动盘
OpenWebStart - JNLP 启动器
NetTopo - 网络拓扑设计
```

目的不是追求统一格式，而是方便浏览器地址栏直接搜索用途关键词。

---

## 7. 当前个性化分类逻辑

### 7.1 AI 与智能开发

```text
02_AI 与智能开发
├── 01_AI 助手与搜索
├── 02_Codex、OpenCode 与 AI 编程
├── 03_模型、API 与算力
├── 04_模型与本地部署
├── 05_AI 绘图与生成
├── 06_AI 智能体、自动化与集成
└── 07_聚合与中转
```

原则：不再按“国内 / 国际”分类，而是按使用场景分类。

### 7.2 网络工程与安全

优先顺序符合日常工作主线：

```text
H3C
→ 华为
→ 网络基础
→ 网络实验与仿真
→ 网络工具
→ 域名/DNS/IP/诊断
→ 远程接入
→ 代理客户端
→ 代理服务
→ 服务端搭建
→ 安全
```

### 7.3 Linux、服务器与云

```text
Linux 系统与运维
→ Docker
→ Linux 面板
→ 自建服务
→ 云平台与云主机
→ 自动化脚本与青龙
```

### 7.4 设备、玩机与实验室

```text
本地设备入口
→ 路由与刷机
→ 软路由与虚拟化
→ 5G/MIFI/随身 WiFi
→ 通信/物联网/短信转发
→ 手机/ROM/Android
→ ARM 设备/硬件/维修
→ 串流
→ PCDN
```

---

## 8. 标准维护流程

### 平时

```text
新书签
  ↓
00_待整理
```

### 每两周

逐个判断：

1. 值不值得保留？
2. 以后第一反应会去哪找？
3. 是否已经存在重复 URL？
4. 是否应该进入历史归档？

### 每 3 个月

导出 HTML 后执行完整流程：

```text
原始 HTML
    ↓
bookmark_organizer.py
    ↓
全量重新归类 + 去重 + 编号
    ↓
bookmark_audit.py
    ↓
检查重复、空目录、小目录、大目录、泛化目录、编号问题
    ↓
保存新版本
```

---

## 9. 自动整理命令

### macOS / Linux

```bash
python3 bookmark_organizer.py bookmarks.html \
  --policy bookmark_policy.json \
  -o bookmarks_organized.html \
  --report organizer_report.json
```

### Windows PowerShell

```powershell
py .\bookmark_organizer.py .\bookmarks.html `
  --policy .\bookmark_policy.json `
  -o .\bookmarks_organized.html `
  --report .\organizer_report.json
```

自动整理会：

- 对每个书签执行分类规则；
- 清空可以明确归类的 `00_待整理` 内容；
- 未知内容仍保留在 `00_待整理`，不会强行猜测；
- 删除重复 URL；
- 保留书签标题、URL、图标和时间属性；
- 给所有子目录重新编号。

---

## 10. 审计命令

```bash
python3 bookmark_audit.py bookmarks_organized.html \
  --policy bookmark_policy.json \
  -o bookmark_audit_report.md \
  --json bookmark_audit_report.json
```

默认检查：

- 总书签数；
- 重复 URL；
- 重复标题；
- 空目录；
- 小型叶子目录；
- 超大目录；
- 泛化目录名称；
- `00_待整理` 数量；
- `90_历史归档` 数量；
- 一级目录编号；
- 子目录缺少编号；
- 同级重复编号；
- 编号缺号；
- 编号与显示顺序不一致；
- 私网、本地 URL；
- 疑似带 token、key、password 等敏感参数的 URL。

联网检查外部链接：

```bash
python3 bookmark_audit.py bookmarks_organized.html \
  --policy bookmark_policy.json \
  --check-links
```

默认跳过：

- 私网地址；
- localhost；
- 疑似包含敏感参数的 URL。

---

## 11. 修改分类体系

所有分类优先级和自动分类规则都在：

```text
bookmark_policy.json
```

主要字段：

```text
top_level_order
    一级目录顺序

child_order
    每个父目录下的子目录优先顺序

core_small_folders
    允许长期保留的小目录

generic_folder_names
    审计时判定为泛化的目录名

classification.exact_url_overrides
    指定 URL 的精确归类

classification.title_rules
    基于标题/URL 关键词的规则

classification.fallback_path_map
    现有目录到新目录的兜底映射
```

修改策略后，先用副本测试，不直接覆盖唯一书签文件。

---

## 12. 安全规则

书签 HTML 可能包含：

- 私网 IP；
- 本地管理地址；
- token；
- key；
- session；
- 其他登录参数。

因此：

1. 不随意公开上传完整书签文件；
2. 不把含敏感参数的 URL 展开写进公开报告；
3. 联网检测默认跳过私网和敏感 URL；
4. 每次修改前保留原始导出文件。

---

## 13. 推荐版本管理方式

文件命名：

```text
private-bookmarks-input.html
bookmarks_personalized_v6_2026_10_01.html
```

建议长期保留：

```text
latest/
    bookmarks_latest.html
    bookmark_policy.json
    BOOKMARK_RULES.md
    bookmark_organizer.py
    bookmark_numbering.py
    bookmark_audit.py

archive/
    v4/
    v5/
    ...
```

---

## 14. 最终目标

不要追求“完美分类”。

真正有价值的是：

- 收藏时不被打断；
- 以后能快速找到；
- 目录结构不会失控；
- 规则可以持续演进；
- 自动化脚本负责重复劳动，人工只负责最终判断。
