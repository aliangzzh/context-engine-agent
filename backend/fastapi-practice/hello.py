from fastapi import FastAPI

app = FastAPI(title="我的第一个 FastAPI")


@app.get("/hello")
def hello():
    return {"msg": "hello fastapi"}
