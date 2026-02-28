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
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class Entry:
    guid: str
    title: str
    link: str
    description: str
    published_at: str
    source: str
    score: int


def normalize_config(config: Dict) -> Dict:
    normalized = dict(config or {})

    normalized["brand_name"] = str(
        normalized.get("brand_name", "AutoAffiliate Pulse") or "AutoAffiliate Pulse"
    ).strip()
    normalized["site_tagline"] = str(
        normalized.get("site_tagline", "РђРІС‚Рѕ-РїРѕРґР±РѕСЂРєР° РїРѕР»РµР·РЅС‹С… РЅР°С…РѕРґРѕРє Рё СЃРґРµР»РѕРє")
        or "РђРІС‚Рѕ-РїРѕРґР±РѕСЂРєР° РїРѕР»РµР·РЅС‹С… РЅР°С…РѕРґРѕРє Рё СЃРґРµР»РѕРє"
    ).strip()

    output_dir = str(normalized.get("output_dir", "site") or "site").strip()
    normalized["output_dir"] = output_dir or "site"

    state_db = str(normalized.get("state_db", "state.db") or "state.db").strip()
    normalized["state_db"] = state_db or "state.db"

    for key in ("feeds", "keywords", "commercial_keywords"):
        value = normalized.get(key)
        if not isinstance(value, list):
            normalized[key] = []

    feeds: List[str] = []
    seen_feeds: Set[str] = set()
    for feed in normalized.get("feeds", []):
        candidate = str(feed or "").strip()
        if not candidate:
            continue
        if not candidate.startswith(("http://", "https://")):
            continue
        if candidate in seen_feeds:
            continue
        seen_feeds.add(candidate)
        feeds.append(candidate)
    normalized["feeds"] = feeds

    telegram = normalized.get("telegram")
    if not isinstance(telegram, dict):
        telegram = {}
    telegram.setdefault("notify_every_run", True)
    telegram.setdefault("run_report_mode", "short")
    normalized["telegram"] = telegram

    seo = normalized.get("seo")
    if not isinstance(seo, dict):
        seo = {}
    seo.setdefault("enabled", True)
    seo.setdefault("default_description", normalized["site_tagline"])
    seo.setdefault("default_image", "")
    seo.setdefault("home_keywords", ["ai", "productivity", "tools", "offers"])
    normalized["seo"] = seo

    try:
        normalized["post_selection_min_score"] = int(normalized.get("post_selection_min_score", 0))
    except Exception:
        normalized["post_selection_min_score"] = 0

    try:
        normalized["post_selection_fallback_min_score"] = int(
            normalized.get(
                "post_selection_fallback_min_score",
                max(0, normalized["post_selection_min_score"] - 1),
            )
        )
    except Exception:
        normalized["post_selection_fallback_min_score"] = max(
            0,
            normalized["post_selection_min_score"] - 1,
        )

    normalized["post_selection_adaptive_fallback"] = bool(
        normalized.get("post_selection_adaptive_fallback", True)
    )

    try:
        normalized["max_posts_per_run"] = max(1, int(normalized.get("max_posts_per_run", 5)))
    except Exception:
        normalized["max_posts_per_run"] = 5

    try:
        normalized["max_posts_per_source_domain"] = max(
            1,
            int(normalized.get("max_posts_per_source_domain", 2)),
        )
    except Exception:
        normalized["max_posts_per_source_domain"] = 2

    try:
        normalized["max_posts_per_feed"] = max(1, int(normalized.get("max_posts_per_feed", 3)))
    except Exception:
        normalized["max_posts_per_feed"] = 3

    normalized["evergreen_republish_enabled"] = bool(
        normalized.get("evergreen_republish_enabled", False)
    )

    try:
        normalized["evergreen_republish_min_age_days"] = int(
            normalized.get("evergreen_republish_min_age_days", 7)
        )
    except Exception:
        normalized["evergreen_republish_min_age_days"] = 7

    try:
        normalized["evergreen_republish_cooldown_days"] = int(
            normalized.get("evergreen_republish_cooldown_days", 3)
        )
    except Exception:
        normalized["evergreen_republish_cooldown_days"] = 3

    try:
        normalized["evergreen_republish_max_per_run"] = int(
            normalized.get("evergreen_republish_max_per_run", 10)
        )
    except Exception:
        normalized["evergreen_republish_max_per_run"] = 10

    return normalized


def build_absolute_url(base_url: str, relative_path: str) -> str:
    clean_base = str(base_url or "").strip().rstrip("/")
    clean_path = str(relative_path or "").strip().lstrip("/")
    if not clean_base:
        return ""
    return f"{clean_base}/{clean_path}"


def text_fingerprint(value: str) -> str:
    lowered = str(value or "").lower()
    lowered = re.sub(r"\s+", " ", lowered)
    lowered = re.sub(r"[^a-z0-9Р°-СЏС‘ ]+", "", lowered)
    return lowered.strip()


def dedupe_entries(entries: List[Entry]) -> Tuple[List[Entry], int]:
    unique: List[Entry] = []
    seen: Set[str] = set()
    duplicates = 0

    for entry in entries:
        domain = extract_domain(entry.link)
        key = f"{domain}|{text_fingerprint(entry.title)}"
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(entry)

    return unique, duplicates


def choose_unique_filename(base_slug: str, pages_dir: Path, used_filenames: Set[str]) -> str:
    candidate = f"{base_slug}.html"
    index = 2
    while candidate in used_filenames or (pages_dir / candidate).exists():
        candidate = f"{base_slug}-{index}.html"
        index += 1
    used_filenames.add(candidate)
    return candidate


def build_seo_description(raw_text: str, fallback: str, max_len: int = 165) -> str:
    value = strip_html(raw_text or "").strip() or str(fallback or "").strip()
    if len(value) <= max_len:
        return value
    return value[: max_len - 1].rstrip() + "вЂ¦"


def load_config(path: Path) -> Dict:
    with path.open("r", encoding="utf-8-sig") as file:
        return normalize_config(json.load(file))


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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS republish_state (
            original_guid TEXT PRIMARY KEY,
            last_republished_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def parse_iso_datetime(value: str) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(dt.UTC)
    except Exception:
        return None


def select_evergreen_candidates(
    conn: sqlite3.Connection,
    min_age_days: int,
    cooldown_days: int,
    limit: int,
) -> List[Dict[str, str]]:
    if limit <= 0:
        return []

    now = dt.datetime.now(dt.UTC)
    min_age_delta = dt.timedelta(days=max(0, min_age_days))
    cooldown_delta = dt.timedelta(days=max(0, cooldown_days))

    republish_rows = conn.execute(
        "SELECT original_guid, last_republished_at FROM republish_state"
    ).fetchall()
    republish_map: Dict[str, dt.datetime] = {}
    for original_guid, last_republished_at in republish_rows:
        parsed = parse_iso_datetime(last_republished_at)
        if parsed is not None:
            republish_map[original_guid] = parsed

    rows = conn.execute(
        """
        SELECT guid, title, link, published_at, source, created_at
        FROM published
        WHERE guid NOT LIKE '%#republish-%'
        ORDER BY created_at ASC
        """
    ).fetchall()

    candidates: List[Dict[str, str]] = []
    for guid, title, link, published_at, source, created_at in rows:
        created_dt = parse_iso_datetime(created_at)
        if created_dt is None:
            continue
        if now - created_dt < min_age_delta:
            continue

        last_republished_dt = republish_map.get(guid)
        if last_republished_dt is not None and now - last_republished_dt < cooldown_delta:
            continue

        candidates.append(
            {
                "guid": guid,
                "title": title,
                "link": link,
                "published_at": published_at,
                "source": source,
            }
        )
        if len(candidates) >= limit:
            break

    return candidates


def mark_evergreen_republished(conn: sqlite3.Connection, original_guid: str) -> None:
    conn.execute(
        """
        INSERT INTO republish_state (original_guid, last_republished_at)
        VALUES (?, ?)
        ON CONFLICT(original_guid) DO UPDATE SET last_republished_at = excluded.last_republished_at
        """,
        (original_guid, dt.datetime.now(dt.UTC).isoformat()),
    )
    conn.commit()


def fetch_url(url: str, timeout: int = 20, retries: int = 3, retry_delay_sec: float = 1.5) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AutoAffiliatePulse/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
            for encoding in ("utf-8", "cp1251", "latin-1"):
                try:
                    return raw.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="ignore")
        except Exception as error:
            last_error = error
            if attempt < retries:
                time.sleep(retry_delay_sec * attempt)
    if last_error is None:
        raise RuntimeError("Unknown error while fetching URL")
    raise last_error


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
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    value = value[:80].strip("-")
    return value or f"post-{int(time.time())}"


def render_post(entry: Entry, monetized_link: str, config: Dict, filename: str = "") -> str:
    cta_variants = config.get("cta_variants", ["РџСЂРѕРІРµСЂРёС‚СЊ РїСЂРµРґР»РѕР¶РµРЅРёРµ"])
    cta_text = random.choice(cta_variants)
    hook_variants = config.get(
        "hook_variants",
        [
            "РљРѕСЂРѕС‚РєРѕ: РіРґРµ Р·РґРµСЃСЊ С†РµРЅРЅРѕСЃС‚СЊ Рё РєР°Рє СЌС‚Рѕ РјРѕР¶РЅРѕ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РґР»СЏ СЂРѕСЃС‚Р° РґРѕС…РѕРґР°.",
            "РџСЂР°РєС‚РёС‡РЅРѕ: С‡С‚Рѕ РїРѕРїСЂРѕР±РѕРІР°С‚СЊ СЃРµРіРѕРґРЅСЏ, С‡С‚РѕР±С‹ РїРѕР»СѓС‡РёС‚СЊ СЂРµР·СѓР»СЊС‚Р°С‚ Р±С‹СЃС‚СЂРµРµ.",
        ],
    )
    hook_text = random.choice(hook_variants)
    source_domain = urllib.parse.urlparse(entry.link).netloc
    lead_magnet = config.get("lead_magnet", {})
    lead_title = lead_magnet.get("title", "Р‘РѕРЅСѓСЃ: С‡РµРє-Р»РёСЃС‚ РІРЅРµРґСЂРµРЅРёСЏ")
    lead_description = lead_magnet.get(
        "description",
        "Р—Р°Р±РµСЂРёС‚Рµ РјРёРЅРё-РіР°Р№Рґ Рё РїРѕР»СѓС‡РёС‚Рµ РїСЂРѕСЃС‚СѓСЋ СЃС…РµРјСѓ РІРЅРµРґСЂРµРЅРёСЏ Р·Р° 20 РјРёРЅСѓС‚.",
    )
    lead_button = lead_magnet.get("button_text", "РџРѕР»СѓС‡РёС‚СЊ С‡РµРє-Р»РёСЃС‚")
    lead_url = lead_magnet.get("url", "")
    telegram_channel = config.get("telegram", {}).get("channel_url", "")
    analytics = config.get("analytics", {})
    goatcounter_site = analytics.get("goatcounter_site", "")
    seo = config.get("seo", {})
    seo_enabled = bool(seo.get("enabled", True))
    canonical_url = (
        build_absolute_url(config.get("public_base_url", ""), f"posts/{filename}")
        if filename
        else ""
    )
    seo_description = build_seo_description(
        entry.description,
        seo.get("default_description") or config.get("site_tagline", ""),
    )
    default_image = str(seo.get("default_image", "") or "").strip()
    analytics_script = (
        f'<script data-goatcounter="https://{html.escape(goatcounter_site)}/count" async src="//gc.zgo.at/count.js"></script>'
        if goatcounter_site
        else ""
    )
    tracking_script = (
        """
<script>
document.addEventListener('click', function (event) {
  var link = event.target.closest('a[data-track="cta"]');
  if (!link) return;
  if (window.goatcounter && typeof window.goatcounter.count === 'function') {
    var source = link.dataset.trackSource || 'unknown';
    var label = link.dataset.trackLabel || 'cta';
    window.goatcounter.count({
      path: '/cta/' + source + '/' + encodeURIComponent(label),
      title: 'CTA click: ' + label,
      event: true
    });
  }
});
</script>
"""
        if goatcounter_site
        else ""
    )
    disclaimer = config.get(
        "affiliate_disclaimer",
        "РњР°С‚РµСЂРёР°Р» РјРѕР¶РµС‚ СЃРѕРґРµСЂР¶Р°С‚СЊ РїР°СЂС‚РЅРµСЂСЃРєРёРµ СЃСЃС‹Р»РєРё. РњС‹ РјРѕР¶РµРј РїРѕР»СѓС‡Р°С‚СЊ РєРѕРјРёСЃСЃРёСЋ Р±РµР· РґРѕРїР»Р°С‚С‹ РґР»СЏ РІР°СЃ.",
    )

    lead_button_html = (
        f'<a class="cta cta-secondary" href="{html.escape(lead_url)}" target="_blank" rel="noopener" data-track="cta" data-track-source="leadmagnet" data-track-label="{html.escape(entry.title)}">{html.escape(lead_button)}</a>'
        if lead_url
        else ""
    )
    telegram_html = (
        f'<p class="meta">РџРѕРґРїРёСЃРєР°: <a href="{html.escape(telegram_channel)}" target="_blank" rel="noopener">Telegram РєР°РЅР°Р»</a></p>'
        if telegram_channel
        else ""
    )

    seo_tags = ""
    if seo_enabled:
        seo_tags = "\n".join(
            [
                f'<meta name="description" content="{html.escape(seo_description)}" />',
                f'<meta property="og:title" content="{html.escape(entry.title)}" />',
                f'<meta property="og:description" content="{html.escape(seo_description)}" />',
                '<meta property="og:type" content="article" />',
                f'<meta name="twitter:card" content="{html.escape("summary_large_image" if default_image else "summary")}" />',
            ]
        )
        if canonical_url:
            seo_tags += f'\n<link rel="canonical" href="{html.escape(canonical_url)}" />'
            seo_tags += f'\n<meta property="og:url" content="{html.escape(canonical_url)}" />'
        if default_image:
            seo_tags += f'\n<meta property="og:image" content="{html.escape(default_image)}" />'

    json_ld = ""
    if seo_enabled and canonical_url:
        schema = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": entry.title,
            "description": seo_description,
            "datePublished": entry.published_at,
            "url": canonical_url,
            "mainEntityOfPage": canonical_url,
            "publisher": {
                "@type": "Organization",
                "name": config.get("brand_name", "AutoAffiliate Pulse"),
            },
        }
        if default_image:
            schema["image"] = [default_image]
        json_ld = (
            '<script type="application/ld+json">'
            + json.dumps(schema, ensure_ascii=False).replace("</", "<\\/")
            + "</script>"
        )

    return f"""<!doctype html>
<html lang=\"ru\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>{html.escape(entry.title)} | {html.escape(config['brand_name'])}</title>
    {seo_tags}
    <link rel=\"stylesheet\" href=\"../assets/style.css\" />
    {analytics_script}
    {json_ld}
</head>
<body>
    <main class=\"container\">
        <header class=\"page-head\">
            <a href=\"../index.html\" class=\"back\">в†ђ РќР° РіР»Р°РІРЅСѓСЋ</a>
            <h1>{html.escape(entry.title)}</h1>
            <div class=\"tag-row\">
                <span class=\"tag\">РСЃС‚РѕС‡РЅРёРє: {html.escape(source_domain)}</span>
                <span class=\"tag\">{html.escape(entry.published_at)}</span>
            </div>
        </header>

        <section class=\"card spotlight\">
            <p class=\"hook\">{html.escape(hook_text)}</p>
            <p class=\"lead\">{html.escape(entry.description or 'РљСЂР°С‚РєРёР№ РѕР±Р·РѕСЂ РїРѕ С‚РµРјРµ Рё РІРѕР·РјРѕР¶РЅРѕСЃС‚СЏРј РјРѕРЅРµС‚РёР·Р°С†РёРё.')}</p>
            <div class=\"actions\">
                <a class=\"cta\" href=\"{html.escape(monetized_link)}\" rel=\"nofollow sponsored noopener\" target=\"_blank\" data-track=\"cta\" data-track-source=\"offer\" data-track-label=\"{html.escape(entry.title)}\">{html.escape(cta_text)}</a>
            </div>
            <p class=\"disclaimer\">{html.escape(disclaimer)}</p>
        </section>

        <section class=\"card growth\">
            <h3>{html.escape(lead_title)}</h3>
            <p>{html.escape(lead_description)}</p>
            <div class=\"actions\">{lead_button_html}</div>
            {telegram_html}
        </section>

        <section class=\"ad-slot\">
            <p>Р РµРєР»Р°РјРЅС‹Р№ СЃР»РѕС‚ (РІСЃС‚Р°РІСЊС‚Рµ AdSense/РґСЂСѓРіСѓСЋ СЃРµС‚СЊ)</p>
            <pre>&lt;!-- Ad code here --&gt;</pre>
        </section>

        <footer class=\"footer\">
            <a href=\"../privacy.html\">Privacy Policy</a>
            <span>В·</span>
            <a href=\"../disclaimer.html\">Affiliate Disclaimer</a>
        </footer>
    </main>
    {tracking_script}
</body>
</html>
"""

def write_css(path: Path) -> None:
    css = """
* { box-sizing: border-box; }
body {
    margin: 0;
    font-family: Inter, Segoe UI, Arial, sans-serif;
    background: radial-gradient(1200px 500px at 20% -10%, #e0e7ff 0%, #f8fafc 48%, #f8fafc 100%);
    color: #111827;
}
.container { max-width: 940px; margin: 0 auto; padding: 26px; }
h1 { margin: 10px 0 12px; line-height: 1.2; font-size: clamp(28px, 4vw, 38px); }
h3 { margin: 0 0 8px; font-size: 20px; }
p { line-height: 1.6; }

.page-head { margin-bottom: 14px; }
.tag-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.tag {
    display: inline-flex;
    align-items: center;
    padding: 6px 10px;
    font-size: 12px;
    border-radius: 999px;
    background: #eef2ff;
    color: #4338ca;
    font-weight: 600;
}

.card, .ad-slot, .post-list li {
    background: #fff;
    border-radius: 16px;
    padding: 20px;
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.07);
    border: 1px solid #eef2ff;
}

.hero {
    margin-bottom: 16px;
    background: linear-gradient(135deg, #0f172a, #312e81);
    color: #f8fafc;
}
.hero .hook { color: #e2e8f0; }

.stats { display: flex; gap: 10px; flex-wrap: wrap; margin: 14px 0 4px; }
.stat {
    background: rgba(255,255,255,0.12);
    color: #e2e8f0;
    border: 1px solid rgba(255,255,255,0.2);
    border-radius: 12px;
    padding: 8px 10px;
    font-size: 12px;
    font-weight: 600;
}

.meta, .disclaimer { color: #6b7280; font-size: 14px; }
.lead { margin: 0 0 10px; }
.back { color: #4f46e5; text-decoration: none; font-weight: 600; }
.hook { margin-top: 0; font-weight: 700; }
.actions { display: flex; gap: 10px; flex-wrap: wrap; }

.cta {
    display: inline-block;
    margin-top: 12px;
    text-decoration: none;
    background: linear-gradient(135deg, #4f46e5, #7c3aed);
    color: #fff;
    padding: 11px 15px;
    border-radius: 12px;
    font-weight: 700;
}
.cta:hover { transform: translateY(-1px); }
.cta-secondary { background: #111827; }

.spotlight { border-left: 4px solid #6366f1; }

.post-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 14px; }
.post-list li { transition: transform .16s ease, box-shadow .16s ease; }
.post-list li:hover { transform: translateY(-2px); box-shadow: 0 14px 28px rgba(15,23,42,.10); }
.post-list a { color: #111827; text-decoration: none; }
.post-title { font-size: 18px; line-height: 1.35; margin: 0; }
.post-meta { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; }

.hot-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 14px; }
.hot-item {
    border-radius: 14px;
    padding: 14px;
    background: rgba(255,255,255,0.10);
    border: 1px solid rgba(255,255,255,0.18);
}
.hot-item a { color: #fff; text-decoration: none; }
.hot-kicker { font-size: 11px; letter-spacing: .07em; text-transform: uppercase; color: #c7d2fe; margin-bottom: 6px; }
.hot-title { margin: 0; font-size: 15px; line-height: 1.35; }
.hot-badges { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.hot-badge {
    display: inline-flex;
    align-items: center;
    border-radius: 999px;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 700;
    color: #e0e7ff;
    background: rgba(99, 102, 241, 0.36);
    border: 1px solid rgba(199, 210, 254, 0.35);
}
.hot-badge-ai { background: rgba(59, 130, 246, 0.28); border-color: rgba(147, 197, 253, 0.45); }
.hot-badge-saas { background: rgba(139, 92, 246, 0.28); border-color: rgba(196, 181, 253, 0.45); }
.hot-badge-deal { background: rgba(16, 185, 129, 0.28); border-color: rgba(110, 231, 183, 0.45); }
.hot-badge-free { background: rgba(217, 70, 239, 0.28); border-color: rgba(240, 171, 252, 0.45); }
.hot-badge-showhn { background: rgba(245, 158, 11, 0.30); border-color: rgba(253, 224, 71, 0.45); }
.hot-badge-trending { background: rgba(244, 63, 94, 0.28); border-color: rgba(253, 164, 175, 0.45); }
.hot-link {
    display: inline-block;
    margin-top: 10px;
    padding: 7px 10px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 700;
    color: #fff;
    background: rgba(255,255,255,0.16);
    border: 1px solid rgba(255,255,255,0.28);
    text-decoration: none;
}
.hot-link:hover { background: rgba(255,255,255,0.22); }

.ad-slot pre { overflow-x: auto; }
.footer { margin-top: 22px; color: #6b7280; font-size: 14px; }
.footer a { color: #4f46e5; text-decoration: none; }
""".strip()
    path.write_text(css, encoding="utf-8-sig")


def render_index(posts: List[Dict], config: Dict) -> str:
    telegram_channel = config.get("telegram", {}).get("channel_url", "")
    lead_magnet = config.get("lead_magnet", {})
    hero_cta_label = lead_magnet.get("button_text", "РџРѕР»СѓС‡РёС‚СЊ Р±РѕРЅСѓСЃ")
    hero_cta_url = lead_magnet.get("url", "")
    analytics = config.get("analytics", {})
    goatcounter_site = analytics.get("goatcounter_site", "")
    seo = config.get("seo", {})
    seo_enabled = bool(seo.get("enabled", True))
    seo_description = build_seo_description(
        config.get("site_tagline", ""),
        seo.get("default_description", config.get("site_tagline", "")),
    )
    home_canonical = build_absolute_url(config.get("public_base_url", ""), "index.html")
    default_image = str(seo.get("default_image", "") or "").strip()
    home_keywords = seo.get("home_keywords", [])
    if not isinstance(home_keywords, list):
        home_keywords = []
    home_keywords_content = ", ".join(str(item).strip() for item in home_keywords if str(item).strip())

    analytics_script = (
        f'<script data-goatcounter="https://{html.escape(goatcounter_site)}/count" async src="//gc.zgo.at/count.js"></script>'
        if goatcounter_site
        else ""
    )
    tracking_script = (
        """
<script>
document.addEventListener('click', function (event) {
    var link = event.target.closest('a[data-track="cta"]');
    if (!link) return;
    if (window.goatcounter && typeof window.goatcounter.count === 'function') {
        var source = link.dataset.trackSource || 'unknown';
        var label = link.dataset.trackLabel || 'cta';
        window.goatcounter.count({
            path: '/cta/' + source + '/' + encodeURIComponent(label),
            title: 'CTA click: ' + label,
            event: true
        });
    }
});
</script>
"""
        if goatcounter_site
        else ""
    )
    hero_button_html = (
        f'<a class="cta" href="{html.escape(hero_cta_url)}" target="_blank" rel="noopener" data-track="cta" data-track-source="index-hero" data-track-label="leadmagnet">{html.escape(hero_cta_label)}</a>'
        if hero_cta_url
        else ""
    )
    hero_telegram_html = (
        f'<p class="meta">РЎР»РµРґРёС‚СЊ Р·Р° РѕР±РЅРѕРІР»РµРЅРёСЏРјРё: <a href="{html.escape(telegram_channel)}" target="_blank" rel="noopener">Telegram</a></p>'
        if telegram_channel
        else ""
    )

    stats_html = (
        f'<div class="stats"><span class="stat">РџРѕСЃС‚РѕРІ: {len(posts)}</span><span class="stat">РћР±РЅРѕРІР»СЏРµС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё</span><span class="stat">РўРµРјР°: AI / Productivity</span></div>'
    )

    source_counts: Dict[str, int] = {}
    for post in posts:
        source_domain = extract_domain(post.get("source", ""))
        if source_domain:
            source_counts[source_domain] = source_counts.get(source_domain, 0) + 1
    top_sources = sorted(source_counts.items(), key=lambda item: item[1], reverse=True)[:6]
    source_chips_html = "".join(
        f'<span class="tag">{html.escape(domain)} В· {count}</span>' for domain, count in top_sources
    )
    trust_block_html = (
        f'<section class="card"><h3>РџСЂРѕРІРµСЂРµРЅРЅС‹Рµ РёСЃС‚РѕС‡РЅРёРєРё</h3><p class="meta">Р›РµРЅС‚Р° СЃРѕР±РёСЂР°РµС‚СЃСЏ РёР· РЅРµСЃРєРѕР»СЊРєРёС… РґРѕРјРµРЅРѕРІ, С‡С‚РѕР±С‹ РЅРµ Р·Р°РІРёСЃРµС‚СЊ РѕС‚ РѕРґРЅРѕРіРѕ СЃР°Р№С‚Р°.</p><div class="tag-row">{source_chips_html}</div></section>'
        if source_chips_html
        else ""
    )

    badge_rules = [
        ("AI", "ai", ["ai", "openai", "claude", "copilot", "llm", "gpt"]),
        ("SaaS", "saas", ["saas", "startup", "tool", "platform", "software"]),
        ("Deal", "deal", ["deal", "discount", "sale", "promo", "coupon", "off"]),
        ("Free", "free", ["free", "Р±РµСЃРїР»Р°С‚РЅРѕ"]),
        ("Show HN", "showhn", ["show hn"]),
    ]

    def get_hot_badges(title: str) -> List[Dict[str, str]]:
        title_lower = title.lower()
        labels: List[Dict[str, str]] = []
        for label, badge_class, tokens in badge_rules:
            if any(token in title_lower for token in tokens):
                labels.append({"label": label, "class": badge_class})
            if len(labels) >= 3:
                break
        if not labels:
            labels.append({"label": "Trending", "class": "trending"})
        return labels

    items = []
    for post in posts:
        items.append(
            f"<li><a href=\"posts/{html.escape(post['filename'])}\"><h3 class=\"post-title\">{html.escape(post['title'])}</h3><div class=\"post-meta\"><span class=\"tag\">{html.escape(post['published_at'])}</span><span class=\"tag\">Р§РёС‚Р°С‚СЊ РѕР±Р·РѕСЂ</span></div></a></li>"
        )

    hot_items = []
    for index, post in enumerate(posts[:3], start=1):
        badge_html = "".join(
            f'<span class="hot-badge hot-badge-{html.escape(item["class"])}">{html.escape(item["label"])}</span>'
            for item in get_hot_badges(post["title"])
        )
        hot_items.append(
            f"<article class=\"hot-item\"><div class=\"hot-kicker\">Р“РѕСЂСЏС‡РёР№ РѕС„С„РµСЂ #{index}</div><div class=\"hot-badges\">{badge_html}</div><a href=\"posts/{html.escape(post['filename'])}\"><h4 class=\"hot-title\">{html.escape(post['title'])}</h4></a><a class=\"hot-link\" href=\"posts/{html.escape(post['filename'])}\" data-track=\"cta\" data-track-source=\"hot-offer\" data-track-label=\"{html.escape(post['title'])}\">РћС‚РєСЂС‹С‚СЊ в†—</a></article>"
        )

    hot_html = f'<div class="hot-grid">{"".join(hot_items)}</div>' if hot_items else ""
    posts_html = "\n".join(items) if items else "<li>РџРѕРєР° РЅРµС‚ РјР°С‚РµСЂРёР°Р»РѕРІ. Р—Р°РїСѓСЃС‚РёС‚Рµ РіРµРЅРµСЂР°С‚РѕСЂ РїРѕР·Р¶Рµ.</li>"

    seo_tags = ""
    home_json_ld = ""
    if seo_enabled:
        seo_lines = [
            f'<meta name="description" content="{html.escape(seo_description)}" />',
            f'<meta property="og:title" content="{html.escape(config["brand_name"])}" />',
            f'<meta property="og:description" content="{html.escape(seo_description)}" />',
            '<meta property="og:type" content="website" />',
            f'<meta name="twitter:card" content="{html.escape("summary_large_image" if default_image else "summary")}" />',
        ]
        if home_keywords_content:
            seo_lines.append(f'<meta name="keywords" content="{html.escape(home_keywords_content)}" />')
        if home_canonical:
            seo_lines.append(f'<link rel="canonical" href="{html.escape(home_canonical)}" />')
            seo_lines.append(f'<meta property="og:url" content="{html.escape(home_canonical)}" />')
        if default_image:
            seo_lines.append(f'<meta property="og:image" content="{html.escape(default_image)}" />')
        seo_tags = "\n    ".join(seo_lines)

        if home_canonical:
            website_schema = {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": config.get("brand_name", "AutoAffiliate Pulse"),
                "description": seo_description,
                "url": home_canonical,
                "inLanguage": "ru",
            }
            home_json_ld = (
                '<script type="application/ld+json">'
                + json.dumps(website_schema, ensure_ascii=False).replace("</", "<\\/")
                + "</script>"
            )

    return f"""<!doctype html>
<html lang=\"ru\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>{html.escape(config['brand_name'])}</title>
    {seo_tags}
    <link rel=\"stylesheet\" href=\"assets/style.css\" />
    {analytics_script}
    {home_json_ld}
</head>
<body>
    <main class=\"container\">
        <header class=\"page-head\">
            <h1>{html.escape(config['brand_name'])}</h1>
            <p>{html.escape(config['site_tagline'])}</p>
            {stats_html}
        </header>
        <section class=\"card hero\">
            <p class=\"hook\">Свежие инструменты и офферы для роста продуктивности и дохода.</p>
            {hero_button_html}
            {hero_telegram_html}
            {hot_html}
        </section>
        {trust_block_html}
        <ul class=\"post-list\">{posts_html}</ul>
        <footer class=\"footer\">
            <a href=\"privacy.html\">Privacy Policy</a>
            <span>В·</span>
            <a href=\"disclaimer.html\">Affiliate Disclaimer</a>
        </footer>
    </main>
    {tracking_script}
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
        <a href=\"index.html\" class=\"back\">в†ђ РќР° РіР»Р°РІРЅСѓСЋ</a>
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
<p>РњС‹ СѓРІР°Р¶Р°РµРј РІР°С€Сѓ РєРѕРЅС„РёРґРµРЅС†РёР°Р»СЊРЅРѕСЃС‚СЊ. РЎР°Р№С‚ {brand_name} РјРѕР¶РµС‚ РѕР±СЂР°Р±Р°С‚С‹РІР°С‚СЊ С‚РµС…РЅРёС‡РµСЃРєРёРµ РґР°РЅРЅС‹Рµ (РЅР°РїСЂРёРјРµСЂ, IP, user-agent, cookies) РґР»СЏ Р°РЅР°Р»РёС‚РёРєРё Рё СѓР»СѓС‡С€РµРЅРёСЏ СЃРµСЂРІРёСЃР°.</p>
<p>РњС‹ РјРѕР¶РµРј РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ СЃС‚РѕСЂРѕРЅРЅРёРµ СЃРµСЂРІРёСЃС‹ Р°РЅР°Р»РёС‚РёРєРё Рё СЂРµРєР»Р°РјС‹, РєРѕС‚РѕСЂС‹Рµ РїСЂРёРјРµРЅСЏСЋС‚ cookies РІ СЂР°РјРєР°С… СЃРІРѕРёС… РїРѕР»РёС‚РёРє.</p>
<p>РњС‹ РЅРµ РїСЂРѕРґР°С‘Рј РїРµСЂСЃРѕРЅР°Р»СЊРЅС‹Рµ РґР°РЅРЅС‹Рµ С‚СЂРµС‚СЊРёРј Р»РёС†Р°Рј. РџРѕ РІРѕРїСЂРѕСЃР°Рј РѕР±СЂР°Р±РѕС‚РєРё РґР°РЅРЅС‹С…: {contact_email}.</p>
<p>РџРѕР»СЊР·СѓСЏСЃСЊ СЃР°Р№С‚РѕРј, РІС‹ СЃРѕРіР»Р°С€Р°РµС‚РµСЃСЊ СЃ СЌС‚РѕР№ РїРѕР»РёС‚РёРєРѕР№ РєРѕРЅС„РёРґРµРЅС†РёР°Р»СЊРЅРѕСЃС‚Рё.</p>
""".strip()

    disclaimer_content = f"""
<p>Р§Р°СЃС‚СЊ СЃСЃС‹Р»РѕРє РЅР° СЃР°Р№С‚Рµ {brand_name} СЏРІР»СЏСЋС‚СЃСЏ РїР°СЂС‚РЅС‘СЂСЃРєРёРјРё (affiliate links). Р•СЃР»Рё РІС‹ СЃРѕРІРµСЂС€Р°РµС‚Рµ РїРѕРєСѓРїРєСѓ РїРѕ С‚Р°РєРѕР№ СЃСЃС‹Р»РєРµ, РјС‹ РјРѕР¶РµРј РїРѕР»СѓС‡РёС‚СЊ РєРѕРјРёСЃСЃРёСЋ Р±РµР· РґРѕРїР»Р°С‚С‹ РґР»СЏ РІР°СЃ.</p>
<p>РњР°С‚РµСЂРёР°Р»С‹ РЅРѕСЃСЏС‚ РёРЅС„РѕСЂРјР°С†РёРѕРЅРЅС‹Р№ С…Р°СЂР°РєС‚РµСЂ Рё РЅРµ СЏРІР»СЏСЋС‚СЃСЏ С„РёРЅР°РЅСЃРѕРІРѕР№, СЋСЂРёРґРёС‡РµСЃРєРѕР№ РёР»Рё РёРЅРІРµСЃС‚РёС†РёРѕРЅРЅРѕР№ СЂРµРєРѕРјРµРЅРґР°С†РёРµР№.</p>
<p>РњС‹ СЃС‚СЂРµРјРёРјСЃСЏ Рє С‚РѕС‡РЅРѕСЃС‚Рё РґР°РЅРЅС‹С…, РЅРѕ РЅРµ РіР°СЂР°РЅС‚РёСЂСѓРµРј Р°РєС‚СѓР°Р»СЊРЅРѕСЃС‚СЊ С†РµРЅ, СѓСЃР»РѕРІРёР№ Рё РЅР°Р»РёС‡РёСЏ РѕС„С„РµСЂРѕРІ Сѓ СЃС‚РѕСЂРѕРЅРЅРёС… СЃРµСЂРІРёСЃРѕРІ.</p>
<p>РџРѕ РІРѕРїСЂРѕСЃР°Рј Рё РїСЂРµС‚РµРЅР·РёСЏРј: {contact_email}.</p>
""".strip()

    (paths["output"] / "privacy.html").write_text(
    render_legal_page("Privacy Policy", privacy_content, config),
    encoding="utf-8-sig",
    )
    (paths["output"] / "disclaimer.html").write_text(
    render_legal_page("Affiliate Disclaimer", disclaimer_content, config),
    encoding="utf-8-sig",
    )


def load_recent_posts(conn: sqlite3.Connection, limit: int = 50) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT title, published_at, local_path, source
        FROM published
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    posts = []
    for title, published_at, local_path, source in rows:
        filename = Path(local_path).name
        posts.append(
            {
                "title": title,
                "published_at": published_at,
                "filename": filename,
                "source": source,
            }
        )
    return posts


def write_seo_files(paths: Dict[str, Path], posts: List[Dict], config: Dict) -> None:
    seo = config.get("seo", {})
    if not bool(seo.get("enabled", True)):
        return

    base_url = str(config.get("public_base_url", "") or "").strip().rstrip("/")
    now_iso = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")

    sitemap_urls: List[str] = []
    if base_url:
        for rel in ("index.html", "privacy.html", "disclaimer.html"):
            sitemap_urls.append(
                f"  <url><loc>{html.escape(build_absolute_url(base_url, rel))}</loc><lastmod>{now_iso}</lastmod></url>"
            )
        for post in posts:
            post_url = build_absolute_url(base_url, f"posts/{post.get('filename', '')}")
            if not post_url:
                continue
            sitemap_urls.append(
                f"  <url><loc>{html.escape(post_url)}</loc><lastmod>{now_iso}</lastmod></url>"
            )

    sitemap_xml = "\n".join(
        [
            '<?xml version="1.0" encoding="utf-8-sig"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            *sitemap_urls,
            "</urlset>",
        ]
    )
    (paths["output"] / "sitemap.xml").write_text(sitemap_xml, encoding="utf-8-sig")

    robots_lines = [
        "User-agent: *",
        "Allow: /",
    ]
    if base_url:
        robots_lines.append(f"Sitemap: {build_absolute_url(base_url, 'sitemap.xml')}")
    (paths["output"] / "robots.txt").write_text("\n".join(robots_lines) + "\n", encoding="utf-8-sig")


def post_to_telegram(config: Dict, text: str) -> None:
    telegram = config.get("telegram", {})
    token = os.getenv("TELEGRAM_BOT_TOKEN") or telegram.get("bot_token")
    chat_id = telegram.get("chat_id")
    if not token or not chat_id:
        return

    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as error:
        print(f"telegram_error type={type(error).__name__}: {error}")


def should_send_telegram_run_report(config: Dict) -> bool:
    telegram = config.get("telegram", {})
    return bool(telegram.get("notify_every_run", True))


def build_telegram_run_report(config: Dict, result: Dict[str, int]) -> str:
    brand = config.get("brand_name", "AutoAffiliate Pulse")
    base_url = config.get("public_base_url", "").rstrip("/")
    home_url = f"{base_url}/index.html" if base_url else ""
    telegram = config.get("telegram", {})
    report_mode = str(telegram.get("run_report_mode", "short")).strip().lower()

    if report_mode == "detailed":
        lines = [
            f"{brand}: С†РёРєР» Р·Р°РІРµСЂС€С‘РЅ",
            f"created={result.get('created', 0)}",
            f"fetched={result.get('fetched', 0)}",
            f"fetched_raw={result.get('fetched_raw', 0)}",
            f"deduped={result.get('deduped', 0)}",
            f"selected={result.get('selected', 0)}",
            f"republished={result.get('republished', 0)}",
            f"feeds_failed={result.get('feeds_failed', 0)}",
            f"published_total={result.get('published_total', 0)}",
            f"duration_sec={result.get('duration_sec', 0)}",
        ]
    else:
        lines = [
            (
                f"вњ… Р¦РёРєР»: created={result.get('created', 0)} "
                f"| fetched={result.get('fetched', 0)} "
                f"| deduped={result.get('deduped', 0)} "
                f"| errors={result.get('feeds_failed', 0)}"
            )
        ]

    if home_url:
        lines.append(home_url)
    return "\n".join(lines)


def run_once(config: Dict) -> Dict[str, int]:
    started_at = time.time()
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
        except Exception as error:
            print(f"feed_error source={feed} error={type(error).__name__}: {error}")
            errors += 1

    fetched_raw = len(all_entries)
    all_entries.sort(key=lambda item: item.score, reverse=True)
    all_entries, deduped_count = dedupe_entries(all_entries)

    created = 0
    publish_limit = int(config.get("max_posts_per_run", 5))
    max_per_domain = max(1, int(config.get("max_posts_per_source_domain", 2)))
    max_per_feed = max(1, int(config.get("max_posts_per_feed", 3)))
    post_selection_min_score = int(config.get("post_selection_min_score", 0))
    post_selection_fallback_min_score = int(
        config.get("post_selection_fallback_min_score", max(0, post_selection_min_score - 1))
    )
    post_selection_adaptive_fallback = bool(config.get("post_selection_adaptive_fallback", True))
    evergreen_enabled = bool(config.get("evergreen_republish_enabled", False))
    evergreen_min_age_days = int(config.get("evergreen_republish_min_age_days", 7))
    evergreen_cooldown_days = int(config.get("evergreen_republish_cooldown_days", 3))
    evergreen_max_per_run = int(config.get("evergreen_republish_max_per_run", 10))

    selected_entries: List[Entry] = []
    selected_guids = set()
    selected_title_keys: Set[str] = set()
    domain_counts: Dict[str, int] = {}
    feed_counts: Dict[str, int] = {}

    for entry in all_entries:
        if len(selected_entries) >= publish_limit:
            break
        if is_already_published(conn, entry.guid):
            continue
        if entry.score < post_selection_min_score:
            continue

        title_key = text_fingerprint(entry.title)
        if title_key and title_key in selected_title_keys:
            continue

        source_domain = extract_domain(entry.link) or "unknown"
        source_feed = entry.source or "unknown"

        if domain_counts.get(source_domain, 0) >= max_per_domain:
            continue
        if feed_counts.get(source_feed, 0) >= max_per_feed:
            continue

        selected_entries.append(entry)
        selected_guids.add(entry.guid)
        if title_key:
            selected_title_keys.add(title_key)
        domain_counts[source_domain] = domain_counts.get(source_domain, 0) + 1
        feed_counts[source_feed] = feed_counts.get(source_feed, 0) + 1

    if len(selected_entries) < publish_limit:
        for entry in all_entries:
            if len(selected_entries) >= publish_limit:
                break
            if entry.guid in selected_guids:
                continue
            if is_already_published(conn, entry.guid):
                continue
            if entry.score < post_selection_min_score:
                continue
            title_key = text_fingerprint(entry.title)
            if title_key and title_key in selected_title_keys:
                continue
            selected_entries.append(entry)
            selected_guids.add(entry.guid)
            if title_key:
                selected_title_keys.add(title_key)

    if post_selection_adaptive_fallback and len(selected_entries) < publish_limit:
        for entry in all_entries:
            if len(selected_entries) >= publish_limit:
                break
            if entry.guid in selected_guids:
                continue
            if is_already_published(conn, entry.guid):
                continue
            if entry.score < post_selection_fallback_min_score:
                continue
            title_key = text_fingerprint(entry.title)
            if title_key and title_key in selected_title_keys:
                continue
            selected_entries.append(entry)
            selected_guids.add(entry.guid)
            if title_key:
                selected_title_keys.add(title_key)

    republished_original_guids: List[str] = []
    if evergreen_enabled and len(selected_entries) < publish_limit:
        evergreen_limit = min(
            max(0, evergreen_max_per_run),
            max(0, publish_limit - len(selected_entries)),
        )
        evergreen_candidates = select_evergreen_candidates(
            conn,
            min_age_days=evergreen_min_age_days,
            cooldown_days=evergreen_cooldown_days,
            limit=evergreen_limit,
        )
        for item in evergreen_candidates:
            unique_suffix = int(time.time()) + len(republished_original_guids)
            entry = Entry(
                guid=f"{item['guid']}#republish-{unique_suffix}",
                title=f"{item['title']} (РѕР±РЅРѕРІР»РµРЅРѕ)",
                link=item["link"],
                description="",
                published_at=dt.datetime.now(dt.UTC).isoformat(),
                source=item["source"],
                score=max(post_selection_fallback_min_score, post_selection_min_score),
            )
            selected_entries.append(entry)
            selected_guids.add(entry.guid)
            title_key = text_fingerprint(entry.title)
            if title_key:
                selected_title_keys.add(title_key)
            republished_original_guids.append(item["guid"])
            if len(selected_entries) >= publish_limit:
                break

    used_filenames: Set[str] = set()

    for entry in selected_entries:
        monetized = apply_affiliate(entry.link, config.get("affiliate", {}))
        slug = slugify(entry.title)
        filename = choose_unique_filename(slug, paths["pages"], used_filenames)
        post_path = paths["pages"] / filename

        html_content = render_post(entry, monetized, config, filename=filename)
        post_path.write_text(html_content, encoding="utf-8-sig")

        save_published(conn, entry, str(post_path))
        created += 1

        post_to_telegram(
            config,
            f"{entry.title}\n{config.get('public_base_url', '').rstrip('/')}/posts/{filename}",
        )

    for original_guid in republished_original_guids:
        mark_evergreen_republished(conn, original_guid)

    posts = load_recent_posts(conn)
    index_html = render_index(posts, config)
    (paths["output"] / "index.html").write_text(index_html, encoding="utf-8-sig")
    write_seo_files(paths, posts, config)

    total_published = conn.execute("SELECT COUNT(*) FROM published").fetchone()[0]

    conn.close()

    result = {
        "created": created,
        "feeds_failed": errors,
        "fetched": len(all_entries),
        "fetched_raw": fetched_raw,
        "deduped": deduped_count,
        "selected": len(selected_entries),
        "republished": len(republished_original_guids),
        "published_total": int(total_published),
        "duration_sec": int(max(0, round(time.time() - started_at))),
    }
    if should_send_telegram_run_report(config):
        post_to_telegram(config, build_telegram_run_report(config, result))
    return result


def rebuild_all_posts(config: Dict) -> Dict[str, int]:
    paths = ensure_dirs(config)
    write_css(paths["assets"] / "style.css")
    write_legal_pages(paths, config)

    db_path = Path(config.get("state_db", "state.db"))
    conn = db_connect(db_path)

    rows = conn.execute(
        """
        SELECT guid, title, link, published_at, source, local_path
        FROM published
        ORDER BY created_at DESC
        """
    ).fetchall()

    rebuilt = 0
    used_filenames: Set[str] = set()
    for guid, title, link, published_at, source, local_path in rows:
        entry = Entry(
            guid=guid,
            title=title,
            link=link,
            description="",
            published_at=published_at,
            source=source,
            score=0,
        )
        monetized = apply_affiliate(entry.link, config.get("affiliate", {}))
        filename = Path(local_path).name
        if not filename:
            filename = choose_unique_filename(slugify(title), paths["pages"], used_filenames)
        else:
            used_filenames.add(filename)
        html_content = render_post(entry, monetized, config, filename=filename)

        post_path = Path(local_path)
        if not post_path.is_absolute():
            post_path = Path(post_path)
        if post_path.name != filename:
            post_path = post_path.with_name(filename)
        post_path.parent.mkdir(parents=True, exist_ok=True)
        post_path.write_text(html_content, encoding="utf-8-sig")
        rebuilt += 1

    posts = load_recent_posts(conn)
    index_html = render_index(posts, config)
    (paths["output"] / "index.html").write_text(index_html, encoding="utf-8-sig")
    write_seo_files(paths, posts, config)

    conn.close()
    return {"rebuilt": rebuilt}


def run_daemon(config: Dict, interval_minutes: int) -> None:
    while True:
        try:
            result = run_once(config)
            print(
                f"[{dt.datetime.now().isoformat(timespec='seconds')}] "
                f"new_posts={result['created']} fetched={result['fetched']} feed_errors={result['feeds_failed']}"
            )
        except Exception as error:
            print(
                f"[{dt.datetime.now().isoformat(timespec='seconds')}] "
                f"daemon_error={type(error).__name__}: {error}"
            )
        time.sleep(max(1, interval_minutes) * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoAffiliate Pulse")
    parser.add_argument("--config", default="config.json", help="РџСѓС‚СЊ РґРѕ config.json")
    parser.add_argument("--daemon", action="store_true", help="Р‘РµСЃРєРѕРЅРµС‡РЅС‹Р№ СЂРµР¶РёРј")
    parser.add_argument("--interval", type=int, default=180, help="РРЅС‚РµСЂРІР°Р» РІ РјРёРЅСѓС‚Р°С…")
    parser.add_argument(
        "--rebuild-all",
        action="store_true",
        help="РџРµСЂРµСЃРѕР±СЂР°С‚СЊ РІСЃРµ СЂР°РЅРµРµ РѕРїСѓР±Р»РёРєРѕРІР°РЅРЅС‹Рµ РїРѕСЃС‚С‹ РїРѕ С‚РµРєСѓС‰РµРјСѓ С€Р°Р±Р»РѕРЅСѓ",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        example_config_path = config_path.parent / "config.example.json"
        if example_config_path.exists():
            config_path.write_text(example_config_path.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
            print(f"config_missing_recovered=true path={config_path}")
        else:
            raise FileNotFoundError("РЎРѕР·РґР°Р№С‚Рµ config.json РЅР° РѕСЃРЅРѕРІРµ config.example.json")

    config = load_config(config_path)

    if args.daemon:
        run_daemon(config, args.interval)
        return

    if args.rebuild_all:
        result = rebuild_all_posts(config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    result = run_once(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
