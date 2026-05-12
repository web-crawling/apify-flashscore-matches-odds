FROM apify/actor-python:3.14

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
