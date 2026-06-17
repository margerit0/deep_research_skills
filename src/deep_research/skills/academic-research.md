---
name: academic-research
description: 学术/科研类研究（论文、综述、研究方法、引用追溯）。当主题涉及 arxiv、期刊、研究方法、技术综述时使用。
when_to_use: 研究主题包含"论文/综述/研究/method/algorithm/paper"等关键词，或问题需要可追溯的学术证据
---

# 学术研究方法论

## 信息源优先级
- 一手：arxiv.org / 期刊官网 / 实验室主页 / 作者个人页
- 二手：综述、textbook、Wikipedia（仅作 anchor 与术语对齐，不作论据）
- 排除：媒体科普、聚合博客、SEO 内容农场

## 查询模式
- `"<topic>" site:arxiv.org`
- `"<topic>" survey OR review filetype:pdf`
- `"<topic>" benchmark dataset`
- 找到关键论文后追查其引用与被引（用论文标题再搜一次）

## 停止判据
- 已有 ≥3 篇原始研究 + 1 篇综述/教科书章节
- 关键定义、方法、benchmark 数字均已对齐
- 最近两次搜索返回的论文已在已知集合中

## 引用规范
- 论文：作者(年). 标题. 期刊/会议. URL
- arxiv：给 `abs/` 链接而非 `pdf/`
- 同一论文有期刊版与预印版时，引用期刊版
