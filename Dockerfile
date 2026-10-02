# Everything runs in here: no toolchain on the host.
#   docker build -t morsefun:dev .
#   docker run --rm -v "$PWD":/work -w /work morsefun:dev python -m unittest discover -s tests
FROM python:3.12-slim
WORKDIR /work
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONDONTWRITEBYTECODE=1
