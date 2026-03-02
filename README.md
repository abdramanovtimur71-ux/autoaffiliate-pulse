# AutoAffiliate Pulse

Автономный микро-бизнес: скрипт сам собирает контент из RSS, фильтрует по нише, добавляет партнёрские параметры, публикует SEO-страницы и может отправлять анонсы в Telegram.

## Как это зарабатывает

1. **Affiliate CPA/CPS**: добавляются ваши партнёрские параметры (`aff`, `tag`, UTM).
2. **Реклама**: на страницах есть место под AdSense/другую сеть.
3. **Спонсорские размещения**: можно продавать рекламные посты в том же шаблоне.

> Доход не гарантирован: зависит от трафика, ниши и качества офферов.

## Быстрый старт (Windows)

1. Убедитесь, что установлен Python 3.10+.
2. Скопируйте `config.example.json` в `config.json`.
3. Заполните в `config.json`:
   - `public_base_url` (ваш домен),
   - affiliate-параметры,
   - `lead_magnet.url` и `telegram.channel_url` для блоков конверсии,
   - `commercial_keywords` и `min_publish_score` для отбора более коммерческих материалов,
   - `money_mode` и `money_mode_min_score` для агрессивного режима монетизации,
   - `max_posts_per_source_domain` и `max_posts_per_feed` для распределения публикаций по разным сайтам,
   - `money_mode_fallback`, чтобы при пустой выдаче автоматически смягчать фильтр,
   - `legal.contact_email` для автогенерации legal-страниц,
   - `analytics.goatcounter_site` для трекинга кликов по CTA,
   - при необходимости `telegram.bot_token` и `telegram.chat_id`.

Если указать `telegram.bot_token` и `telegram.chat_id`, система будет отправлять в Telegram:

- анонсы новых постов,
- heartbeat-отчёт по каждому циклу (`created`, `fetched`, `feeds_failed`).

В расширенном режиме (`telegram.run_report_mode = detailed`) heartbeat также включает:
`fetched_raw`, `deduped`, `selected`, `republished`, `published_total`, `duration_sec`.

Управление heartbeat: `telegram.notify_every_run` (`true`/`false`).
Формат heartbeat: `telegram.run_report_mode` (`short` или `detailed`).

Безопаснее хранить токен в переменной окружения `TELEGRAM_BOT_TOKEN` (тогда `telegram.bot_token` можно оставить пустым).

Для максимального охвата используйте профиль:

- `max_posts_per_run`: `30`
- `max_posts_per_source_domain`: `4`
- `max_posts_per_feed`: `5`
- `post_selection_min_score`: `5` (quality floor, чтобы отсеивать слабые материалы)
- `post_selection_adaptive_fallback`: `true` (если не набралось до лимита — включается добор)
- `post_selection_fallback_min_score`: `4` (мягкий порог только для добора)
- `evergreen_republish_enabled`: `true` (добавляет переупаковку старых материалов при нехватке новых)
- `evergreen_republish_min_age_days`: `1` и `evergreen_republish_cooldown_days`: `3`

Legal-страницы `privacy.html` и `disclaimer.html` генерируются автоматически при каждом запуске.
SEO-файлы `sitemap.xml` и `robots.txt` тоже генерируются автоматически.
В HTML-страницы автоматически добавляются SEO-мета-теги: `description`, `canonical`, OpenGraph и JSON-LD schema.

### Трекинг кликов по CTA (просто и без backend)

1. Зарегистрируйте сайт в GoatCounter.
2. Укажите в `analytics.goatcounter_site` значение вида `yourname.goatcounter.com`.
3. После деплоя в отчётах GoatCounter будут события вида `/cta/<source>/<label>`.

### Проверка, что деньги реально будут начисляться

Проверить конфиг монетизации:

```powershell
python app.py --config config.json --monetization-check-only
```

Запуск в строгом режиме (упадёт, если остались `YOUR_*` и другие проблемы):

```powershell
python app.py --config config.json --strict-monetization
```
4. Разовый запуск:

```powershell
C:/Users/HP/AppData/Local/Programs/Python/Python314/python.exe app.py --config config.json
```

После запуска появится папка `site/` с готовым статическим сайтом.

## Автозапуск в Windows Task Scheduler (уже готово)

В проекте есть скрипты:

- `scripts/run_autopulse.ps1` — запуск генерации с логами в `logs/autopulse.log`.
- `scripts/setup_scheduler.ps1` — регистрация задачи планировщика.
- `scripts/setup_autonomous.ps1` — включает полный автономный режим одной командой.

`run_autopulse.ps1` уже включает:

- автоповтор запуска при временной ошибке (retry),
- ротацию лога при достижении лимита размера.

Создать/обновить задачу:

```powershell
./scripts/setup_scheduler.ps1
```

Имя задачи по умолчанию: `AutoAffiliatePulse-Every3Hours`.

### Полный автономный режим (рекомендуется)

Одна команда:

```powershell
./scripts/setup_autonomous.ps1
```

Что произойдёт автоматически:

1. Если нет `config.json`, он будет создан из `config.example.json`.
2. Будет зарегистрирована/обновлена задача планировщика.
3. Будет выполнен немедленный пробный запуск.
4. Дальше проект будет работать сам по расписанию.

По умолчанию скрипт пытается создать задачу от имени `SYSTEM` (для работы без входа пользователя в Windows).
Если прав администратора нет — автоматически включается безопасный fallback на текущего пользователя.

Если нужно запускать только в вашей сессии пользователя:

```powershell
./scripts/setup_autonomous.ps1 -RunAsCurrentUser
```

## Автономный режим (демон, если нужен)

```powershell
C:/Users/HP/AppData/Local/Programs/Python/Python314/python.exe app.py --config config.json --daemon --interval 180
```

Это запускает обновление каждые 180 минут.

## GitHub Pages: автодеплой без секретов

В проект добавлен workflow: `.github/workflows/github-pages-autodeploy.yml`.

После пуша в GitHub:

1. Откройте `Settings → Pages`.
2. В `Build and deployment` выберите `Source: GitHub Actions`.

Готово: каждые 3 часа workflow сам генерирует `site/` и публикует сайт.

### Публикация в GitHub одной командой

```powershell
./scripts/publish_github.ps1
```

Скрипт сам:

1. попросит вход в GitHub через браузер,
2. создаст репозиторий,
3. запушит код,
4. запустит workflow `GitHub Pages AutoDeploy`.

## Cloudflare Pages: опционально

В проект добавлен workflow: `.github/workflows/cloudflare-pages-autodeploy.yml`.

Что нужно один раз сделать в GitHub репозитории:

1. Добавить secrets:
   - `CF_API_TOKEN`
   - `CF_ACCOUNT_ID`
2. Добавить repository variable:
   - `CF_PAGES_PROJECT` (имя проекта Cloudflare Pages)

После этого GitHub Actions будет каждые 3 часа:

1. запускать генератор,
2. деплоить папку `site/` в Cloudflare Pages.

Если секреты/переменная ещё не заданы, workflow Cloudflare будет автоматически пропускаться (а не падать ошибкой).

## Публикация сайта

Подходит любой static hosting: Cloudflare Pages, Netlify, GitHub Pages, Vercel static.

- Деплойте содержимое папки `site/`.
- Укажите домен из `public_base_url`.

## Вариант 24/7 без вашего ПК

- Запуск на VPS/облаке через `Task Scheduler`, `cron` или PM2/supervisor.
- Либо GitHub Actions по расписанию с коммитом обновлённой папки `site/`.

## Минимальная воронка монетизации

- Ниша: AI инструменты для малого бизнеса.
- Трафик: SEO + Telegram канал.
- Конверсия: лид-магнит (чек-лист/гайд) + партнёрская ссылка в каждой статье.

## Legal checklist (обязательно)

- Публикуйте disclosure о партнёрских ссылках на страницах.
- Не копируйте чужие тексты дословно, делайте переработку и указывайте источник.
- Не давайте ложных обещаний дохода и не используйте фейковые скидки.
- Соблюдайте правила партнёрских программ (источники трафика, брендовые ограничения).
- Если собираете email/контакты — добавьте Privacy Policy и страницу контактов.
