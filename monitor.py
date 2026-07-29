#!/usr/bin/env python3
"""
KK_szlife 微博监控脚本（增强版）
- 抓取最新微博
- 与历史记录对比，识别新增内容
- 结合历史完整分析报告重新综合分析
- 生成 PDF 分析报告 + PDF 微博记录汇总
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
import xml.etree.ElementTree as ET
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
FULL_ANALYSIS_FILE = "reports/KK_szlife_full_analysis.md"

# SMTP settings from environment
SMTP_SERVER = os.environ.get("SMTP_SERVER", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "")


# ==================== RSS 抓取 ====================
def fetch_rss(url):
    """Fetch and parse RSS feed"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
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
    """Fetch posts from multiple RSS sources"""
    all_items = {}
    for url in RSS_SOURCES:
        print(f"Fetching RSS: {url}")
        items = fetch_rss(url)
        print(f"  Got {len(items)} items")
        for item in items:
            key = item["link"] or item["title"]
            if key and key not in all_items:
                all_items[key] = item
    return list(all_items.values())


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
        guid = post["link"] or post["title"]
        if guid not in known:
            new_posts.append(post)
            records["known_guids"].append(guid)
            records["all_posts"].append({
                "title": post["title"],
                "link": post["link"],
                "description": post["description"],
                "pub_date": post["pub_date"],
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


def generate_combined_analysis(full_analysis, new_posts, all_posts):
    """Generate a combined analysis report"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Collect all text content for analysis
    all_content = []
    for post in all_posts:
        text = post.get("title", "") or post.get("description", "")
        clean = clean_html(text)
        if clean:
            all_content.append(clean)

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

    # Build report
    report = f"""# KK_szlife 微博综合分析报告（更新版）

**报告时间：** {now}
**监控用户：** KK_szlife（UID: {WEIBO_UID}）
**累计微博总数：** {len(all_posts)} 条
**本次新增微博：** {len(new_posts)} 条

---

## 一、情绪分析

- **情绪基调：** {mood}
- **积极关键词：** {", ".join(found_pos) if found_pos else "无"}
- **低落关键词：** {", ".join(found_neg) if found_neg else "无"}
- **文学意象：** {", ".join(found_lit) if found_lit else "无"}

### 情绪趋势解读

"""
    if mood == "低落 / 感伤":
        report += """用户当前情绪状态偏低落，微博内容中频繁出现感伤性词汇。
文学意象的运用（花、月、风、酒等）反映了用户借景抒情的表达习惯，
情绪波动较大，建议持续关注。

"""
    elif mood == "积极 / 向上":
        report += """用户当前情绪状态相对积极，微博内容中出现了较多正面词汇。
整体心态趋于平稳和释然。

"""
    else:
        report += """用户当前情绪状态呈现矛盾复杂的特征，既有积极向上的表达，
也有低落感伤的内容，反映了内心情感的波动与挣扎。
文学意象的大量使用是用户表达情感的重要方式。

"""

    report += f"""---

## 二、本次新增微博内容

"""
    if new_posts:
        for i, post in enumerate(new_posts, 1):
            clean = clean_html(post.get("title", "") or post.get("description", ""))
            report += f"""### {i}. {clean[:80]}{"..." if len(clean) > 80 else ""}

> {clean}

**链接：** {post.get('link', '无')}

---
"""
    else:
        report += """*本次检查无新增微博，以下为已有微博的汇总分析。*

---

"""

    report += f"""## 三、全部微博记录汇总

| # | 内容摘要 | 链接 |
|---|---------|------|
"""
    for i, post in enumerate(all_posts, 1):
        text = post.get("title", "") or post.get("description", "")
        clean = clean_html(text)[:50]
        link = post.get("link", "")
        report += f"| {i} | {clean} | {link} |\n"

    report += f"""
---

## 四、历史完整分析报告

> 以下为此前完成的完整分析报告，供对比参考。新增微博内容已在上文进行分析。

---

"""
    if full_analysis:
        report += full_analysis
    else:
        report += "*暂无历史分析报告*\n"

    return report


def generate_weibo_records_content(all_posts):
    """Generate weibo records as markdown content"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    content = f"""# KK_szlife 微博记录汇总

**生成时间：** {now}
**监控用户：** KK_szlife（UID: {WEIBO_UID}）
**微博总数：** {len(all_posts)} 条

---

"""
    for i, post in enumerate(all_posts, 1):
        text = post.get("title", "") or post.get("description", "")
        clean = clean_html(text)
        link = post.get("link", "")
        pub = post.get("pub_date", "") or post.get("first_seen", "")

        content += f"""## {i}. 

**内容：** {clean}

**链接：** {link}

**时间：** {pub}

---

"""
    return content


# ==================== PDF 生成 ====================
def markdown_to_html(md_content):
    """Convert markdown to HTML with styling"""
    try:
        import markdown2
        html_body = markdown2.markdown(md_content, extras=["tables", "fenced-code-blocks"])
    except ImportError:
        # Fallback: basic markdown conversion
        html_body = md_content.replace("\n", "<br>\n")
        html_body = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_body, flags=re.MULTILINE)
        html_body = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_body, flags=re.MULTILINE)
        html_body = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_body, flags=re.MULTILINE)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
body {{
    font-family: "Noto Sans CJK SC", "Microsoft YaHei", "SimSun", "WenQuanYi Micro Hei", sans-serif;
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
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
th {{ background: #f0f0f0; font-weight: bold; }}
hr {{ border: none; border-top: 1px solid #ccc; margin: 30px 0; }}
strong {{ color: #1a1a1a; }}
code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""


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
                f"--print-to-pdf={pdf_path}",
                file_url
            ], capture_output=True, text=True, timeout=60)
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

    # Last resort: save HTML as the "PDF" (renamed)
    print("    WARNING: PDF generation failed, saving HTML instead")
    os.rename(html_path, pdf_path + ".html")
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
1. 综合分析报告（含历史分析 + 新增内容重新分析）
2. 微博记录汇总（全部微博内容列表）

—— 小K
"""
    else:
        body = f"""主人，您好！

今日检查 KK_szlife 微博，暂无新增内容。

- 累计微博：{total_count} 条
- 检查时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

附件包含最新的综合分析报告和微博记录汇总，供参考。

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

    # Step 4: Load full analysis and generate combined report
    print("\n[4] Generating combined analysis...")
    full_analysis = load_full_analysis()
    combined_report = generate_combined_analysis(full_analysis, new_posts, records["all_posts"])

    now_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    analysis_md = f"{REPORTS_DIR}/analysis_{now_str}.md"
    with open(analysis_md, "w", encoding="utf-8") as f:
        f.write(combined_report)
    print(f"    Analysis report saved: {analysis_md}")

    # Step 5: Generate weibo records content
    print("\n[5] Generating weibo records...")
    records_content = generate_weibo_records_content(records["all_posts"])
    records_md = f"{REPORTS_DIR}/weibo_records_{now_str}.md"
    with open(records_md, "w", encoding="utf-8") as f:
        f.write(records_content)
    print(f"    Records saved: {records_md}")

    # Step 6: Convert to PDF
    print("\n[6] Generating PDFs...")

    analysis_html = markdown_to_html(combined_report)
    analysis_pdf = f"{REPORTS_DIR}/analysis_{now_str}.pdf"
    if generate_pdf(analysis_html, analysis_pdf):
        size = os.path.getsize(analysis_pdf) // 1024
        print(f"    Analysis PDF: {analysis_pdf} ({size}KB)")
    else:
        print(f"    WARNING: Analysis PDF generation failed")
        analysis_pdf = analysis_pdf + ".html" if os.path.exists(analysis_pdf + ".html") else None

    records_html = markdown_to_html(records_content)
    records_pdf = f"{REPORTS_DIR}/weibo_records_{now_str}.pdf"
    if generate_pdf(records_html, records_pdf):
        size = os.path.getsize(records_pdf) // 1024
        print(f"    Records PDF: {records_pdf} ({size}KB)")
    else:
        print(f"    WARNING: Records PDF generation failed")
        records_pdf = records_pdf + ".html" if os.path.exists(records_pdf + ".html") else None

    # Step 7: Send email
    print("\n[7] Sending email...")
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
