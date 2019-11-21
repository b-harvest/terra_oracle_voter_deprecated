# Terra_oracle_voter
autovoting script for Terra oracle by B-Harvest

## Disclaimer
The script is in highly experimental state, and users should aware that all result from the terra_oracle_voter script is responsible to the user himself/herself.

## Language
Python3

## Preliminary
The server running this script should run terrad with synced status.

## Configure(in terra_oracle_vote.py)
telegram_token = ""\
telegram_chat_id = ""\
stop_oracle_trigger_recent_diverge = 0.1 # stop oracle when price change exceeds stop_oracle_trigger\
stop_oracle_trigger_exchange_diverge = 0.1 # stop oracle when price change exceeds stop_oracle_trigger\
pause_broadcast = 1.0 # pause time after each tx broadcasting\
feeder = "" # oracle feeder address\
validator = "" # validator operator address\
key_name = "" # key name\
key_password = "" # key password\
fee_denom = "ukrw"\
fee_gas = "100000"\
fee_amount = "1500"\
home_cli = "/home/ubuntu/.terracli"\

fx_map = {"uusd":"USDUSD","ukrw":"USDKRW","usdr":"USDSDR","umnt":"USDMNT"}\
active_candidate = ["uusd","ukrw","usdr","umnt"]\
hardfix_active_set = [] # hardfix the active set. does not care about stop_oracle_trigger_recent_diverge\
chain_id = "columbus-2"\
round_block_num = 12.0

## Functions
1. Main feature : prevote and vote on terra oracle.
2. Risk management feature : when percentage difference between calculated price and latest oracle price diverge more than stop_oracle_trigger, warn user via telegram and exit the program
