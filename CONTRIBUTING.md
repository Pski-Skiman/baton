# 参与开发

先读[README](README.md)、[SKILL](SKILL.md)；仓库Agent另读[AGENTS.md](AGENTS.md)。规则修改说明实际问题和影响；用户未授权的技能修改先提候选。

| 路径 | 用途 |
| --- | --- |
| SKILL.md | 必读规则与按需路由 |
| references/ | 操作模板、细节与边界 |
| docs/ | 教程、命令和故障排查 |
| scripts/ | 标准库辅助工具 |
| tests/ | 临时目录行为回归 |
| VERSION、CHANGELOG.md | 版本和实际验收范围 |

```sh
python -m unittest discover -s tests -v
python scripts/validate_package.py
```

先留复现再改共同原因，验证文档链接、编码和真实CLI输出。仅字符串命中不能证明语义完整。

获授权发布时先核对工作区、分支和远程，仅暂存发布白名单，回读差异再提交新版本和新标签，按授权推送并回读。远程有新提交先安全整合，不强推或覆盖标签。提交成功与远程发布成功分别报告。

仓库、现场源、安装副本分别管理，同步先确定授权目标并核对字节。尚未选择许可证，不自行添加许可。
