# -*- coding: utf-8 -*-

import json
import time
import subprocess
from multiprocessing import Pool
import sys
import hashlib
import requests


# user setup
telegram_token = ""
telegram_chat_id = ""
stop_oracle_trigger = 0.1 # stop oracle when price change exceeds stop_oracle_trigger
pause_broadcast = 1.0 # pause seconds after each tx broadcasting
feeder = "" # oracle feeder address
validator = "" # validator address
key_name = ""
key_password = ""
fee_denom = "ukrw"
fee_gas = "50000"
fee_amount = "750"
home_cli = "/home/ubuntu/.terracli"
chain_id = "columbus-2"

# parameters
fx_map = {"uusd":"USDUSD","ukrw":"USDKRW","usdr":"USDSDR"}
active = ["uusd","ukrw","usdr"]
round_block_num = 12.0

# set last update time
last_height = 0

def get_current_prevotes(denom):
    try:
        # get block height
        cmd = "sudo terracli query oracle prevotes --denom " + denom + " --output json --chain-id " + chain_id
        prevotes = json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))
        if prevotes["prevotes"] == None:
            return []
        else:
            return prevotes["prevotes"]
    except:
        print("get current prevotes error!")
        return False

def get_current_votes(denom):
    try:
        # get block height
        cmd = "sudo terracli query oracle votes --denom " + denom + " --output json --chain-id " + chain_id
        votes = json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))
        if votes["votes"] == None:
            return []
        else:
            return votes["votes"]
    except:
        print("get current votes error!")
        return False

def get_data(source):
    if source=="get_fx_rate":
        return get_fx_rate()
    elif source=="get_sdr_rate":
        return get_sdr_rate()
    elif source=="get_coinone_luna_price":
        return get_coinone_luna_price()
    elif source=="get_swap_price":
        return get_swap_price()

# get latest block info
def get_latest_block():
    err_flag = False
    try:
        # get block height
        cmd = "sudo terracli status"
        status = json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))
        latest_block_height = int(status["sync_info"]["latest_block_height"])
        latest_block_time = status["sync_info"]["latest_block_time"]
    except:
        print("get block height error!")
        err_flag = True
        latest_block_height = None
        latest_block_time = None
    return err_flag, latest_block_height, latest_block_time

# get real fx rates
def get_fx_rate():
    err_flag = False
    try:
        # get currency rate
        url = "https://www.freeforexapi.com/api/live?pairs=USDUSD,USDKRW,USDEUR,USDCNY,USDJPY"
        api_result = json.loads(requests.get(url).text)
        real_fx = {"USDUSD":1.0,"USDKRW":1.0,"USDEUR":1.0,"USDCNY":1.0,"USDJPY":1.0,"USDSDR":1.0}
        real_fx["USDUSD"] = float(api_result["rates"]["USDUSD"]["rate"])
        real_fx["USDKRW"] = float(api_result["rates"]["USDKRW"]["rate"])
        real_fx["USDEUR"] = float(api_result["rates"]["USDEUR"]["rate"])
        real_fx["USDCNY"] = float(api_result["rates"]["USDCNY"]["rate"])
        real_fx["USDJPY"] = float(api_result["rates"]["USDJPY"]["rate"])
    except:
        print("get currency rate error!")
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
        print("get sdr rate error!")
        err_flag = True
        sdr_rate = None
    return err_flag, sdr_rate

# get coinone luna krw price
def get_coinone_luna_price():
    err_flag = False
    try:
        # get luna/krw
        url = "https://api.coinone.co.kr/orderbook/?currency=luna&format=json"
        luna_result = json.loads(requests.get(url).text)
        askprice = float(luna_result["ask"][0]["price"])
        bidprice = float(luna_result["bid"][0]["price"])
        midprice = (askprice + bidprice)/2.0
        luna_price = {"base_currency":"ukrw","exchange":"coinone","askprice":askprice,"bidprice":bidprice,"midprice":midprice}
        luna_base = "USDKRW"
        luna_midprice_krw = float(luna_price["midprice"])
    except:
        print("get luna/krw price error!")
        err_flag = True
        luna_price = None
        luna_base = None
        luna_midprice_krw = None
    return err_flag, luna_price, luna_base, luna_midprice_krw

# get swap price
def get_swap_price():
    err_flag = False
    try:
        swap_price = []
        for currency in active:
            cmd = "sudo terracli query oracle price --denom " + currency + " --output json --chain-id " + chain_id
            swap_price.append(float(json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))["price"]))
            time.sleep(0.5)
    except:
        print("get swap price error!")
        err_flag = False
        swap_price = []
        for item in last_swap_price:
            swap_price.append(item)
    return err_flag, swap_price

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

def broadcast_vote(price, salt):
    msg_list = []
    hash_result = {"uusd":"","ukrw":"","usdr":""}
    for denom in active:
        msg_list.append({"type":"oracle/MsgPriceVote","value":{"price":str(price[denom]),"salt":str(salt[denom]),"denom":denom,"feeder":feeder,"validator":validator}})
        hash_result[denom] = get_hash(str(salt[denom]), str(price[denom]), denom, validator)
    tx_json = {"type":"auth/StdTx","value":{"msg":msg_list,"fee":{"amount":[{"denom":fee_denom,"amount":fee_amount}],"gas":fee_gas},"signatures":[],"memo":""}}
    print("signing vote...")
    with open("tx_oracle_vote.json","w+") as f:
        f.write(json.dumps(tx_json))
    time.sleep(0.5)
    cmd = "echo " + key_password + " | sudo terracli tx sign tx_oracle_vote.json --from " + key_name + " --chain-id " + chain_id + " --home " + home_cli
    tx_json_signed = json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))
    #print(tx_json_signed)
    with open("tx_oracle_vote_signed.json","w+") as f:
        f.write(json.dumps(tx_json_signed))
    time.sleep(0.5)
    print("broadcasting vote...")
    cmd = "echo " + key_password + " | sudo terracli tx broadcast tx_oracle_vote_signed.json --output json --from " + key_name + " --chain-id " + chain_id + " --home " + home_cli
    result = json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))
    return result


def broadcast_prevote(hash):
    msg_list = []
    for denom in active:
        msg_list.append({"type":"oracle/MsgPricePrevote","value":{"hash":str(hash[denom]),"denom":str(denom),"feeder":feeder,"validator":validator}})
    tx_json = {"type":"auth/StdTx","value":{"msg":msg_list,"fee":{"amount":[{"denom":fee_denom,"amount":fee_amount}],"gas":fee_gas},"signatures":[],"memo":""}}
    print("signing prevote...")
    with open("tx_oracle_prevote.json","w+") as f:
        f.write(json.dumps(tx_json))
    time.sleep(0.5)
    cmd = "echo " + key_password + " | sudo terracli tx sign tx_oracle_prevote.json --from " + key_name + " --chain-id " + chain_id + " --home " + home_cli
    tx_json_signed = json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))
    #print(tx_json_signed)
    with open("tx_oracle_prevote_signed.json","w+") as f:
        f.write(json.dumps(tx_json_signed))
    time.sleep(0.5)
    print("broadcasting prevote...")
    cmd = "echo " + key_password + " | sudo terracli tx broadcast tx_oracle_prevote_signed.json --output json --from " + key_name + " --chain-id " + chain_id + " --home " + home_cli
    result = json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))
    return result

def broadcast_all(vote_price, vote_salt, prevote_hash):
    msg_list = []
    hash_result = {"uusd":"","ukrw":"","usdr":""}
    for denom in active:
        msg_list.append({"type":"oracle/MsgPriceVote","value":{"price":str(vote_price[denom]),"salt":str(vote_salt[denom]),"denom":denom,"feeder":feeder,"validator":validator}})
        hash_result[denom] = get_hash(str(vote_salt[denom]), str(vote_price[denom]), denom, validator)
    for denom in active:
        msg_list.append({"type":"oracle/MsgPricePrevote","value":{"hash":str(prevote_hash[denom]),"denom":str(denom),"feeder":feeder,"validator":validator}})
    tx_json = {"type":"auth/StdTx","value":{"msg":msg_list,"fee":{"amount":[{"denom":fee_denom,"amount":fee_amount}],"gas":fee_gas},"signatures":[],"memo":""}}
    print("signing vote/prevote...")
    with open("tx_oracle_vote_prevote.json","w+") as f:
        f.write(json.dumps(tx_json))
    time.sleep(0.5)
    cmd = "echo " + key_password + " | sudo terracli tx sign tx_oracle_vote_prevote.json --from " + key_name + " --chain-id " + chain_id + " --home " + home_cli
    tx_json_signed = json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))
    #print(tx_json_signed)
    with open("tx_oracle_vote_prevote_signed.json","w+") as f:
        f.write(json.dumps(tx_json_signed))
    time.sleep(0.5)
    print("broadcasting vote/prevote...")
    cmd = "echo " + key_password + " | sudo terracli tx broadcast tx_oracle_vote_prevote_signed.json --output json --from " + key_name + " --chain-id " + chain_id + " --home " + home_cli
    result = json.loads(subprocess.check_output(cmd,shell=True).decode("utf-8"))
    return result


err_flag = True
while err_flag:
    latest_block_err_flag, latest_block_height, latest_block_time = get_latest_block()
    if latest_block_err_flag == False:
        height = latest_block_height
        if height>last_height:
            err_flag = False
            last_height=height
    time.sleep(0.5)

last_prevoted_round = 0

while True:

    err_flag = True
    while err_flag:
        latest_block_err_flag, latest_block_height, latest_block_time = get_latest_block()
        if latest_block_err_flag == False:
            height = latest_block_height
            if height>last_height:
                err_flag = False
                last_height=height
        time.sleep(0.5)

    current_round = int(float(height-1)/round_block_num)
    next_height_round = int(float(height)/round_block_num)

    if next_height_round > last_prevoted_round and ((current_round+1)*round_block_num-height == 0 or (current_round+1)*round_block_num-height>3):

        # get oracle prices
        # get data
        all_err_flag = False
        ts = time.time()
        p = Pool(4)
        res_fx, res_sdr, res_coinone, res_swap = p.map(get_data, ["get_fx_rate","get_sdr_rate","get_coinone_luna_price","get_swap_price"])
        p.close()
        p.join()
        fx_err_flag, real_fx = res_fx
        sdr_err_flag, sdr_rate = res_sdr
        coinone_err_flag, luna_price, luna_base, luna_midprice_krw = res_coinone
        swap_price_err_flag, swap_price = res_swap
        if fx_err_flag or sdr_err_flag or coinone_err_flag or swap_price_err_flag:
            all_err_flag = True

        # reorganize data
        if all_err_flag==False:
            try:
                # get swap price
                real_fx["USDSDR"] = sdr_rate
                swap_price_compare = []
                i = 0
                for currency in active:
                    market_price = float(luna_midprice_krw * (real_fx[fx_map[currency]] / real_fx[luna_base]))
                    swap_price_compare.append({"market":currency,"swap_price":swap_price[i],"market_price":market_price})
                    i += 1
                result = {"index":int(ts/60), "timestamp":ts, "block_height":latest_block_height, "block_time":latest_block_time,"swap_price_compare":swap_price_compare, "real_fx":real_fx, "luna_price_list":[luna_price]}
            except:
                print("reorganize data error!")
                all_err_flag = True

        # prevote for current round
        if all_err_flag==False:
            price_temp = {"uusd":0.0,"ukrw":0.0,"usdr":0.0}
            hash_temp = {"uusd":"","ukrw":"","usdr":""}
            salt_temp = {"uusd":"","ukrw":"","usdr":""}
            for denom in active:
                for prices in result["swap_price_compare"]:
                    if prices["market"] == denom:
                        if abs(prices["market_price"]/prices["swap_price"]-1.0) <= stop_oracle_trigger:
                            print("prevoting " + denom + " : " + str(prices["market_price"]) + "(percent_change:" + str("{0:.4f}".format((prices["market_price"]/prices["swap_price"]-1.0)*100.0)) + "%)")
                            salt_temp[denom] = get_salt(str(time.time()))
                            price_temp[denom] = str("{0:.18f}".format(float(prices["market_price"])))
                            hash_temp[denom] = get_hash(salt_temp[denom], price_temp[denom], denom, validator)
                            break
                        else:
                            alarm_content = denom + " price diversion at height " + str(height) + "! market_price:" + str("{0:.4f}".format(prices["market_price"])) + ", swap_price:" + str("{0:.4f}".format(prices["swap_price"]))
                            alarm_content += "(percent_change:" + str("{0:.4f}".format((prices["market_price"]/prices["swap_price"]-1.0)*100.0)) + "%)"
                            print(alarm_content)
                            try:
                                requestURL = "https://api.telegram.org/bot" + str(telegram_token) + "/sendMessage?chat_id=" + telegram_chat_id + "&text="
                                requestURL = requestURL + str(alarm_content)
                                response = requests.get(requestURL, timeout=1)
                            except:
                                pass
                            sys.exit()

            if last_prevoted_round != current_round:
                print("we don't have any prevote to vote. only prevote...")
                broadcast_prevote(hash_temp)
            else:
                # broadcast vote/prevote at the same time!
                print("broadcast vote/prevote at the same time...")
                broadcast_all(this_price, this_salt, hash_temp)

            time.sleep(pause_broadcast)

            # update last_prevoted_round
            last_prevoted_round = next_height_round
            this_price = {"uusd":0.0,"ukrw":0.0,"usdr":0.0}
            this_salt = {"uusd":"","ukrw":"","usdr":""}
            for denom in active:
                this_price[denom] = price_temp[denom]
                this_salt[denom] = salt_temp[denom]
            last_swap_price = []
            for item in swap_price:
                last_swap_price.append(item)
    else:
        print(str(height) + " : wait " + str((current_round+1)*round_block_num-height) + " blocks until this round ends...")

    time.sleep(1)
