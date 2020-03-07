import requests
import json
import time
import os
import asyncio
import aiohttp

start = time.time()
http_timeout = 2

async def fx_for(symbol_to):
    async with aiohttp.ClientSession() as async_session:
        response = await async_session.get(
        "https://www.alphavantage.co/query",
        timeout=http_timeout,
            params={
            'function': 'CURRENCY_EXCHANGE_RATE',
            'from_currency': 'USD',
            'to_currency': symbol_to,
            'apikey': ''
            }
        )
        api_result = await response.json()
        return api_result

symbol_list = ["KRW",
        "EUR",
        "CNY",
        "JPY",
        "XDR",
        "MNT"]

loop = asyncio.get_event_loop()
futures = [fx_for(symbol_lists) for symbol_lists in symbol_list]
api_result = loop.run_until_complete(asyncio.gather(*futures))

result_real_fx = {
    "USDUSD": 1.0,
    "USDKRW": 1.0,
    "USDEUR": 1.0,
    "USDCNY": 1.0,
    "USDJPY": 1.0,
    "USDSDR": 1.0,
    "USDMNT": 1.0
}

list_number = 0
for symbol in symbol_list:
    if symbol == "XDR":
        symbol = "SDR"
    result_real_fx["USD"+symbol] = float(
        api_result[list_number]["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
    list_number = list_number +1 
print("time :", time.time() - start)
print(result_real_fx)
