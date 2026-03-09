from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/transcript/{video_id}")
def get_transcript(video_id: str):
    try:
        api = YouTubeTranscriptApi()
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
