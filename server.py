
import os, tempfile
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import yt_dlp, requests

app = FastAPI(title="OneSite API", version="1.0.0")

# CORS: 블로그/위젯에서 호출 가능하도록 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 상태 확인
@app.get("/health")
def health():
    return {"ok": True}

# 정적 파일 폴더(선택): 필요시 ./static을 루트에 둬서 확인
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

PREFERRED_CAPTION_EXTS = ["vtt", "srt", "ttml", "srv3", "json3"]
PREFERRED_LANGS = ["ko", "ko-KR", "en", "en-US", "en-GB"]

def _extract_info(url: str, download: bool = False, format_: Optional[str] = None, outtmpl: Optional[str] = None):
    ydl_opts = {
        "quiet": True,
        "noplaylist": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "skip_download": not download,
        "extract_flat": False,
    }
    if format_:
        ydl_opts["format"] = format_
        ydl_opts["merge_output_format"] = "mp4"
    if outtmpl:
        ydl_opts["outtmpl"] = outtmpl

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=download)
    return info

def _format_list(info: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for f in (info.get("formats") or []):
        size = f.get("filesize") or f.get("filesize_approx")
        out.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolution": f"{f.get('width','?')}x{f.get('height','?')}" if (f.get('width') and f.get('height')) else (f.get("resolution") or ""),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "fps": f.get("fps"),
            "filesize": size,
            "format_note": f.get("format_note"),
            "abr": f.get("abr"),
            "tbr": f.get("tbr"),
        })
    return out

def _collect_captions(info: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    tracks = []
    def push_from(container, auto):
        if not container: return
        for lang, arr in container.items():
            for t in arr or []:
                url = t.get("url"); ext = t.get("ext")
                if not url or not ext: continue
                tracks.append({"lang": lang, "ext": ext, "url": url, "auto": auto})
    push_from(info.get("subtitles"), auto=False)
    push_from(info.get("automatic_captions"), auto=True)

    def lang_rank(l):
        for i, cand in enumerate(PREFERRED_LANGS):
            if l == cand or l.lower().startswith(cand.split("-")[0]):
                return i
        return 999
    def ext_rank(e):
        try: return PREFERRED_CAPTION_EXTS.index(e)
        except ValueError: return 98

    tracks.sort(key=lambda x: (lang_rank(x["lang"]), ext_rank(x["ext"]), 1 if x["auto"] else 0))
    return {"tracks": tracks}

@app.post("/api/probe")
def api_probe(payload: Dict[str, Any] = Body(...)):
    url = payload.get("url")
    if not url: raise HTTPException(status_code=400, detail="Missing 'url'.")
    info = _extract_info(url, download=False)
    return {
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "webpage_url": info.get("webpage_url"),
        "ext": info.get("ext"),
        "formats": _format_list(info),
        "captions": _collect_captions(info),
    }

@app.post("/api/download")
def api_download(payload: Dict[str, Any] = Body(...)):
    url = payload.get("url"); format_id = payload.get("format_id")
    if not url or not format_id:
        raise HTTPException(status_code=400, detail="Body must include 'url' and 'format_id'.")
    tmpdir = tempfile.mkdtemp(prefix="onesite_")
    outtmpl = os.path.join(tmpdir, "%(title)s.%(ext)s")
    fmt = f"{format_id}+bestaudio/best" if str(format_id).isdigit() else str(format_id)
    try:
        info = _extract_info(url, download=True, format_=fmt, outtmpl=outtmpl)
        if "requested_downloads" in info and info["requested_downloads"]:
            final_path = info["requested_downloads"][0].get("filepath")
        else:
            cand = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)]
            cand.sort(key=os.path.getmtime, reverse=True)
            final_path = cand[0] if cand else None
        if not final_path or not os.path.exists(final_path):
            raise HTTPException(status_code=500, detail="File not found after download.")
        filename = os.path.basename(final_path)
        return FileResponse(final_path, filename=filename, media_type="application/octet-stream")
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"DownloadError: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@app.post("/api/captions")
def api_captions(payload: Dict[str, Any] = Body(...)):
    url = payload.get("url")
    if not url: raise HTTPException(status_code=400, detail="Missing 'url'.")
    info = _extract_info(url, download=False)
    return _collect_captions(info)

@app.get("/api/captions/download")
def api_captions_download(url: str = Query(...), lang: Optional[str] = Query(None), ext: Optional[str] = Query(None)):
    info = _extract_info(url, download=False)
    caps = _collect_captions(info)["tracks"]
    if not caps: raise HTTPException(status_code=404, detail="No captions available.")
    def matches(t):
        ok = True
        if lang:
            ok = ok and (t["lang"] == lang or t["lang"].lower().startswith(lang.lower().split("-")[0]))
        if ext:
            ok = ok and (t["ext"].lower() == ext.lower())
        return ok
    filtered = [t for t in caps if matches(t)]
    chosen = (filtered or caps)[0]
    r = requests.get(chosen["url"], timeout=20)
    if r.status_code != 200 or not r.content:
        raise HTTPException(status_code=502, detail="Failed to fetch caption data from source.")
    suffix = chosen["ext"].lower()
    media = "text/vtt" if suffix == "vtt" else "text/plain"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix="."+suffix)
    tmp.write(r.content); tmp.flush(); tmp.close()
    return FileResponse(tmp.name, filename=f"captions_{chosen['lang']}.{suffix}", media_type=media)
