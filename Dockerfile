# 1. Use a lightweight Python 3.11 image (The Nana 'Production' standard)
FROM python:3.11-slim

# 2. Prevent Python from buffering logs (Important for cloud observability)
ENV PYTHONUNBUFFERED=1

# 3. Set the working directory inside the container
WORKDIR /app

# 4. Copy requirements first to take advantage of Docker layer caching
COPY requirements.txt .

# 5. Install the 'Suppliers' (dependencies)
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy the entire 'Laptop' (source code) into the container
COPY . .

# 7. Expose the port our Motherboard (FastAPI) listens on
EXPOSE 8000

# 8. The command to start the system
CMD ["python", "entrypoints.py"]