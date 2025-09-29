
# Backend (FastAPI + yt-dlp + ffmpeg)

## 로컬 실행
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
# http://localhost:8000/health  => {"ok": true}
```

## Docker
```bash
docker build -t onesite-api .
docker run --rm -p 8000:8000 onesite-api
```

## 엔드포인트
- `GET /health` → 상태확인
- `POST /api/probe` `{url}` → 메타/포맷/자막요약
- `POST /api/download` `{url, format_id}` → 파일 스트림
- `POST /api/captions` `{url}` → {tracks:[{lang, ext, auto}]}
- `GET /api/captions/download?url=...&lang=ko&ext=vtt` → 자막 파일
