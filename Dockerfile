# Chaldea - Hỏi đáp trên bảng tính Excel (đội AI26C0102)
# Ảnh Linux amd64, chỉ dùng CPU (không GPU), chứa sẵn mã nguồn và thư viện.
#
# Build:  docker build --platform linux/amd64 -t ai26c0102 .
# Chạy :  docker run --rm -e OPENROUTER_API_KEY=<key> -v <thư_mục_dữ_liệu>:/data ai26c0102 --input /data --output /data/submission.csv
# Ảnh gốc cố định phiên bản (Python 3.12.15, Debian 13) để môi trường chấm giống hệt môi trường đã kiểm thử
FROM python:3.12.15-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

# Cài thư viện trước (tận dụng cache khi chỉ đổi mã nguồn)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Mã nguồn (API key KHÔNG nằm trong ảnh: truyền bằng biến môi trường OPENROUTER_API_KEY khi chạy)
COPY main.py .
COPY chaldea/ ./chaldea/

# Tham số chấm truyền thẳng vào main.py, ví dụ: --input /data --output /data/submission.csv
# Không truyền tham số: tự tìm queries.json trong /data, /input, /code, ... và ghi submission.csv cạnh nó
# (hoặc vào /output nếu thư mục này được mount).
ENTRYPOINT ["python", "/app/main.py"]
