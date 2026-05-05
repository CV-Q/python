# POI 抓取工具 — 使用说明（简明）

简介
本工具用于按任务配置从多个地图供应商（百度/高德/天地图等）抓取 POI 数据，支持增量导出、区域展开（省/市/县/网格）、调度与 GUI 操作。

依赖环境

- Python 3.8+
- 建议在虚拟环境中安装依赖：
    - `pip install -r requirements.txt`
    - 若需要 Excel 导出，请安装 `openpyxl`。

主要文件与目录

- `map_poi_fetcher.py`：核心调度与抓取逻辑（包含任务运行、缓存处理、区域规范化等）。
- `providers.py`：各地图供应商的网络请求实现（fetch_provider_records）。
- `gui_pyqt.py`：PyQt5 图形界面实现（推荐使用 GUI 操作任务/更新行政区）。
- `config/poi_config.json`：主配置文件，包含 api_keys、tasks、resources 等。
- `config/region_cache.json`：行政区缓存（仅保存名字或简化结构），GUI 从此构建区划树。
- `POI_Data/`：抓取结果输出目录（按日期分文件夹）。
- `logs/poi_fetcher_logs.jsonl`：运行日志文件。
- `tools/`：包含若干本地验证/模拟脚本（便于回归测试）。

快速开始

1. 准备配置文件：

   - 复制 `config/poi_config.example.json` 到 `config/poi_config.json`，填写 `api_keys`（baidu/gaode/tianditu）。
1. 安装依赖：

   - `pip install -r requirements.txt`
1. 启动 GUI：

   - `python map_poi_fetcher.py --gui --config config/poi_config.json`
1. 使用说明（GUI）：

   - 首次启动不会联网拉取行政区；如果需要更新行政区，请在 GUI 点击 “更新行政区” 并选择要拉取的省份（例如：京津冀+山西+陕西+河南+湖北）。
   - 配置任务（任务名、区域类型、资源类型、是否启用增量等），保存后单击“开始”运行任务。

关于行政区缓存与联网策略

- 程序启动时不会自动联网获取行政区数据，以避免无意的外网请求。只有在用户显式点击“更新行政区”时，才会调用高德（或其他）API并把抓取到的省/市/区数据合并到 `config/region_cache.json`。
- 为避免命名不一致导致的重复/缺失，工具内置了 `unify_region_cache` 来规范化 `region_cache` 的顶层省名（例如："河南" 与 "河南省" 会合并为统一键）。

增量（incremental）策略

- 增量文件保存在 `POI_Data/YYYY-MM-DD/任务名_incremental.csv`。
- 去重逻辑：仅与该增量文件中的 key 做比对，不会与历史所有文件合并去重（满足每任务增量的需求）。

常见操作命令

- 列出任务：`python map_poi_fetcher.py --list-tasks --config config/poi_config.json`
- 执行单个任务：`python map_poi_fetcher.py --run-task "任务名" --config config/poi_config.json`
- 执行所有任务：`python map_poi_fetcher.py --run-all --config config/poi_config.json`
- 导出日志：`python map_poi_fetcher.py --export-logs logs_export.json --config config/poi_config.json`

更新记录（简要）

- v0.2.0 (2026-04-18): 规范化 `region_cache` 并延后首次联网；GUI 从缓存加载；补充中文注释与使用说明文档；整合 USAGE 文档并修复若干语法/缩进问题，重构 `providers` 实现以改进天地图与高德的兼容性。本版本包含以下提交：
    - 165dd97 2026-04-17 chore: add provider data_type_map JSON files (gaode/tianditu/baidu) and conversion script
    - e03ff45 2026-04-16 feat: auto-generate provider-specific minimal config after first successful provider response
    - ab39ced 2026-04-16 feat(gui): add region/resources tree multi-select UI and support Tianditu in provider dropdown
    - d816af1 2026-04-16 feat: add Tianditu provider and provider-specific config support; replace Tencent with Tianditu
    - 52e59bd 2026-04-16 chore: freeze dependencies and update requirements.txt
    - 5123acf 2026-04-16 docs: document desensitized config example and .gitignore update
    - 6584700 2026-04-16 chore: add desensitized config example and update .gitignore to exclude secrets and build artifacts
    - c09eca0 2026-04-13 docs: normalize changelog format in README
    - 0bcc5b6 2026-04-13 docs: add brief summary of recent updates
    - c2a28dc 2026-04-13 docs: update README with latest commit 8ef4265
- v0.1.0: 规范化 region_cache 并延后首次联网；GUI 从缓存加载；补充中文注释与使用说明文档。

故障排查

- 若 GUI 未显示某省/市：请先在 GUI 中点击“更新行政区”并选择相关省份进行合并；或运行 `tools/run_unify_cache.py` 来执行缓存规范化。
- 若抓取结果为空或数量异常：检查 `config/poi_config.json` 中的 `api_keys` 与 `provider` 设置，查看 `logs/poi_fetcher_logs.jsonl` 中的异常信息。

联系我们

- 若需进一步帮助，请在工作区内打开 issues 或直接在代码注释中查找维护者联系方式（如有）。

注意事项

- 使用 provider API 需要在配置文件中设置相应的 API key（`config/poi_config.json`）。
- Excel 导出需要 `openpyxl`。


## 2026-05-05 变更记录

- 配置模型收口为单一 `config/poi_config.json`，运行时仅使用 `tasks[*]` 中的 `provider`、`resources` 与 `admin_regions`，移除了旧的顶层兼容字段依赖。
- 高德与天地图任务资源以编码保存和回显，GUI 保存任务时保留用户原始行政区选择，不再在保存阶段把“全部”展开成完整区县列表。
- 修复任务切换时的行政区回显问题：当配置为整省或整市时，界面会正确恢复省级或市级勾选，不再被父节点状态推导覆盖。
- 行政区统一以 `config/region_cache.json` 为准，并按高德标准名称规范化；普通启动和刷新不再回写缓存，只有显式更新行政区时才会触发更新写入。
- 查询执行收口为串行模式：并发数固定为 `1`，高德与天地图的运行时区域展开、分页累计、自动调度到期判断和单次请求失败后最多重试 `2` 次已经补齐回归验证。

本轮已验证的回归脚本：

- `tests/test_task_only_config.py`
- `tests/test_gui_save_task_resources.py`
- `tests/test_gui_save_task_regions.py`
- `tests/test_gui_load_task_regions.py`
- `tests/test_region_cache_standardization.py`
- `tests/test_runtime_subtasks_and_paging.py`
- `tests/test_scheduler_due_logic.py`
- `tests/test_request_retry.py`
- `tests/test_serial_execution_only.py`

## 2026-04-20 变更记录

- 修复：最终去重逻辑现在使用任务开始时的增量键快照，避免本次运行期间已追加到增量文件的数据被误判为“已存在”从而导致内存结果被全部去重（参见 map_poi_fetcher.py）。
- 修复：修正多行政区展开问题，确保选择多个区/县时会为每个行政区生成并执行子任务。
- 改进：`gui_pyqt.py` 中移除“全局设置”选项卡；在保存任务时同时保存导出格式 `export_format` 到全局配置，并在保存时把 `gaode`/`tianditu` 的资源码转回中文名称再写入任务配置。

测试/验证建议：

- 在 GUI 中保存任务（包含天地图或高德的资源代码），检查 `config/poi_config.json` 中 `tasks[].resources` 是否为中文名称且 `export_format` 已更新。
- 运行一个真实任务并观察日志最后一行的“抓取总数 / 去重后 / 输出”是否合理。