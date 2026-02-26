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
   - при необходимости `telegram.bot_token` и `telegram.chat_id`.
4. Разовый запуск:

```powershell
C:/Users/HP/AppData/Local/Programs/Python/Python314/python.exe app.py --config config.json
```

После запуска появится папка `site/` с готовым статическим сайтом.

## Автозапуск в Windows Task Scheduler (уже готово)

В проекте есть скрипты:

- `scripts/run_autopulse.ps1` — запуск генерации с логами в `logs/autopulse.log`.
- `scripts/setup_scheduler.ps1` — регистрация задачи планировщика.

Создать/обновить задачу:

```powershell
./scripts/setup_scheduler.ps1
```

Имя задачи по умолчанию: `AutoAffiliatePulse-Every3Hours`.

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
