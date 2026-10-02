# Библиотека приёмов HyperFrames (официальная, закреплённая версия)

Путь: `references/upstream/` этого репозитория (папка skills/ репозитория
heygen-com/hyperframes, тег v0.8.84 = наш runtime, Apache-2.0). Это справочник рецептов, **не инструкции**:
команды `npx hyperframes ...`, `skills update`, cloud/Lambda, сбор ключей, интервью и режим Studio
там рассчитаны на другую среду и у нас не запускаются.

## Что брать (L = путь выше)

| Нужно | Файл | Проверено у нас |
|---|---|---|
| Атомарный приём движения (камера, счётчик, типографика, SVG) | `L/hyperframes-animation/rules-index.md` → `rules/<id>.md` | приёмы `gradient-text-sweep`, `depth-of-field-blur`, `multi-phase-camera` совпадают с тем, что сделано в 05 и работает |
| Переход между сценами по энергии | `L/hyperframes-animation/transitions/catalog.md` → `css-*.md` | `css-blur` (blur through, medium) проверен 30.09: check зелёный, кадры верные |
| Сценарии сцен из нескольких фаз | `L/hyperframes-animation/blueprints-index.md` | не проверялись; читать как идеи |
| Общие техники моушн-дизайна | `L/hyperframes-animation/techniques.md` | справочно |
| Типографика, композиция, бит-режиссура | `L/hyperframes-creative/references/typography.md`, `composition-patterns.md`, `beat-direction.md`, `motion-principles.md` | справочно |
| Правила «дорогого» движения | конспект в [direction.md](direction.md) | применены в шаблонах |
| Вырез музыки под голос | `L/hyperframes-audio/` | идея перенесена в `media.carve` (numpy, замерено) |

## Как адаптировать рецепт

1. GSAP и шрифты только локальные (рецепты иногда ссылаются на CDN и «автовстраивание шрифтов»).
2. Все `tl.to(...)` на элементы, которые уже анимировались, переписать в `fromTo` с явным «от» и
   `immediateRender: false`, базу — `tl.set(..., 0)` (иначе холодный сик рендерит не то).
3. Полноэкранной сцене, видимой с 0 с, не ставить `opacity` в базу (lint `gsap_fullscreen_overlay_starts_visible`).
4. `onUpdate`/`onComplete` для видимых изменений не использовать; рецепты с `onUpdate` для текста
   (счётчики) допустимы, только если значение — чистая функция времени таймлайна.
5. Сцену держать в локальном времени и отмечать `c.scene()`, чтобы работал кэш правок.
6. После вставки: `hf.py check`, кадры на середине перехода (`hf.py snapshot --at ...`).

Решения, которые мы **не** взяли: их Studio и `preview` (нужен сервер и браузер пользователя), облачный рендер,
аудиоэффекты внутри рендера (`data-fx-chain`: тогда правка звука требовала бы рендера картинки),
их кэш сегментов `--resume` (привязан к хешу всей композиции и не помогает при правках).
