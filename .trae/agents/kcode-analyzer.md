---
name: kcode-analyzer
description: Analyzer for one KCode batch.
---

Follow prompts/kcode-analyzer.md.
Use only the provided evidence bundle for code facts.
Produce analysis.md and findings.jsonl.
Before writing files, read human_readable_output_language and language_policy from the task package.
All Markdown and human-readable JSON/JSONL fields you write must be Chinese; preserve schema ids, JSON field names, file paths, commands, API endpoints, and code identifiers as-is.
