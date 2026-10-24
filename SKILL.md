---
name: labops-montage
description: Edit vertical talking-head reels (Instagram Reels, Shorts, TikTok) from raw phone footage - cut pauses and retakes, jump zooms on the face, captions from a catalogue, accents, inserts (logos, screenshots, memes found by the skill, numbers, the user's own clips), animated graphics (HyperFrames), text behind the head (person cut-out), studio voice (ElevenLabs), grey moments, video effects (shake, glitch, flash, freeze), sound effects, clean voice - with the user's OK at every key step. Also analyses a blogger's editing style from their reels and packs it into its own skill. Use when the user asks to edit/montage a reel or video, «смонтируй рилс», «смонтируй в стиле @...», «разбери монтаж блогера», or sends raw footage for a reel.
---

# labops-montage

Reels editing by labopsai. Scripts in `scripts/` of this skill's folder (usually `~/.claude/skills/labops-montage`),
run with `python3 <skill folder>/scripts/<name>.py`; the commands below are relative to that folder. Every script has `--help`.

**Talk to the user in their language, simply, no technical details unless asked.** Before installing anything,
say in one line what and why. At steps marked **[OK]** wait for the user's answer. If you run as a Telegram
agent, the user does not see your terminal: everything they must see goes into the chat.

## 0. Setup (once)

1. Check what is there: `ffmpeg -version` (need 7.1+), `python3 --version` (3.10+).
   Missing ffmpeg: macOS `brew install ffmpeg`, Windows `winget install Gyan.FFmpeg`,
   Linux - a static build from johnvansickle.com/ffmpeg (distro packages are often older than 7.1).
2. `pip install -r requirements.txt` and `python3 -m playwright install chromium`
   (Playwright draws captions and inserts in a headless browser; OpenCV finds the face; MediaPipe cuts the
   person out of the background). Optional: `pip install faster-whisper` (free speech recognition, no key).
3. Node.js 22+ for animated graphics (HyperFrames: HTML + GSAP animation -> video): `node --version`.
   Missing: macOS `brew install node`, Windows `winget install OpenJS.NodeJS.LTS`, Linux nodejs.org/en/download
   (or nvm). HyperFrames itself is fetched by `npx` on the first render. Check: `python3 scripts/graphics.py demo
   test.mov`. A different Node: set `LABOPS_NPX=/path/to/npx`.
4. Keys go to `~/.config/labops-montage/keys.env`, one per line `NAME=value`. Give the user the command to
   open this file and let them paste the key there themselves; never print keys in replies.
   - `GROQ_API_KEY` - speech recognition, free tier (console.groq.com). Or `OPENAI_API_KEY` (paid), or
     faster-whisper without a key.
   - `HIKERAPI_KEY` - download Instagram reels for style analysis (hikerapi.com, about $0.001 per request).
     Without it the user sends reference videos as files.
   - `ELEVENLABS_API_KEY` - optional: studio-clean voice (`voice.py`) and more sound effects (elevenlabs.io,
     the free plan has 10 000 credits a month; voice cleaning takes about 1 000 credits per minute of audio).
5. `python3 scripts/doctor.py --keep` -> everything OK, show the user the test preview.

## 1. Files

Telegram bots download files only up to 20 MB and send up to 50 MB. Phone footage is hundreds of MB, so:
- the user uploads the source to Google Drive with access "anyone with the link" and sends the link;
  or a shared Google Drive folder through rclone (rclone.org: copies files between the computer and
  Google Drive; one-time Google login by link);
- ask for videos as **files**, not as "video" (Telegram recompresses videos);
- send previews 720p (they fit 50 MB), the final 1080x1920 goes to Google Drive;
- transcribe the user's voice messages: edits often come by voice.

## 2. Workflow

Work in a project folder per reel (`<project>`). Never run two renders at once: heavy video jobs can run out
of memory and kill the session. Report to the user after every step; during long renders at least every
15-20 minutes; report errors at once, in plain words, with a way out.

**Step 1. Format.** Ask: (a) own video in the base style, (b) by reference - 1-5 reels of a blogger whose
editing they like, (c) from scratch (no footage: graphics, screenshots, voice). Ask for the source and language.

**Step 2. Prepare.**
```
python3 scripts/trim.py init <raw.mov> <project> --lang ru --prompt "names, products, terms"
```
Read `work/phrases.txt`: find retakes and slips (keep the last good take), then
```
python3 scripts/trim.py cut <project> --drop 12.3-15.8,40.1-41.0 --speed 1.2
```
Speed: 1.2 for the whole reel, 1.3 for passing parts. Fix recognition typos in `work/words.json`
(captions are made from it; names spelled exactly).

**Step 3. Passport [OK].**
```
python3 scripts/plan.py draft <project> --cta "пиши СЛОВО в комментарии"
```
Edit `plan.draft.json` by meaning (hook, which inserts, grey moments, sounds, effects), copy to `plan.json`,
send the user `plan.md` in short: length and pace, hook (first 2-3 s), what is cut, where inserts/memes/logos
are, grey moments (where the person slips or pauses, black-and-white, funny), sound and video effects, CTA.
Effects (`"fx"` in a beat): shake on a strong word, glitch on a joke, flash on a new thought, freeze for a
pause; not more often than once per 3 s.
Memes: pick them yourself, never ask the user to send memes. The user only says where memes go (or you propose
the places in the passport). `python3 scripts/memes.py fetch <project>/memes` (public page of @membeztexta, no
key), look at `memes.py sheet <project>/memes memes.png`, choose by the meaning of the phrase, download with
`memes.py get <project>/memes N`, show the chosen memes (still frames) in the passport; replace any the user
dislikes. No memes with brands or logos. In plan.json: `{"kind": "meme", "src": "<file>", "layout":
"full|card|split"}`; video memes play muted for the beat.
Animated graphics (`{"kind": "gfx", "layout": "full|split|card", "gfx": {...}}`, types in `graphics.py --help`):
for numbers, comparisons, lists, commands said in the speech; only real numbers and words. Text behind the head:
`{"kind": "text", "layout": "behind", "text": "РЕМОНТ"}` (one short word, big, the head covers its lower part).
Voice: offer the studio voice (ElevenLabs voice isolation, `voice.py`) when the sound is noisy or echoey and the
user has a key; it spends credits, so ask first.
The user's own clips (b-roll) only when the user sent them and asked: `{"kind": "broll", "src": "<file>",
"layout": "cover"}` (whole frame, the voice goes on) or `"src": [a, b, c], "layout": "stack"` (2-3 clips one above
the other).

**Step 4. Catalogue [OK].** Take a frame of their video (`ffmpeg -ss 3 -i <project>/work/clean.mp4 -frames:v 1 frame.jpg`)
and show numbered variants on it; the user answers with numbers. Do not choose for them.
```
python3 scripts/subtitles.py sheet frame.jpg subs.png        # 24 caption styles
python3 scripts/catalogs.py accents frame.jpg accents.png     # 8 accent looks
python3 scripts/catalogs.py grey frame.jpg grey.png           # grey moments
python3 scripts/catalogs.py layouts frame.jpg layouts.png     # how the frame is arranged during inserts
python3 scripts/catalogs.py effects frame.jpg effects.png     # 4 video effects (still hint)
python3 scripts/graphics.py sheet frame.jpg graphics.png      # 7 animated graphics (final frame)
python3 scripts/effects.py demo <project>/work/clean.mp4 effects.mp4   # the same effects moving, numbered
```
To the user say "how the frame is arranged" (not "layout"), and explain "glitch" (colour noise like a broken TV).
Sounds: play `assets/sfx/*.wav` (click, tick, pop, blip, whoosh, swipe, riser, hit, ding) or generate more
with `scripts/sounds_ai.py` (ElevenLabs, ask first: it spends credits). Save the picks in `project.json`;
next time the user can say "captions 3, accent 1".

**Step 5. Build.**
```
python3 scripts/plan.py check <project>          # fix every ERROR
python3 scripts/plan.py apply <project>
python3 scripts/logos.py <project>/assets Claude Notion   # official logo candidates: look, pick, put the path in plan.json
python3 scripts/faces.py track <project> && python3 scripts/faces.py frame <project>
python3 scripts/subtitles.py render <project> --style <id> --accent "слово1,слово2" --accent-look <N>
python3 scripts/voice.py <project>              # only if the user chose the studio voice (ElevenLabs, spends credits)
python3 scripts/inserts.py <project>             # pictures, text, video, animated graphics (HyperFrames)
python3 scripts/cutout.py <project>              # only if there is text behind the head (layout "behind")
python3 scripts/assemble.py <project>              # out/preview.mp4, 720p
python3 scripts/framesheet.py <project>                # out/frames.jpg: look at it before sending
python3 scripts/verify.py <project>                  # fix every ERROR
```
Send the preview with a one-line summary.

**Step 6. Edits [OK].** The user sends edits. Before the new version, check it against their list point by
point and write what was done for each. Edit the same project (no "v2" copies). After their OK:
`python3 scripts/assemble.py <project> --final --name <slug>` -> `verify.py` -> upload to Google Drive.

## 3. Editing rules (always)

- Cut once, only in pauses between phrases; `trim.py` follows the real end of the sound and keeps a natural
  pause (~0.2 s). After any re-cut run `faces.py track` again and `verify.py` (it re-recognises the render and
  flags words clipped at joins).
- Sound: no music (the user adds it in Instagram at publishing); gentle denoise and one static gain to about
  -15 LUFS; never a loudness compressor (it lifts room noise in every pause).
- Captions on every talking-head reel: lower third above the Instagram caption and nickname, lower case,
  2-3 words, no typos.
- Inserts never cover the face; hook changes the picture within 1.5 s; do not cut linking words between
  blocks ("дальше", "второй момент").
- Only official logos; never invent facts or numbers; by reference - repeat techniques (pace, cuts, layouts,
  captions), never copy the blogger's frames, music or text.
- Format 1080x1920 30 fps; preview 720p first, final only after OK.

## 4. Style of a blogger (format b)

```
python3 scripts/blogger.py fetch <style-folder> <reel links or files>
python3 scripts/blogger.py measure <style-folder>
```
Look at every `sheets/NN.jpg` and `metrics.md`, write `<style-folder>/style.md`: hook, framing and layouts,
captions (font, case, size, position, accents), inserts and graphics, sound effects, pace, CTA - techniques
only. Edit the reel with these settings (all steps and [OK] gates as usual).
**After the final OK, ask the user:** "Сохранить этот монтаж как отдельный скилл «смонтируй в стиле @<name>»?
Тогда в следующий раз хватит одной фразы." Only on yes: `python3 scripts/blogger.py skill <style-folder> --handle
<name>` makes the skill `montage-<name>` (in ~/.claude/skills): "смонтируй в стиле <name>" edits with these
settings. Add the user's edits from this reel to its style.md, so the next reel starts closer.

## 5. When something breaks

| Problem | What to do |
|---|---|
| Bot cannot download the video | File over 20 MB: ask for a Google Drive link |
| Result does not send to the chat | Over 50 MB: send the 720p preview, the final to Google Drive |
| Instagram reel does not download | HIKERAPI_KEY missing or private account: ask for the file |
| Process killed in the middle of a render | Out of memory: one render at a time, preview 720p first |
| A word is clipped at a join (`verify.py`) | `trim.py cut` with a larger `--pause`, or move the drop range |
| Captions show a wrong word | Fix `work/words.json`, run `subtitles.py render` again |
| Insert covers the face | Run `faces.py track` after the last cut; use layout `full` or `split` |
| Captions font looks plain | No internet for Google Fonts during render: check the connection |
| "TODO" error in `plan.py check` | Put a real file path into that insert (logo, screenshot, meme) |
