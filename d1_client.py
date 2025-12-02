import os
import json
import requests
from typing import Dict, Any, Optional
from dotenv import load_dotenv,find_dotenv
load_dotenv(find_dotenv())

class D1Client:
    def __init__(self):
        self.api_token = os.getenv("CF_DB_APIKEY")
        self.database_id = os.getenv("CLOUDFLARE_DATABASE_ID")
        self.account_id = os.getenv("CF_ACCOUNT_ID")
        
        if not all([self.api_token, self.database_id, self.account_id]):
            raise ValueError("Missing required environment variables: CF_DB_APIKEY, CLOUDFLARE_DATABASE_ID, CF_ACCOUNT_ID")
            
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/d1/database/{self.database_id}/query"
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    def execute(self, sql: str, params: list = None) -> Dict[str, Any]:
        payload = {"sql": sql}
        if params:
            payload["params"] = params
            
        response = requests.post(self.base_url, headers=self.headers, json=payload)
        response.raise_for_status()
        
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            error_msg = "; ".join([e.get("message", "Unknown error") for e in errors])
            raise Exception(f"D1 Query failed: {error_msg}")
            
        return data

    def fetch_all(self, sql: str, params: list = None) -> list:
        data = self.execute(sql, params)
        # D1 response structure usually has 'result' which is a list of results (one per query)
        # Each result has 'results' which is the list of rows
        if not data.get("result"):
            return []
            
        # Assuming single query execution
        return data["result"][0].get("results", [])

    def fetch_one(self, sql: str, params: list = None) -> Optional[Dict[str, Any]]:
        rows = self.fetch_all(sql, params)
        if rows:
            return rows[0]
        return None
