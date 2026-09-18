# ARG-070 · Simulated EDC Management API for development. The real connector arrives with F07-16.
FROM python:3.12-alpine
COPY server.py /edc/server.py
USER 10001
EXPOSE 19193
CMD ["python", "/edc/server.py"]
