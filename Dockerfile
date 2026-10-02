# Everything runs in here: no toolchain on the host.
#
#   docker build -t morsefun:dev .
#   docker run --rm -v "$PWD":/work -w /work morsefun:dev python -m unittest discover -s tests
#   docker run --rm -p 8080:8080 morsefun:dev            # the web front end
#
# or, for the web front end with a restart policy, see compose.yaml.
FROM python:3.12-slim
WORKDIR /work
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY morsefun ./morsefun
EXPOSE 8080
CMD ["python", "-m", "morsefun.web", "--host", "0.0.0.0", "--port", "8080"]
