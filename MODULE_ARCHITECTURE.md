# 模块化架构文档

## 概述

已将 `scheduler_service.py` 的功能分离成多个独立的工具模块，方便测试和维护。

## 模块列表

### 1. d1_task_manager.py
**职责**: D1 数据库任务管理

**主要功能**:
- `get_active_tasks()` - 获取所有活跃任务
- `get_task_by_id(task_id)` - 根据ID获取任务
- `get_tasks_by_user(user_id)` - 获取用户的所有任务
- `update_task_execution_time(task_id, execution_time)` - 更新任务执行时间
- `create_task()` - 创建新任务
- `deactivate_task(task_id)` - 停用任务

**使用示例**:
```python
from d1_task_manager import get_task_manager

task_manager = get_task_manager()
tasks = task_manager.get_active_tasks()
```

### 2. data_fetcher.py
**职责**: 从本地数据库获取视频/文章数据

**主要功能**:
- `get_recent_videos(channel_ids, days=7, max_videos_per_channel=5)` - 获取最近的视频
- `get_videos_by_ids(video_ids)` - 根据视频ID列表获取视频

**特性**:
- 自动获取最新字幕数据
- 时间过滤（1-30天）
- 限制文章数量（最多30篇）
- 按日期排序

**使用示例**:
```python
from data_fetcher import get_data_fetcher

data_fetcher = get_data_fetcher()
articles = await data_fetcher.get_recent_videos(['channel_id_1', 'channel_id_2'], days=7)
```

### 3. ai_generator.py
**职责**: AI内容生成（二阶段）

**主要功能**:
- `generate_headline(articles, prompt, user_provided_prompt=False)` - 生成标题和幻灯片
- `truncate_text(text, max_length)` - 智能截断文本
- `merge_summary_content(summary, content)` - 合并内容避免重复

**生成流程**:
1. **Phase 1**: 生成标题 + 内容（带引用）
2. **Phase 2**: 生成演示幻灯片（5-10张）

**特性**:
- 结构化JSON Schema
- 内联引用自动链接化
- 支持多种幻灯片类型（bullets, barChart, pieChart, lineChart, bigNumber）
- 中文提示词支持

**使用示例**:
```python
from ai_generator import get_ai_generator

ai_gen = get_ai_generator()
result = await ai_gen.generate_headline(
    articles=articles,
    prompt="总结最新AI发展趋势",
    user_provided_prompt=True
)
# result = {"title": "...", "content": "...", "slides": [...]}
```

### 4. headline_manager.py
**职责**: D1 数据库标题管理

**主要功能**:
- `insert_headline(user_id, title, content, article_count, ...)` - 插入新标题
- `get_headline_by_id(headline_id)` - 获取单个标题
- `get_headlines_by_user(user_id, limit=50)` - 获取用户的标题列表
- `get_recent_headlines(limit=10)` - 获取最近的标题
- `update_headline(headline_id, ...)` - 更新标题
- `delete_headline(headline_id)` - 删除标题
- `get_statistics(user_id=None)` - 获取统计信息

**使用示例**:
```python
from headline_manager import get_headline_manager

headline_mgr = get_headline_manager()
headline_id = headline_mgr.insert_headline(
    user_id='user123',
    title='AI技术趋势2024',
    content='详细内容...',
    article_count=15,
    slides=[...]
)
```

### 5. scheduler_service.py (已重构)
**职责**: 任务调度和执行

**主要变化**:
- 使用新的工具模块
- 简化的任务执行流程
- 保持原有调度逻辑

**工作流程**:
```python
async def run_task(task):
    # 1. 获取数据
    articles = await self.data_fetcher.get_recent_videos(feed_ids, days=7)
    
    # 2. AI生成
    result = await self.ai_generator.generate_headline(articles, prompt)
    
    # 3. 保存结果
    headline_id = self.headline_manager.insert_headline(...)
    
    # 4. 更新任务
    self.task_manager.update_task_execution_time(task_id, time)
```

## 架构图

```
┌─────────────────────┐
│ scheduler_service   │  ◄── 主调度服务
└──────────┬──────────┘
           │
           ├──► d1_task_manager    (D1任务管理)
           │
           ├──► data_fetcher       (数据获取)
           │         │
           │         └──► youtube_channel_processor
           │
           ├──► ai_generator       (AI生成)
           │         │
           │         └──► OpenAI API
           │
           └──► headline_manager   (D1标题管理)

所有模块依赖: d1_client.py
```

## 优势

1. **单一职责**: 每个模块专注一个功能
2. **易于测试**: 可以独立测试每个模块
3. **可复用**: 其他服务可以直接使用这些工具
4. **易维护**: 修改一个功能不影响其他部分
5. **类型安全**: 清晰的函数签名和返回类型

## 测试方法

### 单独测试模块
```python
# 测试任务管理器
from d1_task_manager import get_task_manager
task_manager = get_task_manager()
tasks = task_manager.get_active_tasks()
print(f"活跃任务: {len(tasks)}")

# 测试数据获取
from data_fetcher import get_data_fetcher
data_fetcher = get_data_fetcher()
articles = await data_fetcher.get_recent_videos(['channel_id'], days=7)
print(f"获取文章: {len(articles)}")

# 测试AI生成
from ai_generator import get_ai_generator
ai_gen = get_ai_generator()
result = await ai_gen.generate_headline(articles, "总结最新趋势")
print(f"生成标题: {result['title']}")

# 测试标题管理
from headline_manager import get_headline_manager
headline_mgr = get_headline_manager()
stats = headline_mgr.get_statistics()
print(f"统计: {stats}")
```

### 完整工作流测试
参考 `scheduler_service.py` 中的 `run_task()` 方法

## 配置要求

环境变量:
- `OPENAI_API_KEY` - OpenAI API密钥
- `OPENAI_BASE_URL` - OpenAI API地址（可选）
- `OPENAI_MODEL` - 使用的模型（默认 gpt-4o-mini）
- `CF_DB_APIKEY` - Cloudflare D1 API密钥
- `CLOUDFLARE_DATABASE_ID` - D1数据库ID
- `CF_ACCOUNT_ID` - Cloudflare账户ID

## 扩展建议

1. **添加RSS源支持** - 在 `data_fetcher.py` 中添加RSS获取方法
2. **缓存机制** - 减少重复的API调用
3. **错误重试** - 实现自动重试机制
4. **并发处理** - 支持并发处理多个任务
5. **更多幻灯片类型** - 扩展幻灯片生成能力

## 更新日志

**2024-12-29**:
- ✅ 创建 d1_task_manager.py
- ✅ 创建 data_fetcher.py
- ✅ 创建 ai_generator.py
- ✅ 创建 headline_manager.py
- ✅ 重构 scheduler_service.py
- ✅ 删除旧的 task_utils.py
- ✅ 所有模块通过语法检查
