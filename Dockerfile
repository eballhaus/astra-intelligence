# ===============================================
# Astra Intelligence – Phase-90 Stable Dockerfile
# ===============================================

FROM python:3.12-slim

# 1. Working directory
WORKDIR /app

# 2. Copy files
COPY . /app

# 3. Install Poetry
RUN pip install --no-cache-dir poetry

# 4. Ensure Poetry creates venv inside container
RUN poetry config virtualenvs.in-project true

# 5. Install dependencies
RUN poetry install --no-root

# 6. Load environment variables
ENV PYTHONUNBUFFERED=1
ENV POETRY_VIRTUALENVS_IN_PROJECT=true

# 7. Expose Streamlit port
EXPOSE 8501

# 8. Launch Astra
CMD [ "poetry", "run", "streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0" ]

