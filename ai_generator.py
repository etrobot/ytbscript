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
        
        Phase 1: 生成标题 + 内容（带引用）
        Phase 2: 生成演示幻灯片
        
        Args:
            articles: 文章列表
            prompt: 用户提示词
            user_provided_prompt: 是否是用户自定义提示词
        
        Returns:
            {
                "title": str,
                "content": str,
                "slides": list
            }
        """
        if not articles:
            return {
                "title": "无可用内容",
                "content": "未找到可用文章进行摘要。",
                "slides": []
            }
        
        if not self.openai:
            return {
                "title": "AI配置错误",
                "content": "OpenAI API密钥未配置，跳过摘要生成。",
                "slides": []
            }
        
        MAX_ARTICLES = 30
        
        # 1. 先构造列表和索引映射 (Construct list and index map)
        index_map = {}
        articles_for_ai = []
        
        for idx, article in enumerate(articles[:MAX_ARTICLES], 1):
            title = article.get('title', '无标题').strip()
            url = article.get('url', '#')
            feed_name = article.get('feedName', '未知来源')
            video_views = article.get('videoViews')
            
            # 记录元数据用于后续拼装 (Pinning)
            index_map[idx] = {
                "url": url,
                "title": title
            }
            
            # 2. 抽取编号、title和文章给ai (Extract ID, title, and article for AI)
            # 构建显示标题（包含热度信息，如果可用）
            views_str = f" ({video_views:,} views)" if isinstance(video_views, (int, float)) else ""
            display_header = f"[{idx}] {title}{views_str} — {feed_name}"
            
            # 获取并合并内容
            video_transcript = article.get('videoTranscript', '')
            merged_source = video_transcript or self.merge_summary_content(article.get('summary', ''), article.get('content', ''))
            snippet = self.truncate_text(merged_source, 1500)
            
            articles_for_ai.append(f"{display_header}\n{snippet}")
        
        articles_text = "\n\n".join(articles_for_ai)
        
        # ==================== Phase 1: 生成标题和内容 ====================
        default_instruction = (
            "Create an executive-ready headline post based on the provided sources. "
            "Write concise paragraphs that synthesize key themes, trends, and actionable insights for content creators. "
            "Use the language of the user's query."
        )
        
        primary_instruction = prompt.strip() if user_provided_prompt and prompt.strip() else default_instruction
        
        content_prompt = (
            f"{primary_instruction}\n\n"
            f"Sources (most recent first, up to {MAX_ARTICLES} items):\n{articles_text}\n\n"
            f"Citations requirement: Use inline citations with <sup>[n]</sup> where n corresponds to the numbered source above. "
            f"Do NOT include a References section; only include the summary paragraphs.\n\n"
            f"Return strict JSON with: {{ \"title\": string, \"content\": string }}\n"
            f"Only output strict JSON without code fences or commentary."
        )
        
        logger.info(f"开始生成内容，使用 {len(articles[:MAX_ARTICLES])} 篇文章...")
        
        try:
            # Phase 1: 内容生成
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
                            "required": ["title", "content"],
                            "properties": {
                                "title": {"type": "string"},
                                "content": {"type": "string"}
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
            generated_content = content_parsed.get("content", "No content available.")
            
            # 3. 再用正则解析ai给出的编号，再拼上列表对应title和url
            final_content = self._linkify_citations(generated_content.strip(), index_map)
            
            # ==================== Phase 2: 生成幻灯片 ====================
            logger.info("开始生成演示幻灯片...")
            
            slides_prompt = self._build_slides_prompt(generated_content)
            
            slides_response = await self.openai.chat.completions.create(
                model=self.model,
                temperature=0.4,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一位演示设计师，将摘要转换为清晰、数据优先的幻灯片。"
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
            
            logger.info(f"成功生成：标题='{generated_title[:50]}...', 内容长度={len(final_content)}, 幻灯片数={len(slides)}")
            
            return {
                "title": generated_title,
                "content": final_content,
                "slides": slides
            }
        
        except json.JSONDecodeError as e:
            logger.error(f"解析AI响应失败: {e}")
            return {
                "title": "生成的标题",
                "content": "解析AI响应时出错",
                "slides": []
            }
        except Exception as e:
            logger.error(f"OpenAI API错误: {e}")
            return {
                "title": "生成标题时出错",
                "content": str(e),
                "slides": []
            }
    
    def _linkify_citations(self, html: str, index_map: Dict) -> str:
        """将引用转换为可点击链接，支持 sup 和 裸露引用"""
        import re
        
        def replace(match):
            sup_n = match.group(1)
            bare_n = match.group(2)
            
            n_str = sup_n or bare_n
            if not n_str:
                return match.group(0)
                
            n = int(n_str)
            meta = index_map.get(n)
            if not meta:
                return match.group(0)
            
            href = meta["url"]
            title = meta["title"]
            
            if sup_n:
                # <sup>[n]</sup> -> <sup><a ...>[n] Title</a></sup>
                return f'<sup><a href="{href}" target="_blank" rel="noopener noreferrer">[{n}] {title}</a></sup>'
            else:
                # [n] -> <a ...>[n] Title</a>
                return f'<a href="{href}" target="_blank" rel="noopener noreferrer">[{n}] {title}</a>'

        # 组合正则：优先匹配 sup 格式，再匹配裸露格式
        # 使用分组 1 匹配 sup 中的数字，分组 2 匹配裸露的数字
        pattern = r'<sup>\s*\[(\d+)\]\s*</sup>|(?<![\w#])\[(\d+)\](?![\w;])'
        return re.sub(pattern, replace, html)
    
    def _build_slides_prompt(self, content: str) -> str:
        """构建幻灯片生成提示词"""
        return (
            f"你是一个演示应用的JSON数据生成器。\n"
            f"你的任务是将执行摘要转换为一个扁平的JSON对象，表示带有每张幻灯片引人入胜脚本的幻灯片组。\n\n"
            
            f"必需的JSON结构：\n"
            f"{{\n"
            f"  \"slides\": [\n"
            f"    {{\n"
            f"      \"type\": \"bullets\",\n"
            f"      \"title\": \"幻灯片标题\",\n"
            f"      \"subtitle\": \"可选副标题\",\n"
            f"      \"bulletItems\": [{{\"icon\": \"trending\", \"title\": \"要点标题\", \"subtitle\": \"4-10字解释\"}}],\n"
            f"      \"bullets\": [\"旧版支持\"],\n"
            f"      \"script\": \"解释这些要点的口述旁白。\"\n"
            f"    }},\n"
            f"    {{\n"
            f"      \"type\": \"bigNumber\",\n"
            f"      \"title\": \"关键指标\",\n"
            f"      \"highlightVal\": 100,\n"
            f"      \"highlightDesc\": \"增长描述\",\n"
            f"      \"script\": \"突出这个数字的口述旁白。\"\n"
            f"    }},\n"
            f"    {{\n"
            f"      \"type\": \"barChart\",\n"
            f"      \"title\": \"数据趋势\",\n"
            f"      \"chartData\": [{{\"name\": \"Q1\", \"value\": 10}}, {{\"name\": \"Q2\", \"value\": 20}}],\n"
            f"      \"script\": \"分析这一趋势的口述旁白。\"\n"
            f"    }}\n"
            f"  ]\n"
            f"}}\n\n"
            
            f"生成规则：\n"
            f"1. 输出必须是有效的JSON。\n"
            f"2. 根据主题的复杂性生成5到10张幻灯片。\n"
            f"3. 内容：\n"
            f"   - 提供全面和真实的内容。\n"
            f"   - 不要人为限制项目符号或字数。\n"
            f"   - 在图表中使用尽可能多的数据点来显示趋势。\n"
            f"   - 重要：从所有文本内容（包括脚本、标题、副标题和项目符号）中删除所有HTML标签和引用（如<sup>[n]</sup>）。\n"
            f"4. \"type\"必须是：\"bullets\"、\"barChart\"、\"pieChart\"、\"lineChart\"、\"bigNumber\"之一。\n"
            f"5. 确保多样化的幻灯片类型（不仅仅是项目符号）。\n"
            f"6. 关键：每张幻灯片的\"script\"必须是适合配音的简洁、引人入胜的旁白段落。\n"
            f"7. 对于项目符号风格的幻灯片，优先使用带有结构化数据的\"bulletItems\"：\n"
            f"   - \"icon\"：使用语义关键词，如\"trending\"、\"sparkles\"、\"chart\"、\"clock\"、\"target\"、\"users\"、\"globe\"、\"zap\"、\"check\"、\"rocket\"\n"
            f"   - \"title\"：简短有力的标题\n"
            f"   - \"subtitle\"：4-10字解释\n"
            f"8. 不要包含单独的封面/标题幻灯片。直接从实质性幻灯片开始。\n\n"
            
            f"要转换的执行摘要：\n{content}\n\n"
            
            f"仅输出严格的JSON，不包含代码围栏或注释。"
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
                                "script": {"type": "string"}
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
