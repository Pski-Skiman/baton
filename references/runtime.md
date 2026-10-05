# 防中断辅助工具（手动原型）

Python标准库脚本随此技能自足发布；不依赖另装anti-interruption技能。先读[liveness](liveness.md)判断适用性。

## 能力与启用

分别声明可在活动会话连续执行、可跑后台命令、可被外部调度再次唤醒的能力及实测证据；未知不等于不支持。脚本运行不意味着模型持续判断。启用、授权、角色另列，不把工具能力自动变成长期常驻义务。

## 安静窗口

```
python scripts/quiet_window_watch.py --dir <共享目录> --me <本人前缀> --files <当前载体> --window 300 --interval 10 --max-minutes 10
```

显式指定当前关键载体；所有文件必须可读。window/interval/max-minutes必须正数；五分钟中断约束用window=300。`--party`只用于补充检测本人以外的签到行，不能证明在场。私有客户端记忆不计入协作推进。

仅真正追加本方消息且原文无其它差分时判mine；他方消息、未知改动、删除/重排/重复ID或读取失败不能被本方ID遮蔽。WINDOW_SATISFIED只证明采样范围内观察到的窗口，不证明全项目无活动、不提供收尾权限。有限轮询可能漏掉两次采样间发生又撤回的变化；新增未列入载体不自动覆盖。

时间间隔用单调时钟，脚本只在变化和终态输出，避免每次无变化轮询刷JSON。时间上限到达输出TIMEOUT并交接，不自动改任务为完成。

## 可取消计划

```
python scripts/shutdown_plan.py arm --dir <共享目录> --who <本人> --round <本轮ID> --me-prefix <本人前缀> --watch-files <载体> --basis-file <依据文件> --minutes 5 --reason <实际原因>
python scripts/shutdown_plan.py cancel --dir <共享目录> --who <本人> --reason <取消原因>
python scripts/shutdown_plan.py check --dir <共享目录> --who <本人>
```

状态放在共享目录`.baton-state/`，每个who独立计划；同计划读改写用原子创建锁保护。旧版本`_skills/anti-interruption/.state`不自动迁移，恢复需核对用户任务与旧状态。who限制为ASCII字母数字连字符/下划线，不用删字符的方法把不同名字折叠为同一路径。

interrupt计划至少5分钟，需非空轮次、前缀、监测集合与依据；reminder至少1分钟，不能声称满足中断窗口。计划到期只输出TIMER_ELAPSED，不自动取消、不运行AI、不执行系统关机。到期时重新核对已声明监测文件和依据；消息新增、未知变动或无法读取时阻塞。它不是实时消息监听；收到新工作需执行者主动取消。

续期最多2次且写新依据；重新arm保存历史，不能以循环重建计划绕过实际等待义务。计划期限保存完整epoch，显示时间不参与舍入判定；系统时钟变化会影响计划到期，不以它代替单调时钟安静窗口。到期check在同计划锁内完成以免和cancel交错读取；结果只对应检查瞬间，行动前仍需复核。陈旧或损坏锁只报告，不按TTL抢占；释放核对token。异常持久化、断电/重启、网络共享与跨平台原子性没有完整保证。

返回码与JSON事件共同核对：成功命令可输出WAITING/NOT_ARMED，不能只看exit=0就宣布满足。status遇损坏状态报STATE_UNREADABLE；check证据不足以非零退出。测试中的模拟时间不当作真实五分钟端到端验证。
