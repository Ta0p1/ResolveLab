# ResolveLab

让支持 Agent 不仅声称“已修复”，还要用实际数据证明。

ResolveLab 是一个可在本地运行的数据同步故障恢复实验平台：本地模型选择工具、
SQLite 保存真实操作结果、独立验证器检查任务是否完成，并生成可复现评测报告。

v0.2 包括 10 种开发回归场景、9 个工具、可视化执行轨迹、幂等操作记录、
中断恢复、独立故障组合测试集，以及实际在本地 GPU 上运行的 LoRA 后训练。
交互演示使用 Ollama，训练和成对评测使用 Transformers / PEFT。

训练集、开发集、测试集分别包含 72 / 8 / 24 个任务，按故障组合和种子分开。
Qwen3-0.6B 使用 528 个经过执行验证的专家动作训练；基础模型与适配模型使用
相同提示、解码方式和工具预算。完整结果、失败轨迹及复现步骤见
[后训练报告](artifacts/v0.2/RESULTS.md)和[实验协议](docs/post-training.md)。

原先部分提交后耗尽输出预算的失败，已加入有上限的推理重试；真实 Qwen3-4B
在 3 个回归种子上均成功恢复。报告保留额外生成成本及原始失败，不隐藏代价。

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
选择 **Local LLM · Ollama**。**Post-training** 页面展示已经测得的训练曲线和成对测试结果。

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
