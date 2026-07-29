# 京东到家订单采集与状态验证

这个工具会原样保存京东订单列表接口的 JSON 响应，也可以把本地复刻的京东主状态判定结果与真实订单页面显示文字进行比较。

## 准备 Cookie

使用本机浏览器完成商家后台登录后，将 Playwright 格式的 Cookie 数组保存为 `data/cookies.json`。该文件包含登录凭据：不得提交到 Git、不得发送到聊天中，也不要把它的内容写入日志。

安装项目依赖并准备验证用浏览器：

```bash
python -m pip install -e .
playwright install chromium
```

## 执行一次采集

```bash
python -m jd_monitor capture
```

成功时，工具只显示页数和响应数。原始响应追加保存到 `data/raw_order_responses.jsonl`；每一行包含抓取时间、请求时间窗口、页码以及未修改的 `response` 对象。

可以显式指定私有 Cookie 文件与输出位置：

```bash
python -m jd_monitor capture --cookies data/cookies.json --output data/raw_order_responses.jsonl
```

## 验证订单状态

执行一次原始采集，打开可见的 Chromium，读取京东订单页面最终显示的状态并逐单比较：

```bash
python -m jd_monitor verify
```

浏览器窗口会保持可见，登录失效或京东要求额外验证时可以人工处理。原始接口响应仍追加到 `data/raw_order_responses.jsonl`；脱敏后的比较结果追加到 `data/status_verification.jsonl`。

持续验证时指定间隔秒数。同一个正常浏览器会话会被复用；页面读取失败时，下一轮会重新打开：

```bash
python -m jd_monitor verify --interval 60
```

也可以显式指定三个本地文件：

```bash
python -m jd_monitor verify \
  --cookies data/cookies.json \
  --raw-output data/raw_order_responses.jsonl \
  --log data/status_verification.jsonl
```

验证结果含义：

- `matched`：本地判定和京东页面一致；
- `mismatched`：两者文字不同；
- `missing_on_page`：接口中存在，但页面遍历没有找到；
- `local_unknown`：当前京东规则没有命中；
- `local_conflict`：异常数据同时命中多个京东规则；
- `page_error`：登录、页面加载或页面结构读取失败。

验证日志只保存订单号、状态文字、规则编号和参与状态判定的字段，不保存客户姓名、电话、地址、备注、商品、完整订单或 Cookie。`data/` 目录不会提交到 Git。
