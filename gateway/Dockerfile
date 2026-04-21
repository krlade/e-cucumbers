FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 3001
CMD ["python", "manage.py", "runserver", "0.0.0.0:3001"]
