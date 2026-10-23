# ResolveLab

让支持 Agent 不仅声称“已修复”，还要用实际数据证明。

ResolveLab 是一个可在本地运行的 Agent 工程与后训练实验平台：本地模型选择工具，
独立验证器检查真实结果，公开数据、训练记录、失败轨迹和可重复执行的评测。

![结构化输出基线、三组 LoRA 训练与真实 HTTP 轨迹](docs/assets/http-study.png)

## v0.4：先拆穿 v0.3 的结果，再用等量对照检验 DAgger

- **自我审查**：v0.3 的 30 个测试回合实际只有 3 条记录；配对的 0.6B 基线从未接触到
  任何故障；只移动目标位置的反事实实验表明，v0.3 adapter 在原示范下解出 54/54 个
  第二页及以后的目标，把示范的目标挪到第一页后变成 0/54，学到的是示范的排列方式。
  见 [审查报告](docs/v0.3-review.md)。
- **新基准**：288 个回合，每个回合一条独立记录；目标位置、相似引用的形态和任务措辞
  都是声明的因素，测试集一半使用训练中从未出现的措辞。
- **对比设计**：`dagger` 在学习者自己访问的状态上加入经重放验证的老师标注；
  `bc-volume` 从同一批回合加入同样数量的专家行。实验与判定规则在任何 v2 模型运行前
  登记，测试输入和全部 adapter 在第一次测试前锁定。

| 测试集（120 个独立回合） | 种子 3407 / 42 / 2026 | 均值 |
|---|---|---:|
| Qwen3-0.6B 基线 | 0/120 | 0.0% |
| Qwen3-1.7B 基线（单示范 / 三示范） | 28/120 / 18/120 | 23.3% / 15.0% |
| v0.3 已发布 adapter | 42、30、34 | 29.4% |
| 行为克隆 `bc` | 113、112、102 | 90.8% |
| 行为克隆 + 额外专家数据 `bc-volume` | 115、108、104 | 90.8% |
| 行为克隆 + DAgger 数据 `dagger` | **118、117、119** | **98.3%** |

`dagger − bc-volume` = **+7.5 个百分点，95% 区间 [1.9, 13.3]**（同时重抽训练种子和记录；
按登记规则判定为成立），安全违规数相同。只加专家数据没有任何提升。差异来自专家数据中
从未出现的一种累积错误：抄错 ETag 后自己触发 412 并陷入循环，占 `bc-volume` 33 个失败中的
26 个，`dagger` 为 0。[完整结果、失败分类与局限](artifacts/v0.4/RESULTS.md)；无需 GPU 的审计：
`python scripts/verify_casedesk_v2.py`。

## v0.3：控制 JSON 结构后，再看决策是否正确

> 作为头条结论已被 [v0.3 审查](docs/v0.3-review.md) 取代；作为登记记录原样保留。

- 第二个服务 CaseDesk 通过真实 HTTP 请求操作工单，支持分页、ETag 并发冲突、
  幂等键、提交后的 502 响应、429 重试等待和任务中途的权限撤销。
- Qwen3-0.6B、Qwen3-1.7B 基线和 LoRA 模型使用同一工具 Schema、训练示例、
  提示及调用预算。解码器保证结构约束，不替模型选工具、工单 ID 或恢复策略。
  另外加入 Qwen3-4B / Ollama 对照，单独标明量化、后端及解码器实现差异。
- 使用 48 个训练任务中的 322 个已验证专家动作，运行三个预先指定的训练种子，
  每组按开发集损失选择检查点，再测全新冻结的 30 个测试回合
  （10 种故障组合 × 3 个独立于训练的记录种子）。
- 分开报告调用格式、真实完成率、错误写入、虚假成功和多余写入。
  页面可以查看全部模型任务；`python scripts/verify_http_study.py` 无需 GPU
  就能重新执行公开动作，核对 HTTP 响应、最终记录、数据与模型哈希。

<!-- HTTP_RESULTS_START -->

| Policy | Task success | Schema-valid calls | False success |
|---|---:|---:|---:|
| Qwen3-0.6B base | 0/30 | 100.0% | 10 |
| Qwen3-1.7B base | 12/30 | 100.0% | 14 |
| 0.6B LoRA / 3407 | 20/30 | 100.0% | 0 |
| 0.6B LoRA / 42 | 30/30 | 100.0% | 0 |
| 0.6B LoRA / 2026 | 20/30 | 100.0% | 10 |

Supplementary Qwen3-4B Q4_K_M / Ollama: **6/30** passed, **100.0%** schema-valid calls. Different quantization/backend; not a matched training effect.

[Full results, paired intervals and failures](artifacts/v0.3/RESULTS.md).
<!-- HTTP_RESULTS_END -->

[发布验收](artifacts/v0.3/validation.json)：129 项测试、全部 180 次 HTTP 轨迹重放、
浏览器检查及干净环境安装检查均通过。

CaseDesk 是真实 HTTP 边界后的合成服务，状态只在进程存续期间保留。
结果衡量已知 API 下新故障组合的恢复，尚未验证生产可靠性或未知工具泛化。
[实验协议与复现](docs/httpdesk-protocol.md) · [模型卡](docs/httpdesk-model-card.md) ·
[面试追问与边界](docs/interview-notes.md)

<details>
<summary>历史 v0.2：首次训练、部分提交修复与格式混淆</summary>

## 历史 v0.2

v0.2 包括 10 种开发回归场景、9 个工具、可视化执行轨迹、幂等操作记录、
中断恢复、独立故障组合测试集，以及实际在本地 GPU 上运行的 LoRA 后训练。
交互演示使用 Ollama，训练和成对评测使用 Transformers / PEFT。

训练集、开发集、测试集分别包含 72 / 8 / 24 个任务，按故障组合和种子分开。
Qwen3-0.6B 使用 528 个经过执行验证的专家动作训练；基础模型与适配模型使用
相同提示、解码方式和工具预算。完整结果、失败轨迹及复现步骤见
[后训练报告](artifacts/v0.2/RESULTS.md)和[实验协议](docs/post-training.md)。

原先部分提交后耗尽输出预算的失败，已加入有上限的推理重试；真实 Qwen3-4B
在 3 个回归种子上均成功恢复。报告保留额外生成成本及原始失败，不隐藏代价。

</details>

## 启动

```powershell
git clone https://github.com/Ta0p1/ResolveLab.git
cd ResolveLab
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\resolvelab.exe serve
```

打开 <http://127.0.0.1:8765>。无需模型就可运行明确标为 scripted 的规则基线。
真实模型运行需要先启动 Ollama，并执行 `ollama pull qwen3:4b`，然后在页面中
选择 **Local LLM · Ollama**。**HTTP study** 展示本轮对照、三组训练与全部测试轨迹；
**Post-training** 保留 v0.2 结果。HTTP study 展示的是记录的真实模型执行，不是实时推理。

## 如何理解结果

- `reference`：针对已知环境编写的规则策略，用来检查环境是否可解。
- `naive`：刻意较弱的重复追加策略，用来演示重复写入与错误成功声明。
- `ollama`：真实本地模型推理，没有隐藏的规则回退。
- Pass 包含权限不足时的正确升级处理；报告另外列出真正完成修复的任务数。
- 10 个演示场景属于开发回归集。独立测试集检验同一服务中未训练的故障组合，
  不代表对新工具、新领域或生产事故的泛化能力。
- `python scripts/verify_experiment.py` 无需 GPU，可重新执行公开测试轨迹验证报告。

[英文 README](README.md) · [评测协议](docs/evaluation.md) ·
[演示讲稿](docs/demo.md) · [英文简历素材](docs/resume.md) ·
[后续训练路线](docs/roadmap.md)
