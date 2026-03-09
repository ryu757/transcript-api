import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from youtube_transcript_api.proxies import WebshareProxyConfig, GenericProxyConfig

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def build_api():
    """環境変数に応じてプロキシ設定を切り替え"""
    proxy_user = os.environ.get("PROXY_USERNAME")
    proxy_pass = os.environ.get("PROXY_PASSWORD")
    proxy_url  = os.environ.get("PROXY_URL")  # 汎用プロキシ用

    if proxy_user and proxy_pass:
        return YouTubeTranscriptApi(proxies=WebshareProxyConfig(
            proxy_username=proxy_user,
            proxy_password=proxy_pass,
        ))
    elif proxy_url:
        return YouTubeTranscriptApi(proxies=GenericProxyConfig(
            http_proxy=proxy_url,
            https_proxy=proxy_url,
        ))
    else:
        return YouTubeTranscriptApi()

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/transcript/{video_id}")
def get_transcript(video_id: str):
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
            return {"segments": [], "error": "no_transcript"}

        segs = transcript.fetch()
        return {"segments": [s.text.replace("\n", " ") for s in segs if s.text.strip()]}

    except TranscriptsDisabled:
        return {"segments": [], "error": "disabled"}
    except Exception as e:
        return {"segments": [], "error": str(e)}
