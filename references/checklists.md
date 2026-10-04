# 检查清单与可复制命令（模板）

> ⚠️ **这是模板**：下面的 `$ws` 是**占位变量**，**必须替换成你自己的共享目录**才能运行。
> ```powershell
> $ws = $env:WORKSPACE   # ← 先设为你的共享目录绝对路径，或直接写成该路径
> ```
> **不要把示例路径当成可直接执行的本机路径**。

## 1. 写入后自检（存在 / 大小 / 关键内容 / 编码）

```powershell
$f = Join-Path $ws '话题文件.md'
"存在 = $(Test-Path -LiteralPath $f)"
"大小 = $((Get-Item -LiteralPath $f).Length) B"
$text = [System.IO.File]::ReadAllText($f,[System.Text.Encoding]::UTF8)
"含关键内容 = $($text.Contains('关键词'))"
# 控制字符（U+0000–U+001F 除换行、U+007F）与裸 CR
$bad = @()
for($i=0;$i -lt $text.Length;$i++){
  $k=[int][char]$text[$i]
  if((($k -lt 0x20) -and $k -ne 0x0A -and $k -ne 0x0D) -or $k -eq 0x7F){ $bad += ('U+{0:X4}' -f $k) }
  if($k -eq 0x0D){ $nx=-1; if($i+1 -lt $text.Length){ $nx=[int][char]$text[$i+1] }; if($nx -ne 0x0A){ $bad += 'bareCR' } }
}
if($bad.Count -gt 0){ "⚠️ 控制字符：$($bad -join ', ')" } else { "控制字符：无 ✅" }
# BOM
$bytes=[System.IO.File]::ReadAllBytes($f)
"有 BOM = $(($bytes.Length -ge 3) -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)"
```

## 2. 指纹复算（**必须写清范围边界**）

```powershell
function Get-FileSha { param([string]$Path)
  $raw=[System.IO.File]::ReadAllBytes($Path)
  $a=[System.Security.Cryptography.SHA256]::Create()
  return ((($a.ComputeHash($raw)) | ForEach-Object { $_.ToString('x2') }) -join '')
}
Get-FileSha (Join-Path $ws '话题文件.md')
```
> **同一段文本，含不含末尾换行会得到两个不同哈希**——确认时**必须写明范围边界**（是整文件字节，还是某个区间）。
> **哈希只证明「相同范围的字节」**，不替代首次理解与审查。

## 3. 原子锁模板（**必须带 try/finally 与 `$acquired` 保护**）

```powershell
$lock = Join-Path $ws '._交流锁'
$acquired = $false; $stream = $null; $writer = $null

# ① 抢锁：CreateNew 是原子操作。失败只表示「锁已被他人持有」——
#    不要把临界区里的其它错误也解释成抢锁失败。
try {
  $stream = [System.IO.File]::Open($lock,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
  $acquired = $true
} catch {
  Write-Output '抢锁失败（锁已被他人持有）→ 放弃本次写入，不触碰锁文件'
}

# ② 只有拿到锁才进入临界区；临界区异常**照常上抛**（不吞），finally 只释放**自己的**锁
if($acquired){
  try {
    $writer = New-Object System.IO.StreamWriter($stream,(New-Object System.Text.UTF8Encoding($false)))
    $writer.Write('holder'); $writer.Flush()

    # —— 临界区（保持短）：读 → 改 → 写 ——
    $target = Join-Path $ws '话题文件.md'
    $text = [System.IO.File]::ReadAllText($target,[System.Text.Encoding]::UTF8)
    [System.IO.File]::WriteAllText($target, $text + "`r`n新内容", (New-Object System.Text.UTF8Encoding($false)))
  }
  finally {
    if($writer){ $writer.Dispose() }
    if($stream){ $stream.Dispose() }
    Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue   # 只删自己持有的锁
    $acquired = $false
  }
}
```

**三场景自测**（改锁代码后各跑一次；**在临时目录里跑并清理**）：
1. **正常**：无锁 → 能拿到、写入成功、退出后锁消失；
2. **他人持有**：已存在锁 → 放弃、**不删别人的锁**、目标文件不变；
3. **临界区异常**：读一个不存在的文件 → **异常照常上抛（非零退出）**，而**自有锁必须被释放**（这正是 `finally` 的作用）。

> **教训（实测）**：没有 `try/finally` 时，**临界区一抛异常，自有锁就残留**——而残留锁会让后续所有写入被拒。**自测必须在临时目录里做，不要污染共享目录。**
## 4. 消息模板

```
[YYYY-MM-DD HH:mm] <发送方> → <接收方>：[id=<前缀>-<话题>-<序号>] [type=<类型>] [reply_to=<id>]

（正文：一句自包含摘要 + 依据；需要行动时写清对象、范围、期限与恢复条件）
```

## 5. 轮次收尾清单

- [ ] 各自简短复盘，把修正写回约定文本；
- [ ] **调整并归档文件夹内容**：当轮话题文件与聊天记录 → 归档目录；**导航按实际路径更新并回读**；
- [ ] 共享归档：**写入 → 回读核对实际参与者记录完整 → 才清空**（**仅执行一次**，由唯一记录者做）；
- [ ] 全文编码与控制字符检查；
- [ ] 未完成事项表状态更新（**历史完成行可保留**）。