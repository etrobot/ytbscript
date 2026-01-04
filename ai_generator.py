"""
AI Generator - 二阶段AI生成（内容+幻灯片）
"""
import os
import json
import logging
from typing import List, Dict
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class AIGenerator:
    """AI内容生成器"""
    
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
            self.openai = AsyncOpenAI(api_key=api_key, base_url=base_url)
            self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        else:
            self.openai = None
            self.model = None
            logger.warning("OPENAI_API_KEY 未配置，AI生成功能将被禁用")
    
    def truncate_text(self, text: str, max_length: int) -> str:
        """智能截断文本（在单词边界处）"""
        if not text or len(text) <= max_length:
            return text
        return text[:max_length].rsplit(' ', 1)[0] + '...'
    
    def merge_summary_content(self, summary: str, content: str) -> str:
        """智能合并摘要和内容，避免重复"""
        s = summary or ''
        c = content or ''
        if not s:
            return c
        if not c:
            return s
        # 检查摘要内容是否在内容中重复
        slice_text = s[20:].strip() if len(s) > 20 else s
        if slice_text and slice_text in c:
            return c
        return f"{s}\n\n{c}".strip()
    
    async def generate_headline(self, articles: List[Dict], prompt: str, 
                               user_provided_prompt: bool = False) -> Dict:
        """
        二阶段生成标题和内容
        
        Phase 1: 生成标题 + 内容（带引用和sections）
        Phase 2: 生成演示幻灯片（带citation tracking）
        
        Args:
            articles: 文章列表
            prompt: 用户提示词
            user_provided_prompt: 是否是用户自定义提示词
        
        Returns:
            {
                "title": str,
                "content": str,
                "slides": list,
                "citedFeeds": list,
                "citedArticles": list
            }
        """
        if not articles:
            return {
                "title": "无可用内容",
                "content": "未找到可用文章进行摘要。",
                "slides": [],
                "citedFeeds": [],
                "citedArticles": []
            }
        
        if not self.openai:
            return {
                "title": "AI配置错误",
                "content": "OpenAI API密钥未配置，跳过摘要生成。",
                "slides": [],
                "citedFeeds": [],
                "citedArticles": []
            }
        
        MAX_ARTICLES = 30
        
        # 1. 构造列表和文章映射 (Construct list and article map with IDs)
        article_map = {}
        articles_for_ai = []
        
        for idx, article in enumerate(articles[:MAX_ARTICLES], 1):
            article_id = article.get('id', '')
            title = article.get('title', '无标题').strip()
            url = article.get('url', '#')
            feed_name = article.get('feedName', '未知来源')
            feed_id = article.get('feedId', '')
            feed_icon = article.get('feedIcon')
            image_url = article.get('imageUrl')
            video_views = article.get('videoViews')
            
            # 记录元数据用于后续拼装 (Store metadata with article ID)
            article_map[article_id] = {
                "url": url,
                "title": title,
                "feedName": feed_name,
                "feedId": feed_id,
                "feedIcon": feed_icon,
                "imageUrl": image_url,
                "index": idx
            }
            
            # 2. 构建带ID的文章列表给AI (Build article list with IDs for AI)
            views_str = f" ({video_views:,} views)" if isinstance(video_views, (int, float)) else ""
            display_header = f"{idx}. [ID: {article_id}] {title} — {feed_name}{views_str}"
            
            # 获取并合并内容
            summary = article.get('summary', '')
            content = article.get('content', '')
            video_transcript = article.get('videoTranscript', '') or ''
            
            # 智能合并内容，避免重复
            if summary and content:
                # 检查summary开头20字符是否与content开头20字符相同
                if summary[:20] == content[:20]:
                    merged_source = content + video_transcript
                else:
                    merged_source = summary + content + video_transcript
            else:
                merged_source = (summary or content) + video_transcript
            
            snippet = self.truncate_text(merged_source, 1500)
            articles_for_ai.append(f"{display_header}\n   {snippet}")
        
        articles_text = "\n\n".join(articles_for_ai)
        
        # ==================== Phase 1: 生成标题和内容 (with sections and citations) ====================
        default_instruction = (
            "Create an executive-ready headline post based on the provided sources. "
            "Write concise paragraphs that synthesize key themes, trends, and actionable insights for content creators. "
            "Use the language of the user's query"
        )
        
        primary_instruction = prompt.strip() if user_provided_prompt and prompt.strip() else default_instruction
        
        content_prompt = (
            f"{primary_instruction}\n\n"
            f"Sources (most recent first, up to {MAX_ARTICLES} items):\n{articles_text}\n\n"
            f"Structure requirement: Organize your response into thematic sections. Each section should cite specific sources using their article IDs.\n\n"
            f"Return strict JSON with: {{ \"title\": string, \"sections\": Array<{{ \"section\": string, \"cite\": string[] }}> }}\n"
            f"- \"section\": A paragraph of content (2-4 sentences)\n"
            f"- \"cite\": An array of article IDs (the ID values from the sources above) used in this section (e.g., [\"Xy3kN2mP\", \"bQ9wR5tL\"])\n"
            f"Only output strict JSON without code fences or commentary."
        )
        
        logger.info(f"开始生成内容，使用 {len(articles[:MAX_ARTICLES])} 篇文章...")
        logger.info(f"Content prompt: {content_prompt[:500]}...")
        
        try:
            # Phase 1: 内容生成（结构化sections with citations）
            content_response = await self.openai.chat.completions.create(
                model=self.model,
                temperature=0.4,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert editor who writes concise, well-cited executive posts based on provided sources."
                    },
                    {
                        "role": "user",
                        "content": content_prompt
                    }
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "ai_headline_content",
                        "schema": {
                            "type": "object",
                            "required": ["title", "sections"],
                            "properties": {
                                "title": {"type": "string"},
                                "sections": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["section", "cite"],
                                        "properties": {
                                            "section": {"type": "string"},
                                            "cite": {
                                                "type": "array",
                                                "items": {"type": "string"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            )
            
            content_raw = content_response.choices[0].message.content
            if not content_raw:
                raise Exception("AI返回空内容响应")
            
            content_parsed = json.loads(content_raw)
            generated_title = content_parsed.get("title", "AI Headline")
            sections = content_parsed.get("sections", [])
            
            # 收集所有被引用的文章ID (Collect all cited article IDs)
            used_article_ids = set()
            for sec in sections:
                cite_array = sec.get("cite", [])
                if isinstance(cite_array, list):
                    for article_id in cite_array:
                        if article_id and isinstance(article_id, str):
                            used_article_ids.add(article_id)
            
            # 构建HTML内容（带内联引用） (Build HTML content with inline citations)
            generated_content = ""
            for sec in sections:
                paragraph = sec.get("section", "")
                cite_array = sec.get("cite", []) if isinstance(sec.get("cite"), list) else []
                
                if paragraph:
                    # 将文章ID映射到索引号用于显示 (Map article IDs to index numbers for display)
                    citation_numbers = [
                        article_map[article_id]["index"]
                        for article_id in cite_array
                        if article_id in article_map
                    ]
                    
                    citation_html = f" <sup>[{', '.join(map(str, citation_numbers))}]</sup>" if citation_numbers else ""
                    generated_content += f"<p>{paragraph}{citation_html}</p>\n\n"
            
            # 构建引用部分（只包含被使用的引用，按索引排序） (Build references section)
            references_section = ""
            if used_article_ids:
                sorted_articles = sorted(
                    [article_map[article_id] for article_id in used_article_ids if article_id in article_map],
                    key=lambda x: x["index"]
                )
                
                references_list = "<br>\n".join(
                    f'[{meta["index"]}] <a href="{meta["url"] or "#"}" target="_blank" rel="noopener noreferrer">{meta["title"]}</a> — {meta["feedName"]}'
                    for meta in sorted_articles
                )
                
                references_section = f"\n\n<h3>References</h3>\n{references_list}"
            
            final_content = generated_content.strip() + references_section
            
            # ==================== Phase 2: 生成幻灯片（带citation tracking） ====================
            logger.info("开始生成演示幻灯片...")
            
            slides_prompt = self._build_slides_prompt(sections)
            
            slides_response = await self.openai.chat.completions.create(
                model=self.model,
                temperature=0.4,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a presentation designer that converts summaries into clear, data-first slides."
                    },
                    {
                        "role": "user",
                        "content": slides_prompt
                    }
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": self._get_slides_json_schema()
                }
            )
            
            slides_raw = slides_response.choices[0].message.content
            if not slides_raw:
                logger.warning("AI返回空幻灯片响应")
                slides = []
            else:
                slides_parsed = json.loads(slides_raw)
                slides = slides_parsed.get("slides", []) if isinstance(slides_parsed, dict) else []
            
            # 提取被引用的feeds和articles (Extract cited feeds and articles)
            cited_feed_map = {}
            cited_articles_list = []
            
            for article_id in used_article_ids:
                if article_id in article_map:
                    article = article_map[article_id]
                    feed_id = article["feedId"]
                    if feed_id and feed_id not in cited_feed_map:
                        cited_feed_map[feed_id] = {
                            "feedId": feed_id,
                            "feedName": article["feedName"],
                            "feedIcon": article["feedIcon"]
                        }
                    cited_articles_list.append({
                        "articleId": article_id,
                        "articleTitle": article["title"],
                        "feedName": article["feedName"],
                        "feedIcon": article["feedIcon"],
                        "imageUrl": article["imageUrl"],
                        "url": article["url"]
                    })
            
            cited_feeds = list(cited_feed_map.values())
            
            logger.info(f"成功生成：标题='{generated_title[:50]}...', 内容长度={len(final_content)}, 幻灯片数={len(slides)}, 引用feeds={len(cited_feeds)}, 引用articles={len(cited_articles_list)}")
            
            return {
                "title": generated_title,
                "content": final_content,
                "slides": slides,
                "citedFeeds": cited_feeds,
                "citedArticles": cited_articles_list
            }
        
        except json.JSONDecodeError as e:
            logger.error(f"解析AI响应失败: {e}")
            return {
                "title": "生成的标题",
                "content": "解析AI响应时出错",
                "slides": [],
                "citedFeeds": [],
                "citedArticles": []
            }
        except Exception as e:
            logger.error(f"OpenAI API错误: {e}")
            return {
                "title": "生成标题时出错",
                "content": str(e),
                "slides": [],
                "citedFeeds": [],
                "citedArticles": []
            }
    
    def _add_references_section(self, html: str, index_map: Dict) -> str:
        """在内容末尾添加引用部分"""
        import re
        
        # 收集内容中使用的所有引用编号
        citation_pattern = r'\[(\d+)\]'
        used_citations = set()
        
        for match in re.finditer(citation_pattern, html):
            used_citations.add(int(match.group(1)))
        
        # 构建引用部分
        if used_citations:
            sorted_citations = sorted(used_citations)
            references_list = []
            
            for n in sorted_citations:
                meta = index_map.get(n)
                if meta:
                    href = meta.get("url", "#")
                    title = meta["title"]
                    references_list.append(f'[{n}] <a href="{href}" target="_blank" rel="noopener noreferrer">{title}</a>')
                else:
                    references_list.append(f'[{n}] (Reference not found)')
            
            references_section = '\n\n<h3>References</h3>\n' + '<br>\n'.join(references_list)
            return html + references_section
        
        return html
    
    def _build_slides_prompt(self, sections: List[Dict]) -> str:
        """构建幻灯片生成提示词"""
        sections_json = json.dumps(sections, ensure_ascii=False, indent=2)
        return (
            f"Create a rich set of 7-10 presentation slides from the following executive summary. Prioritize breadth of coverage and clarity.\n\n"
            
            f"Requirements:\n"
            f"- Do not include a separate cover/title slide. Start directly with substantive slides.\n"
            f"- Mix slide types and include at least: 1 bullets slide, 1 bigNumber slide, and 1 chart slide (barChart or pieChart or lineChart).\n"
            f"- Do not cap bullet count artificially; use as many bullets as helpful.\n"
            f"- Prefer short, strong titles and concise scripts for narration.\n"
            f"- IMPORTANT: Remove all HTML tags and citation references like <sup>[n]</sup> from all text content including scripts, titles, subtitles, and bullets. The content should be clean plain text suitable for narration.\n"
            f"- CRITICAL: For each slide, include a \"cite\" field (array of article IDs) that lists which source articles are referenced in that slide's content. Extract article IDs from the citation numbers in the summary sections.\n\n"
            
            f"Summary with sections and citations:\n{sections_json}\n\n"
            
            f"Return strict JSON with: {{ \"slides\": Slide[] }} where Slide = {{ \"type\": \"bullets|barChart|pieChart|lineChart|bigNumber\", \"title\": string, \"subtitle\": string, \"bulletItems\": Array<{{\"icon\"?: string, \"title\": string, \"subtitle\"?: string}}>, \"bullets\"?: string[], \"highlightVal\"?: number, \"highlightDesc\"?: string, \"chartData\"?: [{{\"name\": string, \"value\": number}}], \"footer\"?: string, \"script\": string, \"cite\": string[] }}\n\n"
            
            f"For any bullets-style content, prefer \"bulletItems\" with short, punchy titles and a 4-10 word subtitle. Use a simple semantic icon keyword like \"trending\", \"sparkles\", \"chart\", \"clock\", \"target\", \"users\", \"globe\", \"zap\", \"check\", or \"rocket\".\n\n"
            
            f"Only output strict JSON without code fences or commentary."
        )
    
    def _get_slides_json_schema(self) -> Dict:
        """获取幻灯片JSON架构"""
        return {
            "name": "ai_headline_slides",
            "schema": {
                "type": "object",
                "required": ["slides"],
                "properties": {
                    "slides": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["type", "title", "script"],
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["bullets", "barChart", "pieChart", "lineChart", "bigNumber"]
                                },
                                "title": {"type": "string"},
                                "subtitle": {"type": "string"},
                                "bulletItems": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["title"],
                                        "properties": {
                                            "icon": {"type": "string"},
                                            "title": {"type": "string"},
                                            "subtitle": {"type": "string"}
                                        }
                                    }
                                },
                                "bullets": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "highlightVal": {"type": "number"},
                                "highlightDesc": {"type": "string"},
                                "chartData": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["name", "value"],
                                        "properties": {
                                            "name": {"type": "string"},
                                            "value": {"type": "number"}
                                        }
                                    }
                                },
                                "footer": {"type": "string"},
                                "script": {"type": "string"},
                                "cite": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                }
                            }
                        }
                    }
                }
            }
        }


# 全局实例
_ai_generator_instance = None


def get_ai_generator() -> AIGenerator:
    """获取AI生成器实例（单例模式）"""
    global _ai_generator_instance
    if _ai_generator_instance is None:
        _ai_generator_instance = AIGenerator()
    return _ai_generator_instance
