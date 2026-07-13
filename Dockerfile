# Single runtime stage -- no compiled extensions of our own to build, and
# keeping one stage keeps this simple for a single-user local tool.
FROM python:3.11-slim-bookworm

# Runtime system libs:
#  - libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0: WeasyPrint's
#    text/graphics rendering stack (see README "Setup"). Package is
#    libgdk-pixbuf-2.0-0 on bookworm/noble -- the old libgdk-pixbuf2.0-0 name is
#    now a transitional package pointing at this one.
#  - fonts-dejavu-core: slim images ship no fonts at all; WeasyPrint needs at
#    least one real font family on the system font stack to render text.
#  - tesseract-ocr tesseract-ocr-eng ghostscript: OCR path for scanned PDFs
#    (see README "Setup" / ocrmypdf). Without these the app still runs; it
#    just rejects scanned PDFs with a clear error instead of OCRing them.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        fonts-dejavu-core \
        tesseract-ocr \
        tesseract-ocr-eng \
        ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only what pip needs to resolve/build the package first, so dependency
# layers stay cached across source-only edits.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Non-root user; owns /app (including the jobs dir it creates at runtime) so
# uploads/outputs work with either the named volume or a bind mount from the
# compose file.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin remediate \
    && mkdir -p /app/jobs \
    && chown -R remediate:remediate /app
USER remediate

VOLUME ["/app/jobs"]

EXPOSE 8000

CMD ["uvicorn", "remediate.app:app", "--host", "0.0.0.0", "--port", "8000"]
