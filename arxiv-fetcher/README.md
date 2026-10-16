# Evidence-Gated Daily Literature Fetcher

### Mihomo 代理与抓取恢复

`config.yaml` 的 `network.require_proxy: true` 要求抓取及模型请求使用代理；
`network.mihomo_profile` 从指定配置读取 `mixed-port`（当前为7890），不会导入节点凭据。
也可用 `network.proxy_url: http://127.0.0.1:7890` 显式覆盖端口。
Mihomo须在任务执行时运行；代理不可用时报告错误，不会自动改走直连。TLS证书校验保持开启。

arXiv API限流时，本轮后续查询改用官方高级检索网页，保留提交日期范围。
网页回退将作者字段和部分分类条件放宽为文本查询，随后仍通过兴趣相关性初筛及正文审查。
arXiv请求串行且至少间隔3秒；可设置 `network.arxiv_search: web` 直接使用网页检索。

候选先保存为 `logs/discovery_日期_时间.json` 及同名Markdown，即使模型服务故障也不会丢失。
候选清单不等于正式推荐。模型恢复后可从JSON继续审查，无需再次查询来源：

```text
D:\ProgramData\anaconda3\envs\Filend\python.exe run_scheduled.py --from-discovery logs/discovery_日期_时间.json
D:\ProgramData\anaconda3\envs\Filend\python.exe run_scheduled.py --arxiv-only --start-date 2026-10-05 --end-date 2026-10-11
```

追加 `--discover-only` 可只保存候选清单，不调用模型或生成正式推荐。

原有每日12:00任务继续使用相同入口，并自动读取上述代理配置。

## 当前运行方式

当前入口为 `arxiv_daily.py`，调用 `curated_fetcher.py`。以下配置取代旧版“每领域5篇、只读摘要生成总结”的行为。

- 每天全领域累计最多 **5篇**，允许0篇；不为领域配额或篇数凑数。
- 正文初审分数严格大于75的论文另存于日期目录的 `初审保留/`，包括复核未通过者，保留双方意见；不计入正式推荐上限。这里使用正文初审分数，不是摘要筛选的priority。可用 `--retain-from-audit logs/review_日期_时间.json` 从已有审查记录补存，无需联网。
- 七个方向见 `config.yaml`，Agent的检索不限于harness和self-improving；MLIP团队声望不直接决定入选。
- 默认检索最近14天，arXiv覆盖全部方向，Crossref补充反应机理期刊论文。每个查询取12条候选，非穷尽检索。
- 摘要初筛后，最多18篇进入完整HTML/PDF正文文本审查及反方复核。正文获取失败、过长无法完整审查、证据不足或模型失败均不降级推荐。
- 要求至少两条可在正文中定位的原文证据；评分至少85，同时满足实质创新、深入论证或机理突破之一。分数不代表科学质量保证。
- 笔记列出实质推进、已有工作对比、宣称与证据、局限和复核意见。自动文本审查不等于实验复现、图像或补充材料核验，第二轮同模型复核也不是独立专家审查。
- 历史推荐和arXiv版本去重；当天重复运行共享总量限制。不要绕过启动器同时启动多个写入进程。

### 本机命令

```text
D:\ProgramData\anaconda3\envs\Filend\python.exe arxiv_daily.py --check
D:\ProgramData\anaconda3\envs\Filend\python.exe run_scheduled.py --probe
D:\ProgramData\anaconda3\envs\Filend\python.exe run_scheduled.py --dry-run
D:\ProgramData\anaconda3\envs\Filend\python.exe run_scheduled.py
D:\ProgramData\anaconda3\envs\Filend\python.exe -m unittest test_curated_fetcher -q
```

`--check`只检查本地配置；`--probe`实测接口和模型认证；`--dry-run`执行实际检索审查并消耗API额度，但不写推荐及状态。启动器自身仍记录运行日志。`--max-results`控制每个查询的候选量，不改变每日推荐上限；`--days-back`覆盖时间窗口。

### 定时任务与输出

任务配置为每日12:00，直接运行Filend环境中的Python和 `run_scheduled.py`，启动器使用脚本所在目录，不依赖PowerShell字符串解析。最长运行两小时。使用当前登录用户身份，因此需要用户已登录且网络可用。

在管理员终端导入本机任务配置：

```text
schtasks.exe /Create /TN "arXiv Daily Fetcher" /XML D:\ECUST\Filend_Knowledge_Base\arxiv-fetcher\scheduler_task.xml /F
```

`scheduler_task.xml`包含本机用户SID和绝对路径，不适用于其他电脑。通用安装脚本 `setup_scheduler.ps1` 同样已改为12:00、Filend环境和直接Python启动。

- 笔记和速览：`D:\ECUST\Filend_Knowledge_Base\Papers\YYYY-MM-DD\`
- 运行日志：`arxiv-fetcher\logs\arxiv_daily_YYYYMMDD.log`
- 审查记录：`arxiv-fetcher\logs\review_日期_时间.json`
- 入选论文的审查原文：`arxiv-fetcher\logs\evidence\`
- 推荐账本：`recommendations.json`；兼容旧账本 `fetched_papers.json`，保留历史文件。

推荐仍通过Obsidian文件交付，未配置邮件或聊天消息发送。检索/模型故障会返回非零退出码，并与“候选未通过质量门槛”区分。

### 在线阅读补充的交付要求

用户要求直接在线阅读时，无需下载PDF；可由当前对话AI读取可访问的HTML正文并总结，不依赖自动审查接口。每篇交付必须包含中文Summary、具体方法（输入/流程/输出）、创新点与已有工作区别、关键结果及正文定位、局限、与用户研究的关系。对话中也应呈现核心总结，不能仅给链接或筛选短评。研究启发须标为推断，综述不能写成原创方法；此流程的笔记不得伪称通过原双轮自动评分。本条为人工交互工作流要求，不代表定时程序已具备该回退能力。

模型服务读取 `config.yaml` 的 `llm` 配置。目前使用 `gpt-6.1-sol`，通过流式Responses协议调用指定中转服务；临时过载最多尝试6次，指数退避15–120秒，并遵循服务端 `Retry-After`。来源GET请求对超时、断连和临时HTTP错误最多尝试5次，永久HTTP错误立即报告；日志保留HTTP状态码。`api_key_file` 指向本机 `D:/ECUST/scripts/codex/codex-zzy.ps1`，只解析密钥的字面量赋值，不执行脚本、不复制密钥。设置该文件时优先使用文件；未设置时使用 `ARXIV_LLM_KEY` 或 `api_key`。认证失败需更换有效凭据；勿将密钥写入日志或提交到版本库。

---

## 旧版说明（仅作历史参考，行为以以上说明为准）

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
