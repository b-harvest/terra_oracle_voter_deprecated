# Terra_oracle_voter
Oracle autovoting script for Terra(v0.3.0+) oracle by B-Harvest

## Disclaimer
The script is in highly experimental state, and users should aware that all result from the terra_oracle_voter script is responsible to the user himself/herself.

## Language
Python3.8 Recommended

## Preliminary
The server running this script should run terrad with synced status.

## New features
1) error handling
- when coinone price, last swap price, or fx rate is unavailable, vote -1 for all oracle
- when coinone bid-ask spread is wider than `bid_ask_spread_max`, vote -1 for all oracle
- when other exchange price than coinone is unavailable, exclude those prices from averaging
- when calculated oracle price and last oracle price differ more than `stop_oracle_trigger_recent_diverge`, vote -1 for the denom
2) period-customized vwma(volume weighted moving average) for coinone market price
3) customized weights for each exchange's market price
4) use LCD endpoint to get recent oracle prices

* Thank you Peter(ChainLayer.io) for reviewing and testing the script!


## Configure(in terra_oracle_vote.py)
### user setup
telegram_token = ""\
telegram_chat_id = ""\
stop_oracle_trigger_recent_diverge = 0.1 # stop oracle when price change exceeds stop_oracle_trigger\
stop_oracle_trigger_exchange_diverge = 0.1 # stop oracle when price change exceeds stop_oracle_trigger\
bid_ask_spread_max = 0.05 # vote negative price when bid-ask price is wider than bid_ask_spread_max\
feeder = "" # oracle feeder address\
validator = "" # validator address\
key_name = "" # oracle feeder key name\
key_password = "" # oracle feeder key password\
fee_denom = "ukrw" # fee denom\
fee_gas = "170000" # fee gas\
fee_amount = "356200" # fee amount in ukrw\
home_cli = "/home/ubuntu/.terracli" # terracli home directory\
node = "tcp://<NODE IP>:26657" # node to broadcast the txs\
terracli = "sudo /home/ubuntu/go/bin/terracli" # path to terracli binary\
coinone_share_default = 1.0 # default coinone weight for averaging oracle price\
bithumb_share_default = 0 # default bithumb weight for averaging oracle price\
gopax_share_default = 0 # default gopax weight for averaging oracle price\
gdac_share_default = 0 # default gdac weight for averaging oracle price\
price_divergence_alert = False # alert when exchange prices diverge\
vwma_period = 3*600 # period for volume weight moving average of coinone price in seconds\
band_endpoint = "https://terra-lcd.bandchain.org" # an end-point to bandprotocol query node\
band_luna_price_params = "13,1_000_000_000,10,16" # A set of parameters for query a specific request on BandChain which is consist of 4 values (oracle_script_id,multiplier,min_count,ask_count)\
fx_api_option = "alphavantage,free_api,band" # A list of fx price data sources where results from each source in the list are taken to find the median.
BINANCE_KEY= BINANCE account api_key(read only)\
BINANCE_SECRET= BINANCE account api_secret(read only)

### parameters
fx_map = {"uusd": "USDUSD","ukrw": "USDKRW","usdr": "USDSDR","umnt": "USDMNT","ueur": "USDEUR","ujpy": "USDJPY","ugbp": "USDGBP","uinr": "USDINR","ucad": USDCAD","uchf": "USDCHF","uhkd": "USDHKD","uaud": "USDAUD","usgd": "USDSGD","ucny":"USDCNY",}\
active_candidate = ["uusd","ukrw","usdr","umnt","ueur","ujpy","ugbp","uinr","ucad","uchf","uhkd","uaud","usgd","ucny"] # candidate for active denom set\
hardfix_active_set = ["uusd","ukrw","usdr","umnt","ueur","ujpy","ugbp","uinr","ucad","uchf","uhkd","uaud","usgd","ucny"] # hardfix the active set. does not care last oracle price availability\
chain_id = "columbus-4" # chain id\
round_block_num = 5.0 # number of blocks for each oracle round

### Systemctl
Copy the oracle.service file to /etc/systemd/system and change the location of the working directory and oracle file accordingly
enable the service with systemctl enable oracle
start the service with systemctl start oracle
