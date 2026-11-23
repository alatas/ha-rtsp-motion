FROM python:3.14-slim
COPY --from=bluenviron/mediamtx:1.15.0 /mediamtx /usr/local/bin/mediamtx
COPY bench/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /repo/bench
