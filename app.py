import argparse
import datetime as dt
import html
import json
import os
import random
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Entry:
    guid: str
    title: str
    link: str
    description: str
    published_at: str
    source: str
    score: int


def load_config(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def ensure_dirs(config: Dict) -> Dict[str, Path]:
    output_dir = Path(config["output_dir"])
    pages_dir = output_dir / "posts"
    assets_dir = output_dir / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    return {"output": output_dir, "pages": pages_dir, "assets": assets_dir}


def db_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS published (
            guid TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            published_at TEXT NOT NULL,
            source TEXT NOT NULL,
            local_path TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def fetch_url(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "AutoAffiliatePulse/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    for encoding in ("utf-8", "cp1251", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def compute_entry_score(
    title: str,
    description: str,
    link: str,
    niche_keywords: List[str],
    commercial_keywords: List[str],
    affiliate_domains: List[str],
) -> int:
    text = f"{title} {description}".lower()
    score = 0

    score += sum(2 for kw in niche_keywords if kw in text)
    score += sum(3 for kw in commercial_keywords if kw in text)

    title_lower = title.lower()
    score += sum(2 for kw in commercial_keywords if kw in title_lower)

    parsed = urllib.parse.urlparse(link)
    domain = parsed.netloc.lower().replace("www.", "")
    if any(item and item in domain for item in affiliate_domains):
        score += 5

    return score


def contains_any_keyword(text: str, keywords: List[str]) -> bool:
    lowered_text = text.lower()
    return any(keyword and keyword in lowered_text for keyword in keywords)


def extract_domain(link: str) -> str:
    parsed = urllib.parse.urlparse(link)
    return parsed.netloc.lower().replace("www.", "")


def parse_rss(
    xml_text: str,
    source_url: str,
    keywords: List[str],
    commercial_keywords: List[str],
    affiliate_domains: List[str],
    min_score: int,
    money_mode: bool,
    money_mode_min_score: int,
    require_commercial_in_title: bool,
    require_affiliate_domain: bool,
) -> List[Entry]:
    root = ET.fromstring(xml_text)
    items: List[Entry] = []
    lowered_keywords = [item.lower() for item in keywords]
    lowered_commercial_keywords = [item.lower() for item in commercial_keywords]
    active_min_score = money_mode_min_score if money_mode else min_score

    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        guid = (node.findtext("guid") or link or title).strip()
        description = (node.findtext("description") or "").strip()
        published = (node.findtext("pubDate") or dt.datetime.now(dt.UTC).isoformat()).strip()

        if not title or not link:
            continue

        title_has_commercial = contains_any_keyword(title, lowered_commercial_keywords)
        domain = extract_domain(link)
        link_has_affiliate_domain = any(item and item in domain for item in affiliate_domains)

        if money_mode and require_commercial_in_title and not title_has_commercial:
            continue
        if money_mode and require_affiliate_domain and not link_has_affiliate_domain:
            continue

        score = compute_entry_score(
            title=title,
            description=description,
            link=link,
            niche_keywords=lowered_keywords,
            commercial_keywords=lowered_commercial_keywords,
            affiliate_domains=affiliate_domains,
        )
        if score < active_min_score:
            continue

        items.append(
            Entry(
                guid=guid,
                title=title,
                link=link,
                description=strip_html(description),
                published_at=published,
                source=source_url,
                score=score,
            )
        )

    return items


def strip_html(value: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return html.unescape(cleaned).strip()


def apply_affiliate(link: str, affiliate: Dict) -> str:
    if not link.startswith("http"):
        return link

    parsed = urllib.parse.urlparse(link)
    domain = parsed.netloc.lower().replace("www.", "")

    for rule in affiliate.get("domain_rules", []):
        rule_domain = rule.get("domain", "").lower().replace("www.", "")
        if rule_domain and rule_domain in domain:
            query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            query.update(rule.get("params", {}))
            return urllib.parse.urlunparse(
                parsed._replace(query=urllib.parse.urlencode(query, doseq=True))
            )

    global_params = affiliate.get("global_utm", {})
    if global_params:
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        for key, value in global_params.items():
            query.setdefault(key, value)
        return urllib.parse.urlunparse(
            parsed._replace(query=urllib.parse.urlencode(query, doseq=True))
        )

    return link


def is_already_published(conn: sqlite3.Connection, guid: str) -> bool:
    row = conn.execute("SELECT 1 FROM published WHERE guid = ?", (guid,)).fetchone()
    return row is not None


def save_published(conn: sqlite3.Connection, entry: Entry, local_path: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO published (guid, title, link, published_at, source, local_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.guid,
            entry.title,
            entry.link,
            entry.published_at,
            entry.source,
            local_path,
            dt.datetime.now(dt.UTC).isoformat(),
        ),
    )
    conn.commit()


def slugify(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]+", "-", text.lower()).strip("-")
    value = value[:80].strip("-")
    return value or f"post-{int(time.time())}"


def render_post(entry: Entry, monetized_link: str, config: Dict) -> str:
        cta_variants = config.get("cta_variants", ["Проверить предложение"])
        cta_text = random.choice(cta_variants)
        hook_variants = config.get(
                "hook_variants",
                [
                        "Коротко: где здесь ценность и как это можно использовать для роста дохода.",
                        "Практично: что попробовать сегодня, чтобы получить результат быстрее.",
                ],
        )
        hook_text = random.choice(hook_variants)
        source_domain = urllib.parse.urlparse(entry.link).netloc
        lead_magnet = config.get("lead_magnet", {})
        lead_title = lead_magnet.get("title", "Бонус: чек-лист внедрения")
        lead_description = lead_magnet.get(
                "description",
                "Заберите мини-гайд и получите простую схему внедрения за 20 минут.",
        )
        lead_button = lead_magnet.get("button_text", "Получить чек-лист")
        lead_url = lead_magnet.get("url", "")
        telegram_channel = config.get("telegram", {}).get("channel_url", "")
        disclaimer = config.get(
                "affiliate_disclaimer",
                "Материал может содержать партнерские ссылки. Мы можем получать комиссию без доплаты для вас.",
        )

        lead_button_html = (
                f'<a class="cta cta-secondary" href="{html.escape(lead_url)}" target="_blank" rel="noopener">{html.escape(lead_button)}</a>'
                if lead_url
                else ""
        )
        telegram_html = (
                f'<p class="meta">Подписка: <a href="{html.escape(telegram_channel)}" target="_blank" rel="noopener">Telegram канал</a></p>'
                if telegram_channel
                else ""
        )

        return f"""<!doctype html>
<html lang=\"ru\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>{html.escape(entry.title)} | {html.escape(config['brand_name'])}</title>
    <link rel=\"stylesheet\" href=\"../assets/style.css\" />
</head>
<body>
    <main class=\"container\">
        <header>
            <a href=\"../index.html\" class=\"back\">← На главную</a>
            <h1>{html.escape(entry.title)}</h1>
            <p class=\"meta\">Источник: {html.escape(source_domain)} · {html.escape(entry.published_at)}</p>
        </header>

        <section class=\"card\">
            <p class=\"hook\">{html.escape(hook_text)}</p>
            <p>{html.escape(entry.description or 'Краткий обзор по теме и возможностям монетизации.')}</p>
            <a class=\"cta\" href=\"{html.escape(monetized_link)}\" rel=\"nofollow sponsored noopener\" target=\"_blank\">{html.escape(cta_text)}</a>
            <p class=\"disclaimer\">{html.escape(disclaimer)}</p>
        </section>

        <section class=\"card growth\">
            <h3>{html.escape(lead_title)}</h3>
            <p>{html.escape(lead_description)}</p>
            {lead_button_html}
            {telegram_html}
        </section>

        <section class=\"ad-slot\">
            <p>Рекламный слот (вставьте AdSense/другую сеть)</p>
            <pre>&lt;!-- Ad code here --&gt;</pre>
        </section>

        <footer class=\"footer\">
            <a href=\"../privacy.html\">Privacy Policy</a>
            <span>·</span>
            <a href=\"../disclaimer.html\">Affiliate Disclaimer</a>
        </footer>
    </main>
</body>
</html>
"""

def write_css(path: Path) -> None:
    css = """
* { box-sizing: border-box; }
body { margin: 0; font-family: Inter, Segoe UI, Arial, sans-serif; background: #f6f7fb; color: #111827; }
.container { max-width: 820px; margin: 0 auto; padding: 24px; }
h1 { margin: 8px 0 12px; line-height: 1.25; }
h3 { margin: 0 0 8px; }
.card, .ad-slot, .post-list li { background: #fff; border-radius: 12px; padding: 18px; box-shadow: 0 1px 4px rgba(17,24,39,.08); }
.meta, .disclaimer { color: #6b7280; font-size: 14px; }
.back { color: #4f46e5; text-decoration: none; }
.hook { margin-top: 0; font-weight: 600; }
.cta { display: inline-block; margin-top: 12px; text-decoration: none; background: #4f46e5; color: white; padding: 10px 14px; border-radius: 10px; font-weight: 600; }
.cta-secondary { background: #111827; }
.post-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }
.post-list a { color: #111827; text-decoration: none; }
.ad-slot pre { overflow-x: auto; }
.hero { margin-bottom: 14px; }
.footer { margin-top: 18px; color: #6b7280; font-size: 14px; }
.footer a { color: #4f46e5; text-decoration: none; }
""".strip()
    path.write_text(css, encoding="utf-8")


def render_index(posts: List[Dict], config: Dict) -> str:
    telegram_channel = config.get("telegram", {}).get("channel_url", "")
    lead_magnet = config.get("lead_magnet", {})
    hero_cta_label = lead_magnet.get("button_text", "Получить бонус")
    hero_cta_url = lead_magnet.get("url", "")
    hero_button_html = (
        f'<a class="cta" href="{html.escape(hero_cta_url)}" target="_blank" rel="noopener">{html.escape(hero_cta_label)}</a>'
        if hero_cta_url
        else ""
    )
    hero_telegram_html = (
        f'<p class="meta">Следить за обновлениями: <a href="{html.escape(telegram_channel)}" target="_blank" rel="noopener">Telegram</a></p>'
        if telegram_channel
        else ""
    )

    items = []
    for post in posts:
        items.append(
            f"<li><a href=\"posts/{html.escape(post['filename'])}\"><strong>{html.escape(post['title'])}</strong></a><br/><span class=\"meta\">{html.escape(post['published_at'])}</span></li>"
        )

    posts_html = "\n".join(items) if items else "<li>Пока нет материалов. Запустите генератор позже.</li>"

    return f"""<!doctype html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{html.escape(config['brand_name'])}</title>
  <link rel=\"stylesheet\" href=\"assets/style.css\" />
</head>
<body>
  <main class=\"container\">
    <h1>{html.escape(config['brand_name'])}</h1>
    <p>{html.escape(config['site_tagline'])}</p>
    <section class=\"card hero\">
      <p class=\"hook\">Свежие инструменты и офферы для роста продуктивности и дохода.</p>
      {hero_button_html}
      {hero_telegram_html}
    </section>
    <ul class=\"post-list\">{posts_html}</ul>
        <footer class=\"footer\">
            <a href=\"privacy.html\">Privacy Policy</a>
            <span>·</span>
            <a href=\"disclaimer.html\">Affiliate Disclaimer</a>
        </footer>
  </main>
</body>
</html>
"""


def render_legal_page(title: str, content_html: str, config: Dict) -> str:
        return f"""<!doctype html>
<html lang=\"ru\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>{html.escape(title)} | {html.escape(config['brand_name'])}</title>
    <link rel=\"stylesheet\" href=\"assets/style.css\" />
</head>
<body>
    <main class=\"container\">
        <a href=\"index.html\" class=\"back\">← На главную</a>
        <h1>{html.escape(title)}</h1>
        <section class=\"card\">{content_html}</section>
    </main>
</body>
</html>
"""


def write_legal_pages(paths: Dict[str, Path], config: Dict) -> None:
        brand_name = html.escape(config.get("brand_name", "AutoAffiliate Pulse"))
        contact_email = html.escape(config.get("legal", {}).get("contact_email", "contact@example.com"))

        privacy_content = f"""
<p>Мы уважаем вашу конфиденциальность. Сайт {brand_name} может обрабатывать технические данные (например, IP, user-agent, cookies) для аналитики и улучшения сервиса.</p>
<p>Мы можем использовать сторонние сервисы аналитики и рекламы, которые применяют cookies в рамках своих политик.</p>
<p>Мы не продаём персональные данные третьим лицам. По вопросам обработки данных: {contact_email}.</p>
<p>Пользуясь сайтом, вы соглашаетесь с этой политикой конфиденциальности.</p>
""".strip()

        disclaimer_content = f"""
<p>Часть ссылок на сайте {brand_name} являются партнёрскими (affiliate links). Если вы совершаете покупку по такой ссылке, мы можем получить комиссию без доплаты для вас.</p>
<p>Материалы носят информационный характер и не являются финансовой, юридической или инвестиционной рекомендацией.</p>
<p>Мы стремимся к точности данных, но не гарантируем актуальность цен, условий и наличия офферов у сторонних сервисов.</p>
<p>По вопросам и претензиям: {contact_email}.</p>
""".strip()

        (paths["output"] / "privacy.html").write_text(
                render_legal_page("Privacy Policy", privacy_content, config),
                encoding="utf-8",
        )
        (paths["output"] / "disclaimer.html").write_text(
                render_legal_page("Affiliate Disclaimer", disclaimer_content, config),
                encoding="utf-8",
        )


def load_recent_posts(conn: sqlite3.Connection, limit: int = 50) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT title, published_at, local_path
        FROM published
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    posts = []
    for title, published_at, local_path in rows:
        filename = Path(local_path).name
        posts.append({"title": title, "published_at": published_at, "filename": filename})
    return posts


def post_to_telegram(config: Dict, text: str) -> None:
    telegram = config.get("telegram", {})
    token = telegram.get("bot_token")
    chat_id = telegram.get("chat_id")
    if not token or not chat_id:
        return

    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    req = urllib.request.Request(url, data=payload, method="POST")
    urllib.request.urlopen(req, timeout=15).read()


def run_once(config: Dict) -> Dict[str, int]:
    paths = ensure_dirs(config)
    write_css(paths["assets"] / "style.css")
    write_legal_pages(paths, config)

    db_path = Path(config.get("state_db", "state.db"))
    conn = db_connect(db_path)

    all_entries: List[Entry] = []
    errors = 0
    affiliate_domains = [
        item.get("domain", "").lower().replace("www.", "")
        for item in config.get("affiliate", {}).get("domain_rules", [])
    ]
    commercial_keywords = config.get("commercial_keywords", [])
    min_score = int(config.get("min_publish_score", 4))
    money_mode = bool(config.get("money_mode", False))
    money_mode_min_score = int(config.get("money_mode_min_score", 8))
    money_require_commercial_title = bool(
        config.get("money_mode_require_commercial_in_title", True)
    )
    money_require_affiliate_domain = bool(config.get("money_mode_require_affiliate_domain", False))
    money_mode_fallback = bool(config.get("money_mode_fallback", True))

    for feed in config.get("feeds", []):
        try:
            xml_text = fetch_url(feed)
            parsed = parse_rss(
                xml_text,
                feed,
                config.get("keywords", []),
                commercial_keywords,
                affiliate_domains,
                min_score,
                money_mode,
                money_mode_min_score,
                money_require_commercial_title,
                money_require_affiliate_domain,
            )
            if money_mode and money_mode_fallback and not parsed:
                parsed = parse_rss(
                    xml_text,
                    feed,
                    config.get("keywords", []),
                    commercial_keywords,
                    affiliate_domains,
                    min_score,
                    False,
                    money_mode_min_score,
                    money_require_commercial_title,
                    money_require_affiliate_domain,
                )
            all_entries.extend(parsed)
        except Exception:
            errors += 1

    all_entries.sort(key=lambda item: item.score, reverse=True)

    created = 0
    publish_limit = int(config.get("max_posts_per_run", 5))

    for entry in all_entries:
        if created >= publish_limit:
            break
        if is_already_published(conn, entry.guid):
            continue

        monetized = apply_affiliate(entry.link, config.get("affiliate", {}))
        slug = slugify(entry.title)
        filename = f"{slug}.html"
        post_path = paths["pages"] / filename

        html_content = render_post(entry, monetized, config)
        post_path.write_text(html_content, encoding="utf-8")

        save_published(conn, entry, str(post_path))
        created += 1

        post_to_telegram(
            config,
            f"{entry.title}\n{config.get('public_base_url', '').rstrip('/')}/posts/{filename}",
        )

    index_html = render_index(load_recent_posts(conn), config)
    (paths["output"] / "index.html").write_text(index_html, encoding="utf-8")

    conn.close()

    return {"created": created, "feeds_failed": errors, "fetched": len(all_entries)}


def run_daemon(config: Dict, interval_minutes: int) -> None:
    while True:
        result = run_once(config)
        print(
            f"[{dt.datetime.now().isoformat(timespec='seconds')}] "
            f"new_posts={result['created']} fetched={result['fetched']} feed_errors={result['feeds_failed']}"
        )
        time.sleep(max(1, interval_minutes) * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoAffiliate Pulse")
    parser.add_argument("--config", default="config.json", help="Путь до config.json")
    parser.add_argument("--daemon", action="store_true", help="Бесконечный режим")
    parser.add_argument("--interval", type=int, default=180, help="Интервал в минутах")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise FileNotFoundError("Создайте config.json на основе config.example.json")

    config = load_config(config_path)

    if args.daemon:
        run_daemon(config, args.interval)
        return

    result = run_once(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
