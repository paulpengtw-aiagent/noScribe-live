## noScribe Live (this fork): how to run it

This fork adds **noScribe Live**, a page in your browser that shows a transcription appearing in real time while noScribe works. You start a transcription from the command line as usual and add one flag, `--live-feed`. The page watches it: identifying speakers, loading the model, then each segment as it is transcribed, labelled by speaker. The page never starts a transcription itself. Without `--live-feed`, noScribe behaves exactly like upstream.

The paths below are for the owner's Linux machine (noScribe environment in `/home/cheng/noScribe/venv`, models in `/mnt/data/noScribe-models`). On another machine, use your own noScribe Python and model folder.

### What you need

- Linux with an NVIDIA GPU (CUDA) for real transcriptions. The viewer page itself needs no GPU.
- A Python environment with noScribe's requirements installed.
- noScribe Whisper models, for example `breeze-asr-25`, `breeze-asr-26` and `precise`.
- For the viewer: Python 3.11 (through `uv` if installed, else `python3`), Node.js with `pnpm` or `npm` (only to build the page the first time), and `ffmpeg` (for the waveform).

### 1. One-time setup

```sh
git clone https://github.com/paulpengtw-aiagent/noScribe-live.git
cd noScribe-live

# Make the models visible to noScribe
mkdir -p ~/.config/noScribe/whisper_models
for m in breeze-asr-25 breeze-asr-26 precise; do
  ln -sfn /mnt/data/noScribe-models/$m ~/.config/noScribe/whisper_models/$m
done
```

### 2. Start the viewer (terminal 1)

```sh
live/run.sh
```

The first start takes a few minutes. It creates `live/.venv`, installs the server's packages and builds the page. Later starts take seconds. After you update the code (`git pull`), the next start rebuilds the page by itself. Then open **http://localhost:8765**. Until a transcription starts, the page shows that it is waiting.

### 3. Transcribe with live output (terminal 2, from the repo folder)

```sh
PYTHONDONTWRITEBYTECODE=1 /home/cheng/noScribe/venv/bin/python -m noScribe --no-gui \
  --model breeze-asr-25 --speaker-detection auto --timestamps \
  --live-feed live/feeds/ interview.mp3 interview.html
```

- Replace `interview.mp3` with your audio or video file (mp3, m4a, wav, ogg, webm, mp4 and other formats ffmpeg reads), and `interview.html` with where the transcript should be saved. noScribe writes that file exactly as it normally does.
- The page switches to the new transcription by itself.
- `PYTHONDONTWRITEBYTECODE=1` keeps the shared noScribe environment unchanged.
- Run one transcription at a time; the GPU is shared.
- For more options (language, number of speakers, pauses and so on), run `python -m noScribe --help` with the same Python.

On this machine's RTX 5060 Ti, a 3-minute bilingual clip took about 50 seconds, including about 20 seconds of model loading. Segments reached the browser a median of 0.04 seconds after noScribe wrote them.

### 4. Using the page

- **Follow or pick a run.** By default the page follows the newest transcription. The run picker in the header lists earlier runs by day, with their status (live, finished, failed, stopped), length and segment count, and a filter box. A picked run's address (`?run=…`) can be bookmarked or shared.
- **Read back while it streams.** Scroll up and the page stops following; **Jump to live** brings you back. Click a block on the timeline to jump to that part of the transcript.
- **Download the transcript.** When a run finishes, a **Download .odt** button appears (also on finished runs picked from the history). The file has the speakers, timestamps and the text as shown on the page, and opens in LibreOffice (checked) and other OpenDocument editors.
- **Easy view (大字模式).** The Easy / 大字 toggle in the header switches to large text, high contrast, big buttons and no animation, with a plain status sentence on top. It's meant for older viewers and is remembered like the theme and language.
- **Language and theme.** Use the EN/中 toggle and the light/dark switch in the header; on a phone they are in the header menu. The look follows the Nord palette: Polar Night in dark, Snow Storm in light. Chinese transcript text is shown in Traditional characters (Taiwan).
- Opening or reloading the page mid-run catches up on everything so far. If the connection drops, the transcript stays on screen and the page reconnects by itself.

### Rehearse a demo without the GPU

Every transcription leaves a recording of its live output in `live/feeds/<run id>.ndjson`. You can replay one as if it were happening now:

```sh
cd live && .venv/bin/python -m server.replay feeds/<run id>.ndjson --feeds feeds --speed 1
```

A public-domain demo clip (3:22, English and Mandarin speakers taking turns) can be built with `live/samples/make-demo-clip.sh`, which writes `live/samples/demo-en-zh.mp3`. Transcribe it once with step 3, and you have a feed to replay.

### Show it on another device

- **Same network:** start the viewer with `HOST=0.0.0.0 LIVE_TOKEN=<a secret> live/run.sh`, then open `http://<this machine's IP>:8765/?token=<the secret>` once on the other device. A cookie keeps it signed in for 7 days.
- **Over the internet:** see "Share the viewer through a tunnel" in [live/README.md](live/README.md). That tunnel is plain HTTP, so use it with test audio only.

### Stop

Press Ctrl-C in each terminal. Past runs stay in the picker. To clear them, delete the files in `live/feeds/` while the viewer is stopped.

### If something goes wrong

| What you see | What to do |
|---|---|
| The page keeps waiting while noScribe runs | The command must include `--live-feed live/feeds/` and run from the repo folder, because the viewer reads `live/feeds/`. |
| noScribe says the model isn't found | Redo the model links in step 1. |
| Port 8765 is already in use | Start on another port: `PORT=8770 live/run.sh`. |
| A blank or outdated page after updating the code | run.sh normally rebuilds the page by itself; to force it, run `live/run.sh --rebuild`. |
| No waveform | Install `ffmpeg`. |
| GPU memory still in use after you killed a run | A known noScribe issue: after `kill -9`, the speaker-identification worker can stay behind. Find it with `nvidia-smi` and stop that process. Prefer Ctrl-C. |

More detail (all viewer options, the feed format, measurements, how it works and the tests) is in [live/README.md](live/README.md).

---

# noScribe
### Cutting Edge AI Technology for Automated Audio Transcription
</br>

> [!NOTE]
> ### 🚀 The new official website for noScribe: https://noscribe.de
> Learn how to install and use the software, and find tips to improve transcription quality.
>
> 🌐 Available in **English, German, Spanish, Italian, and Dutch**.
>
> Please update your links. 

---

> [!WARNING]
> Somebody has registered the domain **noscribe(dot)ai** to sell transcription services. **Stay away from this platform, I have nothing to do with it.** The real noScribe is free and always will be. This is obviously an attempt to profit from the popularity of my software and the reputation it gained over the years. Very sad. 

## What is noScribe?
- An app to produce **high quality transcripts of interviews** for qualitative social research or journalistic use
- noScribe is **free and open source** ([GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.html)), available for Windows, MacOS and Linux 
- It runs **completely locally** on your computer, protecting the confidentiality of your interviews. No cloud, no worries
- It can distinguish between different **speakers** and understands around 60 languages (more or less, see below)
- It includes a **nice editor** to review, verify and correct the resulting transcript
- It is standing on the shoulders of giants: [Whisper from OpenAI](https://github.com/openai/whisper), [faster-whisper by Guillaume Klein](https://github.com/guillaumekln/faster-whisper) and [pyannote from Hervé Bredin](https://github.com/pyannote/pyannote-audio)

</br>

![Main window](img/noScribe_main_window.png)
(The transcript is from [this interview](https://www.youtube.com/watch?v=vOwajAbvPzQ&t=2018s) which I did in May 2022 with the Russian sociologist Natalia Savelyeva.)

## Download, Installation, and Usage

See the corresponding sections on my website: https://noscribe.de 

To run noScribe without its window in a Docker container (CPU only, for servers and batch jobs), see [docker/README.md](docker/README.md).

## About Me
**Kai Dröge**, PhD in sociology (with a background in computer science), qualitative researcher and teacher, [Lucerne University for Applied Science (Switzerland)](https://www.hslu.ch/de-ch/hochschule-luzern/ueber-uns/personensuche/profile/?pid=823) and [Institute for Social Research, Frankfurt/M. (Germany)](https://www.ifs.uni-frankfurt.de/personendetails/kai-droege.html).

## Donate
NoScribe is free and always will be. However, developing it costs real money. I have purchased hardware for testing and pay Apple annually for a developer ID. If you would like to support this project, you can make a donation on Ko-Fi. Thanks! 

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/noscribe)

## Citation (APA Style)
Dröge, K. (2026). noScribe. AI-powered Audio Transcription (Version XXX) [Computer software]. https://github.com/kaixxx/noScribe

## Other Software
If you are interested in open source software for the analysis of qualitative data, take a look at [QualCoder](https://github.com/ccbogel/QualCoder), where I am a regular contributor.





