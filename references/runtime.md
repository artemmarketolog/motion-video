# Среда рендера

- Runtime: `~/.local/share/motion-video/runtime/` (`MOTION_VIDEO_RUNTIME`), ставит `setup.py`.
- `hyperframes@0.8.84`, `gsap@3.14.2`; точные transitive версии в package-lock.json.
- Node 22+ (проверено на 22.22.1); системные `ffmpeg`, `ffprobe` (проверено на 6.1).
- Chrome for Testing 149.0.7827.55: `<runtime>/chrome/chrome-linux64/chrome` (`MOTION_VIDEO_CHROME`), скачивает `setup.py`.
- Запуск: только `scripts/hf.py`. Нужен установленный `bwrap`; отсутствие
  изоляции — ошибка, не повод незаметно перейти на прямой CLI.
- Wrapper допускает --version/--help, lint/check/snapshot/timeline/render/probe.
  render: 1–6 воркеров (по умолчанию 1; `mv.py` ставит 3, замер в cache-and-edits.md),
  `--quality draft|standard|delivery` (по умолчанию delivery; `mv.py` для новых проектов ставит
  standard + `--video-bitrate 14M`), кодирование во время захвата (`HF_DE_PARALLEL_STREAM=true`), без hardware GPU, strict и без
  best-effort, отказ перезаписывать существующий выход. Таймаут 1800 сек; для длинного ролика
  `hf.py --timeout 7200 /ABS/VIDEO ...`.
- probe: `node /skill/probe.mjs` внутри той же песочницы (скрипты скилла смонтированы только
  для чтения в `/skill`), puppeteer-core из runtime, пишет отпечатки кадров в папку ролика.

Sandbox имеет собственные PID/network namespaces и временный HOME с тем же
именем пути, без содержимого настоящего home. Mounts: system binaries/libs,
Chrome и runtime read-only, одна папка видео read-write. Внешние соединения
блокируются; внутренний localhost нужен для compiler/capture. Обычный Chrome
запускается upstream с no-sandbox внутри этой внешней изоляции.

Переменные wrapper: HYPERFRAMES_NO_TELEMETRY=1, DO_NOT_TRACK=1,
HYPERFRAMES_NO_UPDATE_CHECK=1, HYPERFRAMES_NO_AUTO_INSTALL=1,
HYPERFRAMES_SKIP_SKILLS=1; browser/ffmpeg/ffprobe paths заданы явно.
У snapshot принудительно `--describe false`, ключи провайдеров не передаются.
Разрешённые чтение/запись ограничены mount-ами, не только обещанием CLI.

## Происхождение и ограничение проверки

Официальный [repo](https://github.com/heygen-com/hyperframes), tag v0.8.84,
commit `52f849e2b457435c23c551fd72deeb367593b02a`; Apache-2.0.
Tarball integrity и npm registry signatures проверены. У GSAP собственная
Standard No Charge license, не MIT/Apache; notices сохраняются рядом с копией.

`npm audit` lock дал 0 advisories на 2026-09-28, но это не охватывает весь
код, уже встроенный upstream в JS bundle. В bundle найден fast-uri@3.1.2
с известными High SSRF/normalization advisories; использующий его Ajv путь
статической проверки registry не делает loadSchema/compileAsync. Мы не
включаем registry/cloud/server publication и закрываем наружную сеть.
Это ограниченный проверенный локальный workflow, не утверждение «весь
upstream безопасен/уязвимостей нет».

Не используй upstream init: он устанавливает глобальные skills (даже с
`--skip-skills`), может делать ASR setup и пишет чужие AGENTS. CLI умеет
читать .env CWD, snapshot — обращаться к Gemini, update — менять runtime.
Наш scaffold/wrapper исключают эти действия. Скрипты/инструкции референсов
не становятся доверенными только потому, что они лежат на GitHub.

## Библиотека приёмов upstream

`references/upstream/` — копия `skills/` официального репозитория на том же теге (Apache-2.0, лицензия и NOTICE
внутри папки), только для чтения. Как пользоваться: [upstream-library.md](upstream-library.md).
Последний релиз на 30.09.2026 — v0.8.97; обновление runtime только по процедуре ниже.

## Восстановление и обновление

При отсутствующем node_modules восстанавливай ровно lockfile из этой среды:

```bash
cd ~/.local/share/motion-video/runtime     # или ваш MOTION_VIDEO_RUNTIME
npm ci --ignore-scripts --no-fund --no-audit --userconfig /dev/null
```

Это действие с сетью выполняется вне render sandbox только для ремонта
runtime. Сам рендер ничего не устанавливает. Для новой версии сначала
проверь publisher/source/release и diff зависимостей/side effects,
включая bundled зависимости, затем обнови
отдельную тестовую среду и повтори три формата плюс trim/audio/negative tests.
Не заменяй lock через npm audit fix или @latest посреди работы над роликом.
Новая версия Chrome/Node тоже требует render test; путь wrapper меняется
явно после проверки, не автоматическим сканированием чужих профилей.

Для проверки среды после обновления:

```bash
PY=<motion-video>/.venv/bin/python; S=<motion-video>/scripts
"$PY" "$S/test_sandbox.py"
"$PY" "$S/test_edit.py" /ABS/NEW-EDIT-TEST
"$PY" "$S/smoke_test.py" --out /ABS/NEW-FORMAT-TEST
```

Первый тест использует безобидные canaries; второй — FFmpeg тоны/цветные кадры,
NumPy/Pillow, включая отрицательный missing-media случай; третий — три полных
12-секундных Full HD рендера и QA. Не пересоздавай результаты в прежней папке.

## Если bubblewrap не запускается

Проверка: `bwrap --unshare-all --ro-bind / / true && echo ok`. Ошибка вида `setting up uid map: Permission denied`
значит, что система ограничивает user namespaces (Ubuntu 23.10+ через AppArmor). Варианты по порядку предпочтения:

1. Включить готовый профиль, который разрешает userns только самому bwrap (Ubuntu 24.04 поставляет его в пакете apparmor):
   `sudo aa-enforce /etc/apparmor.d/bwrap-userns-restrict`.
2. Если профиля нет — создать `/etc/apparmor.d/bwrap` с содержимым
   `abi <abi/4.0>, include <tunables/global> profile bwrap /usr/bin/bwrap flags=(unconfined) { userns, }`
   и выполнить `sudo apparmor_parser -r /etc/apparmor.d/bwrap`.
3. В контейнере (Docker и т.п.) user namespaces часто запрещены целиком: рендерить на хосте или в VM.

Обходить песочницу (запускать HyperFrames напрямую) скилл не будет: `hf.py` откажется — это сделано намеренно.
