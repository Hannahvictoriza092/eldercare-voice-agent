# 网络与 Git 配置

> ⚠️ **每个队员第一次 push 之前都要看这份文档。**
> 这篇是根据真实排查过程写的，不是网上抄的通用教程。

---

## 一、结论先行：用 SSH，不要用 HTTPS

| 方式 | 需要代理吗 | 在国内的可用性 |
|---|---|---|
| **SSH**（推荐） | ❌ **不需要** | ✅ 稳定 |
| HTTPS | ✅ 需要，且要单独配给 git | ❌ 容易失败 |

**配好 SSH 之后，代理怎么变都不用管了。**

---

## 二、先诊断：你的问题到底出在哪

国内用 git 访问 GitHub 失败，有三种截然不同的原因。
**先看清楚自己属于哪一种，再对症处理。**

| 报错信息 | 真正的原因 |
|---|---|
| `Failed to connect to github.com port 443 after 21000 ms` | 网络层不通 |
| `Recv failure: Connection was reset` | 连上了，但传数据被掐断 |
| `Error in the HTTP2 framing layer` | HTTP2 协议被干扰 |
| `Invalid username or token. Password authentication is not supported` | ✅ **网络是通的**，只是没用对认证方式 |
| `Permission denied (publickey)` | ✅ **网络是通的**，只是没配密钥 |

> 💡 **关键判断**：如果报的是后两种，说明网络没问题，别再去折腾代理了，
> 直接跳到第三节配 SSH。

### 一个反直觉的坑（本项目真实踩过）

**浏览器能打开 GitHub ≠ git 能用。**

原因是：浏览器和 PowerShell 会自动使用 Windows 系统代理，
但 **git 默认不使用系统代理**，它直连。

所以会出现这种诡异情况：

```
Invoke-WebRequest https://github.com   →  200 OK        （走了代理）
git ls-remote https://github.com/...   →  连接超时       （直连，被墙）
```

如果你的代理开着、浏览器正常，但 git 连不上，**就是这个原因**。
解决办法不是"再去配代理"，而是**改用 SSH**，一劳永逸。

一眼看出是不是这个坑：

```powershell
# 看系统有没有开代理
Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" |
    Select-Object ProxyEnable, ProxyServer

# 看 git 有没有配代理
git config --global --get http.proxy
```

**系统代理有值、git 代理为空** = 中了这个坑。

---

## 三、配置步骤（5 分钟）

### 第 1 步：生成密钥

打开 PowerShell：

```powershell
ssh-keygen -t ed25519 -C "你的邮箱" -f "$env:USERPROFILE\.ssh\id_ed25519" -N '""'
```

一路回车即可。会生成两个文件：

| 文件 | 说明 |
|---|---|
| `id_ed25519` | **私钥**。留在本机，**不要发给任何人** |
| `id_ed25519.pub` | 公钥。待会儿贴到 GitHub 上 |

### 第 2 步：查看公钥

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub"
```

会输出一行，以 `ssh-ed25519` 开头，看起来像：

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... 你的邮箱@example.com
```

**整行复制。**

### 第 3 步：贴到 GitHub

1. 打开 https://github.com/settings/keys
2. 点 **New SSH key**
3. Title 随便填（比如 `我的笔记本`）
4. Key type 选 **Authentication Key**
5. Key 那一栏粘贴刚才复制的那一整行
6. 点 **Add SSH key**

### 第 4 步：验证是否成功

```powershell
ssh -T git@github.com
```

看到这个就成功了：

```
Hi 你的用户名! You've successfully authenticated, but GitHub does not provide shell access.
```

> 如果提示 `Are you sure you want to continue connecting (yes/no)?`，输入 `yes` 回车。

### 第 5 步：把仓库地址改成 SSH

```powershell
git remote set-url origin git@github.com:Hannahvictoriza092/eldercare-voice-agent.git
git remote -v      # 确认看到的是 git@github.com:... 而不是 https://...
```

之后照常 `git push` 就行。

---

### 第 6 步（重要）：清掉残留的代理配置

如果你之前给 git 配过代理，**建议清掉**，否则代理换端口或关掉时会突然失效：

```powershell
git config --global --unset http.proxy
git config --global --unset https.proxy
git config --global --unset http.version
```

**SSH 通道不需要代理**，清掉之后更省心。

---

## 四、如果 SSH 也不通（22 端口被封）

有些网络环境会把 22 端口一起封。改走 443 端口（GitHub 提供的备用通道）：

编辑（或新建）`C:\Users\你的用户名\.ssh\config`，写入：

```
Host github.com
  HostName ssh.github.com
  Port 443
  User git
```

然后重新测：

```powershell
ssh -T git@github.com
```

（本项目的首次推送就是用的这个配置，实测可用。配好之后 `git push` 会自动走 443。）

---

## 五、如果你坚持用 HTTPS + 代理

先说清楚代价：**git 的代理配置是独立的一份，不会跟着系统代理自动变。**

| 情况 | 结果 |
|---|---|
| 代理开着，且 git 里配的端口正确 | ✅ 能用 |
| 代理**换了端口** | ❌ git 还在找老端口，连接失败 |
| 代理**关掉了** | ❌ 同上 |

### 代理换端口后怎么改

```powershell
# 1. 先查系统当前的代理端口
Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" |
    Select-Object ProxyEnable, ProxyServer

# 2. 按查到的端口改 git（假设查出来是 7897）
git config --global http.proxy  http://127.0.0.1:7897
git config --global https.proxy http://127.0.0.1:7897

# 3. 验证
git ls-remote origin
```

### 完全取消代理

```powershell
git config --global --unset http.proxy
git config --global --unset https.proxy
```

### 用 HTTPS 还必须处理认证

GitHub **禁止用密码推送**，会报：

```
remote: Invalid username or token. Password authentication is not supported for Git operations.
```

必须用 Token：

1. https://github.com/settings/tokens → **Generate new token (classic)**
2. **勾选 `repo`**（必须，否则推不了）
3. 生成后复制那串 `ghp_...`（**离开页面就再也看不到了**）
4. 推送时用户名填 GitHub 用户名，密码栏粘贴 token
5. 让 Windows 记住它，省得每次输：

   ```powershell
   git config --global credential.helper manager
   ```

> 💡 对比一下：SSH 配一次永久有效；HTTPS 要管代理端口 + 管 Token 过期。
> **所以强烈建议用 SSH。**

---

## 六、如果都不行

| 方案 | 做法 |
|---|---|
| 手机热点 | 有些校园网/运营商线路更严，换个网络往往就好了 |
| 找能连的同学 | 让他帮你推（代码在你自己本地，不用担心） |

---

## 七、推送失败时的自查清单

按这个顺序排查，基本能定位所有问题：

```powershell
# 1. 远程地址是 SSH 吗？
git remote -v
#    要看到 git@github.com:...
#    如果是 https:// 就改：
#    git remote set-url origin git@github.com:Hannahvictoriza092/eldercare-voice-agent.git

# 2. SSH 认证通吗？
ssh -T git@github.com
#    要看到 "Hi 你的用户名!"
#    - Permission denied  -> 公钥没加对，回第三节第 3 步
#    - 连接超时           -> 走第四节的 443 端口方案

# 3. 有没有残留的代理配置在捣乱？
git config --global --get http.proxy
git config --global --get https.proxy
#    输出为空最好；有值但代理没开，就 unset 掉

# 4. 本地提交了吗？
git log --oneline
```

---

## 八、常见问题

### `Permission denied (publickey)`

说明网络通了，但 GitHub 不认你的密钥。检查：

1. 公钥是不是完整复制了？（必须一整行，从 `ssh-ed25519` 到邮箱）
2. 是不是复制成了私钥？（贴上去的必须是以 `.pub` 结尾那个文件的内容）
3. 是否在正确的 GitHub 账号下添加的？

### `Connection timed out` / `Connection was reset`

网络问题。**直接用 SSH，别折腾代理**（见第一、二节）。

### 浏览器能打开 GitHub，但 git 不行

看第二节的「反直觉的坑」。**改用 SSH 就好。**

### 之前配过代理，代理换端口后 git 挂了

按第五节的「代理换端口后怎么改」重新配，或者干脆 unset 掉改用 SSH。

### 私钥不小心泄露了怎么办

马上去 https://github.com/settings/keys 删掉那个 key，然后重新生成一对。
**私钥泄露 = 别人能以你的身份推代码。**

### 换电脑了怎么办

新电脑上重新生成一对密钥，把新公钥加到 GitHub。
同一个账号可以加多个 key，不同电脑各一对，互不影响。

---

## 九、三个人各配一次

- **各人生成各人的密钥**，不要共享私钥
- 每个人在自己电脑上做一遍第三节的 6 步
- 配好之后，**代理怎么变都不用管了**，这是选 SSH 最大的好处
