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

## 可恢复归档

确认实际路径和当前轮范围；持锁重读→保存原文全文到唯一归档名→回读核对→以**相同范围**精简在用文件→更新导航。任一步失败保留原件，不能清空未确认归档的内容。临时文件、锁与客户端私有记忆不发布。冻结历史不为通过检测而改写。

修改锁/归档代码时，在临时目录验证正常、他方持锁、临界区异常三种路径；检索判据用已知正例和反例自检，字符串匹配只是筛查。
