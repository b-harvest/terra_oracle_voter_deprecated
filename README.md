# Terra_oracle_voter
Oracle autovoting script for Terra(v0.3.0+) oracle by B-Harvest

## Disclaimer
The script is in highly experimental state, and users should aware that all result from the terra_oracle_voter script is responsible to the user himself/herself.

## Language
Python3

## Preliminary
The server running this script should run terrad with synced status.

## Configure(in terra_oracle_vote.py)
# user setup
telegram_token = ""
telegram_chat_id = ""
stop_oracle_trigger_recent_diverge = 0.1 # stop oracle when price change exceeds stop_oracle_trigger
stop_oracle_trigger_exchange_diverge = 0.1 # stop oracle when price change exceeds stop_oracle_trigger
bid_ask_spread_max = 0.05 # vote negative price when bid-ask price is wider than bid_ask_spread_max
pause_broadcast = 1.0 # pausing before broadcast(seconds)
feeder = "" # oracle feeder address
validator = "" # validator address
key_name = "" # oracle feeder key name
key_password = "" # oracle feeder key password
fee_denom = "ukrw" # fee denom
fee_gas = "150000" # fee gas
fee_amount = "1500" # fee amount in ukrw
home_cli = "/home/ubuntu/.terracli" # terracli home directory
node = "tcp://52.78.69.160:26657" # node to broadcast the txs
terracli = "sudo /home/ubuntu/go/bin/terracli" # path to terracli binary
rpc_address = "https://soju-lcd.terra.dev/" # rpc to receive swap price information
coinone_share_default = 1 # default coinone weight for averaging oracle price
gopax_share_default = 0 # default gopax weight for averaging oracle price
gdac_share_default = 0 # default gdac weight for averaging oracle price
price_divergence_alert = False # alert when exchange prices diverge
vwma_period = 3*60 # period for volume weight moving average of coinone price in seconds

# parameters
fx_map = {"uusd":"USDUSD","ukrw":"USDKRW","usdr":"USDSDR","umnt":"USDMNT"}
active_candidate = ["uusd","ukrw","usdr","umnt"] # candidate for active denom set
hardfix_active_set = ["uusd","ukrw","usdr","umnt"] # hardfix the active set. does not care last oracle price availability
chain_id = "soju-0012" # chain id
round_block_num = 5.0 # number of blocks for each oracle round
