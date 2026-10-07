---
name: motion-video
description: "Единый скилл монтажа и моушена (HyperFrames: HTML/CSS/GSAP → MP4) для любого бренда: рекламный монтаж из отснятых клипов и банка кадров с субтитрами (6 стилей), плашками и моушен-перебивками; спокойные анимированные презентации и объясняющие ролики 16:9, моушен-реклама 9:16, истории в переписке и интерфейсе, кинетическая типографика, фото-ролики, мультфильмы-перекладки, премиальные «предметные» ролики. Три уровня проработки (простой, средний, премиум). Быстрые правки без полного перерендера: кэш по отпечаткам кадров, перерисовка только изменённых кусков, правка звука без рендера картинки. Голос через elevenlabs-voice, картинки через image-gen, генерация и анализ музыки, синтез SFX, микс с вырезом частот под голос, проверки и выдача. Триггеры: «смонтируй креатив», «собери видео из клипов», «наложи субтитры», «reels из нарезки», «моушен», «анимированный ролик», «видеопрезентация», «объясняющее видео», «переписка в видео», «кинетическая типографика», «HyperFrames», «поправь ролик». Motion design, video editing, explainer, ads."
---

# Motion video

Один скилл для любого видео, собранного кодом. Движок: HyperFrames в закрытой песочнице (`scripts/hf.py`),
кадр = чистая функция времени. Поверх него свой кэш: правка перерисовывает только изменённые 2-секундные куски.
Рекламный монтаж из отснятых клипов (банк кадров, субтитры, плашки): [footage.md](references/footage.md).
Установка: [README.md](README.md) (`python3 setup.py` ставит всё: venv, движок, браузер, папку студии).

**Три связанных скилла.** Этот репозиторий монтирует, анимирует, сводит звук и рендерит. Озвучка — отдельный скилл
[elevenlabs-voice](https://github.com/artemmarketolog/elevenlabs-voice), картинки — [image-gen](https://github.com/artemmarketolog/image-gen).
Ставьте все три рядом в одну папку скиллов: `voice.py` найдёт озвучку сам (или по `ELEVENLABS_VOICE_SKILL`), картинки
агент делает по `SKILL.md` скилла image-gen. Нужна озвучка или картинка — читай `SKILL.md` соответствующего скилла.
Монтаж, анимация, синтез звуков и рендер работают вовсе без ключей.

Обозначения ниже: `S` — абсолютный путь к `scripts/` этого скилла, `PY` — `<скилл>/.venv/bin/python`,
`<studio>` — папка студии (`MOTION_VIDEO_STUDIO`, по умолчанию `~/video-studio`): `projects/`, `MAKING-OF-INDEX.md`,
`clients.json`, `sources/`, `shots/`, `music/`.
Старый Remotion-ролик при правке переносится на HyperFrames по рецепту `references/upstream/remotion-to-hyperframes/`
([upstream-library.md](references/upstream-library.md)).

## 1. Приём задачи

1. Правка: открой папку ролика: `MAKING-OF.md`, `edits.jsonl`, `review.json`, `BRIEF.md`. Не по памяти.
   Новый ролик «как тот»: указатель `<studio>/MAKING-OF-INDEX.md` и раздел «Как повторить» в `MAKING-OF.md` образца.
2. Тип по [formats.md](references/formats.md), уровень по [levels.md](references/levels.md) (из запроса → из
   брифа серии → по умолчанию средний). В первом ответе: тип, уровень, ожидаемое время. Для правки: тип
   правки и время по таблице [cache-and-edits.md](references/cache-and-edits.md).
3. Уточняй только то, что меняет результат. «Сделай целиком» = без промежуточных вопросов, но с одной обязательной
   остановкой: **лист превью до рендера** (раздел 2a). Премиум и новый визуальный стиль до сборки показываются
   стилевым кадром ([style-frame.md](references/style-frame.md)).
4. Ролик для таргета: сценарий всегда по [copy.md](references/copy.md) (удержание, хук, структура, призыв, живая речь без признаков ИИ).
5. Эталоны задают планку качества, а не стиль: стиль даёт бриф и строка «чем отличается от предыдущих».

## 2. Конвейер нового ролика

```bash
S=/abs/path/to/motion-video/scripts; PY=/abs/path/to/motion-video/.venv/bin/python
V=~/video-studio/projects/acme-01-utro       # папка ролика внутри студии
"$PY" $S/new_project.py $V --template footage-ad|explainer|chat-ui|kinetic-type|photo-editorial|blank --format 9:16 [--merge]
cd $V
# BRIEF.md → сценарий (copy.md) → [стилевой кадр: stillframe.py] → голос и музыка → build.py → проверка → сборка
"$PY" $S/voice.py tts --voice narrator --file work/script.txt --tempo 1.15 --out work/voice.wav   # платно, кэш
"$PY" $S/music.py gen --prompt-file work/music-prompt.txt --seconds 20 --out work/music.raw.mp3  # платно, по одному
"$PY" $S/music.py align work/music.raw.mp3 --drop-at 4.56 --out work/music.wav                  # дроп на нужную секунду
"$PY" $S/cutout.py cut work/gen/heroes.jpg assets/img/heroes                                     # вырезка с #00FF00
"$PY" build.py                                  # index.html, video-spec.json, events.json, mix.json, work/sfx.wav
"$PY" $S/hf.py $V check --json --snapshots
"$PY" $S/preview.py $V --at 0,2.0 --words "хук,Бам,скидка,кнопку" --offset 0.15 --name v1  # лист до рендера → пользователю, ждать «ок»
nohup "$PY" $S/mv.py build $V -o output/master-r1.mp4 --note "первая сборка" > build-r1.log 2>&1 &
"$PY" $S/qa.py $V/output/master-r1.mp4 --spec $V/video-spec.json --out $V/qa/r1
```

- Форматы: `9:16`, `4:5`, `1:1`, `16:9`, `3:4` ([formats.md](references/formats.md), [typography.md](references/typography.md) — безопасные поля и кегли).
- `mv.py build` сам держит очередь: не больше 2 рендеров на машине, третий ждёт слот (ручной `flock` не нужен).
  Рендер — минуты: запускай в фоне и жди по PID (цикл `pgrep -f` по шаблону из своей же команды находит сам себя).
  `new_project.py --merge` дополняет уже созданную папку, ничего не перезаписывая.
- Шаблоны работают во всех пяти форматах; шаблон задаёт скелет, стиль берётся из бренда. `build.py` строится
  на `scripts/mvlib.py` (текст по уровню, камера, якоря сцен, зерно, звуковые события, микс), но кэш работает для любого HTML.
- Сцены в локальном времени (`start + dt`) и `c.scene(start)`: это якоря кэша. Никаких анимаций от общей длины ролика.
- Ремесло: [direction.md](references/direction.md), [typography.md](references/typography.md),
  [captions.md](references/captions.md) (6 стилей субтитров), [inserts.md](references/inserts.md),
  [hyperframes-contract.md](references/hyperframes-contract.md) (контракт HTML/GSAP и грабли lint),
  [upstream-library.md](references/upstream-library.md) (библиотека приёмов, только чтение, `npx` не запускать).
- Картинки для ролика: image-gen с `--project <клиент>/<дата-слаг>`; персонажей и детали генерировать на ровном
  `#00FF00` и вырезать `cutout.py cut` (мягкий край, подавление ореола), буквы для «собранных» слов — `cutout.py glyphs`.
  Персонажи держатся листом героев в `--ref` каждой генерации ([paper-cutout-cartoon](references/cases/paper-cutout-cartoon.md)).

## 2a. Превью до рендера — всегда

Перед первым `mv.py build` каждого нового ролика пользователь видит раскадровку и говорит «ок».

1. После `hf.py check` без ошибок: `preview.py $V --at … --words … --offset <старт голоса> --name vN` →
   `qa/preview-vN.jpg`. 15–25 кадров: кадр 0, конец хука, каждая смена сцены и ключевое событие, дроп, оффер и цена,
   доверие (отзывы/рейтинг), призыв и нажатие кнопки, финал. Повторные слова — `слово#2`, иначе снимок встанет не туда.
2. Сначала смотришь лист сам и правишь всё видимое (обрезанные герои, текст за краем плашки, пустые кадры, хвосты переходов).
3. Пользователю отправляется: лист ссылкой на файл + таблица «с | что в кадре» по каждому снимку (коротко, по делу) +
   что ещё правится до рендера + вопрос «рендер?». Рендер только после его «ок».
4. Повторное превью — перед перерендером после смены сценария или голоса и после крупной переделки сцен. Мелкие правки
   готового мастера (цифра, плашка, звук) — без превью.
5. Пропустить превью можно только если пользователь сказал это про конкретный ролик; на следующие ролики это не переносится.
6. Серия агентами: агент останавливается на превью с отчётом, координатор собирает листы, отправляет пользователю и даёт
   агенту «go» ([series.md](references/series.md)).

## 3. Звук

| Звук | Чем | Правила |
|---|---|---|
| Голос | `voice.py tts` → ядро `elevenlabs-voice` (Eleven v4; `--model eleven_v3` только запасная) | [voice.md](references/voice.md); темп `--tempo`, у v4 нет speed/style |
| Музыка | `music.py gen` (ElevenLabs Music, строго по одному), `analyze`, `split`, `align` | [music-and-beat.md](references/music-and-beat.md) |
| SFX | `sfx.py` (синтез, бесплатно; вариативность по умолчанию) или синтез из физики в `build.py` | [sound-design.md](references/sound-design.md) |
| Микс | `mix.json` → `mv.py` (печатает, на сколько dB музыка под голосом) | [mix.md](references/mix.md): единственный источник цифр |

ElevenLabs напрямую мимо скриптов не вызывать: в них кэш, защита от повторной оплаты и реестр голосов.
Свою музыку (купленный трек, сток) можно класть файлом: `music.py analyze` найдёт доли и дроп, `align` подгонит.

## 4. Правки

```bash
"$PY" $S/mv.py plan  $V               # что изменилось, сколько кусков, оценка времени
"$PY" $S/mv.py build $V -o output/master-r2.mp4 --note "что поменяли"
"$PY" $S/mv.py audio $V -o output/master-r3.mp4 --note "музыка тише"   # только звук, секунды
"$PY" $S/mv.py seams $V output/master-r2.mp4                            # кадры ±1 у стыков
"$PY" $S/frames.py output/master-r2.mp4 --at 8.6,9.0 --out qa/r2-edit.jpg       # правленое место одним листом
```

Меняй исходник → `"$PY" build.py` → `mv.py plan`. Грязных кусков больше, чем ждал: сначала найди причину
(глобальный слой, общий таймер). Время типовых правок: [cache-and-edits.md](references/cache-and-edits.md).
Тот же ролик под другой город, онлайн, дату или цену: копия через `scripts/variant.py`, порядок в [variants.md](references/variants.md).
Замена одного слова в готовой озвучке без переозвучки целиком: [voice.md](references/voice.md).

## 5. Проверки и выдача

- Объём по уровню: [quality-checklist.md](references/quality-checklist.md). Всегда: `hf.py check` без ошибок,
  `qa.py` зелёный, контактный лист и правленые места просмотрены глазами, речь мастера `voice.py asr master.mp4`
  (платно, копейки, OpenAI), `audiocheck.py` при изменении звука, честное «на слух не прослушано».
- Мастер не перезаписывается (`master-rN.mp4`). Один мастер годится и для рекламного кабинета, и для облака, и для
  мессенджера: < 100 МБ на 40 с, отдельных копий не делать ([delivery.md](references/delivery.md)).
  Имена для клиента — без пробелов.
- `edits.jsonl` и общий журнал `~/.local/share/motion-video/ledger.jsonl` пишутся сами; `review.json` с SHA256,
  таймкодами, источниками и ограничениями пишет агент. Карта хранения и `mv.py registry` / `mv.py log`:
  [making-of.md](references/making-of.md), «Где что хранится».
- **История ролика обязательна:** `MAKING-OF.md` по [making-of.md](references/making-of.md) и строка в
  `<studio>/MAKING-OF-INDEX.md`; каждая правка добавляет пункт в «История правок». Так любой агент в новой сессии
  за минуты поймёт, как ролик сделан, и поправит его или соберёт похожий.
- Решения по клиенту (что отклонено, что заходит) — в файлы студии/клиента, не в скилл.

## 6. Серии, среда, кейсы

- Серии и параллельные агенты: [series.md](references/series.md) (координатор готовит платное, один агент = одна папка).
  Готовое описание агента-сборщика для Claude Code: `agents/claude/motion-video-maker.md` (скопируйте в `~/.claude/agents/`).
- Среда: только `scripts/hf.py` (bwrap без сети и HOME), никаких upstream `npx hyperframes init/skills/upgrade`;
  версии, восстановление и тесты: [runtime.md](references/runtime.md).
- Разборы: [cases/](references/cases/) — предмет-герой [hero-object-wheel](references/cases/hero-object-wheel.md) и
  [hero-object-keyboard](references/cases/hero-object-keyboard.md), бумажная перекладка
  [paper-cutout-cartoon](references/cases/paper-cutout-cartoon.md), история в переписке [chat-story](references/cases/chat-story.md),
  презентация продукта [presentation-admin-panel](references/cases/presentation-admin-panel.md).
- Банк кадров из съёмки или генерации: [footage-onboarding.md](references/footage-onboarding.md),
  [footage-bank.md](references/footage-bank.md), [footage-shot-prompts.md](references/footage-shot-prompts.md);
  Google Drive-помощники `scripts/footage/` (`setup.py --with-drive`, один раз `google_auth.py`).
- Тесты скилла (без платных вызовов): `smoke_test.py --out /tmp/NEW`, `templates_test.py --out /tmp/NEW`,
  `test_edit.py /tmp/NEW`, `test_sandbox.py`.
