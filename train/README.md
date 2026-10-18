# Qwen2.5-7B 工具调用微调

给语音助手的「大脑」做 LoRA 微调，目标是让 Qwen **更稳定地选对工具、把参数填全**，
而不是靠 prompt 硬撑。

---

## 一、为什么是「工具调用微调」

我们的 system prompt 已经有 16 个工具定义（5 个用药 + 4 个呼救 + 4 个健康反馈，
加上更多 action 共 16 个）。靠 prompt 引导会遇到三个反复出现的问题：

| 现象 | 后果 |
|---|---|
| 漏填必填字段（药名/剂量/频次/时间） | 程序校验不通过，变成追问，老人得多说一遍 |
| 药名、剂量「脑补」（prompt 里举的例子被当成用户输入） | 老人没说的用量被填进去，**有安全风险** |
| 该闲聊的时候硬调工具 | 体验差，还会写脏数据 |

这三件事都是**行为模式**问题，正是 SFT 擅长的：给它几千条「这句话 → 这个
tool_call」的配对，比在 prompt 里写十条规矩更管用。

---

## 二、数据从哪来（关键设计）

组长那边训练数据还没准备。我们不依赖人工标注，而是**从 skill 库自己的 schema 反推**：

```
skills/*/schema.py  (Pydantic 参数模型)
        │
        ├──> ① 生成话术：按 action 的必填字段，用模板 + 槽位填充造老人口语
        ├──> ② 生成标签：{"name": ..., "arguments": {...}}
        ├──> ③ 用同一个 Pydantic 模型校验标签  ← 不合法直接丢弃
        └──> ④ 组装成与推理完全一致的 messages（system + tools + 对话）
```

好处：

- **标签 100% 合法**：工具名、枚举值、跨字段规则（如「一天三次必须有 3 个时间点」）
  全部由程序保证，不存在人工标注写错
- **风格可控**：话术模板里混入口语、省略、倒装、语气词，模拟老人说话和 ASR 错字
- **可扩展**：新增 skill 或参数，重新跑一遍生成器就有新数据

生成的四类样本：

| 类型 | 占比 | 教模型什么 |
|---|---|---|
| 单轮工具调用 | ~75% | 选对工具、填全参数 |
| 多轮补充 | ~10% | 用户先说一半，追问后**结合上文**补全 |
| 闲聊 / 越界 | ~10% | 该不调工具时别调 |
| 信息不足先追问 | ~5% | 关键信息缺失时**问，不猜** |

---

## 三、训练配置

| 项 | 值 | 理由 |
|---|---|---|
| 方法 | LoRA（r=16, alpha=32, dropout=0.05） | 7B 全参需要 100G+ 显存，A100-40G 放不下 |
| 目标模块 | 全部线性层（q/k/v/o + gate/up/down） | 工具调用需要同时改「理解」和「输出」 |
| 精度 | bf16 + gradient checkpointing | A100 原生支持，省显存 |
| Loss 范围 | **只算 assistant 回复** | prompt 占 5100+ token，全算会浪费算力且学成「背 schema」 |
| 最大长度 | **6144**（实测决定） | 实测 system+tools = **5137** token，样本 p50=5576、max=5737；用 2048 会全量丢弃 |
| batch | 1 × grad_accum 16 | 有效 batch 16 |
| 学习率 | 1e-4，cosine + 3% warmup | LoRA 常用区间 |
| 轮次 | 2 epoch | 数据 4500 条，工具调用是窄任务，LoRA 收敛很快；先 2 轮看效果再加 |
| 显存预计 | 权重 15G + 激活 8-12G | 40G 有余量，可考虑提到 batch=2 |

---

## 四、怎么跑

```bash
# 1. 冒烟（20 步，验证环境/数据/显卡/保存，约 5 分钟）
cd ~/seniortalk_voice_agent_20260929/skill
sbatch train/smoke.slurm
tail -f outputs/slurm/lora_smoke_<JOBID>.log

# 2. 正式训练（含数据生成 + 训练 + 评测，12 小时上限）
sbatch train/train.slurm

# 3. 单独评测（跳过训练，直接比基座 vs LoRA）
python train/eval_lora.py --model ../models/Qwen2.5-7B-Instruct \
    --adapter outputs/lora_v1/adapter --data-dir data/sft --limit 150
```

产出：

```
outputs/lora_v1/
├── adapter/            # LoRA 权重（约 40MB），推理时挂到基座上
├── eval_base.json      # 基座模型指标
└── eval_lora.json      # 微调后指标
```

---

## 五、怎么判断「训好了」

`eval_lora.py` 报六个指标，按重要性排：

| 指标 | 含义 | 期望 |
|---|---|---|
| `tool_accuracy` | 工具选对的比例 | 基座通常已不低，重点看下面两项 |
| `args_exact_rate` | 参数**逐字段完全**正确 | **主要看这个**，漏填/多填都会掉 |
| `schema_valid_rate` | 参数能通过真实 Pydantic 校验 | 应接近 1.0 |
| `field_f1` | 字段级精确率/召回率 | 看是「漏填」还是「瞎填」多 |
| `json_valid_rate` | 输出能解析 | 应接近 1.0 |
| `no_tool_accuracy` | 该闲聊时确实没调工具 | 防止过度调用 |

**验收线建议**（可以拿去跟组长对齐）：
- `args_exact_rate` 相对基座提升 ≥ 15 个百分点
- `schema_valid_rate` ≥ 0.97
- `no_tool_accuracy` 不下降

---

## 六、几个已知的坑

1. **CRLF**：Windows 上编辑的 `.slurm` 会被 sbatch 拒绝。
   已加 `.gitattributes`（`*.slurm text eol=lf`），历史文件用
   `python train/fix_crlf.py train` 修。
2. **依赖不能乱升**：服务器离线，`pip download` 默认会解析出
   peft 0.21 + transformers 5.x，把环境搞坏。本次用
   `--no-deps` 锁 `peft==0.14.0 / accelerate==1.2.1` 与现有
   transformers 4.51.3 配套。
3. **身份字段不能进标签**：`person_id` / `target_person` 由程序注入，
   生成数据和训练标签里都已剔除（与 `qwen_agent.py` 的工具定义一致）。
4. **system prompt 必须一致**：数据生成时直接 `import qwen_agent` 拿 POLICY，
   改了 POLICY 就要重新生成数据，否则训练/推理分布不一致。
5. **工具定义占了 92% 的 prompt**（5137 / 5576 token）。这意味着：
   每条样本真正参与 loss 的只有 20-30 个 token，训练时 GPU 绝大部分算力
   花在前向这些 schema 上。如果后续嫌慢，方向是「减少数据量 + 增加 epoch」
   或做 prefix caching，而不是增大 batch（显存吃得下但时间不会变快）。
6. **Slurm 会把脚本复制到 spool 目录执行** —— 这是个坑：
   - `dirname $0` 拿到的是 spool 路径，**不能用它定位仓库**；
     必须用 `${SLURM_SUBMIT_DIR}`
   - `#SBATCH --output=相对路径` 会写到 spool 目录并因没权限直接失败，
     **必须用绝对路径**
   - 症状：作业 `FAILED 00:00:01`，err 里是
     `mkdir: cannot create directory '/opt/gridview/slurm/spool/slurmd/outputs': Permission denied`
   - 所以脚本统一要求：**在仓库根目录 `sbatch`**
7. **计算节点首次 import 很慢**：`import torch, transformers` 在计算节点冷缓存下
   要 **100 秒左右**（登录节点只要几秒）。这会把短作业的「启动开销」放大，
   写超时时间时要算进去。进程状态显示 `D (disk sleep)` 属正常，不是死锁。

---

## 七、CPU 冒烟：不等 GPU 也能验证代码

`train/cpu_smoke.slurm` 用 `train/make_tiny_model.py` 造一个 **9.8M 参数的迷你 Qwen**
（只复制真实 tokenizer，保证 chat_template 一致），在 **cpu 分区**把整条链路跑一遍：

```
造迷你模型 → 造 40 条小数据 → 预检（长度与真实模型一致）
  → 训练 3 步 → 存 checkpoint → 断点续训到 6 步
  → 导出 adapter → 跑 2 条评测
```

**它验证的是**：数据编码、loss mask、collator、peft 挂载、Trainer、checkpoint、
断点续训、评测指标计算——这些和模型大小无关，所以 CPU 就能排掉绝大部分 bug。

```bash
cd <仓库根目录>
sbatch train/cpu_smoke.slurm
tail -f outputs/slurm/cpu_smoke_<JOBID>.log
```

实测耗时约 11 分钟（其中 2 分钟是 import，8 分钟是两次训练+评测）。

---

## 八、分层排队的现实：GPU 常年排满

`gpu` 分区只有 7 台机器 / 14 张 A100-40G，我们账号（cjzhou）**只能**用 `gpu` 和 `cpu`：

| 分区 | 我们能提交吗 | 原因 |
|---|---|---|
| `gpu` | ✅ | `DenyAccounts` 里没有 cjzhou |
| `cpu` | ✅ | 同上（但没有 GPU） |
| `gpu_test` | ❌ | `AllowAccounts=ybyao,cross_sched,ecnuhpc` |
| `tzhu_g`（A100-80G，常空闲） | ❌ | `AllowAccounts=tzhu_c` |
| `xiaohe2` / `tzhu_c` / `ASC` | ❌ | 各自的 `AllowAccounts` 白名单 |

实测 2026-10-18：14 张卡全被占，`squeue --start` 报的预计开始时间是 **10-21**。
别的用户的作业是隐藏的（`PrivateData=jobs`），看不到结束时间。

所以本项目的训练作业设计成**可分片续跑**：`--time=04:00:00` + 每 100 步存盘 +
`--resume`。一旦某次被超时杀掉，**再 `sbatch` 一次同一个脚本就会从最新断点继续**，
不要删 `outputs/lora_v1/`。

```bash
bash train/cluster_status.sh    # 看排队情况与预计开始时间
sbatch train/train.slurm        # 排上；超时后照原样再提一次
```


---

## 七、下一步可以做的

- [ ] 数据量扩到 1-2 万条（加同义改写、方言化表达、ASR 错字模拟）
- [ ] 加入真实 ASR 输出（等语音那组出结果）作为噪声样本
- [ ] 对比 QLoRA（4bit）看 40G 显存下能否上 batch=4、更快
- [ ] 把评测接到端到端 agent（`qwen_agent.py`）跑，看真实任务成功率
