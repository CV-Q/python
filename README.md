# POI Fetcher (保障资源 POI 抓取与调度工具)

简要说明：这是一个用于抓取百度/高德/腾讯等地图服务 POI 的调度器与工具，支持任务配置、调度、并发执行以及 CSV/JSON/Excel 导出。

主要变更（最近一次提交）：

- 将通用工具提取到 `poi_utils.py`（I/O、导出、日志、去重、坐标转换等）。
- 将地图提供商客户端提取到 `providers.py`（`fetch_baidu`、`fetch_gaode`、`fetch_tencent`、`fetch_provider_records`）。
- 将 PyQt GUI 提取到 `gui_pyqt.py`（`create_gui_pyqt`），并在 `map_poi_fetcher.py` 中使用延迟导入代理。
- 在 `archive/` 中保留了 `map_poi_fetcher_pyqt_backup.py` 作为 GUI 的归档备份。
- 运行并通过了语法检查与快速 smoke test（`map_poi_fetcher.py --help`）。

快速开始：

1. 安装依赖（建议在虚拟环境中）：

```bash
pip install -r requirements.txt
# 可选：pip install PyQt5 openpyxl
```

2. 初始化默认配置：

```
python map_poi_fetcher.py --init-config
```

3. 运行图形界面（PyQt，可选）：

```
python map_poi_fetcher.py --gui
```

4. 命令行帮助：

```
python map_poi_fetcher.py --help
```

注意事项：

- 使用 provider API 需要在配置文件中设置相应的 API key（`config/poi_config.json`）。
- Excel 导出需要 `openpyxl`。

并发与速率限制建议：

- `max_concurrency`：全局并发上限，默认用于 GUI 中任务执行器和作为其它并发设置的默认备份值。增大此值会提高并发任务的吞吐，但也会增加对 CPU、网络和第三方 API 的压力，建议在 1–8 之间根据机器与 API 配额调整。
- `province_expand_concurrency`：当在界面选择“省 -> 全部城市”展开抓取（即城市选择为“全部”）时，控制同时并发请求多少个市。建议值 2–4（比 `max_concurrency` 更保守），可在 GUI 的“全局设置”中配置。
- `province_expand_delay_seconds`：全局最小请求间隔（秒），用于在省级展开时对请求做速率限制以避免触发 API 限速或短时间内被封禁。默认 0.5s；对百度类接口建议设置为 0.8–1.5s 更稳妥。当前实现基于全局锁与 `last_call` 时间实现简易间隔控制；若需更平滑的速率控制（令牌桶等），可进一步改进实现。

使用建议：

- 对于小规模抓取（单市或少量市），`province_expand_concurrency` 可设置较低以减少并发压力。
- 对于覆盖整省的批量抓取，优先降低并发并增加 `province_expand_delay_seconds`，以防 API 响应不完整或被限流。
- 在生产环境运行前，请先在小范围内（1-2 个市）测试配置，确认不会触发第三方服务的限流或错误返回。

确保“无并发”与统一延迟（针对省/市/区县的应用说明）

- 目标：不使用并发，且把省展开时的并发数与延迟作为所有 POI 查询的并发/延迟策略（包括市与区县）。
- 推荐配置：在 `config/poi_config.json`（或通过 GUI 全局设置）将以下项设置为：

```json
{
	"province_expand_concurrency": 1,
	"province_expand_delay_seconds": 1.0
}
```

- 含义：
    - `province_expand_concurrency = 1`：省级展开时按序处理城市（不并发）。
    - `province_expand_delay_seconds = 1.0`：全局最小请求间隔为 1 秒，代码会在每次对第三方 provider 发起请求前确保至少间隔该时长（适用于省/市/区县级别的所有查询）。
- 行为细节：当任务在市级选择为“全部”时，程序会遍历该市下的区/县并逐一查询（顺序执行、受上述延迟控制）；当任务在省级选择为“全部”时，程序会遍历省内各市并对每市按需遍历区/县，均为顺序执行且受统一延迟控制。
- 验证：在小规模（1-2 个市）运行任务并在日志中观察请求时间戳，确认相邻请求之间的时间差不小于 `province_expand_delay_seconds`。

回退与历史：归档文件存放在 `archive/`，如果需要恢复旧实现，可参考其中的备份文件。

作者/维护：项目重构由团队进行，变更已提交到本地 git 仓库。

更新记录（按时间倒序，最近重要提交）：

- `0bcc5b6` (2026-04-13) — docs: add brief summary of recent updates
    - 在 README 中添加本次更新的简要摘要，归纳 GUI 与后端改动要点。
- `8ef4265` (2026-04-13) — chore(gui): expose scheduler.check_interval_minutes; localize provider names; resource example; fix global save button
    - 在 GUI 中暴露 `scheduler.check_interval_minutes`（调度检查间隔，单位：分钟）。
    - 将“提供商”下拉本地化为中文显示（百度/高德/腾讯），保存时映射为内部键。
    - 将 `资源` 示例改为英文 JSON（如 `["gas_station","service_area","hospital"]`），并支持粘贴 JSON 列表或以中/英文逗号分隔的关键词；保存时智能解析并写入配置。
    - 修复并绑定“保存全局设置”按钮，确保在全局设置页点击后能正确写入配置文件。
- `9749040` (2026-04-13) — feat: add '全部' UI options; expand province->cities with configurable concurrency/rate-limit
    - 在城市与区县下拉中加入“全部”选项；当任务城市字段为空（表示“全部”）时，`run_task` 会展开为对该省下所有城市逐市抓取并合并去重结果，提升省级抓取完整性。
    - 新增并发/速率控制配置：`province_expand_concurrency` 与 `province_expand_delay_seconds`，可在 GUI 中调整以避免触发第三方 API 限流。
    - 单市抓取失败会记录为子任务失败日志，但不会中断整个省级任务，便于重试与故障排查。

完整历史请使用 `git log --oneline` 或 `git show <commit>` 查看详细条目。

注意：省级展开会大量增加对第三方地图服务的请求量，请在生产环境使用前配置合适的并发与延迟并先在小规模上进行试验。

- 归档与回退：保留了原 Tk 界面与早期 PyQt 实现的备份文件在 `archive/` 目录，便于回退与对比。

注意：省级展开会大量增加对第三方地图服务的请求量，请在生产环境使用前配置合适的并发与延迟并先在小规模上进行试验。

**本次更新摘要**

- 本次提交（短哈希：8ef4265 / README 提交：c2a28dc）：
    - 在 GUI 中暴露并可配置 `scheduler.check_interval_minutes`（调度检查间隔，单位：分钟）。
    - 将“提供商”下拉本地化为中文显示（百度 / 高德 / 腾讯），并在保存时映射为内部键。
    - 将 `资源` 示例改为英文 JSON（例如 `["gas_station","service_area","hospital"]`），并在界面中显示为可复制的示例。
    - 支持在 `资源` 输入中粘贴 JSON 列表，或使用英文/中文逗号分隔的关键字；保存时会智能解析并写入配置。
    - 修复了“保存全局设置”按钮未绑定的问题（`保存全局设置` 现在会调用保存函数并写入配置文件）。
    - 后端 `map_poi_fetcher.py` 支持将未知资源项作为原生关键词（支持中文关键词），并按中/英文逗号拆分，保留原有已知资源展开逻辑。

**本次提交：脱敏配置与忽略规则**

- 新增 `config/poi_config.example.json`：脱敏示例配置，`api_keys` 字段已替换为 "<REDACTED>"，用于在不暴露真实密钥的情况下运行或共享。
- 新增 `.gitignore`：已添加规则以忽略 `config/poi_config.json`、`POI_Data/`、`logs/`、`build/`、`bin/` 等运行与构建产物。

使用说明：

- 已在仓库根生成 `config/poi_config.example.json`，请使用该示例作为共享或存档版本。
- 请勿将 `config/poi_config.json`（含真实 API keys）提交到远程仓库；真实密钥应存放在安全的秘钥管理系统或环境变量中。

后续选项：

- 我可以为您生成并提交 `requirements.freeze.txt`（可复现依赖快照）。
- 如果需要彻底从 Git 历史中移除已泄露的密钥，我可以指导或执行使用 `git-filter-repo` / BFG 的清理步骤（这将重写历史，请谨慎）。