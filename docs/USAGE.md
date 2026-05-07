POI 抓取工具 — 使用说明（简明）

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
2. 安装依赖：
   - `pip install -r requirements.txt`
3. 启动 GUI：
   - `python map_poi_fetcher.py --gui --config config/poi_config.json`
4. 使用说明（GUI）：
   - 首次启动不会联网拉取行政区；如果需要更新行政区，请在 GUI 点击 “更新行政区” 并选择要拉取的省份（例如：京津冀+山西+陕西+河南+湖北）。
   - 配置任务（任务名、区域类型、资源类型、是否启用增量等），保存后单击“开始”运行任务。

关于行政区缓存与联网策略
- 程序启动时不会自动联网获取行政区数据，以避免无意的外网请求。只有在用户显式点击“更新行政区”时，才会调用高德（或其他）API并把抓取到的省/市/区数据合并到 `config/region_cache.json`。
- 为避免命名不一致导致的重复/缺失，工具内置了 `unify_region_cache` 来规范化 `region_cache` 的顶层省名（例如："河南" 与 "河南省" 会合并为统一键）。

增量（incremental）策略
- 增量文件保存在 `POI_Data/incremental/<provider>/<provider>-<province>_incremental.csv`。
- 去重逻辑：仅与对应 `provider+province` 的固定增量文件中的 key 做比对，可跨天复用历史基线。
- 全量快照导出保持不变，仍输出到 `POI_Data/YYYY-MM-DD/任务名_YYYYMMDD_HHMMSS.csv`。

常见操作命令
- 列出任务：`python map_poi_fetcher.py --list-tasks --config config/poi_config.json`
- 执行单个任务：`python map_poi_fetcher.py --run-task "任务名" --config config/poi_config.json`
- 执行所有任务：`python map_poi_fetcher.py --run-all --config config/poi_config.json`
- 导出日志：`python map_poi_fetcher.py --export-logs logs_export.json --config config/poi_config.json`

更新记录（简要）
- v0.1.0: 规范化 region_cache 并延后首次联网；GUI 从缓存加载；补充中文注释与使用说明文档。

故障排查
- 若 GUI 未显示某省/市：请先在 GUI 中点击“更新行政区”并选择相关省份进行合并；或运行 `tools/run_unify_cache.py` 来执行缓存规范化。
- 若抓取结果为空或数量异常：检查 `config/poi_config.json` 中的 `api_keys` 与 `provider` 设置，查看 `logs/poi_fetcher_logs.jsonl` 中的异常信息。

联系我们
- 若需进一步帮助，请在工作区内打开 issues 或直接在代码注释中查找维护者联系方式（如有）。
