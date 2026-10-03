# Encelada Sound Lab

Мастерская звука для проекта Encelada: музыка по нотам, биты, ремиксы, хоррор-SFX и экспорт прямо в ресурспак Minecraft.
Звук описывается JSON-рецептом (темп, дорожки, инструменты, эффекты, форма песни), а движок рендерит его в WAV/OGG с волной, спектрограммой и анализом.
Работать можно в веб-приложении (http://127.0.0.1:4790), из командной строки или через MCP, где Claude сам пишет и правит звуки.

Что внутри:
- живые инструменты (оркестр Sonatina, рояль Salamander, General MIDI), синтезаторы и нотные блоки;
- биты, аккорды, форма песни, импорт и экспорт MIDI, ремиксы аудио;
- пение по нотам (SoulX-Singer), целые песни с вокалом (ACE-Step 1.5), SFX по описанию (Woosh), всё локально на GPU;
- 19 встроенных генераторов SFX, эффекты, анализ звука, экспорт в `sounds.json`.

Подробно: [soundlab/README.md](soundlab/README.md) и полное руководство [soundlab/GUIDE.md](soundlab/GUIDE.md).

## Запуск

Windows: `Start-SoundLab.cmd`. При первом запуске создаётся `.venv`, ставятся зависимости и скачиваются живые инструменты (около 1.6 ГБ).
Нейросети ставятся отдельно: `python -m soundlab.install neural`. Ключ ElevenLabs необязателен: переменная `ELEVENLABS_API_KEY` или `soundlab/config.json` (он в `.gitignore`).

Большие файлы (инструменты, SoundFont MuseScore General, веса нейросетей, `.venv`) в репозиторий не входят и скачиваются установщиком.

## Демо

Папка [demos/](demos) содержит готовые примеры работы. В каждой папке: `audio.ogg` (прослушать), `recipe.json` (рецепт, из которого звук собран), `waveform.png` и `spectrogram.png` (превью), `analysis.json` и `meta.json`.
Чтобы открыть демо в редакторе, скопируйте его папку в `soundlab/library/`.

| Демо | Тип | Длина | Что это |
|---|---|---|---|
| [demo_ai_abyss_like_49fa](demos/demo_ai_abyss_like_49fa/audio.ogg) | music | 80 с | ACE-Step: ethereal fantasy adventure soundtrack, children's choir singing softly in an invented language, celesta, harp, music box, warm strings, gentle piano, wonder and melancholy, cinematic, anime film score |
| [demo_ai_angel_hymn_8898](demos/demo_ai_angel_hymn_8898/audio.ogg) | music | 60 с | ACE-Step: angelic heavenly choir, soprano voices, cathedral reverb, pipe organ, harp, slow sacred hymn, ethereal |
| [demo_ai_anime_ending_c4cd](demos/demo_ai_anime_ending_c4cd/audio.ogg) | music | 70 с | ACE-Step: нежная аниме-концовка, японский вокал |
| [demo_ai_claws_wall](demos/demo_ai_claws_wall/audio.ogg) | sfx | 6 с | Woosh: long sharp claws slowly scraping along a rough stone wall in a dark corridor |
| [demo_ai_cover_my_melody_5663](demos/demo_ai_cover_my_melody_5663/audio.ogg) | music | 17 с | ACE-Step кавер моей аранжировки (ноты + нейро-певица + рояль) |
| [demo_ai_crawler_vent](demos/demo_ai_crawler_vent/audio.ogg) | sfx | 6 с | Woosh: something with many legs crawling fast inside a metal ventilation shaft, scratching and knocking |
| [demo_ai_giggles_dark](demos/demo_ai_giggles_dark/audio.ogg) | sfx | 6 с | Woosh: several small creatures giggling and snickering quietly in the dark, creepy childlike laughter |
| [demo_ai_jumping_voices_like_2e66](demos/demo_ai_jumping_voices_like_2e66/audio.ogg) | music | 60 с | ACE-Step: upbeat bouncy cheerful game music, playful chopped vocal samples jumping between notes, female vocal chops "ah" "hey" "oh", plucky synths, bright piano, four-on-the-floor light drums, happy walking theme |
| [demo_ai_mimic_help](demos/demo_ai_mimic_help/audio.ogg) | sfx | 6 с | Woosh: a distant unnatural voice calling for help in the woods, slightly wrong and distorted |
| [demo_ai_monster_scream](demos/demo_ai_monster_scream/audio.ogg) | sfx | 6 с | Woosh: terrifying monstrous shriek, close, wet and raspy |
| [demo_ai_siren_head](demos/demo_ai_siren_head/audio.ogg) | sfx | 6 с | Woosh: a giant creature screaming like a distorted air raid siren mixed with a garbled human voice, echoing over a forest at night |
| [demo_alleluia_choir](demos/demo_alleluia_choir/audio.ogg) | sound | 13 с | хор поёт а-ле-лу-я |
| [demo_angel_choir](demos/demo_angel_choir/audio.ogg) | sound | 29 с | ангельский хор (пресет angel choir) |
| [demo_anime_song](demos/demo_anime_song/audio.ogg) | sound | 23 с | аниме-песня на нотах: нейро-певица + инструменты |
| [demo_crawler](demos/demo_crawler/audio.ogg) | sfx | 12 с | SFX: ползун в стенах |
| [demo_dark_giggles](demos/demo_dark_giggles/audio.ogg) | sfx | 13 с | SFX: хихиканье в темноте |
| [demo_lalala](demos/demo_lalala/audio.ogg) | sound | 13 с | голос поёт ля-ля-ля |
| [demo_live_orchestra](demos/demo_live_orchestra/audio.ogg) | sound | 29 с | живые инструменты: рояль, скрипка, виолончель, флейта, хор |
| [demo_mimic](demos/demo_mimic/audio.ogg) | sfx | 24 с | SFX: мимик зовёт голосом |
| [demo_noteblock_beat](demos/demo_noteblock_beat/audio.ogg) | music | 38 с | бит noteblock: F# major, аккорды I vi IV V |
| [demo_phrase_monster](demos/demo_phrase_monster/audio.ogg) | sfx | 6 с | фраза голосом, опущенная для монстра |
| [demo_salamander_piano](demos/demo_salamander_piano/audio.ogg) | sound | 19 с | рояль Salamander Grand Piano |
| [demo_siren_head](demos/demo_siren_head/audio.ogg) | sfx | 20 с | SFX: сиреноголовый |
| [demo_song_abyss](demos/demo_song_abyss/audio.ogg) | music | 77 с | эфирная сказка: челеста, арфа, струнные, детский голос на выдуманном языке, ангельский хор |
| [demo_song_angelic](demos/demo_song_angelic/audio.ogg) | music | 92 с | ангельский гимн: хор голосов + живой хор с шиммером, орган, арфа, струнные |
| [demo_song_jumping](demos/demo_song_jumping/audio.ogg) | music | 37 с | бодрая: прыгающие вокальные чопы, плаки, бочка в пол, бас |
| [demo_song_takopi](demos/demo_song_takopi/audio.ogg) | music | 56 с | нежная аниме-песня: гитара, рояль, глокеншпиль, мягкие барабаны, аниме-вокал по-японски |
| [demo_voice_scream](demos/demo_voice_scream/audio.ogg) | sfx | 5 с | SFX: крик голосом |
