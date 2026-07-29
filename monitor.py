# -*- coding: utf-8 -*-
"""
微博用户 KK_szlife 每日监控脚本
通过 RSSHub RSS 源获取最新微博，对比上次记录，找出新增内容并发送邮件通知。
部署在 GitHub Actions 上，每日自动运行，不依赖本地电脑。
"""

import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

# ============ 配置区 ============
UID = "2241280342"
USERNAME = "KK_szlife"
RSS_URLS = [
    f"https://rsshub.app/weibo/user/{UID}",
    f"https://rsshub.rss3.workers.dev/weibo/user/{UID}",
]

# 邮件配置（从 GitHub Secrets 读取）
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")  # 发件邮箱
SMTP_PASS = os.environ.get("SMTP_PASS", "")  # 邮箱授权码
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "")  # 收件邮箱

# 文件路径
RECORD_FILE = "weibo_records.json"
REPORT_DIR = "reports"
# ================================


def fetch_rss(urls):
    """抓取 RSS 源并解析返回微博列表，支持多源备选"""
    import re
    last_error = None
    for url in urls:
        try:
            print(f"尝试 RSS 源: {url}")
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read().decode("utf-8")

            root = ET.fromstring(data)
            items = []
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link = item.findtext("link", "").strip()
                pub_date = item.findtext("pubDate", "").strip()
                guid = item.findtext("guid", "").strip()

                # 清理 description 中的 HTML 标签
                desc_raw = item.findtext("description", "").strip()
                desc_clean = re.sub(r'<img[^>]*>', '[图片]', desc_raw)
                desc_clean = re.sub(r'<br\s*/?>', '\n', desc_clean)
                desc_clean = re.sub(r'<[^>]+>', '', desc_clean).strip()

                items.append({
                    "title": title,
                    "link": link,
                    "pub_date": pub_date,
                    "guid": guid,
                    "content": desc_clean
                })

            if items:
                print(f"成功从 {url} 获取 {len(items)} 条微博")
                return items
        except Exception as e:
            print(f"RSS 源 {url} 失败: {e}")
            last_error = e

    raise Exception(f"所有 RSS 源均不可用，最后错误: {last_error}")


def load_records():
    """加载上次记录的微博 GUID 列表"""
    if os.path.exists(RECORD_FILE):
        with open(RECORD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"known_guids": [], "last_check": "", "all_posts": []}


def save_records(records):
    """保存微博记录"""
    with open(RECORD_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def find_new_posts(current_posts, records):
    """找出新增的微博"""
    known_guids = set(records["known_guids"])
    new_posts = []
    for post in current_posts:
        if post["guid"] not in known_guids:
            new_posts.append(post)
    return new_posts


def generate_report(new_posts, total_posts, check_time):
    """生成分析报告"""
    os.makedirs(REPORT_DIR, exist_ok=True)

    report_lines = []
    report_lines.append(f"# KK_szlife 微博监控报告")
    report_lines.append(f"")
    report_lines.append(f"**检查时间：** {check_time}")
    report_lines.append(f"**监控用户：** KK_szlife（UID: {UID}）")
    report_lines.append(f"**当前RSS源微博总数：** {total_posts}")
    report_lines.append(f"**新增微博：** {len(new_posts)} 条")
    report_lines.append(f"")
    report_lines.append(f"---")
    report_lines.append(f"")

    if new_posts:
        report_lines.append(f"## 新增微博内容")
        report_lines.append(f"")
        for i, post in enumerate(new_posts, 1):
            report_lines.append(f"### {i}. {post['pub_date']}")
            report_lines.append(f"")
            report_lines.append(f"> {post['content']}")
            report_lines.append(f"")
            report_lines.append(f"链接：{post['link']}")
            report_lines.append(f"")
            report_lines.append(f"---")
            report_lines.append(f"")

        # 简要情绪分析
        report_lines.append(f"## 情绪简要分析")
        report_lines.append(f"")
        all_text = " ".join([p["content"] for p in new_posts])

        # 关键词检测
        positive_keywords = ["开心", "快乐", "幸福", "美好", "释然", "放下", "旅行", "朋友"]
        negative_keywords = ["孤独", "失眠", "累", "难过", "遗憾", "泪", "荒凉", "冷"]
        literary_keywords = ["江山", "花", "月", "沧海", "风", "诗", "酒"]

        positive_hits = [k for k in positive_keywords if k in all_text]
        negative_hits = [k for k in negative_keywords if k in all_text]
        literary_hits = [k for k in literary_keywords if k in all_text]

        if positive_hits and not negative_hits:
            mood = "积极 / 释然"
        elif negative_hits and not positive_hits:
            mood = "低落 / 压抑"
        elif positive_hits and negative_hits:
            mood = "矛盾 / 复杂"
        elif literary_hits:
            mood = "文学化表达 / 感悟"
        else:
            mood = "中性"

        report_lines.append(f"- **情绪基调：** {mood}")
        report_lines.append(f"- **积极关键词：** {', '.join(positive_hits) if positive_hits else '无'}")
        report_lines.append(f"- **低落关键词：** {', '.join(negative_hits) if negative_hits else '无'}")
        report_lines.append(f"- **文学意象：** {', '.join(literary_hits) if literary_hits else '无'}")
    else:
        report_lines.append(f"## 本次检查无新增微博")
        report_lines.append(f"")
        report_lines.append(f"KK_szlife 自上次检查以来未发布新微博。")

    report_content = "\n".join(report_lines)

    # 保存报告文件
    report_filename = f"{REPORT_DIR}/report_{check_time.replace(':', '-').replace(' ', '_')}.md"
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(report_content)

    return report_content, report_filename


def send_email(subject, body, is_html=False):
    """发送邮件通知"""
    if not SMTP_USER or not SMTP_PASS or not NOTIFY_EMAIL:
        print("邮件配置不完整，跳过发送")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_EMAIL
    msg["Subject"] = subject

    if is_html:
        msg.attach(MIMEText(body, "html", "utf-8"))
    else:
        msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, NOTIFY_EMAIL, msg.as_string())
        server.quit()
        print(f"邮件已发送至 {NOTIFY_EMAIL}")
        return True
    except Exception as e:
        print(f"邮件发送失败: {e}")
        return False


def build_email_html(new_posts, check_time):
    """构建 HTML 格式的邮件内容"""
    html = f"""
    <html>
    <head>
    <style>
      body {{ font-family: "Microsoft YaHei", sans-serif; color: #333; line-height: 1.8; }}
      .header {{ background: #6c5ce7; color: white; padding: 20px; border-radius: 8px; text-align: center; }}
      .post {{ background: #f5f3ff; border-left: 4px solid #a29bfe; padding: 15px; margin: 15px 0; border-radius: 4px; }}
      .post-content {{ font-size: 15px; white-space: pre-wrap; }}
      .post-date {{ color: #6c5ce7; font-size: 13px; font-weight: bold; }}
      .footer {{ color: #999; font-size: 12px; margin-top: 20px; border-top: 1px solid #eee; padding-top: 10px; }}
    </style>
    </head>
    <body>
    <div class="header">
      <h2>KK_szlife 微博监控报告</h2>
      <p>检查时间：{check_time} | 新增微博：{len(new_posts)} 条</p>
    </div>
    """

    if new_posts:
        html += "<h3>新增微博内容</h3>"
        for i, post in enumerate(new_posts, 1):
            content = post["content"].replace("<", "&lt;").replace(">", "&gt;")
            html += f"""
            <div class="post">
              <div class="post-date">第 {i} 条 - {post['pub_date']}</div>
              <div class="post-content">{content}</div>
              <div style="margin-top:8px;"><a href="{post['link']}" style="color:#6c5ce7;">查看原微博</a></div>
            </div>
            """
    else:
        html += "<p>本次检查无新增微博，KK_szlife 自上次以来未发布新内容。</p>"

    html += """
    <div class="footer">
      <p>本邮件由 GitHub Actions 自动发送 | KK_szlife 微博监控系统</p>
    </div>
    </body>
    </html>
    """
    return html


def main():
    tz = timezone(timedelta(hours=8))
    check_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== KK_szlife 微博监控启动 {check_time} ===")

    # 1. 抓取 RSS
    print(f"正在抓取 RSS 源...")
    try:
        current_posts = fetch_rss(RSS_URLS)
        print(f"成功获取 {len(current_posts)} 条微博")
    except Exception as e:
        print(f"RSS 抓取失败: {e}")
        send_email("KK_szlife 监控异常", f"RSS 源抓取失败: {e}\n\n检查时间: {check_time}")
        return

    # 2. 加载历史记录
    records = load_records()
    print(f"历史记录: {len(records['known_guids'])} 条已知微博")

    # 3. 对比找出新微博
    new_posts = find_new_posts(current_posts, records)
    print(f"新增微博: {len(new_posts)} 条")

    # 4. 更新记录
    for post in current_posts:
        if post["guid"] not in records["known_guids"]:
            records["known_guids"].append(post["guid"])
            records["all_posts"].append(post)
    records["last_check"] = check_time
    save_records(records)

    # 5. 生成报告
    report_content, report_file = generate_report(new_posts, len(current_posts), check_time)
    print(f"报告已生成: {report_file}")

    # 6. 发送邮件（仅有新微博时发送，或首次运行时发送基线报告）
    is_first_run = len(records["all_posts"]) == len(current_posts) and len(new_posts) == len(current_posts)

    if new_posts:
        subject = f"KK_szlife 微博更新 - {len(new_posts)}条新微博 ({check_time[:10]})"
        html_body = build_email_html(new_posts, check_time)
        send_email(subject, html_body, is_html=True)
        print(f"已发送更新通知邮件")
    elif is_first_run:
        subject = f"KK_szlife 监控已启动 - 基线记录 {len(current_posts)} 条微博"
        html_body = build_email_html(current_posts[:5], check_time)  # 只发最新5条
        send_email(subject, html_body, is_html=True)
        print(f"已发送基线通知邮件")
    else:
        print("无新增微博，不发送邮件")

    print(f"=== 监控完成 ===")


if __name__ == "__main__":
    main()
