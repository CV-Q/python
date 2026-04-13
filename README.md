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

```
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

回退与历史：归档文件存放在 `archive/`，如果需要恢复旧实现，可参考其中的备份文件。

作者/维护：项目重构由团队进行，变更已提交到本地 git 仓库。

最新提交记录：

- 提交哈希：`9749040`（短哈希）
- 提交说明：feat: add '全部' UI options; expand province->cities with configurable concurrency/rate-limit; expose in GUI and README
- 提交时间：2026-04-13

（如果需要精确回退或查看变更，请在仓库中使用 `git log` 或 `git show 9749040`。）
