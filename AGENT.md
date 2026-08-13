# AGENT.md - 京东到家订单监控系统

## 项目概述

京东到家订单原始采集与本地订单池工具。从商家后台 API 采集进行中订单，保存原始 JSON，构建订单池，并通过企业微信群推送通知。

## 技术栈

- Python 3.9+
- requests（HTTP 请求）
- pytest（测试）
- 企业微信 Webhook（消息推送）

## 项目结构

```
jd-monitor/
├── jd_monitor/                # 主代码
│   ├── __main__.py           # CLI 入口（capture / pool 命令）
│   ├── capture.py            # 订单采集（三种状态分页获取）
│   ├── order_pool.py         # 订单池管理（从日志重建）
│   ├── notifications.py      # 主推送逻辑（deadline 检查）
│   ├── store_notifications.py # 门店群推送（按门店名匹配）
│   ├── wechat_webhook.py     # 企业微信 Webhook 客户端
│   └── sent_orders.py        # 已推送订单记录
├── tests/                    # 测试文件
├── config/                   # 门店配置（不含敏感信息）
├── data/                     # 运行时数据（已 gitignore）
├── pyproject.toml            # Python 配置
└── README.md                 # 用户文档
```

## 核心模块职责

| 模块 | 职责 |
|------|------|
| `capture.py` | 采集三种状态订单：waitAccept、waitPrint、waitMake |
| `order_pool.py` | 从 raw JSONL 构建 order_pool.json（订单号 → 首次出现 + 最新数据）|
| `notifications.py` | 主推送：检查 deadline 在 6 分钟内，发送到主企微群 |
| `store_notifications.py` | 门店推送：按 stationName 匹配，检查营业时间 |
| `wechat_webhook.py` | 企业微信 Webhook 客户端（发送文本消息）|

## 常用命令

```bash
# 运行测试
python3 -m pytest tests/ -v

# 运行单个测试文件
python3 -m pytest tests/test_notifications.py -v

# 运行单个测试
python3 -m pytest tests/test_notifications.py::test_name -v

# 执行采集
python3 -m jd_monitor capture

# 重建订单池
python3 -m jd_monitor pool
```

## 关键数据结构

### 订单池 (order_pool.json)

```json
{
  "订单号": {
    "first_seen_at": "2026-08-13T14:30:00+08:00",
    "order": { /* 京东原始订单对象 */ },
    "tab": "waitAccept"
  }
}
```

### 门店配置 (config/store_webhooks.json)

```json
[
  {
    "门店名": "门店名称（与订单 stationName 精确匹配）",
    "营业开始时间": "09:30:00",
    "营业结束时间": "22:00:00",
    "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
  }
]
```

## 修改注意事项

### 推送逻辑

- 主推送：`notifications.py` 中的 `notification_type()` 检查 deadline
- 门店推送：`store_notifications.py` 中的 `send_to_store_groups()` 检查门店名匹配 + 营业时间
- 两种推送共用同一组 eligible orders（deadline 在 6 分钟内）

### 消息格式

所有推送消息都以【京东到家】开头：

```
【京东到家】待接单
订单号：o2o-123456
门店：华为授权体验店（悦荟广场店）
下单时间：2026-08-13 14:30:00
商品：手机壳
```

门店配置确认消息：

```
【京东到家】门店推送配置确认
————————————
门店名称：华为授权体验店（悦荟广场店）
营业时间：09:30 ~ 22:00
推送平台：京东到家订单监控
————————————
状态：配置完成，正常推送中
```

### 敏感信息

- `data/cookies.json` - 登录凭据
- `data/wechat_webhook.txt` - 主推送 webhook
- `config/store_webhooks.json` - 门店 webhook
- 以上文件已 gitignore，不得提交到 Git

### 测试

- 修改推送逻辑时，同步更新 `tests/test_notifications.py`
- 修改 CLI 参数时，同步更新 `tests/test_cli.py`
- 所有测试通过后才能提交

## 常见任务

### 添加新门店

1. 编辑 `config/store_webhooks.json`
2. 添加门店配置（门店名、营业时间、webhook）
3. 运行 `python3 -c "from jd_monitor.store_notifications import format_store_config_confirmation; ..."` 验证格式

### 修改推送格式

1. 修改 `notifications.py` 或 `store_notifications.py` 中的 `format_*` 函数
2. 更新对应测试
3. 运行 `python3 -m pytest tests/ -v` 验证

### 添加新推送类型

1. 在 `notifications.py` 中修改 `notification_type()` 添加新条件
2. 更新测试覆盖新场景
3. 考虑是否需要门店推送也支持新类型
