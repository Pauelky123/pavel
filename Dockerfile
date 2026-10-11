FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ARENA_DB=/data/arena.sqlite3 ARENA_HOST=0.0.0.0 ARENA_PORT=8000
WORKDIR /app
COPY --chown=10001:10001 arena ./arena
COPY --chown=10001:10001 data ./data
RUN useradd --uid 10001 --create-home arena && mkdir /data && chown arena:arena /data
USER arena
CMD ["python", "-m", "arena.api"]
