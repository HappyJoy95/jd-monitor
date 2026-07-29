# 京东到家订单原始采集与本地订单池

这个工具会将订单列表接口的原始 JSON 响应原样保存到日志中，同时读取订单的 `orderId`，从完整日志构建仅保存在本机的派生订单池。

## 准备 Cookie

使用本机浏览器完成商家后台登录后，将 Playwright 格式的 Cookie 数组保存为 `data/cookies.json`。该文件包含登录凭据：不得提交到 Git、不得发送到聊天中，也不要把它的内容写入日志。

## 执行一次采集

```bash
.venv/bin/python -m jd_monitor capture
```

成功时，工具会显示页数、响应数、订单池中的唯一订单数以及订单池路径。原始响应追加保存到 `data/raw_order_responses.jsonl`；每一行包含抓取时间、请求时间窗口、页码以及未修改的 `response` 对象。

可以显式指定私有 Cookie 文件与输出位置：

```bash
.venv/bin/python -m jd_monitor capture --cookies data/cookies.json --output data/raw_order_responses.jsonl
```

自动刷新订单池的路径也可以单独指定：

```bash
.venv/bin/python -m jd_monitor capture --pool data/custom_order_pool.json
```

采集请求使用当天时间范围：

- 下单开始时间：当天 `00:00:00`
- 下单结束时间：本次采集时间
- 预计送达开始时间：当天 `00:00:00`
- 预计送达结束时间：当天 `23:59:59`

## 订单池

每次成功完成所有分页采集后，工具都会读取完整的原始日志，并在同一目录重新构建 `order_pool.json`。订单池以订单号作为顶层键；每个订单项包含：

- `first_seen_at`：该订单首次出现在原始日志中的具体时间。
- `order`：该订单最新一次出现时的完整京东原始对象。重复出现的订单只会覆盖 `order`，不会改变 `first_seen_at`。

也可以独立重建订单池：

```bash
.venv/bin/python -m jd_monitor pool
```

显式指定原始日志与订单池输出位置：

```bash
.venv/bin/python -m jd_monitor pool --input data/raw_order_responses.jsonl --output data/order_pool.json
```

`raw_order_responses.jsonl` 和 `order_pool.json` 都包含完整的客户与订单信息，只能保存在本机：不得提交到 Git，也不得发送到聊天、邮件或其他外部渠道。
