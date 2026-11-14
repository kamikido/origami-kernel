---
name: 1c-its-docs
description: >-
  Поиск и чтение документации, руководств разработчика и стандартов на портале 1С:ИТС (its.1c.ru)
  с обходом защиты DataDome. Открывать, когда требуется получить методические указания 1С,
  описание типовых механизмов или архитектуру конфигураций с ИТС.
---

# Доступ к 1С:ИТС (its.1c.ru) через утилиту its_browser

Утилита расположена в `tools/its/its_browser.py`.
Использует стандартную библиотеку Python (`urllib.request`), TLS-отпечаток которой полностью обходит антибот-защиту DataDome на портале 1С:ИТС (в отличие от `requests`, которая мгновенно блокируется).

---

## 1. Команды CLI (запуск через run_command)

```powershell
# Авторизация (использует ITS_LOGIN и ITS_PASSWORD из tools/.env или переменных среды)
python tools/its/its_browser.py login

# Поиск по материалам ИТС
python tools/its/its_browser.py search "контроль остатков при проведении"

# Получение статьи в формате Markdown
python tools/its/its_browser.py get /db/v83doc/content/123/hdoc

# Получение статьи целиком (без обрезки)
python tools/its/its_browser.py get /db/v83doc/content/123/hdoc --full

# Просмотр ссылок на странице (для навигации по разделам)
python tools/its/its_browser.py links /db/v83doc/content/123/hdoc
```

---

## 2. Использование из Python-скрипта

```python
import sys
sys.path.insert(0, r"tools/its")
from its_browser import make_opener, do_login, fetch_page, html_to_text, save_cookies

op, cj = make_opener()
do_login(op, cj)

final_url, html = fetch_page(op, cj, "/db/metod81/content/...")
text = html_to_text(html, truncate=False)
save_cookies(cj)
```

> **Важно:** Сессия CAS SSO сохраняет куки в `tools/its/.its_cookies.txt`, поэтому повторный логин требуется только после истечения срока действия куки.
