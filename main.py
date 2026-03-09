import os
import re
import json
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
from youtube_transcript_api.proxies import WebshareProxyConfig

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://yewtu.be",
    "https://invidious.privacyredirect.com",
    "https://iv.datura.network",
    "https://invidious.lunar.icu",
    "https://invidious.nerdvpn.de",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}


# ── 方法1: youtube_transcript_api ライブラリ ────────────────────────
def fetch_via_library(video_id: str):
    try:
        proxy_user = os.environ.get("PROXY_USERNAME")
        proxy_pass = os.environ.get("PROXY_PASSWORD")
        api = (
            YouTubeTranscriptApi(proxies=WebshareProxyConfig(
                proxy_username=proxy_user, proxy_password=proxy_pass))
            if proxy_user and proxy_pass
            else YouTubeTranscriptApi()
        )
        tlist = api.list(video_id)
        transcript = None
        for finder, langs in [
            (tlist.find_manually_created_transcript, ["ja"]),
            (tlist.find_generated_transcript, ["ja", "en"]),
        ]:
            try:
                transcript = finder(langs)
                break
            except NoTranscriptFound:
                pass
        if transcript is None:
            return None
        segs = transcript.fetch()
        texts = [s.text.replace("\n", " ") for s in segs if s.text.strip()]
        return {"segments": texts} if texts else None
    except Exception:
        return None


# ── 方法2: ウォッチページHTMLからキャプションURL抽出 ─────────────────
def fetch_via_watch_page(video_id: str):
    try:
        res = requests.get(
            f"https://www.youtube.com/watch?v={video_id}&hl=ja",
            headers=HEADERS, timeout=15,
        )
        html = res.text

        # ytInitialPlayerResponse を JSON として取り出す
        m = re.search(r"ytInitialPlayerResponse\s*=\s*", html)
        if not m:
            return None
        start = m.end()
        depth, end = 0, start
        for i, c in enumerate(html[start:]):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = start + i + 1
                    break
        pr = json.loads(html[start:end])

        tracks = (pr.get("captions", {})
                    .get("playerCaptionsTracklistRenderer", {})
                    .get("captionTracks", []))
        if not tracks:
            return None

        # 日本語優先、次に英語
        target = None
        for lang in ["ja", "en"]:
            for t in tracks:
                if t.get("languageCode", "").startswith(lang):
                    target = t
                    break
            if target:
                break
        if not target:
            target = tracks[0]

        base_url = target.get("baseUrl", "")
        if not base_url:
            return None

        xml_res = requests.get(base_url, headers=HEADERS, timeout=10)
        segs = _parse_subtitle(xml_res.text)
        return {"segments": segs} if segs else None
    except Exception:
        return None


# ── 方法3: Invidious 公開インスタンス ────────────────────────────────
def fetch_via_invidious(video_id: str):
    for instance in INVIDIOUS_INSTANCES:
        try:
            r = requests.get(
                f"{instance}/api/v1/captions/{video_id}",
                timeout=10, headers={"User-Agent": "Mozilla/5.0"},
            )
            if r.status_code != 200:
                continue
            captions = r.json().get("captions", [])
            if not captions:
                continue

            target = None
            for lang in ["ja", "en"]:
                for cap in captions:
                    if cap.get("languageCode", "").startswith(lang):
                        target = cap
                        break
                if target:
                    break
            if not target:
                target = captions[0]

            label = requests.utils.quote(target.get("label", ""))
            vtt = requests.get(
                f"{instance}/api/v1/captions/{video_id}?label={label}",
                timeout=10, headers={"User-Agent": "Mozilla/5.0"},
            )
            if vtt.status_code != 200:
                continue
            segs = _parse_subtitle(vtt.text)
            if segs:
                return {"segments": segs}
        except Exception:
            continue
    return None


# ── 字幕テキスト解析 ─────────────────────────────────────────────────
def _parse_subtitle(content: str) -> list:
    if "WEBVTT" in content:
        texts = []
        for line in content.split("\n"):
            line = line.strip()
            if not line or "-->" in line or line.startswith("WEBVTT") or line.isdigit():
                continue
            text = re.sub(r"<[^>]+>", "", line).strip()
            if text:
                texts.append(text)
        return texts

    if "<text" in content:
        texts = []
        for m in re.findall(r"<text[^>]*>([^<]*)</text>", content):
            text = (m.replace("&amp;", "&").replace("&lt;", "<")
                     .replace("&gt;", ">").replace("&#39;", "'")
                     .replace("&quot;", '"').strip())
            if text:
                texts.append(text)
        return texts

    return []


# ── エンドポイント ────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/transcript/{video_id}")
def get_transcript(video_id: str):
    for fn in [fetch_via_library, fetch_via_watch_page, fetch_via_invidious]:
        result = fn(video_id)
        if result:
            return result
    return {"segments": [], "error": "all_methods_failed"}
