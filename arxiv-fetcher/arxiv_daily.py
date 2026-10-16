#!/usr/bin/env python3
"""
arXiv Daily Fetcher v3 — 自动抓取 & AI 深度总结 & Obsidian 知识图谱导入.

用法:
    python arxiv_daily.py                     # 默认 config.yaml
    python arxiv_daily.py --dry-run           # 预览不写文件
    python arxiv_daily.py --max-results 10    # 每个领域最多抓取 N 篇
    python arxiv_daily.py --days-back 30      # 限定最近 N 天的论文
"""
import argparse, json, os, re, sys, time, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import feedparser, yaml
from http_transport import SESSION

feedparser.USER_AGENT = "arXivDailyFetcher/3.0 (mailto:researcher@example.com)"

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.yaml"
ARXIV_API = "https://export.arxiv.org/api/query"

# ── 以下参数可直接在命令行覆盖，无需写在 config.yaml 中 ──
DEFAULT_MAX_RESULTS = 5
DEFAULT_DAYS_BACK = 730
DEFAULT_PAUSE_SECONDS = 10

# ──────────────────────────────────────────────
# 1. 配置 / 历史
# ──────────────────────────────────────────────
def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_history(path):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ──────────────────────────────────────────────
# 2. arXiv 查询 (关键词分批)
# ──────────────────────────────────────────────
KEYWORDS_PER_BATCH = 3  # arXiv API 限制，每批关键词数不宜过多

def build_query(keywords):
    parts = []
    for kw in keywords:
        safe = kw.replace('"', "").replace("(", "").replace(")", "")
        if " " in safe:
            parts.append(f'all:"{safe}"')
        else:
            parts.append(f"all:{safe}")
    return " OR ".join(parts)

def query_arxiv(interest, max_results):
    all_kw = interest.get("keywords", [])
    num_batches = max(1, (len(all_kw) + KEYWORDS_PER_BATCH - 1) // KEYWORDS_PER_BATCH)
    per_batch = max(1, -(-max_results // num_batches))  # ceil division
    seen_ids = set()
    all_entries = []

    for start in range(0, len(all_kw), KEYWORDS_PER_BATCH):
        if len(all_entries) >= max_results:
            break
        batch = all_kw[start:start + KEYWORDS_PER_BATCH]
        query = build_query(batch)
        params = {
            "search_query": query,
            "start": 0,
            "max_results": min(per_batch, max_results - len(all_entries) + 2),  # +2 for filtering buffer
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
        print(f"  [arXiv] {interest['name']}: batch [{start+1}-{min(start+KEYWORDS_PER_BATCH, len(all_kw))}]/{len(all_kw)} keywords → {params['max_results']} results")

        for attempt in range(5):
            from curated_fetcher import get
            import requests
            try:
                with get(url) as response:
                    resp = feedparser.parse(response.content)
                if resp.get("bozo") and not resp.get("entries"):
                    raise ValueError("Invalid arXiv feed")
            except (requests.RequestException, ValueError) as exc:
                print(f"  [arXiv] Batch failed: {type(exc).__name__}: {exc}")
                break
            status = resp.get("status")
            if status == 429:
                wait = (attempt + 1) * 20
                print(f"  [arXiv] HTTP 429 (rate limit), retrying in {wait}s...")
                time.sleep(wait)
                continue
            if status is not None and status >= 400:
                print(f"  [WARNING] arXiv returned HTTP {status}")
            entries = resp.get("entries", [])
            new_count = 0
            for e in entries:
                eid = e.get("id", "")
                if eid not in seen_ids:
                    seen_ids.add(eid)
                    all_entries.append(e)
                    new_count += 1
            print(f"  [arXiv] got {len(entries)} ({new_count} new), total unique: {len(all_entries)}")
            break
        else:
            print(f"  [arXiv] FAILED after 5 retries")
            continue

        if start + KEYWORDS_PER_BATCH < len(all_kw):
            time.sleep(3)

    return all_entries

# ──────────────────────────────────────────────
# 3. 关键词后过滤 + 论文解析
# ──────────────────────────────────────────────
def matches_keywords(entry, keywords):
    text = (
        f"{entry.get('title', '')} {entry.get('summary', '')} "
        f"{' '.join(t.get('term', '') for t in entry.get('tags', []))}"
    ).lower()
    for kw in keywords:
        if kw.lower() in text:
            return True
    return False

def extract_arxiv_id(entry):
    m = re.search(r"abs/([0-9]+\.[0-9]+(?:v\d+)?)", entry.get("id", ""))
    return m.group(1) if m else entry.get("id", "")

def parse_entry(entry):
    return {
        "arxiv_id": extract_arxiv_id(entry),
        "title": " ".join(entry.get("title", "").split()),
        "authors": [a.get("name", "") for a in entry.get("authors", [])],
        "summary": " ".join(entry.get("summary", "").split()),
        "published": entry.get("published", ""),
        "updated": entry.get("updated", ""),
        "link": entry.get("link", ""),
        "doi": extract_doi(entry),
        "categories": [t.get("term", "") for t in entry.get("tags", [])],
        "comment": entry.get("arxiv_comment", ""),
        "journal_ref": entry.get("arxiv_journal_ref", ""),
    }

def extract_doi(entry):
    for link in entry.get("links", []):
        if link.get("title") == "doi":
            m = re.search(r"10\.\d{4,}/[^\s]+", link.get("href", ""))
            if m: return m.group(0)
    m = re.search(r"10\.\d{4,}/[^\s]+", entry.get("summary", ""))
    return m.group(0).rstrip(".,;") if m else None

def first_author_lastname(authors):
    if not authors: return "Unknown"
    parts = authors[0].split()
    return parts[-1] if parts else authors[0]

def is_within_days(entry, days_back):
    pub_str = entry.get("published", "")
    try:
        pub_date = datetime.strptime(pub_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            upd_str = entry.get("updated", "")
            pub_date = datetime.strptime(upd_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return True
    return pub_date >= datetime.now(timezone.utc) - timedelta(days=days_back)

# ──────────────────────────────────────────────
# 4. LLM 深度总结（丰富版）
# ──────────────────────────────────────────────
def summarize_with_llm(paper, config):
    llm_cfg = config.get("llm", {})
    if not llm_cfg.get("enabled"):
        return None

    api_key = llm_cfg.get("api_key") or os.environ.get("ARXIV_LLM_KEY", "")
    if not api_key:
        print("    [LLM] Missing API key, skipping")
        return None

    provider = llm_cfg.get("provider", "openai")
    model = llm_cfg.get("model", "deepseek-chat")
    api_base = llm_cfg.get("api_base", "")

    authors_display = ", ".join(paper["authors"][:8])
    if len(paper["authors"]) > 8:
        authors_display += f" 等 ({len(paper['authors'])} 位)"

    prompt = f"""你是一位资深的学术研究者，正在为个人知识库撰写论文笔记。请对以下论文进行详尽、专业的中文总结，写得充实、具体，使读者无需翻阅原文即可把握论文全貌。

严格按以下格式输出，每个部分都必须写够内容，不要敷衍：

## 内容总结
（对论文的整体概述，请写 200-400 字：
- 这篇论文要解决什么问题？为什么值得研究？
- 核心发现或贡献是什么？用了什么方法？
- 得出了什么关键结论？有什么意外发现？
- 该工作在领域中的定位和意义。）

## 方法详解
（这是最重要的部分，请尽可能详细，写 300-600 字：
- 论文提出了什么方法/框架/模型？其核心思想是什么？
- 方法由哪些模块/组件构成？各模块分别起什么作用？各模块间如何协同？
- 如果有关键公式或算法流程，请用自然语言描述其思想。
- 实验/计算是如何设计的？使用了什么数据集或系统？关键参数有哪些？
- 方法的创新之处在哪里？与已有方法相比有什么本质不同或优势？
- 请写得足够详细，使读者能把握方法的全貌。）

## 关键结果
（列出主要实验/理论发现，包含具体数值和对比数据：
- 性能提升百分比、对比基线的优势、关键数据指标等。
- 如有多个实验，请逐项说明实验设置和主要发现。）

## 局限与展望
（客观指出方法的局限性和适用边界，以及未来可能的研究方向。）

论文信息：
- 标题: {paper['title']}
- 作者: {authors_display}
- 摘要: {paper['summary']}
- 类别: {', '.join(paper.get('categories', []))}
- 备注: {paper.get('comment', '无')}
- 期刊引用: {paper.get('journal_ref', '无')}"""

    try:
        if provider == "anthropic":
            result = _call_anthropic(api_key, model, prompt, llm_cfg)
        elif provider == "ollama":
            result = _call_ollama(api_base, model, prompt, llm_cfg)
        else:
            result = _call_openai(api_key, api_base, model, prompt, llm_cfg)
        if result:
            print(f"    [LLM] ok ({model})")
        return result
    except Exception as e:
        print(f"    [LLM] Error: {e}")
        return None

def _call_openai(api_key, api_base, model, prompt, llm_cfg):
    import requests
    url = f"{api_base.rstrip('/')}/chat/completions" if api_base else "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": llm_cfg.get("max_tokens", 4000),
        "temperature": llm_cfg.get("temperature", 0.3),
    }
    resp = SESSION.post(url, json=payload, headers=headers, timeout=180)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

def _call_anthropic(api_key, model, prompt, llm_cfg):
    import requests
    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    payload = {"model": model, "max_tokens": llm_cfg.get("max_tokens", 4000), "messages": [{"role": "user", "content": prompt}]}
    resp = SESSION.post(url, json=payload, headers=headers, timeout=180)
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]

def _call_ollama(api_base, model, prompt, llm_cfg):
    import requests
    url = f"{api_base.rstrip('/')}/api/generate" if api_base else "http://localhost:11434/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False, "options": {"temperature": llm_cfg.get("temperature", 0.3)}}
    resp = SESSION.post(url, json=payload, timeout=300)
    resp.raise_for_status()
    return resp.json().get("response", "")

# ──────────────────────────────────────────────
# 5. Obsidian 笔记生成
# ──────────────────────────────────────────────
def classify_paper(paper):
    text = paper["summary"].lower()
    if any(w in text for w in ["review", "survey", "overview"]): return "综述"
    if any(w in text for w in ["benchmark", "dataset"]): return "基准/数据集"
    if any(w in text for w in ["theorem", "proof", "convergence"]): return "理论"
    if any(w in text for w in ["experiment", "measurement", "synthesis"]): return "实验"
    return "方法/算法"

def make_filename(paper):
    year = paper["published"][:4] if paper["published"] else "Unknown"
    author = first_author_lastname(paper["authors"])
    title = paper["title"]
    short = title[:80].rsplit(" ", 1)[0] if len(title) > 80 else title
    safe = re.sub(r'[\\/:*?"<>|]', "-", f"{year} - {author} - {short}")
    return f"{safe}.md"

def build_frontmatter(paper, tags):
    lines = ["---"]
    lines.append(f"title: \"{paper['title']}\"")
    authors_str = ", ".join(paper["authors"]) if paper["authors"] else "Unknown"
    lines.append(f"authors: \"{authors_str}\"")
    year = paper["published"][:4] if paper["published"] else "null"
    lines.append(f"year: {year}")
    lines.append(f"arxiv_id: \"{paper['arxiv_id']}\"")
    lines.append(f"doi: \"{paper.get('doi') or 'null'}\"")
    lines.append(f"link: \"{paper['link']}\"")
    tags_yaml = json.dumps(tags, ensure_ascii=False)
    lines.append(f"tags: {tags_yaml}")
    lines.append(f"created: \"{datetime.now().strftime('%Y-%m-%d')}\"")
    lines.append("---")
    return "\n".join(lines)

def generate_note(paper, config, interest_name):
    tags = ["paper"]
    for cat in paper.get("categories", []):
        tags.append(f"paper/{cat.replace('.', '-')}")
    tags.append(f"paper/领域/{interest_name}")

    authors_display = ", ".join(paper["authors"][:5])
    if len(paper["authors"]) > 5:
        authors_display += f" et al. ({len(paper['authors'])} authors)"

    paper_type = classify_paper(paper)
    llm_summary = summarize_with_llm(paper, config)

    note = []
    note.append(build_frontmatter(paper, tags))
    note.append("")
    note.append(f"## 元数据")
    note.append("")
    note.append(f"- **标题**：{paper['title']}")
    note.append(f"- **作者**：{authors_display}")
    note.append(f"- **arXiv ID**：[{paper['arxiv_id']}]({paper['link']})")
    note.append(f"- **DOI**：{paper.get('doi') or 'null'}")
    note.append(f"- **类别**：{', '.join(paper.get('categories', []))}")
    note.append(f"- **发表时间**：{paper.get('published', 'unknown')}")
    note.append(f"- **领域**：{interest_name}")
    if paper.get("journal_ref"):
        note.append(f"- **期刊**：{paper['journal_ref']}")
    note.append(f"- **论文类型**：{paper_type}")
    note.append("")
    note.append("## 摘要")
    note.append("")
    note.append(paper["summary"])
    note.append("")

    if paper.get("comment"):
        note.append("## 备注")
        note.append("")
        note.append(paper["comment"])
        note.append("")

    if llm_summary:
        note.append("## AI 深度总结")
        note.append("")
        note.append(llm_summary)
        note.append("")
    else:
        for section in ["核心贡献", "方法创新", "关键结果"]:
            note.append(f"## {section}")
            note.append("")
            note.append("> *LLM 总结未生成，待手动补充*")
            note.append("")

    note.append("## 我的思考与下一步")
    note.append("")
    note.append("- [ ] 阅读全文")
    note.append("- [ ] 理解方法细节")
    note.append("- [ ] 思考与自身研究的关联")
    note.append("")
    return "\n".join(note)

def extract_one_line_summary(llm_text):
    if not llm_text:
        return ""
    for label in ["内容总结", "核心贡献"]:
        pattern = rf"{label}\n(.*?)(?=\n## |\Z)"
        m = re.search(pattern, llm_text, re.DOTALL)
        if m:
            lines = m.group(1).strip().split("\n")
            for line in lines:
                clean = line.strip()
                if clean and not clean.startswith("（") and len(clean) > 10:
                    clean = re.sub(r"\*\*", "", clean)
                    return clean[:150]
    lines = [l.strip() for l in llm_text.split("\n") if l.strip() and not l.startswith("#")]
    return (lines[0][:150] + "...") if lines else ""

# ──────────────────────────────────────────────
# 6. 每日综述生成
# ──────────────────────────────────────────────
def generate_daily_overview(date_str, saved_papers, overview_path, vault_path):
    groups = {}
    for p in saved_papers:
        groups.setdefault(p["interest_name"], []).append(p)

    all_fields = list(groups.keys())
    fields_str = "、".join(all_fields)

    lines = []
    lines.append(f"# {date_str} 文献速览")
    lines.append("")
    lines.append(f"共 {len(saved_papers)} 篇论文，涵盖 {fields_str} 等 {len(groups)} 个领域。")
    lines.append("")

    for name, papers in groups.items():
        lines.append(f"## {name}")
        lines.append("")
        for p in papers:
            rel = p["note_path"]
            summary = p["one_line_summary"] or p["title"][:80]
            lines.append(f"- **{p['title']}**: {summary}: `{rel}`")
        lines.append("")

    overview_path.parent.mkdir(parents=True, exist_ok=True)
    overview_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[综述] {overview_path}")

# ──────────────────────────────────────────────
# 7. 主流程
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="arXiv Daily Fetcher v3")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    parser.add_argument("--days-back", type=int, default=DEFAULT_DAYS_BACK)
    parser.add_argument("--pause", type=int, default=DEFAULT_PAUSE_SECONDS)
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[ERROR] Config not found: {config_path}")
        sys.exit(1)

    config = load_config(config_path)
    from http_transport import configure_network
    configure_network(config)
    obs_cfg = config["obsidian"]
    vault_path = Path(obs_cfg["vault_path"])
    today_str = datetime.now().strftime("%Y-%m-%d")
    target_root = vault_path / obs_cfg.get("target_folder", "Papers") / today_str

    history_path = SCRIPT_DIR / "fetched_papers.json"
    history = load_history(history_path)

    overview_path = target_root / f"{today_str}-文献速览.md"

    print(f"{'='*60}")
    print(f"arXiv Daily Fetcher v3 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Vault: {vault_path}")
    print(f"Output: {target_root}")
    print(f"Max per interest: {args.max_results} | Days back: {args.days_back}")
    print(f"Interests: {len(config['interests'])}")
    print(f"{'='*60}")

    total_queried = 0
    total_saved = 0
    total_skipped = 0
    saved_papers = []  # for daily overview

    for interest in config["interests"]:
        name = interest["name"]
        keywords = interest.get("keywords", [])
        print(f"\n{'─'*50}")
        print(f"  {name}")
        print(f"{'─'*50}")

        entries = query_arxiv(interest, args.max_results)
        if not entries:
            continue

        for entry in entries:
            total_queried += 1
            paper = parse_entry(entry)

            if not matches_keywords(entry, keywords):
                continue

            if not is_within_days(entry, args.days_back):
                continue

            arxiv_id = paper["arxiv_id"]
            if arxiv_id in history:
                total_skipped += 1
                continue

            print(f"\n  [{name}] {paper['title'][:90]}...")
            print(f"    {first_author_lastname(paper['authors'])} | arXiv:{arxiv_id}")

            note_content = generate_note(paper, config, name)
            filename = make_filename(paper)
            note_dir = target_root / name
            note_dir.mkdir(parents=True, exist_ok=True)
            filepath = note_dir / filename

            llm_text = ""
            m = re.search(r"## AI 深度总结\n(.*?)(?=\n## [^#]|\Z)", note_content, re.DOTALL)
            if m:
                llm_text = m.group(1).strip()
            one_liner = extract_one_line_summary(llm_text)

            if args.dry_run:
                print(f"    [DRY RUN] → {filepath.relative_to(vault_path)}")
            else:
                filepath.write_text(note_content, encoding="utf-8")
                print(f"    Saved: {filepath.relative_to(vault_path)}")

            total_saved += 1
            history[arxiv_id] = {
                "title": paper["title"],
                "fetched_at": datetime.now().isoformat(),
                "file": str(filepath.relative_to(vault_path)),
                "date": today_str,
                "interest": name,
            }

            saved_papers.append({
                "title": paper["title"],
                "note_path": str(filepath.relative_to(vault_path)),
                "interest_name": name,
                "one_line_summary": one_liner,
                "arxiv_id": arxiv_id,
                "link": paper.get("link", ""),
            })

            time.sleep(args.pause)

        print(f"  [Wait] {args.pause * 2}s between interests...")
        time.sleep(args.pause * 2)

    # 生成每日综述
    if saved_papers and not args.dry_run:
        generate_daily_overview(today_str, saved_papers, overview_path, vault_path)

    if not args.dry_run:
        save_history(history_path, history)

    print(f"\n{'='*60}")
    print(f"DONE: queried {total_queried} | new {total_saved} | skipped {total_skipped}")
    print(f"{'='*60}")


if __name__ == "__main__":
    from curated_fetcher import main as curated_main
    sys.exit(curated_main())
