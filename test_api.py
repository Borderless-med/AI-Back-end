import requests
url = "http://localhost:8000/chat"
payload = {
    "history": [{"role": "user", "content": "Hello, I need a dental clinic"}]
}
response = requests.post(url, json=payload)
print(response.json())