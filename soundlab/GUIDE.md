# Encelada Sound Lab — руководство

Библиотеки: Sonatina Symphonic Orchestra (CC Sampling Plus 1.0, `soundlab/instruments/sso`), MuseScore General SoundFont (MIT), голоса Windows, вокодер WORLD (pyworld).

Полный справочник: рецепты, нотация, ударные, сэмплы, ремиксы, эффекты, экспорт в Minecraft, MCP-инструменты.
Через MCP этот файл читается по разделам: `guide()` — оглавление, `guide("аккорды")` — раздел.

## Быстрый старт

Звук — это **рецепт** (JSON). Движок превращает его в аудио, а библиотека хранит рецепт, звук, картинки, анализ и историю версий.

Минимальный рецепт — мелодия на скрипке:

```json
{"name": "hello_violin", "tempo": 100, "tracks": [
  {"name": "скрипка", "instrument": "violin", "notes": "E5:1 D5 C5 D5 | E5 E5 E5:2 | D5 D5 D5:2 | E5 G5 G5:2"}
]}
```

Порядок работы через MCP:

1. `create_sound(recipe)` — рендер и сохранение. В ответе: `id`, анализ (`analysis.notes` — замечания обычными словами), спектрограмма и волна с отметками секций.
2. Поправить: `edit_sound(id, tracks={"скрипка": {"notes": "..."}})` меняет только указанное. Или `update_sound(id, recipe)` — весь рецепт.
3. Длинная вещь: `preview(sound_id=id, from_beat=32, to_beat=48)` быстро рендерит только кусок.
4. Готово: `export_to_minecraft(id, "ns:event.name")` или `export_file(id, "путь.ogg")`.

Время везде в **долях** (beats). При `tempo: 120` одна доля = 0.5 с, такт 4/4 = 4 доли.

## Рецепт: общая форма

```text
{
  "name": "имя",            — id в библиотеке (латиница, цифры, _)
  "tempo": 120,             — BPM
  "key": "A minor",         — тональность (нужна для ступеней i iv V в аккордах)
  "kind": "music" | "sfx",  — для sfx тишина в конце срезается
  "tags": ["beat"], "description": "...",
  "seed": 1,                — случайность генераторов (разный seed = другая вариация)
  "beats_per_bar": 4,       — долей в такте (для bars)
  "transpose": 0,           — сдвиг всех нот, полутоны
  "channels": 2 | 1,        — 1 = моно
  "sections": {...}, "arrange": "...",   — форма песни (раздел «Секции и аранжировка»)
  "tracks": [ ... ],
  "master": {"effects": [...], "normalize": -1, "fade_out": 2, "length_beats": 64, "trim": true, "tail": 0}
}
```

Три типа дорожек (`type`):

- `notes` (по умолчанию) — ноты, аккорды, ударные на инструменте;
- `sfx` — синтезированный звуковой эффект (крик, ветер, удар…);
- `audio` — готовый звук: ванильный звук Minecraft, свой файл, звук из библиотеки.

Общие поля любой дорожки: `name`, `gain` (0.8), `pan` (−1…1), `effects`, `automation`, `mute`, `solo`.

## Нотация мелодий (notes)

`"notes"` можно писать строкой. Токены через пробел:

| Запись | Что значит |
|---|---|
| `C4` `F#3` `Bb5` `60` | нота (буква, #/b, октава) или MIDI-номер; C4 = 60 = до первой октавы |
| `E` | нота без октавы берёт октаву предыдущей |
| `C4:2` | длительность в долях; `:1/2`, `:3/4`, `:1.5` |
| `C4:q` | буквами: `w`=4 `h`=2 `q`=1 `e`=1/2 `s`=1/4 `t`=1/3; `q.` — с точкой (×1.5) |
| (без `:`) | длительность как у предыдущей ноты |
| `r` `.` `_` | пауза (`r:2`) |
| `-` или `~` | продлить предыдущую ноту/аккорд (`-:2`) |
| `[C4 E G]:2` | аккорд из нот (ноты без октавы идут вверх) |
| `[Am7]:4` | аккорд по названию, в текущей октаве |
| `(C5 D E)x3` | повтор группы; вложенность можно |
| `>` `<` `o5` | октава вверх / вниз / установить |
| `C4!` `C4?` | акцент (+0.15) / тише (−0.25) |
| `C4@0.9` | громкость 0…1 (по умолчанию 0.8) |
| `\|` | тактовая черта, игнорируется (для читаемости) |

Пример: `"A4:1/2 C5 E5 D5 C5:1 A4 . G4:1/2 A4:2.5 | (E5:1/4 D5)x4 C5:2!"`.

Опции дорожки для нотации: `length` (длительность по умолчанию, 1), `velocity` (0.8), `octave` (4), `gate` (0…1 — доля длительности, которую нота звучит; 0.5 = стаккато), `humanize` (1 или `{"time": 0.01, "vel": 0.08}` — живые неровности), `transpose` (полутоны).

Можно и явный список: `"notes": [[начало, длина, "C4", громкость], ...]`. Пятый элемент — опции ноты: `{"pitch": 2, "gain": 0.5}`.

## Аккорды (chords)

`"chords": "Am F C G"` — прогрессия, каждый аккорд по умолчанию на такт (`chord_length`, 4 доли).

- Длительность: `Am:2 F:2 C:4`. `%` — повтор предыдущего аккорда, `r` — пауза.
- Качества: `C` `Cm` `C7` `Cmaj7` `Cm7` `Cm7b5` `Cdim` `Cdim7` `Caug` `Csus2` `Csus4` `C7sus4` `C6` `Cm6` `Cadd9` `C9` `Cmaj9` `Cm9` `C11` `C13` `C5`.
- Бас в аккорде: `G/B`, `C/E`.
- Ступени (нужен `key` у рецепта или дорожки): `i iv V7 VI`, `ii7 V7 Imaj7`, `bVII`, `vii°`. Большая буква — мажор, маленькая — минор.

Как играть (`style`):

| style | звучание |
|---|---|
| `block` | аккорд целиком (по умолчанию) |
| `pulse` | повтор аккорда каждые `pulse` долей (1) — стабы, комп |
| `strum` | «бой» гитары: ноты с задержкой `strum` (0.04 доли) |
| `arp`, `arp_down`, `arp_updown` | арпеджио шагом `arp_step` (0.5) |
| `alberti` | альбертиев бас: 1-5-3-5 |
| `root`, `root_fifth`, `root_octave` | басовая линия из тоник аккордов шагом `pulse` |

Опции: `chord_octave` (3), `bass: true` (добавить тонику октавой ниже), `velocity` (0.7), `gate` (0.95).

Одна прогрессия — три дорожки: аккорды (`style: "pulse"`), бас (`style: "root"`, `chord_octave: 2`), арпеджио (`style: "arp"`, `chord_octave: 5`).

## Ударные: сетки (drums) и наборы (kit)

```json
{"name": "boom_bap", "tempo": 90, "tracks": [
  {"name": "drums", "kit": "synth", "swing": 0.1, "loop": 4, "drums": {
    "kick":  "x......x..x.....",
    "snare": "....x.......x..g",
    "hat":   "x.x.x.x.x.x.x.xo"}}
]}
```

- Одна клетка = `step` долей (0.25 = шестнадцатая). Длина паттерна = клеток × step.
- Символы: `x` удар (0.85), `X` акцент (1.0), `o` тише (0.55), `O` (0.7), `g` призрачная (0.3), `1`…`9` громкость, `r`/`R` ролл ×2, `t` ролл ×3 (трэп-хэты), `.` `-` `_` пауза, пробелы и `|` игнорируются.
- `swing` 0…0.5 — сдвиг чётных клеток (грув). `humanize` — неровности.
- Строка может быть объектом: `"hat": {"p": "x.x.x.x.", "pitch": 3, "gain": 0.6, "step": 0.5}`.

Наборы (`kit`):

| kit | что звучит |
|---|---|
| `synth` | синтезированные: kick kick808 snare clap hat ohat crash ride tom1 tom2 tom3 rim shaker cowbell snap |
| `808` | то же, но kick = длинная 808-бочка, snare = хлопок |
| `gm` | настоящие барабаны General MIDI из SoundFont: kick snare rim clap hat phat ohat tom1…3 floor crash crash2 ride ridebell china splash tamb cowbell shaker cabasa clave woodblock conga bongo triangle… |
| `mc` | нотные блоки Minecraft: kick=bd, snare, hat, cowbell, bell, chime, xylo, bit, pling, bass |
| `{"kick": "mc:entity.generic.explode", ...}` | свой набор: строка → сэмпл / синт-удар / `gm:ride` |

Имя строки может быть сразу ссылкой на сэмпл (`"mc:block.anvil.land": "x..."`), синт-ударом или `gm:<имя>` — в одной сетке можно смешивать.

У синт-ударов есть параметры (`pitch` полутоны, `decay` множитель) — в опциях строки или `"instrument": {"kit": "808", "params": {"decay": 1.5}}`.

## Инструменты

`"instrument"` — строка или объект. Есть четыре «уровня реализма»:

**1. Живые записи (SFZ-сэмплер: рояль Salamander, оркестр Sonatina Symphonic Orchestra)** — настоящие записанные инструменты, по несколько сэмплов на ноту, петли для долгих нот, отпускание. Простые имена (по-английски и по-русски) ведут сюда:

| имя | что звучит |
|---|---|
| `piano` `пианино` `рояль` `grand piano` | **Salamander Grand Piano** — Yamaha C5, 16 слоёв силы удара (старый рояль Sonatina — `sso piano`) |
| `violin` `скрипка` | скрипка соло, долгие ноты; `violin legato`, `violin staccato`, `violin pizzicato`, `violin tremolo` |
| `violins` `скрипки`, `viola` `альт`, `violas`, `cello` `виолончель`, `cellos`, `contrabass` `контрабас` | струнные соло и группы |
| `strings` `струнные` `оркестр`, `strings pizzicato`, `strings staccato` | вся струнная группа |
| `flute` `флейта`, `flute staccato`, `flutes`, `piccolo`, `alto flute`, `oboe` `гобой`, `english horn`, `clarinet` `кларнет`, `bass clarinet`, `bassoon` `фагот` | деревянные духовые |
| `trumpet` `труба`, `trumpets`, `horn` `валторна`, `horns`, `trombone`, `trombones`, `tuba` `туба`, `brass` `духовые` | медь |
| `choir` `хор`, `large choir` `большой хор` | настоящий смешанный хор, тянет гласную «а» |
| `harp` `арфа`, `harpsichord` `клавесин`, `celesta`, `marimba`, `vibraphone`, `glockenspiel`, `xylophone`, `timpani` `литавры` | арфа, клавишные, перкуссия |
| `church organ`, `organ flute`, `organ bass` | орган (регистры) |

Любая другая артикуляция — по словам из имени файла: `"sso:cello solo pizzicato"`, `"sso:horns staccato"`, `"sso:1st violins tremolo"`, `"sso:swell - oboe 8ft"`. Все 298 вариантов — `search_instruments("cello")` или `catalog("real")`. Свои SFZ-библиотеки кладите в `soundlab/instruments/<имя>/` — они найдутся как `<имя>:<файл>`.

Опции: `{"sfz": "…", "release": 0.8, "attack": 0.05}` (длиннее хвост / мягче вступление).

**2. General MIDI из SoundFont MuseScore General** — 128 инструментов, тоже записанные сэмплы, но попроще. Здесь гитары, бас-гитары, саксофоны, синт-звуки, этника: `guitar`/`гитара`, `nylon guitar`, `electric guitar`, `overdrive guitar`, `distortion guitar`/`дисторшн`, `bass guitar`/`бас`, `slap bass`, `synth bass`, `sax`/`саксофон`, `accordion`/`аккордеон`, `harmonica`, `sitar`, `banjo`, `kalimba`, `bagpipe`, `steel drums`, `ocarina`, `music box`, … Чтобы взять GM-версию инструмента, у которого есть живая запись: `"gm:violin"`, `"gm:40"`, `{"gm": "choir"}`.

**3. Синтезаторы** — не живые, синтез; `synth:piano` — это НЕ пианино, а электронный звук (`synth:<имя>` или `{"synth": "pad", "params": {...}}`): `musicbox`, `piano` (мягкое), `epiano`, `bell`, `pad`, `strings`, `choir`, `pluck`, `bass`, `organ`, `saw`, `square`, `triangle`, `sine`. Параметры: `attack`, `release`, `cutoff`, `vibrato`, `dark`, `vowel` (a o u e i).

**4. Сэмплы как инструмент**: нотные блоки `noteblock:harp` `bass` `guitar` `flute` `bell` `chime` `xylophone` `iron_xylophone` `cow_bell` `didgeridoo` `bit` `banjo` `pling`; любой звук — `{"sample": "mc:entity.cat.ambient", "root": "auto"}` (опции `root`, `gate`, `loop`, `attack`, `release`, `start`, `gain`).

**Слои** — одна партия сразу на нескольких инструментах:

```json
{"name": "layer_demo", "tempo": 70, "tracks": [
  {"name": "lead", "instrument": {"layers": ["violin", {"instrument": "choir", "gain": 0.6}, {"instrument": "cello", "transpose": -12, "gain": 0.7}]},
   "notes": "A4:2 C5 E5:4 D5:2 C5 B4:4", "effects": [{"type": "reverb", "size": 0.7, "mix": 0.3}]}
]}
```

**Ударные**: `"drums"`/`"ударные"` (GM-набор) или поле `kit` (см. «Ударные»).

## Нейросети: песни с живым вокалом, пение по нотам, SFX по описанию

Три локальные нейросети (RTX 4090), каждая в своём окружении в `Encelada-Sound-Lab/engines/`. Установка: `python -m soundlab.install neural`. Состояние: `neural_status()`. Все результаты кэшируются (`soundlab/cache/ai`): повторный рендер рецепта не генерирует заново.

| что | модель | лицензия | как вызвать |
|---|---|---|---|
| **Песня целиком с настоящим вокалом** по описанию стиля и тексту (50+ языков, японский тоже) | ACE-Step 1.5 (XL 4B + LM 4B) | MIT | `ai_song(caption, lyrics, …)` |
| **Кавер / перепевка** готового аудио — например, моей аранжировки: структура и мелодия сохраняются, звучит как спродюсированная песня | ACE-Step | MIT | `ai_cover(source, caption, lyrics, strength)` |
| **Переделать кусок** песни (строчку, припев) | ACE-Step | MIT | `ai_repaint(id, start, end, caption, lyrics)` |
| **Певица поёт МОИ ноты** точно по партитуре | SoulX-Singer | Apache 2.0 | инструмент `"певица"` / `{"singer": …}` + `lyrics` |
| **Любой звуковой эффект по описанию** | Woosh (Sony AI) | CC-BY-NC (некоммерч.) | `ai_sfx(prompt)` / `{"sfx": "ai", "params": {"prompt": …}}` |

### ACE-Step: песни «как Suno», локально

```text
ai_song(caption="gentle emotional anime ending theme, j-pop ballad, soft female vocal, piano, acoustic guitar, strings, glockenspiel",
        lyrics="[verse]\nあしたも きっと あえるよね\n…\n[chorus]\n…", language="ja", duration=90, bpm=84, key="D major")
```

- `caption` — по-английски: жанр, настроение, инструменты, голос («ethereal fantasy soundtrack, children's choir chanting in an invented language, celesta, harp, strings» для настроения «Бездны»; «upbeat bouncy vocal chops, playful, plucks, four-on-the-floor» — для «прыгающих голосов»).
- `lyrics` — с тегами секций `[intro] [verse] [chorus] [bridge] [outro]`; `[Instrumental]` или `instrumental=True` — без вокала.
- `language`: `ja`, `en`, `ru`, `zh`, `ko`, … ; `duration` 10–600 с; `bpm`, `key` («D major», «Am»); `seed` — чтобы повторить вариант.
- Первый вызов грузит модели (при установке — скачивает ~20 ГБ), дальше песня на полторы минуты — десятки секунд.
- `ai_cover(source=<id моей аранжировки>, caption=…, lyrics=…, strength=0.5…0.8)` — главный приём: я сочиняю мелодию и аккорды нотами (живые инструменты, певица SoulX), а ACE-Step «переигрывает» это как готовый трек. `strength` ближе к 1 — точнее держится исходника.

### SoulX-Singer: настоящее пение по нотам

Инструмент для дорожки нот — поёт ровно те ноты и длительности, что в рецепте:

| instrument | голос |
|---|---|
| `"голос"`, `"певица"`, `"вокал"`, `{"singer": "en_female"}` | светлый женский (по умолчанию) |
| `{"singer": "zh_female"}` | другой женский тембр |
| `"мужской голос"`, `"певец"`, `{"singer": "zh_male"}` | мужской |
| `"певицы"`, `"хор певиц"`, `"хор голосов"`, `"ангельские голоса"`, `{"singer": …, "takes": 6}` | ансамбль: каждый голос аккорда поётся отдельно, `takes` дублей с разными вариациями |
| `"мужской хор"` | мужской ансамбль |

- `lyrics` — слог на ноту: английские слова (`"hello my friend"`), кана (`"あしたも きっと"`), кириллица (`"ля ля"`), ромадзи с `"lang": "ja"`. `-` в тексте = держать тот же слог на следующей ноте (мелизм).
- Аккорд (`chords` или `[C4 E G]`) раскладывается на голоса сверху вниз — хор поёт гармонию.
- Параметры: `takes`, `seed`, `steps` (32; больше — чище, медленнее), `cfg` (3.0).
- Скорость: загрузка модели ~10 с + несколько секунд на партию; всё кэшируется.
- Вокал сухой — добавляйте `reverb`, для ангельского звучания `shimmer`.

```json
{"name": "example_neural_singer", "tempo": 84, "key": "D major", "tracks": [
  {"name": "vocal", "instrument": "певица", "lyrics": "あしたも きっと あえるよね そらの むこうで まってるよ",
   "notes": "F#4:1/2 A4 B4 A4 F#4:1 E4 | D4:1/2 E4 F#4 A4 B4:2 | A4:1/2 B4 D5 C#5 B4:1 A4 | F#4:3 r:1",
   "effects": [{"type": "reverb", "size": 0.6, "mix": 0.22}]},
  {"name": "piano", "instrument": "piano", "chords": "D Bm G A", "style": "arp", "arp_step": 0.5, "chord_octave": 3, "gain": 0.55},
  {"name": "choir", "instrument": "хор певиц", "lyrics": "a", "chords": "D Bm G A", "chord_octave": 4, "gain": 0.35,
   "effects": [{"type": "shimmer", "size": 1.0, "mix": 0.4}]}
 ]}
```

### Woosh: SFX по описанию

```json
{"name": "example_ai_sfx", "kind": "sfx", "tempo": 60, "tracks": [
  {"type": "sfx", "sfx": "ai", "params": {"prompt": "long sharp claws slowly scraping along a rough stone wall", "duration": 5, "seed": 3}},
  {"type": "sfx", "sfx": "ai", "at": 2, "params": {"prompt": "small creatures giggling quietly in the dark", "duration": 5, "seed": 1},
   "effects": [{"type": "reverb", "size": 0.9, "mix": 0.4}], "gain": 0.8}
 ]}
```

- Описание — по-английски, конкретно: что звучит, из чего, где (коридор, лес, вентиляция), дистанция. Примеры: «monstrous distorted scream echoing across a forest», «something with many legs crawling inside a metal vent», «a distant distorted voice calling for help, unnatural».
- `duration` до 20 с; `seed` — вариант; `model: "quality"` — медленнее, иногда лучше. `ai_sfx(prompt, variants=4)` делает 4 варианта подряд — выбрать лучший.
- Лицензия весов CC-BY-NC: для своего/хобби-сервера нормально, продавать нельзя. Для коммерции — синтез-генераторы Sound Lab (`scrape`, `crawl`, `siren` …) или ElevenLabs.

## Фразы голосом (речь) и старый TTS-голос

Пение делает нейросеть (раздел выше). Синтез речи Windows (Ирина — русский, Zira — английский) остался для **речи и хоррора**: фразы, шёпот, мимики, хихиканье.

- Источник `tts:`: `"tts:Ты зашёл слишком далеко, путник."`, `"tts:en:Welcome, traveller"`. MCP: `speak(text, effects=…, semitones=-7)`. Монстр — `semitones: -7` + `distortion`; призрак — `reverb`; рация — `bandpass` + `static`.
- Старый поющий TTS-голос (роботизированный) доступен как `"tts voice"` / `"tts choir"` — только если нужен именно синтетический эффект.

## Аниме-песни, японский вокал, вокальные чопы

Готовые песни целиком: `compose_song(style)` — `abyss` (эфирная сказка: челеста, арфа, струнные, детский голос на выдуманном языке, ангельский хор в припеве), `takopi` (нежная аниме-песня: гитара, рояль, глокеншпиль, мягкие барабаны, японский вокал), `jumping` (бодрая: прыгающие вокальные чопы, плаки, бочка в пол), `angelic` (гимн). Форма: intro / verse / chorus / verse / chorus / outro. Мелодия генерируется, поэтому для настоящей песни лучше `render=False` → переписать `parts` мелодии и `lyrics` → `create_sound`.

**Японский текст** — пишите каной или ромадзи, каждая мора = одна нота:

- `"lyrics": "あしたも きっと あえるよね"` → а си та мо ки то а э ру ё нэ (っ пропускается, ー тянет гласную);
- ромадзи: `"lyrics": "a shi ta mo", "lang": "ja"`;
- поёт нейро-певица SoulX-Singer (кана → фонемы); для полностью «живой» японской песни с продакшеном — `ai_song(…, language="ja")` или `ai_cover` своей аранжировки.

Пресеты дорожек (`"preset": "…"` — инструмент + эффекты, свои поля дорожки важнее):

| preset | что это |
|---|---|
| `anime vocal` / `аниме вокал` | нейро-певица + яркий EQ + реверб, `lang: ja` |
| `jumping voices` / `вокальные чопы` | нейро-певица короткими нотами «а-я-о-хэй», пинг-понг эхо |
| `abyss chant` | нейро-певица (2 дубля), выдуманные слоги, большой реверб |
| `angel choir` / `ангельский хор` | ансамбль нейро-певиц (6 дублей на голос аккорда) + живой большой хор + шиммер |

Голоса (instrument) — см. таблицу SoulX-Singer выше; все поют нейросетью.

```json
{"name": "example_anime_song", "tempo": 88, "key": "D major",
 "sections": {"verse": {"bars": 4}, "chorus": {"bars": 4}}, "arrange": "verse chorus",
 "tracks": [
  {"name": "vocal", "preset": "anime vocal", "lyrics": "あしたも きっと あえるよね そらの むこうで まってるよ",
   "parts": {"verse": "F#4:1/2 A4 B4 A4 F#4:1 E4 | D4:1/2 E4 F#4 A4 B4:2 | A4:1/2 B4 D5 C#5 B4:1 A4 | F#4:3 r:1",
             "chorus": "B4:1 A4:1/2 F#4 A4:1 D5 | C#5:1/2 B4 A4:1 F#4:2 | G4:1 A4 B4 D5 | C#5:3 r:1"}},
  {"name": "guitar", "instrument": "gm:nylon guitar", "style": "strum", "chord_octave": 3, "gain": 0.5,
   "parts": {"verse": {"chords": "I vi IV V"}, "chorus": {"chords": "IV V iii vi"}}},
  {"name": "piano", "instrument": "piano", "style": "arp", "arp_step": 0.5, "chord_octave": 4, "gain": 0.4,
   "parts": {"chorus": {"chords": "IV V iii vi"}}},
  {"name": "drums", "kit": "gm", "gain": 0.4, "parts": {"chorus": {"drums": {"kick": "x.....x.x.......", "snare": "....x.......x...", "hat": "x.x.x.x.x.x.x.x."}}}}
 ]}
```

## Ангельские хоры

Самое простое — пресет `angel choir` на аккордах:

```json
{"name": "example_angel_choir", "tempo": 60, "key": "C major", "tracks": [
  {"name": "angels", "preset": "angel choir", "chords": "I vi IV V I", "chord_octave": 4},
  {"name": "harp", "instrument": "harp", "chords": "I vi IV V I", "style": "arp_updown", "arp_step": 0.5, "gain": 0.4},
  {"name": "organ", "instrument": "church organ", "chords": "I vi IV V I", "chord_octave": 3, "gain": 0.25}
 ]}
```

Как устроен и как крутить:

- `angel voices` (10 голосов, светлые форманты, придыхание) + живой `large choir` + эффект `shimmer` (реверб, хвост которого уходит на октаву вверх — «сияние»);
- слова вместо «а»: `"lyrics": "а-ле-лу-я"` или латынь `"san-ctus san-ctus"`;
- детский хор поверх: `"instrument": "детский хор"` с мелодией; мужские голоса октавой ниже: `смешанный хор`;
- больше «неба»: `{"type": "shimmer", "size": 1.4, "mix": 0.6, "amount": 0.8}`; мягче верх — `{"type": "lowpass", "cutoff": 7000}`;
- для «жуткого ангела» (как в хорроре): `"formant": 0.85`, аккорды с `dim`/`m7b5`, `shimmer` с `"semitones": 7`.

## Хоррор-звуки: скрежет, ползание, Сиреноголовый, хихиканье, мимик

Генераторы (`"type": "sfx"`):

| sfx | что это | главное в params |
|---|---|---|
| `scrape` | когти/ногти/металл скребут по стене | `material`: stone, wood, metal, nails, glass; `claws` (сколько когтей), `pressure`, `speed` (движений в секунду), `squeal` (визг) |
| `crawl` | кто-то ползёт | `limbs`, `speed`, `weight` (тяжесть), `claws`, `drag` (тащит тело), `wet` (мясо), `bones` (хруст суставов), `distance` |
| `siren` | воздушная сирена (основа Сиреноголового) | `pitch`, `rise`, `fall`, `chord` (двутональная, 0…1), `drive` |
| `giggle` | хихиканье существ в темноте (живой голос) | `creatures`, `pitch`, `small` (маленькие/детские), `breath` (шёпотом), `density` |
| `voice_scream` | крик живым голосом | `pitch`, `rough` (хрип), `vowel`, `formant` |
| `mimic` | мимик зовёт на помощь: фраза повторяется, каждый раз «не так» (заикания, растяжки, чужая интонация, реверс) | `text`, `count`, `wrongness` 0…1, `pitch`, `formant`, `pause` |
| `scream`, `screech`, `growl`, `whisper`, `breathing`, `heartbeat`, `creak`, `drone`, … | прежние синтезированные | см. «Звуковые эффекты» |

Эффект `formant` меняет «размер» голоса: `{"type": "formant", "shift": 0.7, "pitch_semitones": -8}` — огромная тварь; `shift: 1.4` — маленькое существо; `monotone: 110` — мёртвый ровный голос.

Сиреноголовый (сирена + искажённый голос из «мегафона» + эхо над лесом):

```json
{"name": "example_siren_head", "kind": "sfx", "tempo": 60, "tracks": [
  {"name": "siren", "type": "sfx", "sfx": "siren", "params": {"duration": 9, "pitch": 430, "chord": 0.3, "drive": 0.7}, "gain": 0.8},
  {"name": "voice", "type": "sfx", "sfx": "mimic", "at": 4.5,
   "params": {"text": "Помогите. Найдите меня.", "count": 2, "wrongness": 0.9, "pitch": 0.8, "pause": 0.6},
   "effects": [{"type": "bandpass", "cutoff": 1400, "q": 1.2}, {"type": "distortion", "drive": 6}], "gain": 0.7},
  {"name": "static", "type": "sfx", "sfx": "static", "params": {"duration": 12, "crackle": 0.8}, "at": 4, "gain": 0.25},
  {"name": "rumble", "type": "sfx", "sfx": "rumble", "params": {"duration": 12}, "gain": 0.4}
 ], "master": {"effects": [{"type": "delay", "time": 0.45, "feedback": 0.35, "mix": 0.3}, {"type": "reverb", "size": 1.0, "mix": 0.3}]}}
```

Хихиканье в темноте + шёпот + гул:

```json
{"name": "example_dark_giggles", "kind": "sfx", "tempo": 60, "tracks": [
  {"name": "giggles", "type": "sfx", "sfx": "giggle", "params": {"duration": 9, "creatures": 4, "breath": 0.5},
   "effects": [{"type": "reverb", "size": 1.0, "mix": 0.45}, {"type": "autopan", "rate": 0.2}], "gain": 0.8},
  {"name": "whisper", "type": "sfx", "sfx": "whisper", "params": {"duration": 9}, "gain": 0.25, "pan": -0.5},
  {"name": "drone", "type": "sfx", "sfx": "drone", "params": {"duration": 10, "pitch": 41}, "gain": 0.5}
 ]}
```

Когти по каменной стене и что-то ползёт по вентиляции:

```json
{"name": "example_crawler", "kind": "sfx", "tempo": 60, "tracks": [
  {"name": "claws", "type": "sfx", "sfx": "scrape", "params": {"duration": 5, "material": "stone", "claws": 4, "pressure": 0.9}, "gain": 0.8},
  {"name": "vent", "type": "sfx", "sfx": "crawl", "at": 3, "params": {"duration": 6, "limbs": 6, "bones": 0.5, "wet": 0.2},
   "effects": [{"type": "bandpass", "cutoff": 1200, "q": 0.7}, {"type": "reverb", "size": 0.4, "mix": 0.3}], "gain": 0.9},
  {"name": "scrape metal", "type": "sfx", "sfx": "scrape", "at": 5, "params": {"duration": 3, "material": "metal", "squeal": 0.5}, "gain": 0.5}
 ], "master": {"effects": [{"type": "reverb", "size": 0.7, "mix": 0.25}]}}
```

Мимик в лесу (далеко, между деревьями):

```json
{"name": "example_mimic", "kind": "sfx", "tempo": 60, "tracks": [
  {"name": "mimic", "type": "sfx", "sfx": "mimic", "params": {"text": "Эй! Помогите мне! Я здесь", "count": 4, "wrongness": 0.75},
   "effects": [{"type": "lowpass", "cutoff": 3500}, {"type": "reverb", "size": 1.0, "mix": 0.4}], "gain": 0.9},
  {"name": "wind", "type": "sfx", "sfx": "wind", "params": {"duration": 20, "howl": 0.3}, "gain": 0.3}
 ]}
```

Для Minecraft: такие звуки экспортируйте моно, с `variants: 3`, чтобы каждый раз звучало чуть по-другому; длинные (сирена, мимик) — `stream: true`.

## Сэмплы: звуки Minecraft, свои файлы, библиотека

Ссылки на звуки (`ref`) работают везде: как `source` аудио-дорожки, как инструмент-сэмплер, как строка сетки ударных.

| ref | что это |
|---|---|
| `mc:entity.zombie.ambient` | событие звука Minecraft (первый вариант); `#2` — третий вариант |
| `mc:mob/zombie/say1` | конкретный файл из `assets/minecraft/sounds` |
| `mc:note/harp`, `mc:note_block/harp` | звуки нотных блоков |
| `samples:drums/kick.wav` | свой файл в `soundlab/samples/` (wav/ogg/flac/mp3) |
| `library:<id>` | готовый звук из библиотеки (его отрендеренный результат) |
| `tts:Текст фразы`, `tts:en:Text` | фраза голосом (раздел «Пение и фразы») |
| `C:/путь/файл.wav` | любой файл |

Звуки Minecraft берутся из установленной игры (`%APPDATA%/.minecraft`, или переменная `MINECRAFT_DIR`) — это 4000+ ванильных звуков. Поиск: `search_samples("zombie hurt")`, `search_samples("explode", source="mc")`. Высота и длина сэмпла: `sample_info("mc:note/flute")`.

Свою «базу звуков» можно просто положить папками в `soundlab/samples/` — поиск её увидит.

Ванильные звуки принадлежат Mojang: их можно менять и класть в ресурспак своего сервера, но не продавать как свои.

## Секции и аранжировка (sections, parts, arrange)

Форма песни задаётся один раз, а каждая дорожка говорит, что играть в каждой секции.

```json
{"name": "song_form", "tempo": 96, "key": "A minor",
 "sections": {"intro": {"bars": 2}, "verse": {"bars": 4}, "chorus": {"bars": 4}},
 "arrange": "intro verse chorus verse chorus*2",
 "tracks": [
  {"name": "drums", "kit": "gm", "parts": {
     "verse":  {"drums": {"kick": "x.......x.......", "snare": "....x.......x...", "hat": "x.x.x.x.x.x.x.x."}},
     "chorus": {"drums": {"kick": "x...x...x...x...", "snare": "....x.......x...", "ohat": "x.x.x.x.x.x.x.x."}}}},
  {"name": "piano", "instrument": "piano", "chords": "i VI III VII", "style": "pulse", "loop": true},
  {"name": "bass", "instrument": "bass guitar", "chords": "i VI III VII", "style": "root", "chord_octave": 2,
   "sections": "verse chorus"},
  {"name": "lead", "instrument": "flute", "parts": {"chorus": "A5:1 C6 E6 D6 | C6:2 A5:2 | G5:1 A5 C6 B5 | A5:4"}}
 ]}
```

- `sections`: `{"имя": {"bars": 4}}` или `{"beats": 16}`.
- `arrange`: строка или список имён; `chorus*2` — два раза подряд.
- `parts`: `{"секция": содержимое}`. Содержимое — строка мелодии, список нот или объект с `notes`/`chords`/`drums`/`melody` и опциями. Короткий паттерн повторяется до конца секции (`"loop": false` — не повторять). `"=verse"` — взять содержимое другой секции.
- `sections: "verse chorus"` у дорожки без `parts` — её содержимое звучит только в этих секциях (и повторяется). Для `sfx`/`audio` — звук запускается в начале каждой такой секции (плюс `at`).
- `loop: true` — повторять содержимое на всю длину песни; `loop: 4` — 4 раза.

Секции отмечены на картинке волны и возвращаются в ответе (`sections: ["intro@0", "verse@8", …]`), `preview` по долям удобно делать по ним.

## Аудио-дорожки: обработка и ремикс

```text
{"type": "audio", "source": "<ref>", "at": 0,
 "trim": [0.2, 1.5],      — вырезать секунды
 "rate": 1.5,             — скорость как у плёнки (выше и короче)
 "semitones": -5,         — высота без изменения длины
 "fit_beats": 8,          — растянуть/сжать ровно в 8 долей (подогнать луп под темп)
 "reverse": true,
 "slices": 16, "sequence": "0 1 0 1 4 5 6r 7:2 . 8 8", "step": 0.5,   — нарезка и перестановка
 "loop": 4}
```

Ремикс нарезкой: звук режется на `slices` равных частей, `sequence` — порядок: номер среза, `r` — задом наперёд, `:2` — занять 2 шага, `.` — пауза. `step` — длина шага в долях (по умолчанию = длина среза).

Типичный ремикс:

1. `import_midi("song.mid")` → поменять инструменты (`edit_sound`) и темп → свои ударные сеткой;
2. или взять готовый звук: `fit_beats` под новый темп + `slices/sequence` + свои ударные поверх;
3. `transform_audio(source, ...)` делает то же одной командой.

## Звуковые эффекты (SFX-генераторы)

Дорожка `{"type": "sfx", "sfx": "<имя>", "params": {...}, "at": 0, "repeat": {"every": 4, "count": 3}, "duration_beats": 8}`.

| sfx | что это | основные params |
|---|---|---|
| `scream` | человеческий крик с хрипом | duration, pitch, glide, rough, vowel |
| `screech` | скрежет металла | duration, grit, squeal |
| `growl` | рык монстра | duration, pitch, rattle |
| `whisper` | неразборчивый шёпот | duration, rate |
| `heartbeat` | сердцебиение | bpm, beats |
| `drone` | тёмный гул | duration, pitch, breath, brightness |
| `wind` | ветер | duration, howl |
| `riser` | нарастание | duration, from_hz, to_hz |
| `impact` | удар/бум | duration, pitch |
| `glitch` | цифровой глитч | duration, density, crush |
| `static` | радиопомехи | duration, crackle |
| `breathing` | дыхание | duration, rate |
| `creak` | скрип двери | duration, rate, pitch |
| `chime` | искристые колокольчики | duration, notes, root |
| `bubbles` | пузырьки | duration, count |
| `ufo` | гул НЛО | duration, pitch, warble |
| `souls` | голоса улетают вверх | duration, voices, rise |
| `rumble` | подземный гул | duration |
| `sting` | скример-аккорд | duration, root |

Значения по умолчанию: `catalog("sfx")`. Хорошие SFX обычно слоёные: генератор + ванильный звук + ноты + эффекты в одном рецепте (пример в «Примеры»).

## Эффекты обработки

`"effects": [{"type": "reverb", "size": 0.7, "mix": 0.3}, ...]` — цепочка по порядку, у дорожки или у `master`.

| type | параметры | для чего |
|---|---|---|
| `reverb` | size, mix, damping, predelay | зал, пещера |
| `delay` | time (с или "1/4", "3/16"), feedback, mix, pingpong | эхо в темп |
| `distortion` | drive, mix | перегруз |
| `bitcrush` | bits, downsample | ретро, 8-бит |
| `filter` | kind (lowpass/highpass/bandpass), cutoff, q, order | фильтр |
| `lowpass` `highpass` `bandpass` | cutoff, q | короткие формы фильтра |
| `eq` | low, mid, high (дБ), low_freq, mid_freq, mid_q, high_freq | эквалайзер |
| `pitch` | semitones | высота как у плёнки (меняет длину) |
| `pitch_shift` | semitones, grain | высота без изменения длины |
| `stretch` | factor, grain | растяжение во времени |
| `reverse` | — | задом наперёд |
| `tremolo` | rate, depth | дрожание громкости |
| `vibrato` | rate, depth | дрожание высоты |
| `chorus` | delay, depth, rate | «плавание», ширина |
| `ringmod` | freq, mix | металл, робот |
| `stutter` | slice, amount | заикание в ритм |
| `sidechain` | every (доли), depth, release, offset | «качание» под бочку (хаус, трэп) |
| `autopan` | rate или beats, depth | панорама гуляет |
| `lofi` | wow, cutoff, noise_db, crackle, bits | плёнка, шипение, треск |
| `compress` | threshold, ratio, makeup | компрессор |
| `limiter` | threshold, release | лимитер |
| `shimmer` | size, mix, amount, semitones | реверб с октавой вверх — «ангельский» ореол |
| `formant` | shift, pitch_semitones, monotone, mix | размер/тембр голоса (монстр, существо) |
| `width` | width | ширина стерео |
| `gain` | db | громкость |
| `fade` | in, out (с) | появление/затухание |

## Автоматизация

`"automation": {"gain": [[0, 0], [8, 1]], "lowpass": [[16, 18000], [24, 300]], "detune": [[24, 0], [32, -100]], "pan": [[0, -1], [16, 1]]}` — кривые по долям, линейно между точками.

- `gain` — множитель громкости дорожки;
- `lowpass` — частота среза фильтра, Гц;
- `detune` — расстройка нот в центах (−100 = на полтона ниже), для мелодии, которая «плывёт»;
- `pan` — панорама.

## Мастер

`"master": {"effects": [...], "normalize": -1, "fade_out": 2, "length_beats": 64, "tail": 1, "trim": true}`

- `normalize` — пик итога в дБ (−1 по умолчанию);
- `fade_out` — затухание в конце, с;
- `length_beats` (+ `tail` с) — обрезать по долям;
- `trim` — срезать тишину в конце (включено по умолчанию).

## Анализ: как «слушать» результат

Каждый рендер анализируется, результат лежит в `library/<id>/analysis.json` и приходит в ответ MCP:

- `peak_db`, `rms_db`, `crest_db` (динамика), `clipped_percent`;
- `loudness_timeline_db` + `timeline_step_s` — громкость по времени (видно вступление, провалы, кульминацию);
- `bands_percent` — доля энергии: sub (<60 Гц), bass, low_mid, high_mid, air (>6 кГц);
- `brightness_hz` — «яркость» (центроид спектра);
- `stereo_width`, `lr_correlation`;
- `onsets_per_s`, `tempo_bpm_estimate`, `key_estimate`;
- `pitch` — нота короткого звука (для настройки сэмплера);
- `notes` — замечания словами: клиппинг, тишина, перебор низов, слишком тихо и т.п.

Ориентиры: музыка для игры — rms около −14…−18 дБ, crest 8…18 дБ. SFX — короткая атака, без тишины в начале. Для звуков «в мире» проверяйте моно (`lr_correlation` не должен быть низким).

`analyze_sound(id)` — полный анализ, `sample_info(ref)` — анализ любого сэмпла без сохранения.

## Minecraft: экспорт в ресурспак и плагины

`export_to_minecraft(id, "ns:event.name", pack_dir="...", mono=True, stream=False, variants=1, pitch_spread=0, volume=1, pitch=1, attenuation=0, subtitle="")`

- Кладёт `.ogg` в `<pack>/assets/<ns>/sounds/soundlab/`, дописывает `assets/<ns>/sounds.json`, создаёт `pack.mcmeta` (если нет; `pack_format` 64 = 1.21.7–1.21.8).
- `mono=True` — для звуков с позицией в мире (иначе Minecraft не приглушает звук с расстоянием). Музыку можно в стерео (`mono=False`).
- `stream=True` — для длинной музыки (не грузится целиком в память).
- `variants=3, pitch_spread=1` — три версии (разный seed, ±1 полутон): игра выбирает случайную, повторяющийся звук не звучит роботом.
- `attenuation` — на каком расстоянии (блоков) звук затихает (по умолчанию в игре 16).
- Без `pack_dir` всё идёт в `soundlab/exports/` — это готовый ресурспак.

В ответе есть команда и строка Java:

```text
/playsound drugs:halluc.ufo master @s
player.playSound(player.getLocation(), "drugs:halluc.ufo", SoundCategory.MASTER, 1f, 1f);
```

Для Paper/Bukkit-плагина: ресурспак отдаётся игрокам (server.properties `resource-pack` или `player.setResourcePack(...)`), звук играется по имени события. Для Fabric/Forge-мода: `.ogg` и `sounds.json` кладутся в `src/main/resources/assets/<modid>/`, событие регистрируется `SoundEvent.of(Identifier.of(modid, "event.name"))`.

Просто файл: `export_file(id, "C:/.../resources/sounds/x.ogg", mono=True)`.

## MIDI: импорт и экспорт

- `import_midi("C:/Users/.../song.mid")` — каждая MIDI-дорожка/канал становится дорожкой с GM-инструментом из файла, канал 10 — ударные. Дальше меняйте инструменты, темп, добавляйте свои ударные и эффекты — это и есть ремикс/кавер.
- `export_midi(id, "out.mid")` — ноты рецепта (включая нотацию, аккорды и сетки) в MIDI: открыть в DAW или в конвертере для нотных блоков (Note Block Studio).

## ElevenLabs (необязательно)

Если нужен звук, который трудно синтезировать (реалистичная речь толпы, конкретный механизм), можно сгенерировать его ElevenLabs и дальше обрабатывать как любой сэмпл.

- Ключ: переменная `ELEVENLABS_API_KEY` или файл `soundlab/config.json` `{"elevenlabs_api_key": "..."}` (он в .gitignore).
- `elevenlabs_sfx("heavy stone door slowly opening, dungeon echo", duration=4)` — звуковой эффект (0.5–30 с; `loop=True` — бесшовный).
- `elevenlabs_music("dark ambient cave music, slow", seconds=60)` — музыка.
- Результат ложится в библиотеку как `audio`-рецепт: `transform_audio`, нарезка, слои — всё как обычно.

Без ключа всё остальное работает офлайн.

## MCP-инструменты

| инструмент | что делает |
|---|---|
| `guide(topic)` | эта документация по разделам |
| `catalog(section)` | инструменты, наборы, SFX, эффекты, нотация, сэмплы; `catalog("real")` — живые инструменты |
| `search_instruments(query)` | найти живой инструмент / артикуляцию / GM / голос |
| `speak(text, effects, semitones)` | фраза голосом в библиотеку |
| `list_sounds(query)`, `get_sound(id)` | библиотека, рецепт + анализ |
| `create_sound(recipe)` | рендер нового звука |
| `edit_sound(id, tracks, set, remove_tracks)` | частичная правка по именам дорожек |
| `update_sound(id, recipe)` | заменить рецепт целиком |
| `preview(recipe или sound_id, from_beat, to_beat)` | быстрый рендер куска без истории |
| `analyze_sound(id)`, `sample_info(ref)` | анализ |
| `search_samples(query, source)` | поиск звуков Minecraft / своих / библиотеки |
| `ai_song(caption, lyrics, language, …)` | **нейро-песня с живым вокалом (ACE-Step)** |
| `ai_cover(source, caption, lyrics, strength)` | перепеть мою аранжировку как готовый трек |
| `ai_repaint(id, start, end, …)` | переделать кусок песни |
| `ai_sfx(prompt, variants)` | нейро-SFX по описанию (Woosh) |
| `neural_status()` | что из нейросетей установлено/запущено |
| `compose_song(style, lyrics, ...)` | песня нотами: abyss takopi jumping angelic |
| `compose_beat(style, ...)` | стартовый бит: lofi trap house rock chiptune noteblock |
| `compose_calm`, `compose_horror`, `morph` | эмбиент и переход «хорошо → жуть» |
| `make_sfx(kind, params, effects)` | один SFX-генератор |
| `transform_audio(source, ...)` | обработка/ремикс готового звука |
| `import_midi`, `export_midi` | MIDI |
| `export_to_minecraft`, `export_file` | в ресурспак / в файл |
| `elevenlabs_sfx`, `elevenlabs_music` | генерация ElevenLabs (нужен ключ) |
| `revert_sound(id, version)`, `delete_sound(id)` | история, корзина |

Подключение к Claude Code (один раз):

```text
claude mcp add soundlab -s user -- "<папка>\.venv\Scripts\python.exe" "<папка>\soundlab\mcp_server.py"
```

## CLI

```text
python -m soundlab.cli beat trap key="G minor"
python -m soundlab.cli render recipe.json [--id ID]
python -m soundlab.cli preview ID 16 32
python -m soundlab.cli analyze ID
python -m soundlab.cli search zombie hurt --mc
python -m soundlab.cli sample mc:note/flute
python -m soundlab.cli midi-import song.mid
python -m soundlab.cli export ID drugs:halluc.x [pack_dir] --variants=3
python -m soundlab.cli guide аккорды
```

Запускать из папки `Encelada-Sound-Lab` через `.venv\Scripts\python.exe`.

## Веб-приложение

`Start-SoundLab.cmd` → http://127.0.0.1:4790.

- Слева библиотека; в центре звук: плеер, волна с секциями, спектрограмма, дорожки;
- дорожки с явными нотами правятся мышкой в пиано-ролле; дорожки в нотации — текстом (пиано-ролл показывает результат), кнопка «развернуть в ноты» превращает нотацию в обычные ноты;
- «🥁 Бит» — стартовый бит, «▶ Кусок» — быстро прослушать доли от–до;
- справа: лента «Что происходит» (видно, что делает Claude), поиск сэмплов Minecraft (▶ слушать, ＋ добавить дорожкой), клавиатура.

## Примеры

Трэп-бит с 808 и секциями:

```json
{"name": "example_trap", "tempo": 140, "key": "F minor",
 "sections": {"intro": {"bars": 2}, "drop": {"bars": 4}}, "arrange": "intro drop drop",
 "tracks": [
  {"name": "drums", "kit": "808", "parts": {
    "intro": {"drums": {"hat": "x.x.x.x.x.x.x.x."}},
    "drop":  {"drums": {"kick": "x......x..x.....", "snare": "........x.......", "hat": "x.x.xrx.x.x.t.x.", "ohat": "..............x."}}}},
  {"name": "808", "instrument": {"synth": "sine", "params": {"release": 0.4}}, "chords": "i VI iv V", "style": "root",
   "pulse": 2, "chord_octave": 2, "sections": "drop", "effects": [{"type": "distortion", "drive": 2, "mix": 0.4}]},
  {"name": "pad", "instrument": "strings", "chords": "i VI iv V", "chord_octave": 4, "loop": true, "gain": 0.4,
   "effects": [{"type": "sidechain", "every": 1, "depth": 0.6}, {"type": "reverb", "size": 0.6, "mix": 0.3}]},
  {"name": "bell", "instrument": "synth:bell", "parts": {"drop": "F5:1/2 Ab5 C6 Ab5 G5:1 Eb5 | F5:2 r:2"}, "gain": 0.5,
   "effects": [{"type": "delay", "time": "3/16", "feedback": 0.35, "mix": 0.25}]}
 ], "master": {"effects": [{"type": "compress", "threshold": -14}]}}
```

Слоёный SFX для плагина — удар магического посоха (синтез + ванильные звуки):

```json
{"name": "example_staff_hit", "kind": "sfx", "tempo": 120, "tracks": [
  {"name": "boom", "type": "sfx", "sfx": "impact", "params": {"duration": 1.2, "pitch": 140}, "gain": 0.8},
  {"name": "zap", "type": "audio", "source": "mc:entity.evoker.cast_spell", "semitones": 5, "gain": 0.6},
  {"name": "glass", "type": "audio", "source": "mc:block.amethyst_block.break", "at": 0.1, "gain": 0.5},
  {"name": "sparkle", "type": "sfx", "sfx": "chime", "params": {"duration": 1.5, "notes": 5, "root": "E6"}, "at": 0.25, "gain": 0.4}
 ], "master": {"effects": [{"type": "reverb", "size": 0.4, "mix": 0.2}], "normalize": -1}}
```

Музыка на нотных блоках (звучит «как в игре»):

```json
{"name": "example_noteblock_song", "tempo": 110, "key": "G major", "tracks": [
  {"name": "melody", "instrument": "noteblock:bell", "notes": "(G5:1/2 B5 D6 B5 A5:1 G5)x2 | E5:1/2 G5 B5 A5 G5:2"},
  {"name": "harp", "instrument": "noteblock:harp", "chords": "I vi IV V", "style": "arp", "arp_step": 0.5, "chord_length": 2},
  {"name": "bass", "instrument": "noteblock:bass", "chords": "I vi IV V", "style": "root", "chord_length": 2, "chord_octave": 3},
  {"name": "drums", "kit": "mc", "drums": {"kick": "x...x...", "snare": "..x...x.", "hat": "xxxxxxxx"}, "step": 0.5, "loop": 2}
 ]}
```

Ремикс готового звука (нарезка + ударные поверх):

```json
{"name": "example_chop", "tempo": 100, "tracks": [
  {"name": "chops", "type": "audio", "source": "mc:music_disc.cat", "trim": [8, 14], "slices": 8,
   "sequence": "0 1 0 1 2 3 2r 3 4 4 5 5 6 7 6r 7:2", "step": 0.5, "gain": 0.7, "effects": [{"type": "lofi"}]},
  {"name": "drums", "kit": "synth", "drums": {"kick": "x.....x...x.....", "snare": "....x.......x...", "hat": "x.x.x.x.x.x.x.x."}, "loop": 2}
 ]}
```

## Советы по звуку для Minecraft

- Звуки в мире (блоки, мобы, предметы) — **моно**, короткие, без тишины в начале, пик около −1 дБ.
- Ванильные звуки тихие и сухие: реверб делайте умеренный (mix ≤ 0.25), игра не добавляет своего.
- Для частых звуков (шаги, выстрелы, удары) экспортируйте 3–5 `variants` с `pitch_spread` 0.5–1.
- Музыка: `stream=True`, стерео можно, rms около −16 дБ, без клиппинга.
- Низы ниже 60 Гц на ноутбуках не слышны: если `bands_percent.sub` большой, добавьте `highpass` 50–80 Гц или средние частоты.
- `/playsound` принимает `pitch` 0.5–2.0: одну запись можно играть выше/ниже прямо в игре.

## Устранение неполадок

- Нет живых инструментов (`sso:` не находится) — `python -m soundlab.install` (скачает оркестр ~1.4 ГБ и MuseScore General ~216 МБ).
- Голос не поёт («синтез речи Windows не сработал») — нужны голоса Windows (Параметры → Время и язык → Речь) и пакет `pyworld`.
- «нет SoundFont» — положите `.sf2` в `soundlab/soundfonts/`.
- «не нашёл звуки Minecraft» — запустите игру хотя бы раз или задайте `MINECRAFT_DIR`.
- «не понимаю ноту …» / «не понимаю аккорд …» — ошибка в нотации, сообщение показывает токен.
- Рендер долгий — используйте `preview` по долям; `pad`/`strings`/`choir`-синтезаторы тяжелее GM-инструментов.
- Нет зависимостей — запустите `Start-SoundLab.cmd` (создаст `.venv`).
