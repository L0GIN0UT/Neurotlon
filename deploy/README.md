# deploy

Установка Нейротлона на ПК админа (Windows + Docker Desktop) и на ПК стендов, бэкап, сертификаты, репетиция (этап M7).
В зале нет интернета: всё собирается заранее и переносится на флешке.

| Файл | Что |
|---|---|
| `server.Dockerfile` | образ сервера: Python 3.12, `uv sync --locked`, не root, данные в `/data`, миграции при старте, один воркер (одна запись в SQLite) |
| `web.Dockerfile`, `nginx.conf` | образ веб-клиента: сборка Vite → Nginx, HTTPS, прокси `/api`, SSE без буферизации |
| `docker-compose.yml` | сервисы `server`, `web`, `backup`; `docker-compose.build.yml` добавляет сборку (только на машине с интернетом) |
| `.env.example` | `HOST_NAME` и `BACKUP_DIR` |
| `scripts/build-bundle.ps1` | собирает папку для флешки (с интернетом) |
| `scripts/install-admin.ps1` | установка на ПК админа |
| `scripts/make-certs.ps1` | локальный центр сертификации и сертификат сервера (mkcert) |
| `scripts/install-stand.ps1` | установка лаунчера, моста и игр на ПК стенда без интернета |

## 1. Заранее (ПК с интернетом, один раз)

Нужны: Docker Desktop (запущен), `uv`, репозиторий.

1. Скачайте `mkcert.exe` (Windows amd64, <https://github.com/FiloSottile/mkcert/releases>).
2. Соберите пакет. Путь вывода короткий, иначе упрётся в 260 символов Windows:

   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\scripts\build-bundle.ps1 -OutDir C:\nt-bundle -MkcertExe C:\tools\mkcert.exe
   ```

   Скрипт собирает оба образа, сохраняет их в `neurotlon-images.tar` (`docker save`), считает контрольную сумму,
   копирует compose, `.env.example`, скрипты и этот файл, готовит папку `stand\`
   (`uv.exe`, Python 3.12, исходники лаунчера, моста и игр, кэш всех колёс для `uv sync --offline`).
3. Скопируйте `C:\nt-bundle` на флешку целиком (порядка 1–2 ГБ). Состав:

   ```
   neurotlon-images.tar   SHA256SUMS.txt   docker-compose.yml   .env.example   README.md
   scripts\   install-admin.ps1  make-certs.ps1
   tools\     mkcert.exe
   stand\     uv.exe  python\  uv-cache\  neurotlon\  install-stand.ps1
   ```
4. Заранее подготовьте второй ноутбук (раздел 7): тот же пакет, Docker Desktop, копия папки `certs`.
5. У роутера задайте ПК админа постоянный адрес (резерв DHCP или статический IP). Стенды и планшеты ходят по IP
   (`https://192.168.x.x`): имя вида `neurotlon.local` зависит от mDNS и на Android работает не везде.

## 2. ПК админа

Требования: Windows 10/11, Docker Desktop с WSL2 и **Linux-контейнерами**, 4 ГБ свободной памяти.

1. Установите Docker Desktop (установщик тоже заранее на флешку), включите WSL2, запустите, дождитесь «Engine running».
2. Скопируйте пакет с флешки на диск, например в `C:\neurotlon`. Подключите диск для бэкапов.
3. От имени администратора:

   ```powershell
   cd C:\neurotlon
   powershell -ExecutionPolicy Bypass -File scripts\install-admin.ps1
   ```

   Скрипт: проверяет Docker, загружает образы (`docker load`, сверяет контрольную сумму), создаёт `.env` и открывает его
   в блокноте, делает сертификат (если нет `certs\server.pem`), открывает порты 80 и 443 в брандмауэре,
   запускает `docker compose up -d`, ждёт `healthy` и печатает адреса `/admin`, `/judge`, `/board`, `/tablet`.
4. В `.env`:
   - `HOST_NAME` — имя ПК в сети зала (попадает в сертификат);
   - `BACKUP_DIR` — папка бэкапов: флешка или общая папка запасного ноутбука, например `E:/neurotlon-backup`
     (косые черты вперёд). Если диска нет, установка остановится. В Docker Desktop диск должен быть разрешён
     (Settings → Resources → File sharing).
5. Суперпользователь (пароль запрашивается, не короче 8 символов):

   ```powershell
   docker compose exec server neurotlon-server create-superuser --login root
   ```

   Дальше в `/admin`: аккаунты админа, судьи, трёх волонтёров, три станции (токен показывается один раз).
6. Данные лежат в томе Docker `neurotlon-data` (внутри WSL2), а не в папке Windows: SQLite в режиме WAL
   не работает на папках Windows, смонтированных в контейнер. Копия базы — только через бэкап (раздел 6).

Остановить: `docker compose stop`. Запустить: `docker compose up -d --no-build`. Контейнеры сами поднимаются
после перезагрузки ПК (`restart: unless-stopped`, Docker Desktop в автозапуске). Данные при этом не теряются;
`docker compose down -v` **удаляет том с базой**, не запускайте его на мероприятии.

## 3. Сертификаты

`make-certs.ps1` вызывается из `install-admin.ps1`; отдельно:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\make-certs.ps1 -HostName neurotlon.local -ExtraNames 192.168.1.11 -Force
```

Создаёт локальный центр сертификации mkcert и сертификат на `HOST_NAME`, IP ПК, `localhost`, `127.0.0.1` и
`-ExtraNames` (имя или IP запасного ноутбука). Результат в `certs\` (в git не попадает):

- `server.pem`, `server-key.pem` — для Nginx;
- `rootCA.crt` (он же `rootCA.pem`) — **этот файл** ставится на планшеты и стенды. Закрытый ключ центра
  (`mkcert -CAROOT`, `rootCA-key.pem`) остаётся только на ПК админа.

Сертификат нужен, чтобы камера в браузере планшета работала (только HTTPS) и чтобы лаунчер проверял сервер.

## 4. Стенды (ПК с Windows)

Для каждого стенда: флешка с пакетом, `rootCA.crt`, токен станции из админки.

```powershell
cd D:\nt-bundle\stand
powershell -ExecutionPolicy Bypass -File install-stand.ps1 -Discipline darts -ServerUrl https://192.168.1.10 -CaFile D:\certs\rootCA.crt
```

Скрипт копирует Python, исходники и `uv.exe` в `C:\neurotlon`, ставит пакеты из кэша без сети
(`uv sync --offline --locked`), пишет `launcher.toml` из примера (адрес, `ca_file`, `discipline`, путь к токену)
и `bridge.toml`, создаёт `start-bridge.cmd` и `start-launcher.cmd`. Параметр `-InstallCa` (от администратора)
дополнительно ставит центр в хранилище Windows (`certutil -addstore Root`); без него лаунчер использует `ca_file`.

Вручную после установки:

1. **Токен станции.** В `/admin` создайте станцию и сохраните токен одной строкой в `C:\neurotlon\station.token`.
2. **Датчики.** Включите BrainBit/Callibri, найдите их: `C:\neurotlon\uv.exe run --offline --no-sync --project C:\neurotlon\app neurotlon-bridge --scan`.
   Серийные номера впишите в `C:\neurotlon\bridge.toml` → `[devices]` (дартс и футбол: `eeg` и `emg`; понг: `emg_left` и `emg_right`).
3. **Игра.** В `launcher.toml` → `[game] command` пока стоит заглушка `neurotlon_games.stub`; когда игра будет готова,
   укажите её команду (см. `launcher/README.md`).
4. Запуск: `start-bridge.cmd`, затем `start-launcher.cmd`. Лаунчер сверяет дисциплину с сервером и при ошибке
   показывает «Стенд остановлен».

## 5. Планшеты

1. Подключите планшет к Wi-Fi зала (без интернета Android покажет «нет доступа» — это нормально; не отключайте сеть).
2. Скопируйте `rootCA.crt` на планшет. Android: Настройки → Безопасность → Шифрование и учётные данные →
   Установить сертификат → Сертификат ЦС (на некоторых версиях: «Установить из памяти»).
3. Откройте в Chrome `https://192.168.1.10/tablet`: замка с предупреждением быть не должно.
4. Меню Chrome → «Добавить на главный экран» (PWA).
5. Войдите аккаунтом волонтёра своей секции. Сессия живёт сутки; разрешите камеру при первом сканировании.
6. Проверьте: отсканируйте бейдж, запишите тестовый результат, нажмите «Отменить».

## 6. Во время мероприятия

**Бэкап.** Сервис `backup` раз в минуту копирует базу через SQLite Backup API в `BACKUP_DIR`
(`neurotlon-ГГГГММДД-ЧЧММСС.db`, время UTC, хранится 120 последних, запись через временный файл и переименование).
Проверка:

```powershell
docker compose logs --tail 3 backup     # строки "backup written"
dir E:\neurotlon-backup | sort LastWriteTime | select -Last 3
```

Если в логе `ERROR` (диск вынут, нет места), верните диск: сервис повторит попытку через минуту сам.

**Админка** (`/admin`) показывает статус станций; табло — `/board` на большом экране.

**Сервер перезапустился** — ничего делать не нужно: стенды и планшеты досылают результаты из очередей,
повтор безопасен (идемпотентность по `session_id`), табло переподключается само.

**Репетиция** (за день до мероприятия, на пустой базе). Инструмент создаёт `rehearsal-*` аккаунты и 20 участников,
играет все пары по трём дисциплинам, проверяет конфликт, отмену, запрос на исправление, табло по SSE (до 10 с),
фиксацию итогов и XLSX, и печатает PASS/FAIL:

```powershell
docker compose exec server neurotlon-server create-superuser --login root
docker compose exec -e NEUROTLON_REHEARSAL_PASSWORD=ПАРОЛЬ server neurotlon-rehearsal --base-url http://127.0.0.1:8000 --xlsx-out /tmp/itogi.xlsx
```

Инструмент отказывается работать, если в базе уже есть участники. Чтобы вернуть чистую базу после репетиции
(только если в ней нет ничего, кроме репетиционных данных; иначе откажется):

```powershell
docker compose stop server web backup
docker compose run --rm --no-deps backup neurotlon-rehearsal --reset --db /data/neurotlon.db
docker compose up -d --no-build
docker compose exec server neurotlon-server create-superuser --login root
```

Остальная репетиция отказов (отключить сеть, перезапустить сервер `docker compose restart server`, выключить планшет и стенд,
вынуть диск бэкапа) делается руками по чек-листу из `docs/roadmap.md`, M7.

## 7. Если ПК админа вышел из строя

Нужны: запасной ноутбук с Docker Desktop и пакетом, копия папки `certs` (до мероприятия), диск с бэкапами.

1. Дайте ноутбуку IP и имя вышедшего ПК (или заранее внесите его IP в `-ExtraNames` при создании сертификата и
   перенастройте адрес на стендах и планшетах).
2. Скопируйте `certs\` в папку пакета, подключите диск с бэкапами, в `.env` укажите его в `BACKUP_DIR`.
3. `scripts\install-admin.ps1 -NonInteractive` — поднимет пустую систему.
4. Остановите приложение и восстановите последнюю копию:

   ```powershell
   dir E:\neurotlon-backup | sort Name | select -Last 1
   docker compose stop server web backup
   docker compose run --rm --no-deps backup neurotlon-server restore --from /backup/neurotlon-20270101-143000.db --db /data/neurotlon.db
   docker compose up -d --no-build
   ```

   `restore` проверяет копию (`integrity_check`), отказывается работать, пока сервер держит базу открытой
   (поэтому сначала `stop`), а прежнюю базу сохраняет рядом как `neurotlon.db.before-restore-…`.
5. Проверьте `/admin` и `/board`. Результаты за последнюю минуту до сбоя могут отсутствовать: стенды и планшеты
   досылают то, что не подтверждено сервером, остальное волонтёры повторят по запросу судьи.

## 8. После мероприятия

1. `/judge` → «Зафиксировать итоги» (если не сделано).
2. `/admin` → экспорт XLSX (или `GET /api/v1/export.xlsx`). Файл содержит «Итоги» и «Участники», без категорий.
3. Сохраните последнюю копию базы из `BACKUP_DIR` в архив. Выложите таблицу на сайт мероприятия вручную.
4. `docker compose stop`. Том `neurotlon-data` удаляйте (`docker compose down -v`) только после архивации.

## Проверка без Docker

Серверная часть, бэкап и репетиция проверяются тестами: `uv run pytest server/tests/test_backup.py server/tests/test_rehearsal.py`.
Сборку образов и стек проверяет задание `deploy` в CI (`.github/workflows/ci.yml`).
