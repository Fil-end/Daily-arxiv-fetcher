# arXiv Daily Fetcher v3

自动从 arXiv 抓取感兴趣领域的论文，调用 LLM 生成中文深度总结，并导入 Obsidian 知识图谱。

## 功能

- 按关键词从 arXiv 检索论文，支持多领域分组建模
- 调用 LLM（OpenAI 兼容 / Anthropic / Ollama）自动生成结构化中文总结（内容总结、方法详解、关键结果、局限与展望）
- 生成 Obsidian 兼容的 Markdown 笔记，包含 YAML frontmatter、参考文献信息、待办清单
- 每日自动生成文献速览综述
- 去重机制，避免重复抓取
- 支持 Windows 定时任务自动运行

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config.yaml`：

```yaml
interests:
  - name: "催化与表面科学"
    keywords:
      - "heterogeneous catalysis"
      - "DFT"
      - "catalyst"
      # ...

obsidian:
  vault_path: "D:\\your-vault-path"
  target_folder: "Papers"

llm:
  enabled: true
  provider: "openai"          # openai | anthropic | ollama
  api_key: "sk-xxx"          # 或设置环境变量 ARXIV_LLM_KEY
  api_base: "https://api.deepseek.com/v1"
  model: "deepseek-chat"
  max_tokens: 10000
  temperature: 0.3
```

### 3. 运行

```bash
# 默认运行
python arxiv_daily.py

# 预览模式（不写文件）
python arxiv_daily.py --dry-run

# 每领域最多抓取 10 篇
python arxiv_daily.py --max-results 10

# 限定最近 30 天
python arxiv_daily.py --days-back 30
```

## 定时任务（Windows）

以管理员身份运行 PowerShell：

```powershell
# 安装每天 08:00 自动运行
.\setup_scheduler.ps1

# 自定义时间
.\setup_scheduler.ps1 -ScheduleTime "09:00"

# 手动运行一次
.\setup_scheduler.ps1 -RunNow

# 卸载
.\setup_scheduler.ps1 -Uninstall
```

也可直接使用 `run_daily.bat` 配合 Windows 任务计划程序。

## 输出结构

```
{Papers}/{YYYY-MM-DD}/
├── 2025-01-15-文献速览.md          # 每日综述
├── 催化与表面科学/
│   └── 2025 - FirstAuthor - Title.md
├── 强化学习与AI/
│   └── 2025 - FirstAuthor - Title.md
└── ...
```

每篇论文笔记包含：元数据、摘要、AI 深度总结（方法详解、关键结果、局限与展望）、待办清单。

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--config` | 配置文件路径 | `config.yaml` |
| `--dry-run` | 预览模式，不写文件 | `false` |
| `--max-results` | 每个领域最多抓取篇数 | `5` |
| `--days-back` | 限定最近 N 天 | `730` |
| `--pause` | 请求间隔（秒） | `10` |

## LLM 支持

- **OpenAI 兼容**：DeepSeek、OpenAI、本地 vLLM 等，设置 `api_base`
- **Anthropic**：Claude 系列
- **Ollama**：本地模型，设置 `api_base` 为 Ollama 地址

也可通过环境变量 `ARXIV_LLM_KEY` 传入 API Key，避免写入配置文件。
