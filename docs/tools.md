# 工具命令与结果

以下命令从技能/仓库根目录运行，`shared`是已经建立的共享工作目录，其中存在可读的`话题.md`和`当前任务.md`。实际项目请替换路径；脚本路径与共享目录不是同一概念。

需要Python 3.9+，只使用标准库，无需安装依赖。可先用`--help`核对参数。

## 安静窗口：可选有界观察

```sh
python scripts/quiet_window_watch.py --dir shared --me agent_a --files 话题.md --files 当前任务.md --window 300 --interval 10 --max-minutes 10
```

| 参数 | 含义 |
| --- | --- |
| `--dir`、`--me` | 已存在共享目录、本方消息ID前缀（ASCII字母数字或下划线） |
| `--files` | 相对共享目录的载体，可重复；建议始终明确指定 |
| `--window` | 连续窗口秒数，项目五分钟约束使用300 |
| `--interval` | 采样间隔秒数，越长越可能遗漏短暂变化 |
| `--max-minutes` | 最长观察分钟数；上限不足以覆盖窗口时不会保证成功 |
| `--party` | 可重复，他方签到表名字；只是补充检测，不证明在线 |
| `--party-line` | 签到行正则模板，用`{party}`占位；默认匹配Markdown表格中的加粗名字 |
| `--ignore-prefix` | 可重复，被指定前缀的新增消息保守归为未知，仍阻塞窗口 |

不指定files只在启动时选择共享根目录的`.md`文件，不递归、不自动加入后续新文件；空集合拒绝运行。三个时间参数必须正整数。仅本方纯追加不重置窗口；他方、未知或读取失败会重置。

默认party-line只匹配表格。项目使用`[签到] Agent B ｜ ...`时可传`--party-line '^\[签到\]\s*{party}(?=\s|[|｜])[^\n]*'`；模板必须匹配整条行，不能只匹配名字，否则签到状态变化的行哈希不会变化。匹配不到会在START.warn提示；即使签到辅助匹配缺失，整篇归属比较仍会把其它内容变化保守归为未知并重置，不能据此断言检测只看新ID。shell对中文参数的实际传递需本机验证，不能由一次错误泛化为非ASCII不可用。

| JSON事件 | 如何处理 |
| --- | --- |
| START | 已取得基线，开始观察；不是验收 |
| MINE_ATTRIBUTED | 全部变化仅为本方新增消息，窗口继续 |
| HEARD_FROM_OTHERS / UNATTRIBUTED | 读取消息或核对未知变化，窗口重置 |
| UNREADABLE | 必需载体不可读，不给窗口结论 |
| WINDOW_SATISFIED | 所列文件在采样范围满足窗口；继续人工核对任务和授权 |
| TIMEOUT | 未在观察上限内满足，交接真实缺口 |
| ERROR / INTERRUPTED | 参数/基线失败或用户中断；不声称窗口满足 |

退出码：0=观察到窗口；1=参数/基线拒绝；2=超时；3=键盘中断；9=内部归属模块缺失。有限采样可能漏掉两次读取间发生又撤回的修改。

## 手动可取消计划

```sh
python scripts/shutdown_plan.py arm --dir shared --who agent_a --round R-demo --me-prefix agent_a --watch-files 话题.md --watch-files 当前任务.md --basis-file 当前任务.md --minutes 5 --reason "已无独立工作，待人工核对"
python scripts/shutdown_plan.py status --dir shared --who agent_a
python scripts/shutdown_plan.py check --dir shared --who agent_a
python scripts/shutdown_plan.py renew --dir shared --who agent_a --minutes 5 --reason "新增依赖需等待具体审查意见"
python scripts/shutdown_plan.py cancel --dir shared --who agent_a --reason "收到新工作，继续处理"
```

`who`只含ASCII字母数字、下划线或连字符，大小写视为同一身份。消息前缀不含连字符，因为ID首段用于归属；例如`agent_a-demo-001`。

interrupt（默认）至少5分钟，arm必须有轮次、前缀、非空监测集合和依据（`--basis`文字或`--basis-file`文件）。basis-file路径相对共享目录，必须保持可核对；状态恢复也重新检查路径和身份。文件不可读可登记ARM_WARN，但到期不会给通过结论。重复arm输出ALREADY_ARMED，不重设期限。

`--basis`只保存人工理由，不提供文件变化校验；需要依据文件指纹时使用`--basis-file`。纯文字依据合法，不会仅因为basis_hash为空就输出BASIS_UNVERIFIED；该事件用于已声明依据文件却无法核对的情况。

一般提醒可以不监测文件：

```sh
python scripts/shutdown_plan.py arm --dir shared --who agent_a --purpose reminder --minutes 1 --reason "稍后人工检查进度"
```

reminder只证明提醒计时到期，不能当作中断窗口证据。续期最多2次，理由须具体且至少6个字符；不会重新取得基线。收到新工作应主动cancel，脚本不是实时消息监听。

状态位于共享目录`.baton-state/plan_<who小写>.json`，同计划用原子锁保护；可查看但不建议手工编辑。旧状态损坏时保留原件并人工确认，不能清空后假称没有计划。

| JSON事件 | 含义/行动 |
| --- | --- |
| ARMED / CANCELLED / RENEWED | 对应写入已完成 |
| STATUS | 读取当前计划，缺计划时plan为空 |
| ALREADY_ARMED / NOTHING_TO_CANCEL / NOT_ARMED / RENEW_LIMIT | 当前无需或不能执行该动作；exit=0不等于新动作发生 |
| WAITING | 尚未到期；exit=0不等于可以结束 |
| TIMER_ELAPSED | 计时到期，当前快照无阻塞；核对purpose、checked_files及人工前提 |
| READ_ERROR / BASIS_UNVERIFIED / BASIS_CHANGED / DUE_BUT_BLOCKED | 文件、依据或活动阻塞；先处理、取消或交接 |
| STATE_UNREADABLE / STATE_OWNER_MISMATCH / STATE_PATH_OUTSIDE_ROOT | 状态损坏、身份不一致或恢复路径越界；原件不覆盖，不读取越界载体 |
| LOCK_BUSY / STALE_LOCK_SUSPECT | 锁占用或疑似异常；不抢占、不自动删锁 |
| REFUSED / BAD_DUE / CONFLICT | 参数、期限或版本拒绝；不要当作完成 |
| REFUSED_RELEASE_FOREIGN_LOCK | 释放时身份不符，保留锁，需人工核对 |

计划退出码：0=命令完成或无操作（仍须读事件）；1=参数/状态/锁拒绝；2=到期核对被阻塞；4=写入版本冲突；9=模块缺失。命令行语法错误由argparse返回2，与观察工具的TIMEOUT不同。系统时钟会影响计划期限；计划check只比较登记与检查瞬间，不能证明期间连续安静。需要连续采样时用窗口工具。

两工具使用系统当地时间显示事件，窗口间隔使用单调时钟；跨客户端请统一时区。文件系统/磁盘故障可能产生运行异常，不提供断电和任意环境故障的完整恢复保证。
