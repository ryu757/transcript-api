import os
import random
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
]

_proxy_cache: list = []

def fetch_free_proxies() -> list:
    global _proxy_cache
    if _proxy_cache:
        return _proxy_cache
    proxies = []
    for url in PROXY_SOURCES:
        try:
            res = requests.get(url, timeout=5)
            lines = [l.strip() for l in res.text.strip().split("\n") if l.strip()]
            proxies.extend(lines)
        except Exception:
            pass
    random.shuffle(proxies)
    _proxy_cache = proxies
    return proxies

def build_api():
    # 環境変数で Webshare プロキシが設定されている場合はそれを使う
    proxy_user = os.environ.get("PROXY_USERNAME")
    proxy_pass = os.environ.get("PROXY_PASSWORD")
    if proxy_user and proxy_pass:
        return YouTubeTranscriptApi(proxies=WebshareProxyConfig(
            proxy_username=proxy_user,
            proxy_password=proxy_pass,
        ))

    # プロキシなしで試す
    return YouTubeTranscriptApi()

def fetch_transcript_with_retry(video_id: str):
    """プロキシなし → フリープロキシの順で試みる"""
    # 1. 通常リクエスト
    try:
        api = build_api()
        return _do_fetch(api, video_id)
    except Exception:
        pass

    # 2. フリープロキシを最大 15 個試す
    proxies = fetch_free_proxies()
    for proxy in proxies[:15]:
        proxy_url = proxy if "://" in proxy else f"http://{proxy}"
        try:
            api = YouTubeTranscriptApi(proxies=GenericProxyConfig(
                http_proxy=proxy_url, https_proxy=proxy_url
            ))
            result = _do_fetch(api, video_id)
            # 成功したプロキシをキャッシュ先頭に
            _proxy_cache.insert(0, proxy)
            return result
        except Exception:
            continue

    return {"segments": [], "error": "all_proxies_failed"}

def _do_fetch(api, video_id):
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
        return {"segments": [], "error": "no_transcript"}
    segs = transcript.fetch()
    return {"segments": [s.text.replace("\n", " ") for s in segs if s.text.strip()]}

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/transcript/{video_id}")
def get_transcript(video_id: str):
    try:
        return fetch_transcript_with_retry(video_id)
    except TranscriptsDisabled:
        return {"segments": [], "error": "disabled"}
    except Exception as e:
        return {"segments": [], "error": str(e)}
