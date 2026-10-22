from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="PayFlex API", version="1.0.0")

# Base de donnees en memoire (suffisant pour le TP)
accounts: dict[str, dict] = {}


class AccountCreate(BaseModel):
    owner: str = Field(min_length=1)
    balance: float = Field(default=0, ge=0)


class TransferRequest(BaseModel):
    from_id: str
    to_id: str
    amount: float = Field(gt=0)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/accounts", status_code=201)
def create_account(data: AccountCreate):
    account_id = str(uuid4())
    accounts[account_id] = {
        "id": account_id,
        "owner": data.owner,
        "balance": data.balance,
    }
    return accounts[account_id]


@app.get("/accounts/{account_id}")
def get_account(account_id: str):
    if account_id not in accounts:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    return accounts[account_id]


@app.post("/transfers")
def transfer(data: TransferRequest):
    source = accounts.get(data.from_id)
    target = accounts.get(data.to_id)

    if source is None or target is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    if data.from_id == data.to_id:
        raise HTTPException(status_code=400, detail="Comptes identiques")
    if source["balance"] < data.amount:
        raise HTTPException(status_code=400, detail="Solde insuffisant")

    source["balance"] -= data.amount
    target["balance"] += data.amount
    return {
        "status": "success",
        "from_balance": source["balance"],
        "to_balance": target["balance"],
    }