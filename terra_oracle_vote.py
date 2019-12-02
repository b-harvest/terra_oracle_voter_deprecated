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
import os
import subprocess
import time

# External libraries - installation required.
# Most Linux distributions have packaged python-requests.
import requests

# User setup

# Slack webhook
slackurl = os.getenv("SLACK_URL", "")
telegram_token = os.getenv("TELEGRAM_TOKEN", "")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
# https://fcsapi.com
fcsapi_key = os.getenv("FCSAPI_KEY", "")
# https://www.alphavantage.co/
alphavantage_key = os.getenv("ALPHAVANTAGE_KEY", "")
# stop oracle when price change exceeds stop_oracle_trigger
stop_oracle_trigger_recent_diverge = float(os.getenv("STOP_ORACLE_RECENT_DIVERGENCE", "0.1"))
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
fee_gas = os.getenv("FEE_GAS", "150000")
fee_amount = os.getenv("FEE_AMOUNT", "1500")
home_cli = os.getenv("HOME_CLI", "/home/ubuntu/.terracli")
# node to broadcast the txs
node = os.getenv("NODE_RPC", "tcp://52.78.69.160:26657")
# path to terracli binary
terracli = os.getenv("TERRACLI_BIN", "sudo /home/ubuntu/go/bin/terracli")
# rpc to receive swap price information
rpc_address = os.getenv("TERRA_RPC", "https://soju-lcd.terra.dev/")
# default coinone weight
coinone_share_default = float(os.getenv("COINONE_SHARE_DEFAULT", "0.60"))
# default gopax weight
gopax_share_default = float(os.getenv("GOPAX_SHARE_DEFAULT", "0.20"))
# default gdac weight
gdac_share_default = float(os.getenv("GDAC_SHARE_DEFAULT", "0.20"))
price_divergence_alert = os.getenv("PRICE_ALERTS", "false") == "true"
vwma_period = int(os.getenv("VWMA_PERIOD", str(3 * 60)))  # in seconds
misses = int(os.getenv("MISSES", "0"))
alertmisses = os.getenv("MISS_ALERTS", "true") == "true"

# parameters
fx_map = {
    "uusd": "USDUSD",
    "ukrw": "USDKRW",
    "usdr": "USDSDR",
    "umnt": "USDMNT"
}
active_candidate = [
    "uusd",
    "ukrw",
    "usdr",
    "umnt"
]

# hardfix the active set. does not care about stop_oracle_trigger_recent_diverge
hardfix_active_set = [
    "uusd",
    "ukrw",
    "usdr",
    "umnt"
]

chain_id = os.getenv("CHAIN_ID", "soju-0012")
round_block_num = 5.0

# set last update time
last_height = 0

logging.basicConfig(level=logging.DEBUG)
logger = logging.root

# By default, python-requests does not use a timeout. We need to specify
# a timeout on each call to ensure we never get stuck in network IO.
http_timeout = 60

# Separate timeout for alerting calls
alert_http_timeout = 10

# Global requests session for HTTP/1.1 keepalive
# (unfortunately, the timeout cannot be set globally)
session = requests.session()

# Be friendly to the APIs we use and specify a user-agent
session.headers['User-Agent'] = "bharvest-oracle-voter/0 (+https://github.com/b-harvest/terra_oracle_voter)"


def telegram(message):
    if not telegram_token:
        return

    try:
        requests.post(
            "https://api.telegram.org/bot/{}/sendMessage".format(telegram_token),
            json={
                'chat_id': telegram_chat_id,
                'text': message
            },
            timeout=alert_http_timeout
        )
    except:
        logging.exception("Error while sending telegram alert")


def slack(message):
    if not slackurl:
        return

    try:
        requests.post(slackurl, json={"text": message}, timeout=alert_http_timeout)
    except:
        logging.exception("Error while sending Slack alert")


def get_current_misses():
    try:
        result = session.get(
            "{}/oracle/voters/{}/miss".format(rpc_address, validator),
            timeout=http_timeout).json()
        misses = int(result["result"])
        height = int(result["height"])
        return misses, height
    except:
        logging.exception("Error in get_current_misses")
        return 0, 0


def get_current_prevotes(denom):
    try:
        return session.get(
            "{}/oracle/denoms/{}/prevotes".format(rpc_address, denom),
            timeout=http_timeout).json()
    except:
        logging.exception("Error in get_current_prevotes")
        return False


def get_current_votes(denom):
    try:
        result = session.get(
            "{}/oracle/denoms/{}/votes".format(rpc_address, denom),
            timeout=http_timeout).json()
        return result
    except:
        logging.exception("Error in get_current_votes")
        return False


def get_my_current_prevotes():
    try:
        result = session.get(
            "{}/oracle/voters/{}/prevotes".format(rpc_address, validator),
            timeout=http_timeout).json()
        result_vote = []
        for vote in result["result"]:
            if str(vote["voter"]) == str(validator):
                result_vote.append(vote)
        return result_vote
    except:
        logging.exception("Error in get_my_current_prevotes")
        return False


# get latest block info
def get_latest_block():
    err_flag = False
    try:
        result = session.get("{}/blocks/latest".format(rpc_address), timeout=http_timeout).json()
        latest_block_height = int(result["block_meta"]["header"]["height"])
        latest_block_time = result["block_meta"]["header"]["time"]
    except:
        logger.exception("Error in get_latest_block")
        err_flag = True
        latest_block_height = None
        latest_block_time = None

    return err_flag, latest_block_height, latest_block_time


# get real fx rates
def get_fx_rate():
    err_flag = False
    try:
        # get currency rate
        api_result = session.get(
            "https://fcsapi.com/api/forex/latest",
            timeout=http_timeout,
            params={
                'symbol': 'USD/KRW,USD/EUR,USD/CNY,USD/JPY',
                'access_key': fcsapi_key
            }
        ).json()

        result_real_fx = {
            "USDUSD": 1.0,
            "USDKRW": 1.0,
            "USDEUR": 1.0,
            "USDCNY": 1.0,
            "USDJPY": 1.0,
            "USDSDR": 1.0,
            "USDMNT": 1.0
        }

        for currency in api_result["response"]:
            result_real_fx["USD" + str(currency["symbol"][-3:])] = float(currency["price"].replace(',', ''))

        mnt_api_result = session.get(
            "https://www.alphavantage.co/query",
            timeout=http_timeout,
            params={
                'function': 'CURRENCY_EXCHANGE_RATE',
                'from_currency': 'USD',
                'to_currency': 'MNT',
                'apikey': alphavantage_key
            }
        ).json()

        result_real_fx["USDMNT"] = float(
            mnt_api_result["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
    except:
        logger.exception("Error in get_fx_rate")
        err_flag = True
        result_real_fx = None

    return err_flag, result_real_fx


# get real sdr rates
def get_sdr_rate():
    err_flag = False
    try:
        # get sdr
        url = "https://www.imf.org/external/np/fin/data/rms_five.aspx?tsvflag=Y"
        data = session.get(url, timeout=http_timeout).text
        result_sdr_rate = next(filter(lambda x: x.startswith("U.S. dollar"),
                                      data.splitlines())).split('\t')[2]
    except:
        logging.exception("Error in get_sdr_rate")
        err_flag = True
        result_sdr_rate = None
    return err_flag, result_sdr_rate


# get coinone luna krw price
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
        logger.exception("Error in get_coinone_luna_price")
        err_flag = True
        luna_price = None
        luna_base = None
        luna_midprice_krw = None

    return err_flag, luna_price, luna_base, luna_midprice_krw


# get gopax luna krw price
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
        logger.exception("Error in get_gopax_luna_price")
        err_flag = True
        luna_price = None
        luna_base = None
        luna_midprice_krw = None

    return err_flag, luna_price, luna_base, luna_midprice_krw


# get gdac luna krw price
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
        logger.exception("Error in get_gdac_luna_price")
        err_flag = True
        luna_price = None
        luna_base = None
        luna_midprice_krw = None

    return err_flag, luna_price, luna_base, luna_midprice_krw


# get swap price
def get_swap_price():
    err_flag = False
    try:
        result = session.get(
            "{}/oracle/denoms/exchange_rates".format(rpc_address),
            timeout=http_timeout).json()
    except:
        logger.exception("Error in get_swap_price")
        result = []
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
    json.dump(open("tx_oracle_prevote.json", 'w'), tx_json)

    cmd_output = subprocess.check_output([
        terracli,
        "tx", "sign", "tx_oracle_prevote.json",
        "--from", key_name,
        "--chain-id", chain_id,
        "--home", home_cli,
        "--node", node
    ], input=key_password + b'\n').decode()

    tx_json_signed = json.loads(cmd_output)
    json.dump(open("tx_oracle_prevote_signed.json", 'w'), tx_json_signed)

    logger.info("Broadcasting...")
    cmd_output = subprocess.check_output([
        terracli,
        "tx", "broadcast", "tx_oracle_prevote_signed.json",
        "--output", "json",
        "--from", key_name,
        "--chain-id", chain_id,
        "--home", home_cli,
        "--node", node,
    ], input=key_password + b'\n').decode()

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
    time.sleep(0.5)

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
        time.sleep(0.5)

    current_round = int(float(height - 1) / round_block_num)
    next_height_round = int(float(height) / round_block_num)

    if next_height_round > last_prevoted_round and ((current_round + 1) * round_block_num - height == 0 or (
            current_round + 1) * round_block_num - height > 3):

        # get active set of denoms
        res_swap = get_swap_price()
        swap_price_err_flag, swap_price = res_swap

        if swap_price["result"] is None:
            swap_price["result"] = []

        if len(hardfix_active_set) == 0:
            active = []
            for denom in swap_price["result"]:
                active.append(denom["denom"])
        else:
            active = hardfix_active_set

        logger.info("Active set: {}".format(active))

        # get external data
        all_err_flag = False
        ts = time.time()
        p = multiprocessing.Pool(5)
        res_fx, res_sdr, res_coinone, res_gopax, res_gdac = p.map(lambda f: f(), [
            get_fx_rate,
            get_sdr_rate,
            get_coinone_luna_price,
            get_gopax_luna_price,
            get_gdac_luna_price,
        ])

        p.close()
        p.join()
        fx_err_flag, real_fx = res_fx
        sdr_err_flag, sdr_rate = res_sdr
        coinone_err_flag, coinone_luna_price, coinone_luna_base, coinone_luna_midprice_krw = res_coinone
        gopax_err_flag, gopax_luna_price, gopax_luna_base, gopax_luna_midprice_krw = res_gopax
        gdac_err_flag, gdac_luna_price, gdac_luna_base, gdac_luna_midprice_krw = res_gdac
        coinone_share = coinone_share_default
        gopax_share = gopax_share_default
        gdac_share = gdac_share_default

        if fx_err_flag or sdr_err_flag or coinone_err_flag or swap_price_err_flag:
            all_err_flag = True

        if gopax_err_flag:
            gopax_share = 0
        if gdac_err_flag:
            gdac_share = 0

        if not all_err_flag:
            real_fx["USDSDR"] = sdr_rate

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
            # weighted average
            luna_midprice_krw = (float(coinone_luna_midprice_krw) * coinone_share + float(
                gopax_luna_midprice_krw) * gopax_share + float(gdac_luna_midprice_krw) * gdac_share) / (
                                        coinone_share + gopax_share + gdac_share)
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
                    "luna_price_list": [coinone_luna_price, gopax_luna_price]
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

        if all_err_flag == False:

            # prevote for current round
            for denom in active:
                for prices in result["swap_price_compare"]:
                    if prices["market"] == denom:
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
                            this_price[denom] = str("{0:.18f}".format(float(-1)))
                        this_hash[denom] = get_hash(this_salt[denom], this_price[denom], denom, validator)
                        break

        if all_err_flag:  # vote negative when all_err_flag == True
            for denom in active:
                this_price[denom] = str("{0:.18f}".format(float(-1)))
                this_salt[denom] = get_salt(str(time.time()))
                this_hash[denom] = get_hash(this_salt[denom], this_price[denom], denom, validator)

        logger.info("Start voting on height " + str(height + 1))

        # check hash match
        my_current_prevotes = get_my_current_prevotes()

        if not last_hash:
            hash_match_flag = False
        else:
            hash_match_flag = True

            for vote_hash in last_hash:
                this_hash_exist = False
                for prevote in my_current_prevotes:
                    if str(prevote["hash"]) == vote_hash:
                        this_hash_exist = True
                        break
                if not this_hash_exist:
                    hash_match_flag = False
                    break

        if hash_match_flag:  # if all hashes exist
            # broadcast vote/prevote at the same time!
            logger.info("Broadcast votes/prevotes at the same time...")
            broadcast_all(last_price, last_salt, this_hash)
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
            num_blocks=(current_round + 1) * round_block_num - height))

    time.sleep(1)
