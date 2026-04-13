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

回退与历史：归档文件存放在 `archive/`，如果需要恢复旧实现，可参考其中的备份文件。

作者/维护：项目重构由团队进行，变更已提交到本地 git 仓库。
