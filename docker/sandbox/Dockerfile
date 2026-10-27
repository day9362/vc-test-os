# docker.io 在这台机器上连不上，用同一份 python:3.12-slim 的镜像源。
FROM docker.m.daocloud.io/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    MPLCONFIGDIR=/tmp

RUN pip install --no-cache-dir pandas==2.2.3 matplotlib==3.9.2

COPY runner.py /opt/runner/runner.py
