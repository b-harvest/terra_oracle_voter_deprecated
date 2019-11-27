# -*- coding: utf-8 -*-

### WARNING : this script is for terra blockchain with version v0.3.0+ ###

import json
import time
import subprocess
from multiprocessing import Pool
import sys
# installation required
import requests
import hashlib

# user setup
telegram_token = ""
telegram_chat_id = ""
stop_oracle_trigger_recent_diverge = 0.1 # stop oracle when price change exceeds stop_oracle_trigger
stop_oracle_trigger_exchange_diverge = 0.1 # stop oracle when price change exceeds stop_oracle_trigger
bid_ask_spread_max = 0.05 # vote negative price when bid-ask price is wider than bid_ask_spread_max
pause_broadcast = 1.0
feeder = "" # oracle feeder address
validator = "" # validator address
key_name = ""
key_password = ""
fee_denom = "ukrw"
fee_gas = "150000"
fee_amount = "1500"
home_cli = "/home/ubuntu/.terracli"
node = "tcp://52.78.69.160:26657" # node to broadcast the txs
terracli = "sudo /home/ubuntu/go/bin/terracli" # path to terracli binary
rpc_address = "https://soju-lcd.terra.dev/" # rpc to receive swap price information
coinone_share_default = 0.60 # default coinone weight
gopax_share_default = 0.20 # default gopax weight
gdac_share_default = 0.20 # default gdac weight
price_divergence_alert = False
vwma_period = 3*60 # in seconds

# parameters
fx_map = {"uusd":"USDUSD","ukrw":"USDKRW","usdr":"USDSDR","umnt":"USDMNT"}
active_candidate = ["uusd","ukrw","usdr","umnt"]
hardfix_active_set = ["uusd","ukrw","usdr","umnt"] # hardfix the active set. does not care about stop_oracle_trigger_recent_diverge
chain_id = "soju-0012"
round_block_num = 5.0

# set last update time
last_height = 0

def printandflush(message):
    print(message)
    sys.stdout.flush()

def get_current_prevotes(denom):
    try:
        result = json.loads(requests.get(str(rpc_address) + "oracle/denoms/" + str(denom) + "/prevotes").text)
        return result
    except:
        printandflush("get current prevotes error!")
        return False

def get_current_votes(denom):
    try:
        result = json.loads(requests.get(str(rpc_address) + "oracle/denoms/" + str(denom) + "/votes").text)
        return result
    except:
        printandflush("get current votes error!")
        return False

def get_data(source):
    if source=="get_fx_rate":
        return get_fx_rate()
    elif source=="get_sdr_rate":
        return get_sdr_rate()
    elif source=="get_coinone_luna_price":
        return get_coinone_luna_price()
    elif source=="get_gopax_luna_price":
        return get_gopax_luna_price()
    elif source=="get_gdac_luna_price":
        return get_gdac_luna_price()
    elif source=="get_swap_price":
        return get_swap_price()

# get latest block info
def get_latest_block():
    err_flag = False
    try:
        result = json.loads(requests.get(str(rpc_address) + "blocks/latest").text)
        latest_block_height = int(result["block_meta"]["header"]["height"])
        latest_block_time = result["block_meta"]["header"]["time"]
    except:
        printandflush("get block height error!")
        err_flag = True
        latest_block_height = None
        latest_block_time = None
    return err_flag, latest_block_height, latest_block_time

# get real fx rates
def get_fx_rate():
    err_flag = False
    try:
        # get currency rate
        url = "https://www.freeforexapi.com/api/live?pairs=USDUSD,USDKRW,USDEUR,USDCNY,USDJPY,USDMNT"
        api_result = json.loads(requests.get(url).text)
        real_fx = {"USDUSD":1.0,"USDKRW":1.0,"USDEUR":1.0,"USDCNY":1.0,"USDJPY":1.0,"USDSDR":1.0, "USDMNT":1.0}
        real_fx["USDUSD"] = float(api_result["rates"]["USDUSD"]["rate"])
        real_fx["USDKRW"] = float(api_result["rates"]["USDKRW"]["rate"])
        real_fx["USDEUR"] = float(api_result["rates"]["USDEUR"]["rate"])
        real_fx["USDCNY"] = float(api_result["rates"]["USDCNY"]["rate"])
        real_fx["USDJPY"] = float(api_result["rates"]["USDJPY"]["rate"])
        real_fx["USDMNT"] = float(api_result["rates"]["USDMNT"]["rate"])
    except:
        printandflush("get currency rate error!")
        err_flag = True
        real_fx = None
    return err_flag, real_fx

# get real sdr rates
def get_sdr_rate():
    err_flag = False
    try:
    # get sdr
        url = "https://www.imf.org/external/np/fin/data/rms_five.aspx?tsvflag=Y"
        scrap_start = 'U.S. dollar'
        scrap_result = requests.get(url).text
        scrap_cuthead = scrap_result[scrap_result.index(scrap_start) + len(scrap_start):]
        sdr_rate = float(scrap_cuthead[:12])
    except:
        printandflush("get sdr rate error!")
        err_flag = True
        sdr_rate = None
    return err_flag, sdr_rate

# get coinone luna krw price
def get_coinone_luna_price():
    err_flag = False
    try:
        if vwma_period>1:
            url = "https://api.coinone.co.kr/trades/?currency=luna"
            luna_result = json.loads(requests.get(url).text)["completeOrders"]
            hist_price = []
            sum_price_volume = 0
            sum_volume = 0
            now_time = float(time.time())
            for row in luna_result:
                if now_time - float(row['timestamp']) < vwma_period:
                    sum_price_volume += float(row["price"])*float(row["qty"])
                    sum_volume += float(row["qty"])
                else:
                    break
            askprice = sum_price_volume / sum_volume
            bidprice = sum_price_volume / sum_volume
        else:
            url = "https://api.coinone.co.kr/orderbook/?currency=luna&format=json"
            luna_result = json.loads(requests.get(url).text)
            askprice = float(luna_result["ask"][0]["price"])
            bidprice = float(luna_result["bid"][0]["price"])
        midprice = (askprice + bidprice)/2.0
        luna_price = {"base_currency":"ukrw","exchange":"coinone","askprice":askprice,"bidprice":bidprice,"midprice":midprice}
        luna_base = "USDKRW"
        luna_midprice_krw = float(luna_price["midprice"])
    except:
        printandflush("get coinone luna/krw price error!")
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
        luna_result = json.loads(requests.get(url).text)
        askprice = float(luna_result["ask"][0][1])
        bidprice = float(luna_result["bid"][0][1])
        midprice = (askprice + bidprice)/2.0
        luna_price = {"base_currency":"ukrw","exchange":"gopax","askprice":askprice,"bidprice":bidprice,"midprice":midprice}
        luna_base = "USDKRW"
        luna_midprice_krw = float(luna_price["midprice"])
    except:
        printandflush("get gopax luna/krw price error!")
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
        luna_result = json.loads(requests.get(url).text)
        askprice = float(luna_result["ask"][0]["price"])
        bidprice = float(luna_result["bid"][0]["price"])
        midprice = (askprice + bidprice)/2.0
        luna_price = {"base_currency":"ukrw","exchange":"gdac","askprice":askprice,"bidprice":bidprice,"midprice":midprice}
        luna_base = "USDKRW"
        luna_midprice_krw = float(luna_price["midprice"])
    except:
        printandflush("get gopax luna/krw price error!")
        err_flag = True
        luna_price = None
        luna_base = None
        luna_midprice_krw = None
    return err_flag, luna_price, luna_base, luna_midprice_krw

# get swap price
def get_swap_price():
    err_flag = False
    try:
        result = json.loads(requests.get(str(rpc_address) + "oracle/denoms/exchange_rates").text)
    except:
        result = []
        err_flag = True

    return err_flag, result

def get_hash(salt, price, denom, validator):
    m = hashlib.sha256()
    m.update(bytes('{}:{}:{}:{}'.format(str(salt), str(price), str(denom), str(validator)),'utf-8'))
    result = m.hexdigest()[:40]
    return result

def get_salt(string):
    b_string = str(string).encode('utf-8')
    try:
        result = str(hashlib.sha256(b_string).hexdigest())[:4]
    except:
        result = False
    return result

def broadcast_prevote(hash):
    msg_list = []
    for denom in active:
        msg_list.append({"type":"oracle/MsgExchangeRatePrevote","value":{"hash":str(hash[denom]),"denom":str(denom),"feeder":feeder,"validator":validator}})
    tx_json = {"type":"core/StdTx","value":{"msg":msg_list,"fee":{"amount":[{"denom":fee_denom,"amount":fee_amount}],"gas":fee_gas},"signatures":[],"memo":""}}
    printandflush("signing prevote...")
    with open("tx_oracle_prevote.json","w+") as f:
        f.write(json.dumps(tx_json))
    time.sleep(0.5)
    cmd = "echo " + key_password + " | " + terracli + " tx sign tx_oracle_prevote.json --from " + key_name + " --chain-id " + chain_id + " --home " + home_cli + " --node " + node
    tx_json_signed = json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))
    # printandflush(tx_json_signed)
    with open("tx_oracle_prevote_signed.json","w+") as f:
        f.write(json.dumps(tx_json_signed))
    time.sleep(0.5)
    printandflush("broadcasting prevote...")
    cmd = "echo " + key_password + " | " + terracli + " tx broadcast tx_oracle_prevote_signed.json --output json --from " + key_name + " --chain-id " + chain_id + " --home " + home_cli + " --node " + node
    result = json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))
    return result

def broadcast_all(vote_price, vote_salt, prevote_hash):
    msg_list = []
    hash_result = {}
    for denom in active:
        hash_result.update({denom:""})
    for denom in active:
        msg_list.append({"type":"oracle/MsgExchangeRateVote","value":{"exchange_rate":str(vote_price[denom]),"salt":str(vote_salt[denom]),"denom":denom,"feeder":feeder,"validator":validator}})
        hash_result[denom] = get_hash(str(vote_salt[denom]), str(vote_price[denom]), denom, validator)
    for denom in active:
        msg_list.append({"type":"oracle/MsgExchangeRatePrevote","value":{"hash":str(prevote_hash[denom]),"denom":str(denom),"feeder":feeder,"validator":validator}})
    tx_json = {"type":"core/StdTx","value":{"msg":msg_list,"fee":{"amount":[{"denom":fee_denom,"amount":fee_amount}],"gas":fee_gas},"signatures":[],"memo":""}}
    printandflush("signing vote/prevote...")
    with open("tx_oracle_vote_prevote.json","w+") as f:
        f.write(json.dumps(tx_json))
    time.sleep(0.5)
    cmd = "echo " + key_password + " | " + terracli + " tx sign tx_oracle_vote_prevote.json --from " + key_name + " --chain-id " + chain_id + " --home " + home_cli + " --node " + node
    tx_json_signed = json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))
    # printandflush(tx_json_signed)
    with open("tx_oracle_vote_prevote_signed.json","w+") as f:
        f.write(json.dumps(tx_json_signed))
    time.sleep(0.5)
    printandflush("broadcasting vote/prevote...")
    cmd = "echo " + key_password + " | " + terracli + " tx broadcast tx_oracle_vote_prevote_signed.json --output json --from " + key_name + " --chain-id " + chain_id + " --home " + home_cli + " --node " + node
    result = json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))
    return result


main_err_flag = True
while main_err_flag:
    latest_block_err_flag, latest_block_height, latest_block_time = get_latest_block()
    if latest_block_err_flag == False:
        height = latest_block_height
        if height>last_height:
            main_err_flag = False
            last_height=height
    time.sleep(0.5)

last_prevoted_round = 0

while True:

    main_err_flag = True
    while main_err_flag:
        latest_block_err_flag, latest_block_height, latest_block_time = get_latest_block()
        if latest_block_err_flag == False:
            height = latest_block_height
            if height>last_height:
                main_err_flag = False
                last_height=height
        time.sleep(0.5)

    current_round = int(float(height-1)/round_block_num)
    next_height_round = int(float(height)/round_block_num)

    if next_height_round > last_prevoted_round and ((current_round+1)*round_block_num-height == 0 or (current_round+1)*round_block_num-height>3):

        # get active set of denoms
        res_swap = get_swap_price()
        swap_price_err_flag, swap_price = res_swap
        if swap_price["result"] == None: swap_price["result"] = []
        if len(hardfix_active_set) == 0:
            active = []
            for denom in swap_price["result"]:
                active.append(denom["denom"])
        else:
            active = hardfix_active_set
        printandflush("active set : " + str(active))

        # get external data
        all_err_flag = False
        ts = time.time()
        p = Pool(5)
        res_fx, res_sdr, res_coinone, res_gopax, res_gdac = p.map(get_data, ["get_fx_rate","get_sdr_rate","get_coinone_luna_price", "get_gopax_luna_price", "get_gdac_luna_price"])
        p.close()
        p.join()
        fx_err_flag, real_fx = res_fx
        sdr_err_flag, sdr_rate = res_sdr
        real_fx["USDSDR"] = sdr_rate
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
        
        if all_err_flag == False:

            # ignore gopax if it diverge from coinone price or its bid-ask price is wider than bid_ask_spread_max
            if gopax_share > 0:
                if abs(1.0 - float(gopax_luna_midprice_krw)/float(coinone_luna_midprice_krw)) > stop_oracle_trigger_exchange_diverge or float(gopax_luna_price["askprice"])/float(gopax_luna_price["bidprice"]) - 1 > bid_ask_spread_max:
                    gopax_share = 0
                    if price_divergence_alert:
                        alarm_content = denom + " market price diversion at height " + str(height) + "! coinone_price:" + str("{0:.1f}".format(coinone_luna_midprice_krw)) + ", gopax_price:" + str("{0:.1f}".format(gopax_luna_midprice_krw))
                        alarm_content += "(percent_diff:" + str("{0:.4f}".format((coinone_luna_midprice_krw/gopax_luna_midprice_krw-1.0)*100.0)) + "%)"
                        printandflush(alarm_content)
                        try:
                            requestURL = "https://api.telegram.org/bot" + str(telegram_token) + "/sendMessage?chat_id=" + telegram_chat_id + "&text="
                            requestURL = requestURL + str(alarm_content)
                            response = requests.get(requestURL, timeout=1)
                        except:
                            pass

            # ignore gdac if it diverge from coinone price or its bid-ask price is wider than bid_ask_spread_max
            if gdac_share > 0:
                if abs(1.0 - float(gdac_luna_midprice_krw)/float(coinone_luna_midprice_krw)) > stop_oracle_trigger_exchange_diverge or float(gdac_luna_price["askprice"])/float(gdac_luna_price["bidprice"]) - 1 > bid_ask_spread_max:
                    gdac_share = 0
                    if price_divergence_alert:
                        alarm_content = denom + " market price diversion at height " + str(height) + "! coinone_price:" + str("{0:.1f}".format(coinone_luna_midprice_krw)) + ", gdac_price:" + str("{0:.1f}".format(gdac_luna_midprice_krw))
                        alarm_content += "(percent_diff:" + str("{0:.4f}".format((coinone_luna_midprice_krw/gdac_luna_midprice_krw-1.0)*100.0)) + "%)"
                        printandflush(alarm_content)
                        try:
                            requestURL = "https://api.telegram.org/bot" + str(telegram_token) + "/sendMessage?chat_id=" + telegram_chat_id + "&text="
                            requestURL = requestURL + str(alarm_content)
                            response = requests.get(requestURL, timeout=1)
                        except:
                            pass
            
            # vote negative price if coinone bid-ask spread is wider than "bid_ask_spread_max"
            if float(coinone_luna_price["askprice"])/float(coinone_luna_price["bidprice"]) - 1 > bid_ask_spread_max:
                all_err_flag = True

        if all_err_flag == False:

            # weighted average
            luna_midprice_krw = (float(coinone_luna_midprice_krw)*coinone_share + float(gopax_luna_midprice_krw)*gopax_share + float(gdac_luna_midprice_krw)*gdac_share)/(coinone_share+gopax_share+gdac_share)
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
                    swap_price_compare.append({"market":currency,"swap_price":this_swap_price,"market_price":market_price})
                result = {"index":int(ts/60), "timestamp":ts, "block_height":latest_block_height, "block_time":latest_block_time,"swap_price_compare":swap_price_compare, "real_fx":real_fx, "luna_price_list":[coinone_luna_price,gopax_luna_price]}
            except:
                printandflush("reorganize data error!")
                all_err_flag = True
        
        if all_err_flag == False:

            # prevote for current round
            this_price = {}
            this_hash = {}
            this_salt = {}
            for denom in active:
                this_price.update({denom:0.0})
                this_hash.update({denom:""})
                this_salt.update({denom:""})

            for denom in active:
                for prices in result["swap_price_compare"]:
                    if prices["market"] == denom:
                        this_denom_err_flag = False
                        if abs(prices["market_price"]/prices["swap_price"]-1.0) <= stop_oracle_trigger_recent_diverge:
                            printandflush("prevoting " + denom + " : " + str(prices["market_price"]) + "(percent_change:" + str("{0:.4f}".format((prices["market_price"]/prices["swap_price"]-1.0)*100.0)) + "%)")
                        else:
                            alarm_content = denom + " price diversion at height " + str(height) + "! market_price:" + str("{0:.4f}".format(prices["market_price"])) + ", swap_price:" + str("{0:.4f}".format(prices["swap_price"]))
                            alarm_content += "(percent_change:" + str("{0:.4f}".format((prices["market_price"]/prices["swap_price"]-1.0)*100.0)) + "%)"
                            printandflush(alarm_content)
                            try:
                                requestURL = "https://api.telegram.org/bot" + str(telegram_token) + "/sendMessage?chat_id=" + telegram_chat_id + "&text="
                                requestURL = requestURL + str(alarm_content)
                                response = requests.get(requestURL, timeout=1)
                            except:
                                pass
                            this_denom_err_flag = True

                        this_salt[denom] = get_salt(str(time.time()))
                        if this_denom_err_flag == False: # vote negative when this_denom_err_flag == True
                            this_price[denom] = str("{0:.18f}".format(float(prices["market_price"])))
                        else:
                            this_price[denom] = str("{0:.18f}".format(float(-1)))
                        this_hash[denom] = get_hash(this_salt[denom], this_price[denom], denom, validator)
                        break
        
        if all_err_flag == True: # vote negative when all_err_flag == True
            for denom in active:
                this_price[denom] = str("{0:.18f}".format(float(-1)))
                this_hash[denom] = get_hash(this_salt[denom], this_price[denom], denom, validator)
        
        printandflush("start voting on height " + str(height+1))
        if last_prevoted_round != current_round:
            printandflush("we don't have any prevote to vote. only prevote...")
            broadcast_prevote(this_hash)
        else:
            # broadcast vote/prevote at the same time!
            printandflush("broadcast vote/prevote at the same time...")
            broadcast_all(last_price, last_salt, this_hash)

        time.sleep(pause_broadcast)

        # update last_prevoted_round
        last_prevoted_round = next_height_round
        last_price = {}
        last_salt = {}
        for denom in active:
            last_price.update({denom:0.0})
            last_salt.update({denom:""})
        for denom in active:
            last_price[denom] = this_price[denom]
            last_salt[denom] = this_salt[denom]
        last_swap_price = []
        for item in swap_price:
            last_swap_price.append(item)

    else:
        printandflush(str(height) + " : wait " + str((current_round+1)*round_block_num-height) + " blocks until this round ends...")

    time.sleep(1)
