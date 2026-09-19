# 网络与 SSH 配置

> ⚠️ **每个队员第一次用之前都要做这一步。**

## 一、为什么需要这个

如果你在中国大陆，`git clone` / `git push` 走 HTTPS 访问 GitHub 时，
经常会遇到这种情况：

```
fatal: unable to access 'https://github.com/...': Recv failure: Connection was reset
```

或者：

```
fatal: unable to access 'https://github.com/...': Failed to connect to github.com port 443
```

**这不是你代码写错了**，是网络到 GitHub 的连接被中断了。
典型特征是：`ping` 能通、`Test-NetConnection` 显示端口通，但一到传数据就被重置。

**解决办法：改用 SSH 通道。** 实测 SSH 在我们这边是通的，而且配一次就一劳永逸。

---

## 二、配置步骤（5 分钟）

### 第 1 步：生成密钥

打开 PowerShell：

```powershell
ssh-keygen -t ed25519 -C "你的邮箱" -f "$env:USERPROFILE\.ssh\id_ed25519" -N '""'
```

一路回车即可。会生成两个文件：

| 文件 | 说明 |
|---|---|
| `id_ed25519` | **私钥**。留在本机，**绝对不要发给任何人** |
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

## 三、如果 SSH 也不通

有些网络环境会连 22 端口一起封。可以改走 443 端口（GitHub 提供的备用通道）：

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

---

## 四、如果还是不行

按顺序试这几个：

| 方案 | 做法 |
|---|---|
| 1. 开代理/VPN | 开着代理再用 git，一般都能通 |
| 2. 走代理端口 | 假设代理软件监听 `7890`：<br>`git config --global http.proxy http://127.0.0.1:7890`<br>`git config --global https.proxy http://127.0.0.1:7890`<br>不用了记得取消：`git config --global --unset http.proxy` |
| 3. 手机热点 | 有些校园网/运营商线路更严，换网络往往就好了 |
| 4. 找能连的同学 | 让他帮你 `git push`（代码在你自己本地，不用担心） |

---

## 五、常见问题

### `Permission denied (publickey)`

说明网络通了，但 GitHub 不认你的密钥。检查：

1. 公钥是不是完整复制了？（必须一整行，从 `ssh-ed25519` 到邮箱）
2. 是不是复制成了私钥？（贴上去的必须是以 `.pub` 结尾那个文件的内容）
3. 是否在正确的 GitHub 账号下添加的？

### `Connection timed out` / `Connection was reset`

网络问题，见上面第四节。

### 之前配过代理，现在换成别的网络用不了了

取消代理配置：

```powershell
git config --global --unset http.proxy
git config --global --unset https.proxy
```

### 私钥不小心泄露了怎么办

马上去 https://github.com/settings/keys 删掉那个 key，然后重新生成一对。
私钥泄露 = 别人能以你的身份推代码。

---

## 六、给三个人各配一次

每个人都要在自己电脑上做一遍（第 1~5 步）。
**私钥不要共享**——各人生成各人的，各自加到 GitHub 上。
