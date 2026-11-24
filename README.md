# Life Science Evidence Pipeline

面向生命科学文献的可追溯证据工作流，供 Codex 作为 skill 使用。
将文献元数据、开放获取原文、解析产物、原子证据和质量检查分层保存，以 JSONL 作为规范数据源。

A Codex skill for traceable life-science literature evidence: discovery, open-access acquisition,
PDF/JATS parsing, evidence curation, entity review, and release validation.

## 能做什么

- 使用 Europe PMC 核对 PMCID、DOI 等元数据并去重。
- 从 PMC AWS Open Data 获取开放获取 PDF、JATS 和媒体，记录许可证、来源与校验和。
- 调用 MinerU，按配置调用 MarkItDown、Docling，并在可用时调用 GROBID。
- 指导人工或智能体整理原子测量值与作者论断，保留具体来源位置。
- 校验证据字段、来源校验和、JATS 定位和图表标签覆盖，生成状态报告。

领域覆盖分子与细胞研究、组学、动物实验、临床、植物、综述及衰老骨骼肌。
参见 [领域配置](references/domain-profiles.md) 和 [完整工作流](SKILL.md)。

## 当前实现边界

这是 skill 加辅助脚本，不是无人值守的全文自动证据提取服务。
证据整理、实体歧义处理、数值核对和最终 `verified` 审核由人工或智能体完成。
脚本不会自动把解析文本变为已核验的证据。

- 当前命令行入口以 PMCID 为输入，获取路径要求对应 PDF 和 JATS 可用。
- 验证器当前固定检查每篇 5 条证据；自定义语料也须按这一约束准备。
- MinerU 当前命令使用 `-m txt`，Docling 使用 `--no-ocr`；扫描件须单独配置 OCR。
- GROBID 调用目前使用 Windows 的 `where.exe` 和 `curl.exe`；完整批处理以 Windows 为主要运行环境。
- 图表覆盖率是标签出现检查，不证明表格单元格、面板数值或科学含义正确。
- 元数据去重不等于完整版本谱系审核；发布前还需复核版本选择与来源许可。
- 下载器当前实际使用 PMC AWS 路径；代码保留旧 OA 辅助函数，但没有自动旧路径回退。
- 校验通过不替代逐条科学核验、许可核查或敏感内容检查。

## 安装 skill

下载仓库 ZIP，解压后将含 `SKILL.md` 的整个文件夹命名为
`life-science-evidence-pipeline`，复制到 Codex 的 skills 目录。

Windows PowerShell 示例（在仓库根目录运行，目标已存在时先自行备份）：

```powershell
$skillRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$skillTarget = Join-Path $skillRoot 'skills/life-science-evidence-pipeline'
if (Test-Path -LiteralPath $skillTarget) { throw '目标 skill 已存在，请先备份或选择其他位置。' }
New-Item -ItemType Directory -Path (Split-Path -Parent $skillTarget) -Force | Out-Null
Copy-Item -LiteralPath (Get-Location).Path -Destination $skillTarget -Recurse
```

重新打开 Codex 后可显式调用：

```text
$life-science-evidence-pipeline
为我的文献批次建立开放获取、可追溯的证据数据集；先定义 protocol，再获取、解析和逐条核验。
```

安装 skill 不会自动安装解析工具或模型。

## 依赖与运行环境

仓库脚本本身仅使用 Python 标准库。建议 Python 3.12；当前包的离线检查基于这一版本。
完整批处理还需要下列独立运行时，不建议未经验证地把所有解析器装入同一环境。

| 工具 | 用途 | 安装说明 |
|---|---|---|
| MinerU | 必需，主要 PDF 解析器 | [官方仓库](https://github.com/opendatalab/MinerU) |
| MarkItDown | 必需，配置的交叉解析 | [官方仓库](https://github.com/microsoft/markitdown) |
| Docling | 必需，配置的 PDF 交叉解析 | [官方仓库](https://github.com/docling-project/docling) |
| GROBID | 可选，学术结构 | [官方仓库](https://github.com/kermitt2/grobid) |
| InstSci、agent-reach | 可选，另行安装 | 不影响核心公开获取路径 |

按对应官方文档安装各工具的 CLI、模型和系统依赖，再运行：

```powershell
python scripts/check_runtime.py --json
```

返回码 `0` 表示三个必需 CLI 均已找到，`2` 表示至少一个缺失；这不验证模型下载或解析效果。
运行时查找顺序：`PATH` → `RESEARCH_PIPELINE_ROOT` → `CODEX_HOME/tool-runtimes`。
如果不放入 PATH，可采用：

```text
<RESEARCH_PIPELINE_ROOT>/
  mineru/Scripts/mineru.exe
  markitdown/Scripts/markitdown.exe
  docling/Scripts/docling.exe
```

Unix 对应各环境的 `bin/`；完整 GROBID 调用的 Windows 限制见上文。
`GROBID_URL` 可指定服务地址，默认 `http://127.0.0.1:8070`。
版本及命令兼容性由各批次实际验证；本仓库未提供跨解析器的锁定环境。

## 最小使用流程

在仓库根目录执行。仓库附带 5 篇文章的元数据测试语料，不包含文章全文或已核验的证据。

```powershell
python scripts/check_runtime.py --json
python scripts/build_manifest.py --corpus assets/validation-corpus.json --run run
python scripts/fetch_open_access.py --run run
python scripts/parse_batch.py --run run --corpus assets/validation-corpus.json
```

然后按 [证据字段](references/evidence-schema.md) 整理 `run/curated/evidence.jsonl`，
把未决实体放入 `review_queue.jsonl`。逐条查看原文、数值和定位后才设置 `review_status: verified`。
原始示例是字段说明，不是真实研究结果，不能直接复制为核验完成的证据。

准备完 5 篇 × 每篇 5 条证据，再执行：

```powershell
python scripts/validate_run.py --run run --expected-papers 5 --expected-evidence 25
```

校验器会写入 `run/release/release_manifest.json` 与 `validation_report.md`，并更新 protocol 状态。
返回 `0` 表示当前自动检查通过，`2` 表示未通过；阅读 issues 和 degradation 后处理。
在整理证据前运行校验器，预期会因为证据缺失而失败。

```text
run/
├── protocol.json
├── raw/
├── parsed/
├── curated/
│   ├── evidence.jsonl
│   └── review_queue.jsonl
├── manifests/
├── logs/
└── release/
    ├── release_manifest.json
    └── validation_report.md
```

`run/` 默认被 Git 忽略。不要将原始研究运行目录作为 skill 源代码发布。
开放获取文章及第三方工具各自适用其许可，不因本仓库采用 MIT 而改变。

## 质量检查与贡献

```powershell
python -m unittest discover -s tests -v
```

GitHub Actions 在 Windows / Ubuntu、Python 3.12 上运行离线检查；不下载论文、解析器或模型。
这些检查验证基础完整性与失败处理，不代表完整科学证据流程已经端到端验证。
详细规则见 [质量门槛](references/quality-gates.md)。提交改动前说明来源、命令、版本和验证结果；
不要提交论文全文、凭据、会话信息或个人数据。

## 许可证

[MIT](LICENSE)。版权行以项目贡献者统称署名；项目所有者可按实际署名调整。
