import os
import re
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from youtube_transcript_api.proxies import WebshareProxyConfig

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 公開Invidiousインスタンス（複数用意して順に試す）
INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://yewtu.be",
    "https://invidious.privacyredirect.com",
    "https://iv.datura.network",
    "https://invidious.lunar.icu",
    "https://invidious.nerdvpn.de",
    "https://yt.artemislena.eu",
    "https://invidious.slipfox.xyz",
]


def build_api():
    proxy_user = os.environ.get("PROXY_USERNAME")
    proxy_pass = os.environ.get("PROXY_PASSWORD")
    if proxy_user and proxy_pass:
        return YouTubeTranscriptApi(proxies=WebshareProxyConfig(
            proxy_username=proxy_user,
            proxy_password=proxy_pass,
        ))
    return YouTubeTranscriptApi()


def fetch_via_youtube_api(video_id: str):
    """youtube_transcript_api ライブラリで直接取得"""
    try:
        api = build_api()
        tlist = api.list(video_id)
        transcript = None
        try:
            transcript = tlist.find_manually_created_transcript(["ja"])
        except NoTranscriptFound:
            pass
        if transcript is None:
            try:
                transcript = tlist.find_generated_transcript(["ja", "en"])
            except NoTranscriptFound:
                pass
        if transcript is None:
            return None
        segs = transcript.fetch()
        segments = [s.text.replace("\n", " ") for s in segs if s.text.strip()]
        return {"segments": segments} if segments else None
    except Exception:
        return None


def fetch_via_invidious(video_id: str):
    """Invidious公開インスタンス経由で字幕取得"""
    for instance in INVIDIOUS_INSTANCES:
        try:
            res = requests.get(
                f"{instance}/api/v1/captions/{video_id}",
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if res.status_code != 200:
                continue

            data = res.json()
            captions = data.get("captions", [])
            if not captions:
                continue

            # 日本語優先、なければ英語、それ以外は先頭
            target = None
            for lang_prefix in ["ja", "en"]:
                for cap in captions:
                    if cap.get("languageCode", "").startswith(lang_prefix):
                        target = cap
                        break
                if target:
                    break
            if not target:
                target = captions[0]

            label = target.get("label", "")
            vtt_url = (
                f"{instance}/api/v1/captions/{video_id}"
                f"?label={requests.utils.quote(label)}"
            )
            vtt_res = requests.get(
                vtt_url, timeout=10,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if vtt_res.status_code != 200:
                continue

            segments = _parse_subtitle(vtt_res.text)
            if segments:
                return {"segments": segments}
        except Exception:
            continue

    return None


def _parse_subtitle(content: str) -> list:
    """WebVTT または XML 字幕からテキストを抽出"""
    # WebVTT
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

    # XML
    if "<text" in content:
        matches = re.findall(r"<text[^>]*>([^<]*)</text>", content)
        texts = []
        for m in matches:
            text = (m.replace("&amp;", "&").replace("&lt;", "<")
                     .replace("&gt;", ">").replace("&#39;", "'")
                     .replace("&quot;", '"').strip())
            if text:
                texts.append(text)
        return texts

    return []


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/transcript/{video_id}")
def get_transcript(video_id: str):
    # 1. youtube_transcript_api ライブラリ（直接）
    result = fetch_via_youtube_api(video_id)
    if result:
        return result

    # 2. Invidious 経由
    result = fetch_via_invidious(video_id)
    if result:
        return result

    return {"segments": [], "error": "all_methods_failed"}
