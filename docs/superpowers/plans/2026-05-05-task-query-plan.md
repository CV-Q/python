# Task Query Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让高德与天地图任务在界面配置、配置文件、运行时拆分、分页、调度、重试上保持一致。

**Architecture:** GUI 仅保存用户原始任务定义，运行层负责根据 region_cache 和 data_type_tree 动态展开。资源以编码持久化，行政区域以原始选择持久化，调度与重试集中在运行层收口。

**Tech Stack:** Python, PyQt5, JSON config, 自定义 providers, 现有轻量回归脚本

---

### Task 1: 锁定任务保存/回显行为

**Files:**
- Modify: `tests/test_gui_save_task_resources.py`
- Modify: `gui_pyqt.py`

- [ ] 扩展 GUI 回归脚本，断言 admin_regions 保存为原始选择而不是展开结果。
- [ ] 运行 GUI 回归脚本并确认先失败。
- [ ] 最小修改 save_task/load_task，使资源编码与 admin_regions 原始选择都能正确保存和回显。
- [ ] 复跑 GUI 回归脚本直到通过。

### Task 2: 锁定高德/天地图运行时拆分与分页

**Files:**
- Create: `tests/test_runtime_subtasks_and_paging.py`
- Modify: `map_poi_fetcher.py`

- [ ] 编写回归脚本，构造“省/市/全部”任务，断言运行时子任务数量、分页累积结果与最终去重结果正确。
- [ ] 运行脚本并确认先失败。
- [ ] 修复 run_task 中子任务拆分、分页累计和重复队列问题。
- [ ] 复跑脚本直到通过。

### Task 3: 收口高级配置为串行执行

**Files:**
- Modify: `gui_pyqt.py`
- Modify: `map_poi_fetcher.py`
- Modify: `config_loader.py`

- [ ] 增加回归断言或脚本，验证 max_concurrency 为 1 时只走顺序执行。
- [ ] 运行验证并确认当前仍可能走并发分支或允许非 1 值。
- [ ] 将 GUI 和运行层都收口到并发数 1，统一使用查询间隔配置。
- [ ] 复跑相关回归。

### Task 4: 修正自动调度

**Files:**
- Create: `tests/test_scheduler_due_logic.py`
- Modify: `map_poi_fetcher.py`

- [ ] 编写调度回归脚本，验证仅根据最近 success 日志判断是否到期。
- [ ] 运行脚本并确认当前行为有缺口则失败。
- [ ] 修正 due 逻辑与自动启动路径。
- [ ] 复跑脚本直到通过。

### Task 5: 增加失败重试

**Files:**
- Create: `tests/test_request_retry.py`
- Modify: `map_poi_fetcher.py`
- Modify: `providers.py`（仅在接口签名需要时）

- [ ] 编写回归脚本，断言单个请求失败后最多再重试 2 次。
- [ ] 运行脚本并确认先失败。
- [ ] 在 execute_subtask/fetch_with_delay 链路加入最小重试实现。
- [ ] 复跑脚本直到通过。

### Task 6: 总体验证

**Files:**
- Modify: `tests/test_task_only_config.py`（如需补断言）

- [ ] 运行全部回归脚本：`test_task_only_config.py`、`test_gui_save_task_resources.py`、新增的 3 个脚本。
- [ ] 检查变更文件无静态错误。
- [ ] 若有失败，仅修当前失败切片并重复验证。
