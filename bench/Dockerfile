# Pins (chosen 2026-11-24, each at least two weeks old): Python 3.14.9 on Debian trixie
# (published 2026-10-24), libturbojpeg0 as in trixie. Bump them together on purpose.
FROM python:3.14.9-slim-trixie
COPY --from=bluenviron/mediamtx:1.15.0 /mediamtx /usr/local/bin/mediamtx
RUN apt-get update && apt-get install -y --no-install-recommends libturbojpeg0=1:2.1.5-4 && rm -rf /var/lib/apt/lists/*
COPY bench/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /repo/bench
