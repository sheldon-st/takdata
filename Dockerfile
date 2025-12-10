FROM python:3.9.6

RUN mkdir /usr/src/app

COPY send.py /usr/src/app
COPY requirements.txt /usr/src/app
COPY certs /usr/src/app/certs

WORKDIR /usr/src/app

RUN pip install -r requirements.txt

CMD ["python", "./send.py"]