# 前端美化计划 — stock-classroom

> 创建时间: 2026-08-27
> 最后更新: 2026-08-27
> 状态: 进行中

## 总览

对 stock-classroom PyQt5 桌面端进行全面前端美化，覆盖三套主题（Graphite/Obsidian/Ivory），统一所有面板的视觉语言。

---

## Phase 1: 核心主题系统升级

**目标**: 升级 `theme.py` 和 `premium.py`，为所有主题添加更丰富的视觉 token

### 1.1 theme.py 增强
- [ ] 添加阴影/glow token: `card_shadow`, `hover_glow`
- [ ] 添加过渡时间 token: `transition_fast` (150ms), `transition_normal` (250ms)
- [ ] 增强 `qss_table()`: 更好的交替行色、hover 效果、header 样式
- [ ] 新增 `qss_scrollbar()`: 统一滚动条样式
- [ ] 新增 `qss_tooltip()`: 精致 tooltip 样式
- [ ] 新增 `qss_menu()`: 右键菜单样式
- [ ] 为三个主题分别优化渐变参数

### 1.2 premium.py 增强
- [ ] MachinedWell: 更柔和的阴影、更好的 hover 反馈
- [ ] 新增 `pill_qss()`: 药丸状态标签样式函数
- [ ] 新增 `badge_qss()`: 徽章样式函数
- [ ] 增强 SectionTitle: 更精致的短杆+文字排版

---

## Phase 2: 导航栏 & 窗口框架

**目标**: 美化 `platform_shell.py` 的导航栏和顶栏

### 2.1 导航栏 (Nav Rail)
- [ ] 优化导航按钮 hover/checked 过渡效果
- [ ] 改进选中态视觉指示（左侧金色条 already exists, refine width/animation）
- [ ] 增加导航按钮的 tooltip 浮层样式
- [ ] 优化分组标题的排版

### 2.2 顶栏 (Topbar)
- [ ] 优化品牌文字排版和间距
- [ ] 改进搜索框的圆角和 focus 效果
- [ ] 优化窗口控制按钮（最小化/最大化/关闭）的 hover 效果
- [ ] 改进 K线/刷新/日志 按钮的视觉层级

### 2.3 抽屉动画
- [ ] 为右侧 K线抽屉添加平滑滑入/滑出动画

---

## Phase 3: 卡片 & 面板统一

**目标**: 统一所有面板的卡片使用和间距规范

### 3.1 卡片标准化
- [ ] 所有面板的 QFrame 卡片统一使用 `well("card")` 或 `card_qss()`
- [ ] 统一卡片内边距: `dp(12) dp(10)` (外层), `dp(10) dp(8)` (内层)
- [ ] 统一卡片间距: `dp(8)` ~ `dp(10)`

### 3.2 面板间距规范
- [ ] 面板顶级 margin: `dp(14) dp(12)` 
- [ ] 面板内 section 间距: `dp(10)`
- [ ] 统一所有面板的 title + subtitle 排版模式

### 3.3 需要统一的面板
- [ ] overview/panel.py — 核心账户卡、市场卡
- [ ] market/panel.py — 指数卡片、板块表
- [ ] picks/panel.py — 过滤栏
- [ ] holdings/panel.py — 账户摘要卡、持仓卡片
- [ ] trade/panel.py — 摘要卡片、下单面板
- [ ] research/panel.py — 诊断卡片、因子卡片
- [ ] agentops/panel.py — 摘要卡片、日志区域
- [ ] datapipeline/panel.py — 状态卡片、步骤表
- [ ] datacenter/panel.py — 概览卡片
- [ ] flow/panel.py — 流程卡片

---

## Phase 4: 表格 & 列表打磨

**目标**: 统一提升所有表格和列表的视觉质量

### 4.1 表格统一
- [ ] 增强 `qss_table()`: 更好的行高、hover 高亮、选中态发光
- [ ] 统一列宽策略: 代码列 dp(65), 名称列 dp(80), 数值列 dp(65)
- [ ] 统一 header 样式: 字距、字重、底部分隔线
- [ ] 优化空状态显示

### 4.2 列表统一
- [ ] 增强 `qss_list()`: 更好的 item 间距和 hover
- [ ] 统一股票列表的选中态

---

## Phase 5: 按钮 & 输入控件

**目标**: 精细化所有交互控件的视觉体验

### 5.1 按钮
- [ ] 优化普通按钮 hover/press 过渡
- [ ] 完善 accent 按钮（金色主按钮）的视觉层级
- [ ] 改进 segmented toggle 按钮的统一样式
- [ ] 优化 indBtn (indicator button) 的 checked 态

### 5.2 输入控件
- [ ] 改进 QLineEdit focus 时的 accent glow 效果
- [ ] 优化 QComboBox 下拉箭头和选中态
- [ ] 改进 QSpinBox/QDoubleSpinBox 的 hover/focus 态
- [ ] 优化 QCheckBox indicator 的 checked 态动画

---

## Phase 6: 动画 & 微交互

**目标**: 为 UI 添加适度的动画效果，提升操作反馈

### 6.1 过渡动画
- [ ] 按钮 hover 颜色过渡 (CSS transition)
- [ ] 卡片 hover 边框过渡
- [ ] 导航按钮 checked 态过渡

### 6.2 数值动画
- [ ] CountUpLabel 已存在，确保所有数值面板使用它
- [ ] 优化 CountUpLabel 的 ease-out 曲线

### 6.3 加载状态
- [ ] 统一 loading 状态的视觉表现（旋转/脉冲）

---

## Phase 7: 各面板专项清理

**目标**: 修复遗留问题，确保所有面板遵循主题系统

### 7.1 trainer/panel.py
- [ ] 移除本地 `styles.py` 依赖，改用 `frontend.platform.theme`
- [ ] 使用 `well("card")` 包裹占位内容

### 7.2 datacenter/panel.py
- [ ] 移除硬编码 `BG_EVEN`, `BG_ODD`, `C_BORDER`
- [ ] 改用主题 token: `PAL['c_mid']`, `PAL['bg']`, `PAL['border_lo']`

### 7.3 settings/dialog.py
- [ ] 移除硬编码颜色 `C_NAV_BG`, `C_NAV_HOVER`, `C_NAV_SELECTED`
- [ ] 使用主题 token 替代
- [ ] 改进对话框整体视觉风格

### 7.4 全局检查
- [ ] 确保所有面板实现 `on_theme_changed()` 方法
- [ ] 确保所有面板的 `on_theme_changed()` 正确重绘所有子组件
- [ ] 检查并修复所有硬编码颜色值

---

## 进度日志

| 日期 | 完成内容 | 备注 |
|------|---------|------|
| 2026-08-27 | 创建计划文档 | 初始版本 |
| | | |
