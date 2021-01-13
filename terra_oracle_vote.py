#!/usr/bin/python3 -u
# -*- coding: utf-8 -*-
"""
Autovoting script for Terra oracle by B-Harvest
https://github.com/b-harvest/terra_oracle_voter

WARNING : this script is for terra blockchain with version v0.3.0+ only
"""

import hashlib
import json
import logging
import multiprocessing
import concurrent.futures
import os
import subprocess
import time
import functools
import asyncio

# External libraries - installation required:
#  pip3 install --user -r requirements.txt
#
import requests
from prometheus_client import start_http_server, Summary, Counter, Gauge, Histogram
import aiohttp
import statistics
from pyband.obi import PyObi
from pyband.client import Client

# User setup

# Slack webhook
slackurl = os.getenv("SLACK_URL", "")
telegram_token = os.getenv("TELEGRAM_TOKEN", "")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
# https://www.alphavantage.co/
alphavantage_key = os.getenv("ALPHAVANTAGE_KEY", "")
# no using alphavantage
fx_api_option = os.getenv("FX_API_OPTION", "alphavantage,free_api,band")
# stop oracle when price change exceeds stop_oracle_trigger
stop_oracle_trigger_recent_diverge = float(os.getenv("STOP_ORACLE_RECENT_DIVERGENCE", "999999999999"))
# stop oracle when price change exceeds stop_oracle_trigger
stop_oracle_trigger_exchange_diverge = float(os.getenv("STOP_ORACLE_EXCHANGE_DIVERGENCE", "0.1"))
# vote negative price when bid-ask price is wider than bid_ask_spread_max
bid_ask_spread_max = float(os.getenv("BID_ASK_SPREAD_MAX", "0.05"))
# oracle feeder address
feeder = os.getenv("FEEDER_ADDRESS", "")
# validator address
validator = os.getenv("VALIDATOR_ADDRESS", "")
key_name = os.getenv("KEY_NAME", "")
key_password = os.getenv("KEY_PASSWORD", "").encode()
fee_denom = os.getenv("FEE_DENOM", "ukrw")
fee_gas = os.getenv("FEE_GAS", "170000")
fee_amount = os.getenv("FEE_AMOUNT", "356200")
home_cli = os.getenv("HOME_CLI", "/home/ubuntu/.terracli")
# node to broadcast the txs
node = os.getenv("NODE_RPC", "tcp://127.0.0.1:26657")
# path to terracli binary
terracli = os.getenv("TERRACLI_BIN", "sudo /home/ubuntu/go/bin/terracli")
# lcd to receive swap price information
lcd_address = os.getenv("TERRA_LCD", "https://lcd.terra.dev")
# default coinone weight
coinone_share_default = float(os.getenv("COINONE_SHARE_DEFAULT", "1.0"))
# default bithumb weight
bithumb_share_default = float(os.getenv("BITHUMB_SHARE_DEFAULT", "0"))
# default gopax weight
gopax_share_default = float(os.getenv("GOPAX_SHARE_DEFAULT", "0"))
# default gdac weight
gdac_share_default = float(os.getenv("GDAC_SHARE_DEFAULT", "0"))
price_divergence_alert = os.getenv("PRICE_ALERTS", "false") == "true"
vwma_period = int(os.getenv("VWMA_PERIOD", str(3 * 600)))  # in seconds
misses = int(os.getenv("MISSES", "0"))
alertmisses = os.getenv("MISS_ALERTS", "true") == "true"
debug = os.getenv("DEBUG", "false") == "true"
metrics_port = os.getenv("METRICS_PORT", "19000")
band_endpoint = os.getenv("BAND_ENDPOINT", "https://poa-api.bandchain.org")
band_luna_price_params = os.getenv("BAND_LUNA_PRICE_PARAMS", "19,1_000_000,3,4")

METRIC_MISSES = Gauge("terra_oracle_misses_total", "Total number of oracle misses")
METRIC_HEIGHT = Gauge("terra_oracle_height", "Block height of the LCD node")
METRIC_VOTES = Counter("terra_oracle_votes", "Counter of oracle votes")

METRIC_MARKET_PRICE = Gauge("terra_oracle_market_price", "Last market price", ['denom'])
METRIC_SWAP_PRICE = Gauge("terra_oracle_swap_price", "Last swap price", ['denom'])

METRIC_EXCHANGE_ASK_PRICE = Gauge("terra_oracle_exchange_ask_price", "Exchange ask price", ['exchange', 'denom'])
METRIC_EXCHANGE_MID_PRICE = Gauge("terra_oracle_exchange_mid_price", "Exchange mid price", ['exchange', 'denom'])
METRIC_EXCHANGE_BID_PRICE = Gauge("terra_oracle_exchange_bid_price", "Exchange bid price", ['exchange', 'denom'])

METRIC_OUTBOUND_ERROR = Counter("terra_oracle_request_errors", "Outbound HTTP request error count", ["remote"])
METRIC_OUTBOUND_LATENCY = Histogram("terra_oracle_request_latency", "Outbound HTTP request latency", ["remote"])

# parameters
fx_map = {
    "uusd": "USDUSD",
    "ukrw": "USDKRW",
    "usdr": "USDSDR",
    "umnt": "USDMNT",
    "ueur": "USDEUR"
}
active_candidate = [
    "uusd",
    "ukrw",
    "usdr",
    "umnt",
    "ueur"
]

# hardfix the active set. does not care about stop_oracle_trigger_recent_diverge
hardfix_active_set = [
    "uusd",
    "ukrw",
    "usdr",
    "umnt",
    "ueur"
]

# denoms for abstain votes. it will vote abstain for all denoms in this list.
abstain_set = [
    #"uusd",
    #"ukrw",
    #"usdr",
    #"umnt"
]

chain_id = os.getenv("CHAIN_ID", "columbus-4")
round_block_num = 5.0

# set last update time
last_height = 0

logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
logger = logging.root

# By default, python-requests does not use a timeout. We need to specify
# a timeout on each call to ensure we never get stuck in network IO.
http_timeout = 4

# Separate timeout for alerting calls
alert_http_timeout = 4

# Global requests session for HTTP/1.1 keepalive
# (unfortunately, the timeout cannot be set globally)
session = requests.session()

# Be friendly to the APIs we use and specify a user-agent
session.headers['User-Agent'] = "bharvest-oracle-voter/0 (+https://github.com/b-harvest/terra_oracle_voter)"

# Start metrics server in a background thread
start_http_server(int(metrics_port))

def time_request(remote):
    """Returns a decorator that measures execution time."""
    return METRIC_OUTBOUND_LATENCY.labels(remote).time()

@time_request('telegram')
def telegram(message):
    if not telegram_token:
        return

    try:
        requests.post(
            "https://api.telegram.org/bot{}/sendMessage".format(telegram_token),
            json={
                'chat_id': telegram_chat_id,
                'text': message
            },
            timeout=alert_http_timeout
        )
    except:
        logging.exception("Error while sending telegram alert")

@time_request('slack')
def slack(message):
    if not slackurl:
        return

    try:
        requests.post(slackurl, json={"text": message}, timeout=alert_http_timeout)
    except:
        METRIC_OUTBOUND_ERROR.labels('slack').inc()
        logging.exception("Error while sending Slack alert")

@time_request('lcd')
def get_current_misses():
    try:
        result = session.get(
            "{}/oracle/voters/{}/miss".format(lcd_address, validator),
            timeout=http_timeout).json()
        misses = int(result["result"])
        height = int(result["height"])
        return misses, height
    except:
        METRIC_OUTBOUND_ERROR.labels('lcd').inc()
        logging.exception("Error in get_current_misses")
        return 0, 0

@time_request('lcd')
def get_current_prevotes(denom):
    try:
        return session.get(
            "{}/oracle/denoms/{}/prevotes".format(lcd_address, denom),
            timeout=http_timeout).json()
    except:
        METRIC_OUTBOUND_ERROR.labels('lcd').inc()
        logging.exception("Error in get_current_prevotes")
        return False

@time_request('lcd')
def get_current_votes(denom):
    try:
        result = session.get(
            "{}/oracle/denoms/{}/votes".format(lcd_address, denom),
            timeout=http_timeout).json()
        return result
    except:
        METRIC_OUTBOUND_ERROR.labels('lcd').inc()
        logging.exception("Error in get_current_votes")
        return False

@time_request('lcd')
def get_my_current_prevotes():
    try:
        result = session.get(
            "{}/oracle/voters/{}/prevotes".format(lcd_address, validator),
            timeout=http_timeout).json()
        result_vote = []
        for vote in result["result"]:
            if str(vote["voter"]) == str(validator):
                result_vote.append(vote)
        return result_vote
    except:
        METRIC_OUTBOUND_ERROR.labels('lcd').inc()
        logging.exception("Error in get_my_current_prevotes")
        return False

# get latest block info
@time_request('lcd')
def get_latest_block():
    err_flag = False
    try:
        result = session.get("{}/blocks/latest".format(lcd_address), timeout=http_timeout).json()
        latest_block_height = int(result["block"]["header"]["height"])
        latest_block_time = result["block"]["header"]["time"]
    except:
        METRIC_OUTBOUND_ERROR.labels('lcd').inc()
        logger.exception("Error in get_latest_block")
        err_flag = True
        latest_block_height = None
        latest_block_time = None

    return err_flag, latest_block_height, latest_block_time

'''Option, receive sdr with paid service switch.
# get real sdr rates
@time_request('imf')
def get_sdr_rate():
    err_flag = False
    try:
        # get sdr
        url = "https://www.imf.org/external/np/fin/data/rms_five.aspx?tsvflag=Y"
        data = session.get(url, timeout=http_timeout).text
        result_sdr_rate = next(filter(lambda x: x.startswith("U.S. dollar"),
                                      data.splitlines())).split('\t')[2]
    except:
        METRIC_OUTBOUND_ERROR.labels('imf').inc()
        logging.exception("Error in get_sdr_rate")
        err_flag = True
        result_sdr_rate = None
    return err_flag, result_sdr_rate
'''

# get currency rate async def
async def fx_for(symbol_to):
    try:
        async with aiohttp.ClientSession() as async_session:
            async with  async_session.get(
            "https://www.alphavantage.co/query",
            timeout=http_timeout,
                params={
                'function': 'CURRENCY_EXCHANGE_RATE',
                'from_currency': 'USD',
                'to_currency': symbol_to,
                'apikey': alphavantage_key
                }
            ) as response:
                api_result = await response.json(content_type=None)
            return api_result
    except:
            print("for_fx_error")
            
# get currency rate async def
async def fx_for_free(symbol_to):
    try:
        async with aiohttp.ClientSession() as async_session:
            async with  async_session.get(
            "https://api.exchangerate.host/latest",
            timeout=http_timeout,
                params={
                'base': 'USD',
                'symbols': symbol_to
                }
            ) as response:
                api_result = await response.json(content_type=None)
            return api_result
    except:
            print("for_fx_error")

# get real fx rates
@time_request('alphavantage')
def get_fx_rate():
    err_flag = False
    try:
        # get currency rate
        symbol_list = ["KRW",
                "EUR",
                "CNY",
                "JPY",
                "XDR",
                "MNT"]

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
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
    except:
        METRIC_OUTBOUND_ERROR.labels('alphavantage').inc()
        logger.exception("Error in get_fx_rate")
        err_flag = True
        result_real_fx = None

    return err_flag, result_real_fx

#"fx_for" has been merged.
@time_request('band-fx')
def get_fx_rate_from_band():
    err_flag = False
    result_real_fx = None
    try:
        result_real_fx = {"USDUSD": 1.0}
        symbol_list = ["KRW","EUR","CNY","JPY","XDR","MNT"]
        prices = requests.post(
            f"{band_endpoint}/oracle/request_prices",
            json={"symbols":symbol_list,"min_count":3,"ask_count":4}
        ).json()['result']

        for (symbol, price) in zip(symbol_list,prices):
            if symbol == "XDR":
                symbol = "SDR"
            result_real_fx["USD"+symbol] = int(price['multiplier'],10) / int(price['px'],10)
    except:
        METRIC_OUTBOUND_ERROR.labels('band-fx').inc()
        logger.exception("Error in def get_fx_rate_from_band")
        err_flag = True

    return err_flag, result_real_fx

# get real fx rates
@time_request('exchangerateapi')
def get_fx_rate_free():
    err_flag = False
    try:
        # get currency rate
        symbol_list = ["KRW",
                "EUR",
                "CNY",
                "JPY",
                "XDR",
                "MNT"]

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        futures = [fx_for_free(symbol_lists) for symbol_lists in symbol_list]
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
            fx_symbol="USD"+symbol
            if symbol == "XDR":
                fx_symbol = "USDSDR"
            result_real_fx[fx_symbol] = float(
                api_result[list_number]["rates"][symbol])
            list_number = list_number +1 
    except:
        METRIC_OUTBOUND_ERROR.labels('exchangerateapi').inc()
        logger.exception("Error in get_fx_rate_free")
        err_flag = True
        result_real_fx = None

    return err_flag, result_real_fx


# combine all fx rate from sources
def combine_fx(res_fxs):
    fx_combined = {
        "USDUSD":[],
        "USDKRW":[],
        "USDEUR":[],
        "USDCNY":[],
        "USDJPY":[],
        "USDSDR":[],
        "USDMNT":[]
    }
    all_fx_err_flag = True
    for res_fx in res_fxs:
        err_flag, fx = res_fx.result()
        all_fx_err_flag = all_fx_err_flag and err_flag
        if not err_flag:
            for key in fx_combined:
                if key in fx:
                    fx_combined[key].append(fx[key])
    for key in fx_combined:
        if len(fx_combined[key]) > 0:
            fx_combined[key] = statistics.median(fx_combined[key])
        else:
            fx_combined[key] = None
            all_fx_err_flag = True
    return all_fx_err_flag, fx_combined

# get coinone luna krw price
@time_request('coinone')
def get_coinone_luna_price():
    err_flag = False
    try:
        if vwma_period > 1:
            url = "https://api.coinone.co.kr/trades/?currency=luna"
            luna_result = session.get(url, timeout=http_timeout).json()["completeOrders"]
            hist_price = []
            sum_price_volume = 0
            sum_volume = 0
            now_time = float(time.time())

            for row in luna_result:
                if now_time - float(row['timestamp']) < vwma_period:
                    sum_price_volume += float(row["price"]) * float(row["qty"])
                    sum_volume += float(row["qty"])
                else:
                    break

            askprice = sum_price_volume / sum_volume
            bidprice = sum_price_volume / sum_volume
        else:
            url = "https://api.coinone.co.kr/orderbook/?currency=luna&format=json"
            luna_result = session.get(url, timeout=http_timeout).json()
            askprice = float(luna_result["ask"][0]["price"])
            bidprice = float(luna_result["bid"][0]["price"])
        midprice = (askprice + bidprice) / 2.0
        luna_price = {
            "base_currency": "ukrw",
            "exchange": "coinone",
            "askprice": askprice,
            "bidprice": bidprice,
            "midprice": midprice
        }
        luna_base = "USDKRW"
        luna_midprice_krw = float(luna_price["midprice"])
    except:
        METRIC_OUTBOUND_ERROR.labels('coinone').inc()
        logger.exception("Error in get_coinone_luna_price")
        err_flag = True
        luna_price = None
        luna_base = None
        luna_midprice_krw = None

    return err_flag, luna_price, luna_base, luna_midprice_krw


# get bithumb luna krw price
@time_request('bithumb')
def get_bithumb_luna_price():
    err_flag = False
    try:
        # get luna/krw
        url = "https://api.bithumb.com/public/orderbook/luna_krw"
        luna_result = session.get(url, timeout=http_timeout).json()["data"]
        askprice = float(luna_result["asks"][0]["price"])
        bidprice = float(luna_result["bids"][0]["price"])
        midprice = (askprice + bidprice) / 2.0
        luna_price = {
            "base_currency": "ukrw",
            "exchange": "bithumb",
            "askprice": askprice,
            "bidprice": bidprice,
            "midprice": midprice
        }
        luna_base = "USDKRW"
        luna_midprice_krw = float(luna_price["midprice"])
    except:
        METRIC_OUTBOUND_ERROR.labels('bithumb').inc()
        logger.exception("Error in get_bithumb_luna_price")
        err_flag = True
        luna_price = None
        luna_base = None
        luna_midprice_krw = None

    return err_flag, luna_price, luna_base, luna_midprice_krw


# get gopax luna krw price
@time_request('gopax')
def get_gopax_luna_price():
    err_flag = False
    try:
        # get luna/krw
        url = "https://api.gopax.co.kr/trading-pairs/LUNA-KRW/book"
        luna_result = session.get(url, timeout=http_timeout).json()
        askprice = float(luna_result["ask"][0][1])
        bidprice = float(luna_result["bid"][0][1])
        midprice = (askprice + bidprice) / 2.0
        luna_price = {
            "base_currency": "ukrw",
            "exchange": "gopax",
            "askprice": askprice,
            "bidprice": bidprice,
            "midprice": midprice
        }
        luna_base = "USDKRW"
        luna_midprice_krw = float(luna_price["midprice"])
    except:
        METRIC_OUTBOUND_ERROR.labels('gopax').inc()
        logger.exception("Error in get_gopax_luna_price")
        err_flag = True

        # gopax_share is set to zero if an error occurs
        luna_price = 0
        luna_base = 0
        luna_midprice_krw = 0

    return err_flag, luna_price, luna_base, luna_midprice_krw


# get gdac luna krw price
@time_request('gdac')
def get_gdac_luna_price():
    err_flag = False
    try:
        # get luna/krw
        url = "https://partner.gdac.com/v0.4/public/orderbook?pair=LUNA%2FKRW"
        luna_result = session.get(url, timeout=http_timeout).json()
        askprice = float(luna_result["ask"][0]["price"])
        bidprice = float(luna_result["bid"][0]["price"])
        midprice = (askprice + bidprice) / 2.0
        luna_price = {
            "base_currency": "ukrw",
            "exchange": "gdac",
            "askprice": askprice,
            "bidprice": bidprice,
            "midprice": midprice
        }
        luna_base = "USDKRW"
        luna_midprice_krw = float(luna_price["midprice"])
    except:
        METRIC_OUTBOUND_ERROR.labels('gdax').inc()
        logger.exception("Error in get_gdac_luna_price")
        err_flag = True

        # gdac_share is set to zero if an error occurs
        luna_price = 0
        luna_base = 0
        luna_midprice_krw = 0

    return err_flag, luna_price, luna_base, luna_midprice_krw


# get band luna krw price
@time_request('band-luna')
def get_band_luna_price():
    coinone, bithumb, gdac, gopax = None, None, None, None
    try:
        oracle_script_id,multiplier,min_count,ask_count = [int(param,10) for param in band_luna_price_params.split(",")]
        exchanges = ["coinone","bithumb","gdac","gopax"]
        bandcli = Client(band_endpoint)
        schema = bandcli.get_oracle_script(oracle_script_id).schema
        obi = PyObi(schema)
        result = obi.decode_output(
            bandcli.get_latest_request(
                oracle_script_id,
                obi.encode_input({
                    "exchanges":exchanges,
                    "base_symbol":"LUNA",
                    "quote_symbol":"KRW",
                    "multiplier":multiplier
                }),
                min_count,
                ask_count
            ).result.response_packet_data.result
        )
        abms = []
        for (order_book,ex) in zip(result['order_books'],exchanges):
            abm = None
            if order_book['ask'] > 0 and order_book['bid'] > 0 and order_book['mid'] > 0:
                luna_price = {
                    "base_currency": "ukrw",
                    "exchange": f"band_{ex}",
                    "askprice": order_book['ask']/multiplier,
                    "bidprice": order_book['bid']/multiplier,
                    "midprice": order_book['mid']/multiplier
                }
                luna_base = "USDKRW"
                luna_midprice_krw = order_book['mid']/multiplier
                abm = (luna_price, luna_base, luna_midprice_krw)
            abms.append(abm)
        coinone, bithumb, gdac, gopax = abms
    except:
        METRIC_OUTBOUND_ERROR.labels('band-luna').inc()
        logger.exception("Error in get_band_luna_price")

    return coinone, bithumb, gdac, gopax


# get swap price
@time_request('lcd')
def get_swap_price():
    err_flag = False
    try:
        result = session.get(
            "{}/oracle/denoms/exchange_rates".format(lcd_address),
            timeout=http_timeout).json()
    except:
        METRIC_OUTBOUND_ERROR.labels('lcd').inc()
        logger.exception("Error in get_swap_price")
        result = {"result":[]}
        err_flag = True

    return err_flag, result


def get_hash(salt, price, denom, validator):
    m = hashlib.sha256()
    m.update("{}:{}:{}:{}".format(salt, price, denom, validator).encode('utf-8'))
    result = m.hexdigest()[:40]
    return result


def get_salt(string):
    b_string = str(string).encode('utf-8')
    return str(hashlib.sha256(b_string).hexdigest())[:4]


def broadcast_messages(messages):
    tx_json = {
        "type": "core/StdTx",
        "value": {
            "msg": messages,
            "fee": {
                "amount": [
                    {
                        "denom": fee_denom,
                        "amount": fee_amount
                    }
                ],
                "gas": fee_gas
            },
            "signatures": [],
            "memo": ""
        }
    }

    logger.info("Signing...")
    json.dump(tx_json, open("tx_oracle_prevote.json", 'w'))

    cmd_output = subprocess.check_output([
        terracli,
        "tx", "sign", "tx_oracle_prevote.json",
        "--from", key_name,
        "--chain-id", chain_id,
        "--home", home_cli,
        "--node", node
    ], input=key_password + b'\n' + key_password + b'\n').decode()

    tx_json_signed = json.loads(cmd_output)
    json.dump(tx_json_signed, open("tx_oracle_prevote_signed.json", 'w'))

    logger.info("Broadcasting...")
    cmd_output = subprocess.check_output([
        terracli,
        "tx", "broadcast", "tx_oracle_prevote_signed.json",
        "--output", "json",
        "--from", key_name,
        "--chain-id", chain_id,
        "--home", home_cli,
        "--node", node,
    ], input=key_password + b'\n' + key_password + b'\n').decode()

    return json.loads(cmd_output)


def broadcast_prevote(hash):
    logger.info("Prevoting...")

    return broadcast_messages([
        {
            "type": "oracle/MsgExchangeRatePrevote",
            "value": {
                "hash": str(hash[denom]),
                "denom": str(denom),
                "feeder": feeder,
                "validator": validator
            }
        } for denom in active
    ])


def broadcast_all(vote_price, vote_salt, prevote_hash):
    logger.info("Prevoting and voting...")
    return broadcast_messages(
        [
            {
                "type": "oracle/MsgExchangeRateVote",
                "value": {
                    "exchange_rate": str(vote_price[denom]),
                    "salt": str(vote_salt[denom]),
                    "denom": denom,
                    "feeder": feeder,
                    "validator": validator
                }
            } for denom in active
        ] + [
            {
                "type": "oracle/MsgExchangeRatePrevote",
                "value": {
                    "hash": str(prevote_hash[denom]),
                    "denom": str(denom),
                    "feeder": feeder,
                    "validator": validator
                }
            } for denom in active
        ])


main_err_flag = True
while main_err_flag:
    latest_block_err_flag, latest_block_height, latest_block_time = get_latest_block()
    if latest_block_err_flag == False:
        height = latest_block_height
        if height > last_height:
            main_err_flag = False
            last_height = height
    time.sleep(1)

last_prevoted_round = 0
last_active = []
last_hash = []

while True:

    main_err_flag = True
    while main_err_flag:
        latest_block_err_flag, latest_block_height, latest_block_time = get_latest_block()
        if latest_block_err_flag == False:
            height = latest_block_height
            if height > last_height:
                main_err_flag = False
                last_height = height
        time.sleep(1)

    current_round = int(float(height - 1) / round_block_num)
    next_height_round = int(float(height) / round_block_num)

    num_blocks_till_next_round = (current_round + 1) * round_block_num - height

    logger.debug("current_round: %d", current_round)
    logger.debug("next_height_round: %d", next_height_round)
    logger.debug("last_prevoted_round: %d", last_prevoted_round)
    logger.debug("height: %d", height)
    logger.debug("num_blocks_till_next_round: %d", num_blocks_till_next_round)

    if next_height_round > last_prevoted_round and (
            num_blocks_till_next_round == 0 or num_blocks_till_next_round > 3):

        # Get external data
        all_err_flag = False
        ts = time.time()

        fx_api_collection = {
            "alphavantage": get_fx_rate,
            "free_api": get_fx_rate_free,
            "band": get_fx_rate_from_band
        }

        with concurrent.futures.ThreadPoolExecutor() as executor:
            res_swap = executor.submit(get_swap_price)
            res_fxs = []
            for fx_key in fx_api_option.split(","):
                res_fxs.append( executor.submit(fx_api_collection[fx_key]))
            #res_sdr = executor.submit(get_sdr_rate) sdr receive Option
            res_coinone = executor.submit(get_coinone_luna_price)
            res_bithumb = executor.submit(get_bithumb_luna_price)
            res_gopax = executor.submit(get_gopax_luna_price)
            res_gdac = executor.submit(get_gdac_luna_price)
            res_band = executor.submit(get_band_luna_price)

        def metrics_for_result(exchange, result):
            if result:
                METRIC_EXCHANGE_ASK_PRICE.labels(exchange, result['base_currency']).set(result['askprice'])
                METRIC_EXCHANGE_BID_PRICE.labels(exchange, result['base_currency']).set(result['bidprice'])
                METRIC_EXCHANGE_MID_PRICE.labels(exchange, result['base_currency']).set(result['midprice'])

        metrics_for_result('coinone', res_coinone.result()[1])
        metrics_for_result('bithumb', res_bithumb.result()[1])
        metrics_for_result('gopax', res_gopax.result()[1])
        metrics_for_result('res_gdac', res_gdac.result()[1])

        for rb in res_band.result():
            if rb:
                metrics_for_result(rb[0]['exchange'], rb[0])

        # Get active set of denoms
        swap_price_err_flag, swap_price = res_swap.result()

        if swap_price["result"] is None:
            swap_price["result"] = []

        if len(hardfix_active_set) == 0:
            active = []
            for denom in swap_price["result"]:
                active.append(denom["denom"])
        else:
            active = hardfix_active_set

        logger.info("Active set: {}".format(active))

        # combine fx from all sources
        fx_err_flag, real_fx = combine_fx(res_fxs)

        #sdr_err_flag, sdr_rate = res_sdr.result() sdr receive Option
        coinone_err_flag, coinone_luna_price, coinone_luna_base, coinone_luna_midprice_krw = res_coinone.result()
        bithumb_err_flag, bithumb_luna_price, bithumb_luna_base, bithumb_luna_midprice_krw = res_bithumb.result()
        gopax_err_flag, gopax_luna_price, gopax_luna_base, gopax_luna_midprice_krw = res_gopax.result()
        gdac_err_flag, gdac_luna_price, gdac_luna_base, gdac_luna_midprice_krw = res_gdac.result()

        # extract backup luna price from band
        coinone_backup, bithumb_backup, gdac_backup, gopax_backup = res_band.result()

        coinone_share = coinone_share_default
        bithumb_share = bithumb_share_default
        gopax_share = gopax_share_default
        gdac_share = gdac_share_default

        '''sdr receive Option
        if fx_err_flag or sdr_err_flag or coinone_err_flag or swap_price_err_flag:
            all_err_flag = True
        '''
        if fx_err_flag:
            all_err_flag = True
        if coinone_err_flag or swap_price_err_flag:
            if coinone_backup is None:
                all_err_flag = True
            else:
                coinone_luna_price, coinone_luna_base, coinone_luna_midprice_krw = coinone_backup
        if bithumb_err_flag:
            if bithumb_backup is None:
                bithumb_share = 0
            else:
                bithumb_luna_price, bithumb_luna_base, bithumb_luna_midprice_krw = bithumb_backup
        if gopax_err_flag:
            if gdac_backup is None:
                gopax_share = 0
            else:
                gopax_luna_price, gopax_luna_base, gopax_luna_midprice_krw = gopax_backup
        if gdac_err_flag:
            if gopax_backup is None:
                gdac_share = 0
            else:
                gdac_luna_price, gdac_luna_base, gdac_luna_midprice_krw = gdac_backup

        if not all_err_flag:
            #real_fx["USDSDR"] = float(sdr_rate) sdr receive Option

            # ignore bithumb if it diverge from coinone price or its bid-ask price is wider than bid_ask_spread_max
            if bithumb_share > 0:
                if abs(1.0 - float(bithumb_luna_midprice_krw) / float(
                        coinone_luna_midprice_krw)) > stop_oracle_trigger_exchange_diverge or float(
                    bithumb_luna_price["askprice"]) / float(
                    bithumb_luna_price["bidprice"]) - 1 > bid_ask_spread_max:
                    bithumb_share = 0
                    if price_divergence_alert:
                        alarm_content = denom + " market price diversion at height " + str(
                            height) + "! coinone_price:" + str(
                            "{0:.1f}".format(coinone_luna_midprice_krw)) + ", bithumb_price:" + str(
                            "{0:.1f}".format(bithumb_luna_midprice_krw))
                        alarm_content += "(percent_diff:" + str("{0:.4f}".format(
                            (coinone_luna_midprice_krw / bithumb_luna_midprice_krw - 1.0) * 100.0)) + "%)"

                        logger.error(alarm_content)
                        telegram(alarm_content)
                        slack(alarm_content)

            # ignore gopax if it diverge from coinone price or its bid-ask price is wider than bid_ask_spread_max
            if gopax_share > 0:
                if abs(1.0 - float(gopax_luna_midprice_krw) / float(
                        coinone_luna_midprice_krw)) > stop_oracle_trigger_exchange_diverge or float(
                    gopax_luna_price["askprice"]) / float(
                    gopax_luna_price["bidprice"]) - 1 > bid_ask_spread_max:
                    gopax_share = 0
                    if price_divergence_alert:
                        alarm_content = denom + " market price diversion at height " + str(
                            height) + "! coinone_price:" + str(
                            "{0:.1f}".format(coinone_luna_midprice_krw)) + ", gopax_price:" + str(
                            "{0:.1f}".format(gopax_luna_midprice_krw))
                        alarm_content += "(percent_diff:" + str("{0:.4f}".format(
                            (coinone_luna_midprice_krw / gopax_luna_midprice_krw - 1.0) * 100.0)) + "%)"

                        logger.error(alarm_content)
                        telegram(alarm_content)
                        slack(alarm_content)

            # ignore gdac if it diverge from coinone price or its bid-ask price is wider than bid_ask_spread_max
            if gdac_share > 0:
                if abs(1.0 - float(gdac_luna_midprice_krw) / float(
                        coinone_luna_midprice_krw)) > stop_oracle_trigger_exchange_diverge or float(
                    gdac_luna_price["askprice"]) / float(
                    gdac_luna_price["bidprice"]) - 1 > bid_ask_spread_max:
                    gdac_share = 0
                    if price_divergence_alert:
                        alarm_content = denom + " market price diversion at height " + str(
                            height) + "! coinone_price:" + str(
                            "{0:.1f}".format(coinone_luna_midprice_krw)) + ", gdac_price:" + str(
                            "{0:.1f}".format(gdac_luna_midprice_krw))
                        alarm_content += "(percent_diff:" + str("{0:.4f}".format(
                            (coinone_luna_midprice_krw / gdac_luna_midprice_krw - 1.0) * 100.0)) + "%)"

                        logger.error(alarm_content)
                        telegram(alarm_content)
                        slack(alarm_content)

            # vote negative price if coinone bid-ask spread is wider than "bid_ask_spread_max"
            if float(coinone_luna_price["askprice"]) / float(
                    coinone_luna_price["bidprice"]) - 1 > bid_ask_spread_max:
                all_err_flag = True

        if not all_err_flag:
            # Weighted average
            luna_midprice_krw = (
                    (float(coinone_luna_midprice_krw) * coinone_share +
                     float(bithumb_luna_midprice_krw) * bithumb_share +
                     float(gopax_luna_midprice_krw) * gopax_share +
                     float(gdac_luna_midprice_krw) * gdac_share
                     ) / (coinone_share + bithumb_share + gopax_share + gdac_share)
            )

            luna_base = coinone_luna_base

            # reorganize data
            try:
                # get swap price / market price
                swap_price_compare = []

                for currency in active:
                    market_price = float(luna_midprice_krw * (real_fx[fx_map[currency]] / real_fx[luna_base]))
                    this_swap_price = 0.00000001

                    for denom in swap_price["result"]:
                        if denom["denom"] == currency:
                            this_swap_price = float(denom["amount"])
                            break

                    swap_price_compare.append(
                        {"market": currency, "swap_price": this_swap_price, "market_price": market_price})

                result = {
                    "index": int(ts / 60),
                    "timestamp": ts,
                    "block_height": latest_block_height,
                    "block_time": latest_block_time,
                    "swap_price_compare": swap_price_compare,
                    "real_fx": real_fx,
                    "luna_price_list": [coinone_luna_price, bithumb_luna_price, gopax_luna_price]
                }
            except:
                # TODO: how can this fail?
                logger.exception("Reorganize data error")
                all_err_flag = True

        this_price = {}
        this_hash = {}
        this_salt = {}

        for denom in active:
            this_price.update({denom: 0.0})
            this_hash.update({denom: ""})
            this_salt.update({denom: ""})

        if not all_err_flag:

            # prevote for current round
            for denom in active:
                for prices in result["swap_price_compare"]:
                    if prices["market"] == denom:
                        METRIC_MARKET_PRICE.labels(denom).set(prices["market_price"])
                        METRIC_SWAP_PRICE.labels(denom).set(prices["swap_price"])
                        this_denom_err_flag = False
                        if abs(prices["market_price"] / prices[
                            "swap_price"] - 1.0) <= stop_oracle_trigger_recent_diverge:
                            logger.info("Prevoting " + denom + " : " + str(
                                prices["market_price"]) + "(percent_change:" + str("{0:.4f}".format(
                                (prices["market_price"] / prices["swap_price"] - 1.0) * 100.0)) + "%)")
                        else:
                            alarm_content = denom + " price diversion at height " + str(
                                height) + "! market_price:" + str(
                                "{0:.4f}".format(prices["market_price"])) + ", swap_price:" + str(
                                "{0:.4f}".format(prices["swap_price"]))
                            alarm_content += "(percent_change:" + str("{0:.4f}".format(
                                (prices["market_price"] / prices["swap_price"] - 1.0) * 100.0)) + "%)"
                            logger.info(alarm_content)
                            telegram(alarm_content)
                            slack(alarm_content)
                            this_denom_err_flag = True

                        this_salt[denom] = get_salt(str(time.time()))
                        if this_denom_err_flag == False:  # vote negative when this_denom_err_flag == True
                            this_price[denom] = str("{0:.18f}".format(float(prices["market_price"])))
                        else:
                            this_price[denom] = str("{0:.18f}".format(float(0)))
                        this_hash[denom] = get_hash(this_salt[denom], this_price[denom], denom, validator)
                        break

        if all_err_flag:  # vote negative when all_err_flag == True
            for denom in active:
                this_price[denom] = str("{0:.18f}".format(float(0)))
                this_salt[denom] = get_salt(str(time.time()))
                this_hash[denom] = get_hash(this_salt[denom], this_price[denom], denom, validator)
        
        # vote abstain(0) for all denoms in abstain_set
        for denom in abstain_set:
            this_price[denom] = str("{0:.18f}".format(float(0)))
            this_salt[denom] = get_salt(str(time.time()))
            this_hash[denom] = get_hash(this_salt[denom], this_price[denom], denom, validator)

        logger.info("Start voting on height " + str(height + 1))

        # check hash match
        my_current_prevotes = get_my_current_prevotes()

        try:
            if not last_hash:
                hash_match_flag = False
            else:
                hash_match_flag = True

                for vote_hash in last_hash:
                    this_hash_exist = False
                    if my_current_prevotes != bool:
                        for prevote in my_current_prevotes:
                            if str(prevote["hash"]) == vote_hash:
                                this_hash_exist = True
                                break
                    if not this_hash_exist:
                        hash_match_flag = False
                        break
        except:
            logging.exception("check hash match ERROR except")

        if hash_match_flag:  # if all hashes exist
            # broadcast vote/prevote at the same time!
            logger.info("Broadcast votes/prevotes at the same time...")
            broadcast_all(last_price, last_salt, this_hash)
            METRIC_VOTES.inc()
        else:
            logger.info("Broadcast prevotes only...")
            broadcast_prevote(this_hash)

        # update last_prevoted_round
        last_prevoted_round = next_height_round
        last_price = {}
        last_salt = {}
        last_hash = []
        last_active = []
        for denom in active:
            last_price.update({denom: 0.0})
            last_salt.update({denom: ""})
        for denom in active:
            last_price[denom] = this_price[denom]
            last_salt[denom] = this_salt[denom]
            last_active.append(denom)
            last_hash.append(this_hash[denom])
        last_swap_price = []
        for item in swap_price:
            last_swap_price.append(item)

        # Get last amount of misses, if this increased message telegram
        currentmisses, currentheight = get_current_misses()

        METRIC_HEIGHT.set(currentheight)
        METRIC_MISSES.set(currentmisses)

        if currentheight > 0:
            misspercentage = round(float(currentmisses) / float(currentheight) * 100, 2)
            logger.info("Current miss percentage: {}%".format(misspercentage))

        if misses == 0:
            misses = currentmisses

        if currentmisses > misses:
            # we have new misses, alert telegram
            alarm_content = "Terra Oracle misses went from {} to {} ({}%)".format(
                misses, currentmisses, misspercentage)
            logger.error(alarm_content)

            if alertmisses:
                telegram(alarm_content)
                slack(alarm_content)

            misses = currentmisses

    else:
        logger.info("{height}: wait {num_blocks} blocks until this round ends...".format(
            height=height,
            num_blocks=num_blocks_till_next_round))

    time.sleep(1)
