# ResolveLab

让支持 Agent 不仅声称“已修复”，还要用实际数据证明。

ResolveLab 是一个可在本地运行的数据同步故障恢复实验平台：本地模型选择工具、
SQLite 保存真实操作结果、独立验证器检查任务是否完成，并生成可复现评测报告。

第一版包括 10 种合成故障场景、9 个工具、可视化执行轨迹、幂等操作记录、
中断恢复、评测面板和 JSONL 导出。支持 Ollama；尚未实现 vLLM 或模型训练。

## 启动

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\resolvelab.exe serve
```

打开 <http://127.0.0.1:8765>。无需模型就可运行明确标为 scripted 的规则基线。
真实模型运行需要先启动 Ollama，并执行 `ollama pull qwen3:4b`，然后在页面中
选择 **Local LLM · Ollama**。

## 如何理解结果

- `reference`：针对已知环境编写的规则策略，用来检查环境是否可解。
- `naive`：刻意较弱的重复追加策略，用来演示重复写入与错误成功声明。
- `ollama`：真实本地模型推理，没有隐藏的规则回退。
- Pass 包含权限不足时的正确升级处理；报告另外列出真正完成修复的任务数。
- 场景是公开的开发回归集，不能据此声称生产可靠性或未知任务泛化能力。

[英文 README](README.md) · [评测协议](docs/evaluation.md) ·
[演示讲稿](docs/demo.md) · [英文简历素材](docs/resume.md) ·
[后续训练路线](docs/roadmap.md)
