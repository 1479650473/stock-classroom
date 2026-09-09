# THEME.md — 多主题引擎快速参考

> stock-classroom 前端视觉系统。三套完整主题：**Graphite 石墨·冷调极简 / Obsidian 黑曜石·仪器质感 / Ivory 象牙·暖纸编辑风**。每套都是独立的质感语言，不是配色变体。

文档对应代码：`frontend/platform/theme.py`（token + QSS 生成）、`frontend/platform/premium.py`（卡片自绘工具）、`frontend/platform/platform_shell.py`（切换过渡）。

---

## 1. 切换 & 生效

| 项 | 说明 |
|---|---|
| 切换入口 | 设置 → 显示偏好 → **外观主题** 下拉 |
| 持久化 | `backend/configs/settings.json` 的 `theme` 字段（`desktop_app.py` 启动时 `set_theme` 记住） |
| 默认主题 | `graphite`（冷钢蓝，替代旧暖金主题） |
| 即时重绘链 | `theme.set_theme()` emit `signals.changed` → `platform_shell._on_theme_changed` → 重建全局 QSS + `kline.resync_theme()` + `findChildren` 对每控件调 `on_theme_changed()`（有则）否则 `update()` |
| 过渡动效 | `platform_shell._ThemeWipe`：切主题时一笔**斜向柔光带**左→右扫过 ~300ms（`math.sin(t·π)` 包络，深/浅 base alpha 34/30，光带宽 0.30·对角线）。`WA_TransparentForMouseEvents` 不拦鼠标 |

---

## 2. 架构：token & 素材在哪

| 文件 | 职责 |
|---|---|
| `theme.py` | `THEMES={graphite\|obsidian\|ivory}` 完整 token 集；`set_theme(key)`/`current_theme()`/`theme_key()`；`C_*` 模块常量随 `set_theme` 同步；`qss_*` 各控件样式（**obsidian 分支**）；`_graphite/_obsidian/_ivory_template` 全局模板；`build_style(key)` |
| `premium.py` | 共享工具包：`PAL`（随主题同步）、`card_qss`、`value_ss/label_ss/pill_ss`、`SectionTitle`、`CountUpLabel`（步进式）、`BreadthGauge`、`SplitBar`、**`MachinedWell` + `well(name)`**（卡片自绘，各主题专属笔触） |
| `platform_shell.py` | `_ThemeWipe` 过渡 + 重绘链；外壳 chrome（顶栏/导航/左右栈）已去内联背景，交全局 `QWidget` 背景 |

---

## 3. 三主题 Token 对比表

打 `·` 的是一套主题的核心色（同列对比）。

### 3.1 背景 & 面板
| token | graphite | obsidian | ivory |
|---|---|---|---|
| `bg` | `#0B0D11` | `#060708` | `#F3EEE6` |
| `panel` | `#14171C` | `#0E1012` | `#FBF8F2` |
| `raised` | `#1A1E24` | `#14171A` | `#FFFFFF` |
| `overlay` | `#20252C` | `#191C1F` | `#EFEAE0` |
| `border` | `#232830` | `#000000` | `#E2DBCC` |
| `border_soft` | `#1D222A` | `#111316` | `#ECE5D8` |
| `border_top` | `#2E343C` | `#2C3036` | `#D8CFBE` |

### 3.2 文字
| token | graphite | obsidian | ivory |
|---|---|---|---|
| `text` | `#E8EAED` | `#E8E3DA` | `#1C1917` |
| `sub` | `#9AA3B0` | `#9AA0A6` | `#8A8177` |
| `faint` | `#5C6670` | `#5E646B` | `#B4AC9F` |

### 3.3 强调色（accent）与语义色
| token | graphite | obsidian | ivory |
|---|---|---|---|
| `accent` | `#7AA2F7` 钢蓝 | `#E0A050` 琥珀 | `#8E3A2F` 氧化铁红 |
| `accent_hover` | `#8FB4FF` | `#EDB97A` | `#A04A3D` |
| `accent_dim` | `rgba(122,162,247,0.12)` | `rgba(224,160,80,0.12)` | `rgba(142,58,47,0.10)` |
| `on_accent` | `#0A0C10` | `#1A120A` | `#F7F2EA` |
| `up` | `#E5484D` | `#E0564D` | `#8E3A2F` |
| `down` | `#3FB950` | `#3FB950` | `#3F7D50` |
| `info` | `#7AA2F7` | `#E0A050` | `#8E3A2F` |
| `warn` | `#D29922` | `#D29922` | `#B07A2A` |

### 3.4 卡片渐变 & 圆角
| token | graphite | obsidian | ivory |
|---|---|---|---|
| `card_stops` | `#15181D→#12151A→#0E1115` | `#111315→#0D0F11→#0A0B0D` | `#FDFBF5→#FBF8F2→#F6F1E6` |
| `card_border` | `#232830` | `#000000` | `#E4DCCE` |
| `card_border_top` | `#2E343C` | `#2A2F34` | `#D9CFBE` |
| `card_hover_border` | `#333B45` | `#5C4630`（琥珀） | `#C7BA9F` |
| `radius_card` | `9` | `8` | `3`（纸感方角） |

### 3.5 选择 & 滚动
| token | graphite | obsidian | ivory |
|---|---|---|---|
| `sel_bg` | `rgba(122,162,247,0.15)` | `rgba(224,160,80,0.15)` | `rgba(142,58,47,0.12)` |
| `sel_fg` | `#AFC8FF` | `#F2D8AE` | `#7A2F25` |
| `row_alt` | `#12151A` | `#0D0F11` | `#F6F1E6` |
| `scroll_handle` | `#2A313B` | `#23272C` | `#DCD3C2` |

### 3.6 按钮渐变
| token | graphite | obsidian | ivory |
|---|---|---|---|
| `btn_grad` | `#1A1E24→#14171C` | `#111316→#0C0E10` | `#2A2621→#1C1917`（墨色） |
| `btn_grad_hover` | `#20262E→#181C22` | `#191C20→#111418` | `#3A352D→#242019` |
| `btn_border_top` | `#394049` | `#2A2F34` | `#3E372C` |
| `btn_text` | `#DDE2E8` | `#D6D1C8` | `#F3EEE6` |
| `accent_grad` | `#8AB2FF→#6C9DF2` | `#C99B5E→#A87C45` | `#9A4638→#7A2F25` |
| `accent_grad_hover` | `#9CC0FF→#7BA8F6` | `#DBB27A→#B98D50` | `#A55445→#87352A` |
| `accent_border` | `#7AA2F7` | `#C99B5E` | `#8E3A2F` |

---

## 4. 卡片笔触（`MachinedWell` / `well(name)`）

所有卡片背景由 `paintEvent` **每次从当前主题自绘**（非 QSS），切主题即时变、不需重建。建卡用 `well(name)`，**不要** `QFrame()+setStyleSheet(card_qss)`。

通用层：竖向哑光渐变（`card_stops`）+ 顶部高光斜面（`card_border_top`）+ 圆角。

**各主题叠层笔触：**

| 主题 | 笔触 | 技法 / 关键色 |
|---|---|---|
| **obsidian** | 金属嵌槽 | 竖向光泽（顶部白α20→0→底部黑α74）+ 顶边高光白α15 + 1px 内凹槽黑α110 + **拉丝纹**（横向明暗交替发丝，伪随机 `math.sin(row*12.9898)*43758.5453` 取小数，f>0.78 画暗线 a=8+10*(f-0.78)/0.22，否则亮线 a=10+10*f，确定性不闪）+ **四角螺丝**（径向导光 206,200,190→120,116,110→46,44,42 + 斜槽，仅卡 ≥120×80 才画） |
| **graphite** | 冷钢发丝 + 钢板边缘 | 极淡蓝灰横向发丝 `QColor(160,184,210,a)` a=3+4·frac（很淡）+ 1px 冷内嵌钢板线 `QColor(0,0,0,66)` |
| **ivory** | 纸压印 | 顶部暖内阴影 `QColor(90,60,30,26)`（0.12 处归 0）+ 底部纸感捕光 `QColor(255,255,250,66)` + 发丝压印缝 `QColor(0,0,0,20)` |

---

## 5. 控件与数据区：三主题的「质感方向」

每个主题用不同的景深体系（非 QPainter，走 QSS——QLineEdit/QComboBox 需转发子绘制，不可自绘）。`qss_*` helpers 按当前主题分支。

| 主题 | 普通按钮 | 主按钮 `qss_btn_accent`/刷新 | 输入框/下拉/数字框 | 表头 | 选中行 |
|---|---|---|---|---|---|
| **graphite** | 钢板上亮下亮翻边 | 钢蓝凸起金属板（顶边高光） | 凹陷冷钢（顶暗影+底捕光 `raised→panel→raised`） | 凹陷冷钢横轨 | 冷蓝渐入暗底 `sel_bg→rgba(0,0,0,.18)` |
| **obsidian** | 凹陷暗槽（顶 `#000` 阴影 + 底 `btn_border_top` 捕光 + 碗状渐变） | 凸起琥珀金属（顶 `accent_hover` 高光 + 底 `#000` 阴影） | 凹陷暗槽（同按钮） | 凹陷金属横轨（panel→bg→panel + 底 `#000` 凹槽） | 琥珀沉入槽 `sel_bg→rgba(0,0,0,.35)` |
| **ivory** | 墨印纸签（顶白高光 + 纸边 `border_top`） | 氧化红戳记纸签 | 纸压印凹槽（暖边 `border_top` + 底白 `#FFFFFF`） | 压印纸轨（`#FFFFFF→raised→#FFFFFF`） | 氧化红压印槽 `sel_bg→rgba(0,0,0,.05)` |

> 每个主题的这套 QSS 由三处共同保证：`qss_*` helpers（obsidian/graphite/ivory 分支）+ 对应 `_xxx_template` 的全局覆盖（无内联样式的控件）+ 卡片 `well()`。

---

## 6. 使用了主题素材的地方

- **卡片 (`well`)**：market 指数卡、holdings `_make_card`、trade 账户卡+新建卡、datacenter 概览卡+全景卡、datapipeline 状态卡、research `_StatCard`/`_SecCard`（MachinedWell 基类）。
- **数据区 (QSS)**：所有面板的 `qss_table`/`qss_input`/`qss_combo`/`qss_btn*`。
- **图表**：`kline/widget.py` 硬编码色走主题 token（保留 MA5/10/20/60 指标色）；`resync_theme()` 用 `current_theme()` 实时读（勿用 import 冻结 `C_*`）。
- **机加工框**：表/列表/树容器 = `#000`/深色边框 + `card_border_top` 顶边（`_obsidian_template` 等）。
- **外壳**：顶栏/导航/左右栈的背景已交给全局 `QWidget` 背景，切主题即跟。
- **无边框自绘标题栏 (v4.3)**：`platform_shell` 用 `Qt.FramelessWindowHint` + 顶栏右侧自绘窗口控制钮 `QPushButton#winBtn`(transparent→hover 高亮)；`QMainWindow{border:1px solid border;border-top:1px solid border_top}` 给无边框窗描边。拖动/边缘缩放走 `nativeEvent(WM_NCHITTEST)` → 标题栏 HTCAPTION / 边缘 HTLEFT..BOTTOM(8方向)。

---

## 7. 硬规则（避免破浅色主题 & 反复踩坑）

1. **勿硬编码 hex** 在插件卡片/行/调色板——否则 theme 切到 ivory（浅色）时仍卡深色。要读 `premium.PAL` / `theme.current_theme()` / `qss_*`。
2. **勿用 import 时冻结的 `C_*`** 做主题响应式绘制/样式（`kline` 实证：用冻结 `C_BG` 切主题后仍 `#060708`）。改主题需重读：`resync_theme()`/`on_theme_changed()` 用 `current_theme()`/`PAL`（live）。
3. **离屏抓屏不绘文字**：验证文案用 `.text()`/`.rowCount()`，验证视觉用**前台真实平台抓屏**（`QApplication`+`grab()`，`app.processEvents()` 跑数帧）。
4. **QSS 大括号**：含 `{}` 的 QSS 勿用 `.format()`（会把 `{background` 当字段 → KeyError），用字符串拼接或 f-string 里写 `{{`/`}}`。
5. **CountUpLabel 勿用墙钟计时**：`time.monotonic()`+QTimer 会卡中间值（本机 QTimer 快而 monotonic 慢 → t 不到 1）。按步数推进：`_steps=duration//interval`，每 `_tick` `_step+=1; t=_step/_steps`，确定性收敛。
6. **分组按钮 `objectName=indBtn`**：由全局主题着色，勿在插件里硬编码勾选态金色。
7. **克制**：去 AI 味——不加彩虹、无 emoji 于 UI 外壳（仅托盘通知可）、无紫色/蓝渐变背景；精致排版（轻量数字 `Segoe UI Light`+`font-weight:300`、字距 `letter-spacing:2px` 小标签、金色短杆小节标题）。

---

## 8. 维护提示

- 加 token：改 `THEMES[key]`，并同步 `qss_*`/模板对应引用（都在 `theme.py`）。
- 加卡片笔触：在 `MachinedWell.paintEvent` 针对 `theme_key()` 加 `elif` 分支（参考现有 obsidian/graphite/ivory）。
- 改切换动效：`platform_shell._ThemeWipe`（duration/alpha/band 宽度）。
- `build_style(key)` 生成合法 QSS；改完 `py_compile` + 三主题 `build_style` 大括号各自平衡 + 前台抓屏目检。
