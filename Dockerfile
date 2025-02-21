FROM python:3.12

RUN pip install google-cloud-bigquery requests

ADD main.py .

CMD ["python", "./main.py"] 