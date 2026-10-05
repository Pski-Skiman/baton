# 仓库Agent约定

这是技能与脚本源码仓库，真实协作现场另由用户指定。先读README.md和SKILL.md。本文件不授予commit、push、安装客户端或系统操作权限。

- 用户本轮任务决定角色与授权，不继承旧轮写入权；保护未提交修改。指定一方实现/Git，其它方只审查。
- 最小修复，先复现再增加能失败的行为回归；脚本只用Python标准库，不执行系统关机、模型调度或跨会话唤醒。
- attribution.py是共同归属模块；损坏状态、未知活动、读取失败不冒充安静。
- references/runtime.md、docs/tools.md与真实参数、事件和退出码保持一致。README讲用途，SKILL教执行，不放现场聊天或固定参与人。
- 修改后运行 `python -m unittest discover -s tests -v` 和 `python scripts/validate_package.py`。测试只用临时目录，不碰真实计划或他方锁。
- 版本保持VERSION、SKILL metadata、README和CHANGELOG一致。安装副本同步只在用户授权范围内进行。
- 发布仅暂存本轮明确文件，核对差异；不含聊天、用户原文、个人资料、Secret、状态、锁或缓存。不force、不覆盖旧标签。
- 未实际验证的平台与运行期保证如实列出，模拟时间不能冒充真实五分钟测试。
