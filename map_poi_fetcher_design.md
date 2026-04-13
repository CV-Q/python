# map_poi_fetcher.py 项目设计方案与优化历史

## 1. 项目目标

- 提供一个统一的地图 POI 抓取工具，支持百度、高德、腾讯三个常用地图服务。
- 支持可配置 API Key，能够抓取医院、仓库、学校、超市、汽车修理厂、加油站等 POI 类型。
- 提供命令行模式和简易 GUI 界面，方便快速选择参数并导出 CSV/JSON。
- 支持两种查询区域模式：中心点+半径的圆形模式，以及上/下/左/右边界的矩形 bbox 模式。
- 输出结果时根据 CSV 目标文件表头进行智能追加或自动创建新文件，避免格式混淆。

## 2. 核心架构

### 2.1 入口逻辑

- `main()`：解析命令行参数
  - `--provider`：选择 `baidu`、`gaode`、`tencent` 或 `all`
  - `--type`：选择 POI 类型
  - `--mode`：选择查询模式 `circle` 或 `bbox`
  - `--lat/--lon/--radius`：圆形模式参数
  - `--top/--bottom/--left/--right`：矩形模式参数
  - `--config`：API Key 配置文件路径
  - `--output`、`--json`：输出文件路径
  - `--page-limit`：分页数
  - `--gui`：是否打开图形界面

- `create_gui()`：构建 Tkinter 界面
  - 支持圆形/矩形模式切换
  - 支持文件浏览选择配置文件、CSV/JSON 输出路径
  - 在界面中显示抓取日志和错误提示

### 2.2 数据获取与适配

- `load_keys(path)`：从 `map_keys.json` 读取百度、高德、腾讯 API Key
- `normalize_record(source, element, place_type)`：统一结果字段，保证输出字段结构一致
- `fetch_places(provider, ...)`：按 provider 分发到具体实现
  - `fetch_baidu(...)`
  - `fetch_gaode(...)`
  - `fetch_tencent(...)`

### 2.3 输出与结果处理

- `save_to_csv(records, path, warn_callback)`：
  - 若目标 CSV 已存在且表头匹配 `DEFAULT_FIELDS`，则追加数据
  - 若表头不匹配，则自动创建 `<原文件名>_new.csv` 并写入
- `save_to_json(records, path)`：生成 JSON 输出

## 3. 设计要点

### 3.1 统一结果格式

统一输出字段：

- `source`
- `id`
- `name`
- `address`
- `latitude`
- `longitude`
- `type`

这使得后续分析和合并多 provider 数据更简单。

### 3.2 API 适配策略

- 百度：`place/v2/search`，支持 `location+radius` 和 `bounds`
- 高德：`place/around` 和 `place/polygon`
- 腾讯：`place/v1/search`，支持 `nearby` 和 `rectangle`

### 3.3 GUI 与命令行共用逻辑

- `run_fetch(...)` 负责统一抓取流程和日志回调
- GUI 通过 `log_callback` 将结果输出到界面文本框
- 命令行直接打印到终端

## 4. 优化历史

### 初始版本

- 先实现单 provider 的圆形 POI 查询
- 仅支持命令行输出 CSV

### 迭代 1：多 provider 适配

- 加入百度、高德、腾讯三家 API
- 建立统一 `fetch_places()` 分发逻辑
- 规范输出字段格式

### 迭代 2：GUI 增强

- 添加 Tkinter 界面
- 支持选择 provider、类型、经纬度、输出文件
- 增加运行日志显示功能

### 迭代 3：CSV 追加与表头判断

- `save_to_csv()` 增加表头检测
- 若目标文件结构不一致则自动创建新文件
- 提示用户当前写入行为，避免误覆盖

### 迭代 4：矩形 bbox 查询模式

- 增加 `--mode bbox` 命令行参数
- GUI 支持矩形查询输入框
- 百度、高德、腾讯分别支持矩形范围查询模式

### 迭代 5：迁移友好优化

- 生成 `requirements.txt` 方便 `venv` 安装
- 明确文档和配置文件结构，便于复制到新电脑

## 5. 迁移建议

- 复制以下文件：
  - `map_poi_fetcher.py`
  - `map_keys.json`
  - `requirements.txt`
- 在新电脑创建 `venv`
- 执行：
  - `python -m venv venv`
  - `venv\Scripts\activate`
  - `python -m pip install -r requirements.txt`
- 确保新电脑 Python 包含 Tkinter（Windows 通常自带）

## 6. 进一步可选优化

- 增加 `requirements-dev.txt` 或 `environment.yml`
- 将 `map_keys.json` 加入 `.gitignore`，避免 AK 泄露
- 增加 `README.md` 说明使用方法与参数示例
- 支持更多 POI 类型或更多 provider
- 增加结果去重、坐标纠偏、文件合并功能
