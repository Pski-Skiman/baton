# 写入与归档检查

## 共享写入

全部参与方使用同一绝对路径锁。下例`$sharedRoot`需由实际共享目录赋值；抢锁失败保持他方文件不变。异常如实上抛，不把任何IOException都说成“锁已存在”。

```powershell
$lockPath = Join-Path $sharedRoot '._交流锁'
$held = $null
try {
  $held = [IO.File]::Open($lockPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  $target = Join-Path $sharedRoot '当前话题.md'
  $body = @'
需追加的字面正文
'@
  [IO.File]::AppendAllText($target,$body,[Text.UTF8Encoding]::new($false))
} finally {
  if ($null -ne $held) { $held.Dispose(); Remove-Item -LiteralPath $lockPath }
}
```

模板假设所有协作方都不删除/替换他方锁；它不是非协作进程的安全防护。锁内只做短读写；需要读改写时整个序列同锁。含反引号不用双引号here-string；单引号不插值，动态字段用明确替换/拼接。

## 回读

核对目标路径、关键内容、UTF-8严格解码、无BOM、无U+FFFD/意外C0/DEL；CRLF不是裸CR。文档与Python采用无BOM；Windows PowerShell 5.1执行含中文.ps1时须使用能正确解码UTF-8的入口，不能默认ANSI读取。哈希声明整文件字节或确切区间、含不含末尾换行。

按位置检查换行：CR只允许紧接LF；使用`\r(?!\n)`筛出裸CR，不能把CR整类列入正常字符白名单。包含裸CR的历史先逐字节保存再决定修复，不用不同读取器的行号作为归档清空边界。

## 可恢复归档

确认实际路径和当前轮范围；持锁重读→保存原文全文到唯一归档名→回读核对→以**相同范围**精简在用文件→更新导航。任一步失败保留原件，不能清空未确认归档的内容。临时文件、锁与客户端私有记忆不发布。冻结历史不为通过检测而改写。

修改锁/归档代码时，在临时目录验证正常、他方持锁、临界区异常三种路径；检索判据用已知正例和反例自检，字符串匹配只是筛查。

## 收尾检测顺序

持久化六项交接/事项状态→检查其余完成前提→明确关键载体并执行300秒连续窗口→期间消费用户及他方增量、巡检独立工作→新增/未知变化/读取失败阻塞，处理后重新计时→窗口事实和其它闸门复核通过→范围明确FIN/适用客户端完成出口。正常本人完成和全轮收尾都适用；阶段性交付不解除检测；WINDOW_SATISFIED只报事实，不授予完成许可。
