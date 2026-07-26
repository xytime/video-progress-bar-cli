"""Standalone process for the listening helper's private transcription APIs.

# Modification History
| Version | Date       | Author | Description |
| ------- | ---------- | ------ | ----------- |
| 1.0.0   | 2026-07-26 | Codex  | 新增听力助手私有转写服务进程入口 |
"""

from fastapi import FastAPI

from web.listening_transcriber import router


app = FastAPI(title="Listening Transcription Service", version="1.0.0")
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    from config.settings import settings

    uvicorn.run(app, host="127.0.0.1", port=settings.listening_transcriber_port)
