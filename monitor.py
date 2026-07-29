#!/usr/bin/env python3
"""
KK_szlife 微博监控脚本（增强版 v3）
- 通过 m.weibo.cn API 抓取微博（含时间戳、图片URL）
- 下载微博图片
- 使用 Playwright 截图每条微博页面
- 生成 PDF 分析报告 + PDF 微博记录汇总（含真实图片和截图）
- 通过邮件发送两份 PDF 附件
"""

import os
import sys
import json
import re
import time
import smtplib
import datetime
import subprocess
import urllib.request
import urllib.parse
import http.cookiejar
import xml.etree.ElementTree as ET
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

# ==================== 配置 ====================
WEIBO_UID = "2241280342"
RSS_SOURCES = [
    f"https://rsshub.rss3.workers.dev/weibo/user/{WEIBO_UID}",
    f"https://rsshub.app/weibo/user/{WEIBO_UID}",
]
RECORDS_FILE = "weibo_records.json"
REPORTS_DIR = "reports"
IMAGES_DIR = "reports/images"
SCREENSHOTS_DIR = "reports/screenshots"
FULL_ANALYSIS_FILE = "reports/KK_szlife_full_analysis.md"

# SMTP settings from environment
SMTP_SERVER = os.environ.get("SMTP_SERVER", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "")

MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"


# ==================== m.weibo.cn API 抓取 ====================
def fetch_weibo_api():
    """Fetch posts from m.weibo.cn API with visitor cookie"""
    posts = []
    try:
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

        # Step 1: Visit profile page to get cookies
        profile_url = f"https://m.weibo.cn/u/{WEIBO_UID}"
        req = urllib.request.Request(profile_url, headers={
            "User-Agent": MOBILE_UA,
        })
        print(f"  Visiting profile page for cookies...")
        opener.open(req, timeout=15)
        print(f"  Got {len(list(cj))} cookies")

        # Step 2: Call API (page 1)
        api_url = f"https://m.weibo.cn/api/container/getIndex?type=uid&value={WEIBO_UID}&containerid=107603{WEIBO_UID}"
        req = urllib.request.Request(api_url, headers={
            "User-Agent": MOBILE_UA,
            "Referer": profile_url,
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "MWeibo-Pwa": "1",
        })
        print(f"  Calling API...")
        resp = opener.open(req, timeout=15)
        data = json.loads(resp.read().decode("utf-8"))

        cards = data.get("data", {}).get("cards", [])
        print(f"  Got {len(cards)} cards from API")

        for card in cards:
            mblog = card.get("mblog")
            if not mblog:
                continue
            if card.get("card_type") != 9:
                continue

            post_id = mblog.get("id", "")
            text = mblog.get("text", "")
            created_at = mblog.get("created_at", "")
            bid = mblog.get("bid", "")

            # Parse created_at: "Mon Jan 01 10:00:00 +0800 2024"
            pub_time = ""
            if created_at:
                try:
                    dt = datetime.datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
                    pub_time = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    try:
                        dt = datetime.datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
                        pub_time = dt.strftime("%Y-%m-%d %H:%M")
                    except:
                        pub_time = created_at

            # Extract images
            pics = []
            for pic in mblog.get("pics", []):
                url = pic.get("large", {}).get("url") or pic.get("url", "")
                if url:
                    pics.append(url)
            if not pics:
                for pid in mblog.get("pic_ids", []):
                    pics.append(f"https://wx1.sinaimg.cn/large/{pid}.jpg")

            # Clean text
            clean = re.sub(r'<[^>]+>', '', text).strip()

            post = {
                "id": str(post_id),
                "bid": bid,
                "text": clean,
                "raw_text": text,
                "pub_time": pub_time,
                "created_at": created_at,
                "pics": pics,
                "link": f"https://weibo.com/{WEIBO_UID}/{bid}" if bid else f"https://m.weibo.cn/detail/{post_id}",
                "source": "api",
            }
            posts.append(post)

        print(f"  Parsed {len(posts)} valid posts from API")

    except Exception as e:
        print(f"  m.weibo.cn API error: {e}")
        print(f"  Falling back to RSS...")

    return posts


# ==================== RSS 降级方案 ====================
def fetch_rss(url):
    """Fetch and parse RSS feed"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": MOBILE_UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8")
        root = ET.fromstring(content)
        items = []
        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            desc = item.findtext("description", "")
            pub_date = item.findtext("pubDate", "")
            items.append({
                "title": title,
                "link": link,
                "description": desc,
                "pub_date": pub_date
            })
        return items
    except Exception as e:
        print(f"  RSS source error ({url}): {e}")
        return []


def fetch_all_posts():
    """Fetch posts: try API first, then RSS fallback"""
    print("  Trying m.weibo.cn API...")
    posts = fetch_weibo_api()

    if not posts:
        print("  API failed, trying RSS...")
        all_items = {}
        for url in RSS_SOURCES:
            print(f"  Fetching RSS: {url}")
            items = fetch_rss(url)
            print(f"    Got {len(items)} items")
            for item in items:
                key = item["link"] or item["title"]
                if key and key not in all_items:
                    all_items[key] = item

        for item in all_items.values():
            text = item["title"] or item["description"]
            clean = re.sub(r'<[^>]+>', '', text).strip()
            posts.append({
                "id": "",
                "bid": "",
                "text": clean,
                "raw_text": text,
                "pub_time": item.get("pub_date", ""),
                "created_at": item.get("pub_date", ""),
                "pics": [],
                "link": item["link"],
                "source": "rss",
            })

    return posts


# ==================== 图片下载 ====================
def download_image(url, save_path):
    """Download an image to local file"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": MOBILE_UA,
            "Referer": "https://m.weibo.cn/",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            with open(save_path, "wb") as f:
                f.write(resp.read())
        return True
    except Exception as e:
        print(f"    Image download failed ({url[:60]}...): {e}")
        return False


def download_all_images(posts):
    """Download all images for all posts"""
    print("  Downloading images...")
    os.makedirs(IMAGES_DIR, exist_ok=True)
    image_map = {}  # post_id -> [local_paths]

    for post in posts:
        post_id = post.get("id") or post.get("link", "unknown")
        local_images = []
        for i, pic_url in enumerate(post.get("pics", [])):
            ext = ".jpg"
            if ".png" in pic_url:
                ext = ".png"
            elif ".gif" in pic_url:
                ext = ".gif"
            filename = f"{post_id}_{i}{ext}"
            filepath = os.path.join(IMAGES_DIR, filename)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                local_images.append(filepath)
            elif download_image(pic_url, filepath):
                local_images.append(filepath)
                print(f"    Downloaded: {filename}")
        image_map[post_id] = local_images

    total = sum(len(v) for v in image_map.values())
    print(f"  Total images downloaded: {total}")
    return image_map


# ==================== Playwright 截图 ====================
def screenshot_posts(posts):
    """Screenshot Weibo posts using Playwright"""
    screenshots = {}
    print("  Taking screenshots with Playwright...")
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("    Playwright not installed, skipping screenshots")
        return screenshots

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
            context = browser.new_context(
                viewport={"width": 420, "height": 900},
                user_agent=MOBILE_UA,
                device_scale_factor=2,
            )
            page = context.new_page()

            for post in posts:
                post_id = post.get("id")
                if not post_id:
                    continue

                url = f"https://m.weibo.cn/detail/{post_id}"
                screenshot_path = os.path.join(SCREENSHOTS_DIR, f"screenshot_{post_id}.png")

                if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 0:
                    screenshots[post_id] = screenshot_path
                    print(f"    Screenshot exists: {post_id}")
                    continue

                try:
                    page.goto(url, timeout=20000, wait_until="networkidle")
                    time.sleep(3)

                    # Try to find the main content card and screenshot just that
                    try:
                        card = page.query_selector('.weibo-card, .card-wrap, [class*="detail"]')
                        if card:
                            card.screenshot(path=screenshot_path)
                        else:
                            page.screenshot(path=screenshot_path, full_page=False)
                    except:
                        page.screenshot(path=screenshot_path, full_page=False)

                    screenshots[post_id] = screenshot_path
                    print(f"    Screenshot saved: {post_id}")
                except Exception as e:
                    print(f"    Screenshot failed for {post_id}: {e}")

            browser.close()
    except Exception as e:
        print(f"    Playwright error: {e}")

    print(f"  Total screenshots: {len(screenshots)}")
    return screenshots


# ==================== 记录管理 ====================
def load_records():
    """Load existing records"""
    if os.path.exists(RECORDS_FILE):
        with open(RECORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"known_guids": [], "last_check": None, "all_posts": []}


def save_records(records):
    """Save records"""
    with open(RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def find_new_posts(records, posts):
    """Find new posts not in records"""
    known = set(records["known_guids"])
    new_posts = []
    for post in posts:
        guid = post.get("link") or post.get("id") or post.get("text", "")[:50]
        if guid not in known:
            new_posts.append(post)
            records["known_guids"].append(guid)
            records["all_posts"].append({
                "id": post.get("id", ""),
                "bid": post.get("bid", ""),
                "title": post.get("text", "")[:80],
                "text": post.get("text", ""),
                "link": post.get("link", ""),
                "pub_date": post.get("pub_time", ""),
                "pics": post.get("pics", []),
                "first_seen": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    return new_posts


# ==================== 分析报告生成 ====================
def load_full_analysis():
    """Load the existing full analysis report"""
    if os.path.exists(FULL_ANALYSIS_FILE):
        with open(FULL_ANALYSIS_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def clean_html(text):
    """Remove HTML tags from text"""
    return re.sub(r'<[^>]+>', '', text).strip()


def generate_combined_analysis(full_analysis, new_posts, all_posts, image_map, screenshots):
    """Generate a combined analysis report (returns HTML directly for image embedding)"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Collect all text content for analysis
    all_content = []
    for post in all_posts:
        text = post.get("text", "") or post.get("title", "")
        if text:
            all_content.append(text)

    # Emotion analysis
    positive_words = ["开心", "快乐", "幸福", "美好", "温暖", "喜欢", "爱", "感谢",
                      "感恩", "朋友", "希望", "期待", "释然", "平静", "安心"]
    negative_words = ["难过", "伤心", "遗憾", "泪", "哭", "痛苦", "荒凉", "冷",
                      "孤独", "寂寞", "失去", "结束", "再见", "狼藉", "风霜",
                      "惊悚", "苦涩", "留疤", "禁止"]
    literary_words = ["花", "月", "风", "酒", "沧海", "江山", "云", "雨", "雪",
                      "山河", "天涯", "梦", "波涛", "洪水", "千里", "东山岛"]

    found_pos = sorted(set(w for c in all_content for w in positive_words if w in c))
    found_neg = sorted(set(w for c in all_content for w in negative_words if w in c))
    found_lit = sorted(set(w for c in all_content for w in literary_words if w in c))

    pos_count = sum(1 for c in all_content for w in positive_words if w in c)
    neg_count = sum(1 for c in all_content for w in negative_words if w in c)

    if pos_count > neg_count:
        mood = "积极 / 向上"
    elif neg_count > pos_count:
        mood = "低落 / 感伤"
    else:
        mood = "矛盾 / 复杂"

    # Build HTML report directly (for image embedding)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
body {{
    font-family: "Noto Sans CJK SC", "Microsoft YaHei", "SimSun", sans-serif;
    line-height: 1.8;
    max-width: 800px;
    margin: 0 auto;
    padding: 40px;
    color: #333;
}}
h1 {{ color: #1a1a1a; border-bottom: 2px solid #333; padding-bottom: 10px; }}
h2 {{ color: #2c3e50; margin-top: 30px; }}
h3 {{ color: #34495e; }}
blockquote {{ border-left: 4px solid #3498db; margin: 15px 0; padding: 10px 20px; background: #f8f9fa; color: #555; }}
hr {{ border: none; border-top: 1px solid #ccc; margin: 30px 0; }}
strong {{ color: #1a1a1a; }}
.weibo-card {{
    border: 1px solid #e1e4e8;
    border-radius: 8px;
    padding: 15px 20px;
    margin: 15px 0;
    background: #fff;
}}
.weibo-time {{
    color: #999;
    font-size: 0.9em;
    margin-bottom: 8px;
}}
.weibo-text {{
    margin-bottom: 10px;
}}
.weibo-images {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 10px 0;
}}
.weibo-images img {{
    width: 200px;
    height: auto;
    border-radius: 4px;
    border: 1px solid #eee;
}}
.weibo-screenshot {{
    margin: 10px 0;
}}
.weibo-screenshot img {{
    width: 100%;
    max-width: 420px;
    border-radius: 8px;
    border: 1px solid #ddd;
}}
.mood-badge {{
    display: inline-block;
    padding: 3px 12px;
    border-radius: 12px;
    font-size: 0.9em;
    font-weight: bold;
}}
.mood-positive {{ background: #e6f7e6; color: #27ae60; }}
.mood-negative {{ background: #fde8e8; color: #e74c3c; }}
.mood-mixed {{ background: #fff3cd; color: #856404; }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
th {{ background: #f0f0f0; font-weight: bold; }}
</style>
</head>
<body>
<h1>KK_szlife 微博综合分析报告（更新版）</h1>

<p><strong>报告时间：</strong>{now}<br>
<strong>监控用户：</strong>KK_szlife（UID: {WEIBO_UID}）<br>
<strong>累计微博总数：</strong>{len(all_posts)} 条<br>
<strong>本次新增微博：</strong>{len(new_posts)} 条</p>

<hr>

<h2>一、情绪分析</h2>

<p>
<strong>情绪基调：</strong>
<span class="mood-badge {"mood-positive" if mood=="积极 / 向上" else "mood-negative" if mood=="低落 / 感伤" else "mood-mixed"}">{mood}</span>
</p>
<p><strong>积极关键词：</strong>{", ".join(found_pos) if found_pos else "无"}</p>
<p><strong>低落关键词：</strong>{", ".join(found_neg) if found_neg else "无"}</p>
<p><strong>文学意象：</strong>{", ".join(found_lit) if found_lit else "无"}</p>

<h3>情绪趋势解读</h3>
<blockquote>
"""

    if mood == "低落 / 感伤":
        html += """用户当前情绪状态偏低落，微博内容中频繁出现感伤性词汇。文学意象的运用（花、月、风、酒等）反映了用户借景抒情的表达习惯，情绪波动较大，建议持续关注。"""
    elif mood == "积极 / 向上":
        html += """用户当前情绪状态相对积极，微博内容中出现了较多正面词汇。整体心态趋于平稳和释然。"""
    else:
        html += """用户当前情绪状态呈现矛盾复杂的特征，既有积极向上的表达，也有低落感伤的内容，反映了内心情感的波动与挣扎。文学意象的大量使用是用户表达情感的重要方式。"""

    html += "</blockquote>\n<hr>\n\n<h2>二、本次新增微博内容</h2>\n"

    if new_posts:
        for i, post in enumerate(new_posts, 1):
            text = post.get("text", "") or post.get("title", "")
            pub_time = post.get("pub_time", "") or post.get("first_seen", "")
            link = post.get("link", "")
            post_id = post.get("id") or post.get("link", "")

            html += f'<div class="weibo-card">\n'
            html += f'<h3>{i}. {text[:80]}{"..." if len(text) > 80 else ""}</h3>\n'
            if pub_time:
                html += f'<div class="weibo-time">发布时间：{pub_time}</div>\n'
            html += f'<div class="weibo-text">{text}</div>\n'

            # Embed images
            local_images = image_map.get(post_id, [])
            if local_images:
                html += '<div class="weibo-images">\n'
                for img_path in local_images:
                    abs_path = os.path.abspath(img_path)
                    html += f'<img src="file://{abs_path}" alt="微博图片">\n'
                html += '</div>\n'

            # Embed screenshot
            screenshot_path = screenshots.get(post_id)
            if screenshot_path and os.path.exists(screenshot_path):
                abs_path = os.path.abspath(screenshot_path)
                html += f'<div class="weibo-screenshot">\n<h4>微博页面截图</h4>\n'
                html += f'<img src="file://{abs_path}" alt="微博截图">\n</div>\n'

            html += f'<div><a href="{link}">查看原文</a></div>\n'
            html += '</div>\n<hr>\n'
    else:
        html += "<p><em>本次检查无新增微博，以下为已有微博的汇总分析。</em></p>\n<hr>\n"

    # All posts summary table
    html += "\n<h2>三、全部微博记录汇总</h2>\n<table>\n<tr><th>#</th><th>发布时间</th><th>内容摘要</th><th>图片</th></tr>\n"
    for i, post in enumerate(all_posts, 1):
        text = (post.get("text", "") or post.get("title", ""))[:50]
        pub = post.get("pub_date", "") or post.get("first_seen", "")
        pic_count = len(post.get("pics", []))
        html += f"<tr><td>{i}</td><td>{pub}</td><td>{text}</td><td>{pic_count}张</td></tr>\n"
    html += "</table>\n<hr>\n"

    # Historical analysis
    html += "\n<h2>四、历史完整分析报告</h2>\n<blockquote>以下为此前完成的完整分析报告，供对比参考。</blockquote>\n<hr>\n"

    if full_analysis:
        # Convert markdown to basic HTML
        try:
            import markdown2
            html_body = markdown2.markdown(full_analysis, extras=["tables", "fenced-code-blocks"])
        except ImportError:
            html_body = full_analysis.replace("\n", "<br>\n")
            html_body = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_body, flags=re.MULTILINE)
            html_body = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_body, flags=re.MULTILINE)
        html += html_body
    else:
        html += "<p><em>暂无历史分析报告</em></p>\n"

    html += "\n</body>\n</html>"
    return html


def generate_weibo_records_html(all_posts, image_map, screenshots):
    """Generate weibo records as HTML with images and screenshots"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
body {{
    font-family: "Noto Sans CJK SC", "Microsoft YaHei", "SimSun", sans-serif;
    line-height: 1.8;
    max-width: 800px;
    margin: 0 auto;
    padding: 40px;
    color: #333;
}}
h1 {{ color: #1a1a1a; border-bottom: 2px solid #333; padding-bottom: 10px; }}
h2 {{ color: #2c3e50; margin-top: 30px; }}
h3 {{ color: #34495e; }}
hr {{ border: none; border-top: 1px solid #ccc; margin: 30px 0; }}
.weibo-card {{
    border: 1px solid #e1e4e8;
    border-radius: 8px;
    padding: 15px 20px;
    margin: 20px 0;
    background: #fff;
    page-break-inside: avoid;
}}
.weibo-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
    border-bottom: 1px solid #eee;
    padding-bottom: 8px;
}}
.weibo-time {{
    color: #657786;
    font-size: 0.95em;
    font-weight: bold;
}}
.weibo-link {{
    font-size: 0.85em;
    color: #1da1f2;
}}
.weibo-text {{
    margin: 10px 0;
    font-size: 1.05em;
    line-height: 1.8;
}}
.weibo-images {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin: 12px 0;
}}
.weibo-images img {{
    width: 220px;
    height: auto;
    border-radius: 6px;
    border: 1px solid #eee;
}}
.weibo-screenshot {{
    margin: 12px 0;
}}
.weibo-screenshot img {{
    width: 100%;
    max-width: 420px;
    border-radius: 8px;
    border: 1px solid #ddd;
}}
.weibo-screenshot h4 {{
    color: #666;
    font-size: 0.9em;
    margin-bottom: 5px;
}}
.no-image {{
    color: #999;
    font-style: italic;
    font-size: 0.9em;
}}
</style>
</head>
<body>
<h1>KK_szlife 微博记录汇总</h1>

<p><strong>生成时间：</strong>{now}<br>
<strong>监控用户：</strong>KK_szlife（UID: {WEIBO_UID}）<br>
<strong>微博总数：</strong>{len(all_posts)} 条</p>

<hr>
"""

    for i, post in enumerate(all_posts, 1):
        text = post.get("text", "") or post.get("title", "")
        pub = post.get("pub_date", "") or post.get("first_seen", "")
        link = post.get("link", "")
        post_id = post.get("id", "") or post.get("link", "")

        html += f'<div class="weibo-card">\n'
        html += f'<div class="weibo-header">\n'
        html += f'<span class="weibo-time">#{i} | 发布时间：{pub or "未知"}</span>\n'
        html += f'<span class="weibo-link"><a href="{link}">原文链接</a></span>\n'
        html += f'</div>\n'
        html += f'<div class="weibo-text">{text}</div>\n'

        # Embed images
        local_images = image_map.get(post_id, [])
        if local_images:
            html += '<div class="weibo-images">\n'
            for img_path in local_images:
                abs_path = os.path.abspath(img_path)
                html += f'<img src="file://{abs_path}" alt="微博图片">\n'
            html += '</div>\n'
        elif post.get("pics"):
            html += '<p class="no-image">（含图片，下载失败）</p>\n'

        # Embed screenshot
        screenshot_path = screenshots.get(post_id)
        if screenshot_path and os.path.exists(screenshot_path):
            abs_path = os.path.abspath(screenshot_path)
            html += f'<div class="weibo-screenshot">\n<h4>微博页面截图</h4>\n'
            html += f'<img src="file://{abs_path}" alt="微博截图">\n</div>\n'

        html += '</div>\n<hr>\n'

    html += "\n</body>\n</html>"
    return html


# ==================== PDF 生成 ====================
def find_chrome():
    """Find Chrome/Chromium binary on the system"""
    candidates = [
        "google-chrome",
        "google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "chromium-browser",
        "/usr/bin/chromium-browser",
        "chromium",
        "/usr/bin/chromium",
    ]
    for c in candidates:
        try:
            result = subprocess.run([c, "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                print(f"    Found browser: {c} ({result.stdout.strip()})")
                return c
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def generate_pdf(html_content, pdf_path):
    """Generate PDF from HTML using headless Chrome"""
    html_path = pdf_path.replace(".pdf", ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    file_url = f"file://{os.path.abspath(html_path)}"

    # Try Chrome/Chromium first
    chrome = find_chrome()
    if chrome:
        try:
            subprocess.run([
                chrome, "--headless", "--disable-gpu", "--no-sandbox",
                "--allow-file-access-from-files",
                f"--print-to-pdf={pdf_path}",
                file_url
            ], capture_output=True, text=True, timeout=120)
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                os.remove(html_path)
                return True
        except Exception as e:
            print(f"    Chrome PDF error: {e}")

    # Fallback: weasyprint
    try:
        print("    Trying weasyprint fallback...")
        from weasyprint import HTML
        HTML(string=html_content).write_pdf(pdf_path)
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            os.remove(html_path)
            return True
    except Exception as e:
        print(f"    weasyprint error: {e}")

    print("    WARNING: PDF generation failed, saving HTML instead")
    return False


# ==================== 邮件发送 ====================
def send_email(attachments, new_count, total_count):
    """Send email with PDF attachments"""
    if not SMTP_SERVER:
        print("    SMTP not configured, skipping email")
        return False

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_EMAIL
    now = datetime.datetime.now().strftime("%Y-%m-%d")

    if new_count > 0:
        subject = f"KK_szlife 微博更新 - 新增{new_count}条 - {now}"
    else:
        subject = f"KK_szlife 微博监控日报 - {now}"

    msg["Subject"] = subject

    if new_count > 0:
        body = f"""主人，您好！

KK_szlife 微博监控报告已更新：

- 新增微博：{new_count} 条
- 累计微博：{total_count} 条
- 检查时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

附件包含：
1. 综合分析报告（含历史分析 + 新增内容重新分析 + 图片 + 截图）
2. 微博记录汇总（全部微博内容 + 图片 + 截图 + 发布时间）

—— 小K
"""
    else:
        body = f"""主人，您好！

今日检查 KK_szlife 微博，暂无新增内容。

- 累计微博：{total_count} 条
- 检查时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

附件包含最新的综合分析报告和微博记录汇总（含图片和截图），供参考。

—— 小K
"""
    msg.attach(MIMEText(body, "plain", "utf-8"))

    for filepath in attachments:
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            filename = os.path.basename(filepath)
            with open(filepath, "rb") as f:
                part = MIMEBase("application", "pdf")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                encoded_filename = urllib.parse.quote(filename)
                part.add_header("Content-Disposition",
                                f'attachment; filename*=UTF-8\'\'{encoded_filename}')
                msg.attach(part)
            print(f"  Attached: {filename} ({os.path.getsize(filepath)//1024}KB)")

    print(f"  Connecting to {SMTP_SERVER}:{SMTP_PORT}...")
    server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
    server.login(SMTP_USER, SMTP_PASS)
    print("  Login successful!")
    server.sendmail(SMTP_USER, NOTIFY_EMAIL, msg.as_string())
    print("  Email sent successfully!")
    server.quit()
    return True


# ==================== 主程序 ====================
def main():
    print("=" * 60)
    print(f"KK_szlife 微博监控 - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    # Step 1: Fetch posts
    print("\n[1] Fetching Weibo posts...")
    posts = fetch_all_posts()
    print(f"    Total unique posts: {len(posts)}")

    # Step 2: Load records and find new posts
    print("\n[2] Comparing with records...")
    records = load_records()
    new_posts = find_new_posts(records, posts)
    records["last_check"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"    New posts: {len(new_posts)}")
    print(f"    Total known posts: {len(records['known_guids'])}")

    # Step 3: Save records
    save_records(records)
    print("\n[3] Records saved.")

    # Step 4: Download images
    print("\n[4] Downloading images...")
    all_posts_with_data = records["all_posts"]
    # Build a lookup for API posts (with pics)
    posts_by_id = {}
    for p in posts:
        pid = p.get("id") or p.get("link", "")
        if pid:
            posts_by_id[pid] = p

    # Merge API data into stored records
    for stored in all_posts_with_data:
        sid = stored.get("id") or stored.get("link", "")
        if sid in posts_by_id:
            api_post = posts_by_id[sid]
            if api_post.get("pics") and not stored.get("pics"):
                stored["pics"] = api_post["pics"]
            if api_post.get("pub_time") and not stored.get("pub_date"):
                stored["pub_date"] = api_post["pub_time"]

    image_map = download_all_images(posts)

    # Also map images by link for stored records
    for stored in all_posts_with_data:
        sid = stored.get("id") or stored.get("link", "")
        if sid in image_map:
            continue
        # Try to match by link
        for p in posts:
            if p.get("link") == stored.get("link"):
                pid = p.get("id") or p.get("link", "")
                if pid in image_map:
                    image_map[sid] = image_map[pid]
                    break

    # Step 5: Take screenshots
    print("\n[5] Taking screenshots...")
    screenshots = screenshot_posts(posts)

    # Map screenshots to stored records
    for stored in all_posts_with_data:
        sid = stored.get("id") or stored.get("link", "")
        if sid in screenshots:
            continue
        for p in posts:
            if p.get("link") == stored.get("link"):
                pid = p.get("id") or p.get("link", "")
                if pid in screenshots:
                    screenshots[sid] = screenshots[pid]
                    break

    # Step 6: Generate analysis report
    print("\n[6] Generating combined analysis...")
    full_analysis = load_full_analysis()
    analysis_html = generate_combined_analysis(full_analysis, new_posts, all_posts_with_data, image_map, screenshots)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    analysis_pdf = f"{REPORTS_DIR}/analysis_{now_str}.pdf"
    if generate_pdf(analysis_html, analysis_pdf):
        size = os.path.getsize(analysis_pdf) // 1024
        print(f"    Analysis PDF: {analysis_pdf} ({size}KB)")
    else:
        print(f"    WARNING: Analysis PDF generation failed")
        analysis_pdf = None

    # Step 7: Generate weibo records
    print("\n[7] Generating weibo records...")
    records_html = generate_weibo_records_html(all_posts_with_data, image_map, screenshots)
    records_pdf = f"{REPORTS_DIR}/weibo_records_{now_str}.pdf"
    if generate_pdf(records_html, records_pdf):
        size = os.path.getsize(records_pdf) // 1024
        print(f"    Records PDF: {records_pdf} ({size}KB)")
    else:
        print(f"    WARNING: Records PDF generation failed")
        records_pdf = None

    # Step 8: Send email
    print("\n[8] Sending email...")
    attachments = [f for f in [analysis_pdf, records_pdf] if f and os.path.exists(f)]
    if attachments:
        try:
            send_email(attachments, len(new_posts), len(records["known_guids"]))
        except Exception as e:
            print(f"    Email error: {e}")
    else:
        print("    No attachments to send")

    # Cleanup HTML temp files
    for f in Path(REPORTS_DIR).glob("*.html"):
        f.unlink()

    print("\n" + "=" * 60)
    print("Monitoring complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
