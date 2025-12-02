"""
字幕处理工具函数
"""

import re
from fastapi import HTTPException


def vtt_to_json(vtt_path):
    """
    将 VTT 字幕文件转换为 JSON 格式，处理重叠的时间戳并去重
    """
    try:
        with open(vtt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 移除 WEBVTT 头部信息
        content = re.sub(r'^WEBVTT.*?\n\n', '', content, flags=re.DOTALL)

        # 分割成字幕块
        blocks = re.split(r'\n\n+', content.strip())

        # 第一步：解析并去除完全重复的字幕
        unique_subtitles = []
        time_re = re.compile(r'(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})')
        seen_subtitles = set()

        if len(blocks) > 0:
            for block in blocks:
                lines = block.strip().split('\n')
                if len(lines) < 2:
                    continue

                # 查找时间行
                time_match = None
                for line in lines:
                    match = time_re.search(line)
                    if match:
                        time_match = match
                        break

                if not time_match:
                    continue

                start_time, end_time = time_match.groups()

                # 获取字幕文本（跳过时间行和 align/position 信息）
                subtitle_lines = []
                for line in lines:
                    if time_re.search(line) or 'align:' in line or 'position:' in line:
                        continue
                    clean_line = re.sub(r'<[^>]+>', '', line)
                    clean_line = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', clean_line)
                    if clean_line.strip():
                        subtitle_lines.append(clean_line.strip())

                subtitle_text = ' '.join(subtitle_lines).strip()

                if not subtitle_text:
                    continue

                # 使用时间戳+文本作为唯一标识
                subtitle_key = f"{start_time}_{end_time}_{subtitle_text}"

                if subtitle_key in seen_subtitles:
                    continue

                seen_subtitles.add(subtitle_key)

                unique_subtitles.append({
                    "time": f"{start_time} --> {end_time}",
                    "start": start_time,
                    "end": end_time,
                    "subtitle": subtitle_text
                })

        # 第二步：处理相邻字幕的重复部分
        processed_subtitles = []
        for i, item in enumerate(unique_subtitles):
            current_text = item['subtitle']

            if i == 0:
                processed_subtitles.append(item)
                continue

            prev_text = processed_subtitles[-1]['subtitle']

            if current_text in prev_text:
                continue

            if current_text.startswith(prev_text):
                current_text = current_text[len(prev_text):].strip()

            if current_text.strip():
                new_item = item.copy()
                new_item['subtitle'] = current_text
                processed_subtitles.append(new_item)

        return processed_subtitles

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"转换 VTT 到 JSON 时出错: {str(e)}")