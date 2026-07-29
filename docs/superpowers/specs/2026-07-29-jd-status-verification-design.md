# 京东订单状态判定与页面差分验证设计

## 目标

在本地完整复刻京东订单页的主状态判定逻辑，并通过真实京东页面持续验证本地结果。系统以订单接口原始 JSON 为输入，输出京东页面当前显示的主状态；Playwright 定期读取页面最终渲染文字，按订单号比较并将结果追加写入本地验证日志。运行数日后，以不一致日志为证据调整规则。

本阶段只处理订单主状态，不复刻配送时间文案、金额格式、按钮权限或整张订单卡片。

## 数据流

```text
tabQuery/all 原始响应
        │
        ├── 原样写入 raw_order_responses.jsonl
        │
        └── result.newOrderinfoMains.resultList
                  │
                  ├── 本地京东状态判定器
                  │       └── local_status + rule_id
                  │
                  └── 京东订单页最终 DOM
                          └── page_status

local_status + page_status
        └── status_verification.jsonl
```

原始采集、状态判定和页面验证是三个独立单元。页面验证失败不会阻止原始响应落盘，也不会修改原始订单。

## 本地状态判定器

新增独立模块 `jd_monitor/jd_status.py`，暴露：

```python
resolve_jd_status(raw_order: dict) -> JdStatus
```

`JdStatus` 包含：

- `text`：京东页面主状态文字；
- `rule_id`：命中的稳定规则标识；
- `source`：`server_title`、`local_rule`、`unknown` 或 `conflict`；
- `matched_fields`：参与判定的状态字段，不包含客户信息；
- `ruleset_version`：规则来源版本，例如 `pick_assistant-2026-07-29`。

判定器不提供用户可编辑的状态码映射。所有规则直接来自当前 `pick_assistant` 页面模板及其辅助方法。

### 优先级与规则

1. 若 `sendOrderCard.orderStatusTitle` 为非空字符串，直接返回该标题，`source=server_title`，不继续执行本地规则。
2. `stationOrderStatus == 16`：
   - `newOrderinfoExtend.prescriptionDTO.useDrugName` 非空，或 `picUrlList` 非空：`处方单待审核`；
   - 否则：`待接单`。
3. `stationOrderStatus in (1, 20)`：按京东模板条件计算：
   - `printMark == 1 and pickMark == 1 and grabMark != 0 and businessType not in (8, 9)`：`待打印`；
   - `printMark > 1 and pickMark == 1 and grabMark != 0`：`待拣货`；
   - `pickMark == 2` 时，`grabMark` 映射：
     - `1`：`待抢单`
     - `2`：`已抢单`
     - `3`：`已收单`
     - `4`：`已完成`
     - `5`：`取消`
     - `6`：`取货失败`
     - `7`：`取货失败待审核`
     - `8`：`撤销抢单`
     - `10`：`投递失败`
   - `businessType == 8`：`待核验`；
   - `is_self_pickup(order) and pickMark == 2 and grabMark != 0`：`待自提`；
   - `carrierNo == 1130 and grabMark == 0`：`召唤配送失败`；
   - `carrierNo == 1130 and pickMark == 2 and grabMark is None`：`即将召唤配送`。
4. 其他基础状态：
   - `4`：`配送中`
   - `-4`：`已取消`
   - `6`：`已完成`
   - `-3`：`待审核`
   - `30`：`商品已送达`

辅助函数严格复刻京东源码：

```text
is_self_pickup(order) =
  carrierNo 宽松等于 9999
  且 businessTag 不包含字符串 A13
```

Python 实现须兼容 `carrierNo` 的数字和字符串形式，并按子串语义判断 `A13`。

### 互斥与异常数据

京东模板使用多个条件分支，但正常业务数据应得到一个主状态。判定器评估全部适用条件：

- 恰好一个本地规则命中：返回该状态；
- 没有规则命中：返回 `京东未知状态`，`source=unknown`；
- 多个本地规则命中：不擅自选取，返回 `京东状态规则冲突`，`source=conflict`，并记录所有命中的 `rule_id`。

这样可以通过运行日志发现京东字段约束或页面规则理解上的遗漏。

## 京东页面验证器

新增 `jd_monitor/page_verifier.py`，使用 Playwright 打开：

`https://order.jddj.com/static/web/html/pick_assistant.html`

浏览器上下文加载本机 `data/cookies.json`，所有凭据只保存在本机。验证器等待订单根节点 `#content-pick-box1` 和订单卡片渲染完成，再设置与 API 抓取相同的当天时间窗口并触发筛选。

验证器遍历页面与分页，逐卡片提取：

- `order_id`：从包含“订单编号：”的订单信息行读取相邻链接文字；
- `page_status`：从订单卡片标题区域 `.time.redColor` 读取最终可见文字。

页面状态节点应恰好有一个。没有状态节点或出现多个状态节点时，不拼接或猜测，记录为页面结构异常。

分页通过页面“下一页”按钮执行，直至按钮处于禁用状态。每页等待订单列表稳定后再读取，避免将加载中的空列表误判为缺失。

## 比较与日志

新增 `data/status_verification.jsonl`。每行代表一笔订单在一次验证中的结果：

```json
{
  "verified_at": "2026-07-29T15:00:00+08:00",
  "order_id": "...",
  "local_status": "待拣货",
  "page_status": "待拣货",
  "result": "matched",
  "rule_id": "waiting_pick",
  "ruleset_version": "pick_assistant-2026-07-29",
  "status_fields": {
    "stationOrderStatus": 1,
    "printMark": 2,
    "pickMark": 1,
    "grabMark": 1,
    "businessType": 1,
    "carrierNo": "9966"
  }
}
```

`result` 取值：

- `matched`：本地状态与页面状态一致；
- `mismatched`：两者文字不一致；
- `missing_on_page`：API 返回订单但当次页面遍历未找到；
- `local_unknown`：本地没有规则命中；
- `local_conflict`：本地命中多个规则；
- `page_error`：登录失效、页面加载失败、状态节点异常或页面结构变化。

验证日志只保存订单号和参与状态判定的字段，不保存姓名、电话、地址、备注、定位、商品或完整原始订单。`data/` 已被 Git 忽略。

另写入每轮概要：开始/结束时间、API 订单数、页面订单数、匹配数、不一致数、缺失数和错误摘要。概要不得包含 Cookie 或订单个人信息。

## 命令与持续运行

新增命令：

```text
python -m jd_monitor verify
python -m jd_monitor verify --interval 60
```

- 无 `--interval`：执行一次原始抓取、页面读取与比较后退出；
- 有 `--interval`：在同一个浏览器上下文中循环验证，参数单位为秒；
- 每轮使用新的当前时间计算当天查询窗口；
- 单轮失败写入错误概要，下一轮继续；
- 收到终止信号后关闭浏览器并安全退出。

默认使用可见浏览器，便于人工处理登录验证和观察页面。后续只有在持续验证稳定后才考虑无头模式。

## 测试策略

### 状态规则测试

为每个京东状态分支建立最小、脱敏的订单对象测试，包括：

- 服务端标题覆盖本地规则；
- 处方单有/无处方数据；
- 待打印、待拣货；
- `grabMark` 的全部已知映射；
- 待核验、待自提、召唤配送失败、即将召唤配送；
- 配送中、已取消、已完成、待审核、商品已送达；
- 数字/字符串形式的 `carrierNo=9999`；
- `businessTag` 包含/不包含 `A13`；
- 无规则和多规则冲突。

### 页面解析测试

使用脱敏 HTML fixture 测试订单号、单一状态节点、分页状态和页面结构异常。自动化测试不访问京东真实页面，不加载真实 Cookie。

### 真实差分验证

手工验收使用本机登录会话。首轮已有 5 条真实 `stationOrderStatus=6` 订单，本地 `已完成` 与京东页面 `已完成` 达到 5/5 一致。后续持续运行，按 `rule_id` 汇总覆盖情况，并重点检查所有 `mismatched`、`local_unknown` 和 `local_conflict` 记录。

## 验收标准

1. 状态判定器覆盖当前京东模板中全部主状态分支，不提供人为状态码配置。
2. 每条本地结果可追溯到稳定 `rule_id`、规则版本和参与判断的非敏感字段。
3. 页面验证器能自动读取京东最终状态文字并按订单号比较。
4. 单轮与循环模式均将验证结果追加写入 JSONL，失败不会中断原始采集。
5. 日志不包含 Cookie、客户姓名、电话、地址、备注或完整原始订单。
6. 运行数日后，可以按规则覆盖、不一致、未知和冲突记录定位需要调整的分支。
