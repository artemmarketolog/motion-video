# Пример: бумажная перекладка (9:16, 8 с)

Исходник демо-ролика со страницы репозитория. Лиса сгенерирована скиллом image-gen одним листом на #00FF00
(промпт ниже) и вырезана `scripts/cutout.py cut`. Мир (небо, солнце, холмы, ёлки) — чистый CSS; движение —
GSAP с ease `steps(n)`: 12 рисунков в секунду, как у настоящего стоп-моушена, а камера при этом плавная.
Звук — синтез `sfx.py` (`paper`, `soft_hit`, `hit`, `swipe`, `cloth`) на тех же моментах, что и движение.

Повторить:

```bash
PY=<motion-video>/.venv/bin/python; S=<motion-video>/scripts
$PY $S/new_project.py ~/video-studio/projects/my-paper --template blank --format 9:16
cp -r references/examples/paper-cutout-demo/{build.py,assets} ~/video-studio/projects/my-paper/
cd ~/video-studio/projects/my-paper && $PY build.py && $PY $S/mv.py build $PWD -o output/master-r1.mp4 --note "demo"
```

Промпт листа персонажа (image-gen, 16:9, $0.03):
«Character sheet of a friendly paper-cutout cartoon fox in three poses (front, side, waving), colored paper collage
texture with soft shadows between layers, plain flat #00FF00 background, generous empty space around each pose».

Рендер на сервере 6 ядер: ~5 мин. Подробный разбор метода на 40-секундном ролике: [../../cases/paper-cutout-cartoon.md](../../cases/paper-cutout-cartoon.md).
