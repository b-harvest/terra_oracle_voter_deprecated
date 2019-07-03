# terra_oracle_voter
autovoting script for Terra oracle\\

## Disclaimer
The script is highly experimental state, and users should aware that all result from the terra_oracle_voter script is responsible to the user himself/herself.\\

## language
python3\\

## configure(in terra_oracle_vote.py)
telegram_token = ""\
telegram_chat_id = ""\
stop_oracle_trigger = 0.1 # stop oracle when price change exceeds stop_oracle_trigger\
pause_broadcast = 8.0 # pause time after each tx broadcasting\
feeder = "" # oracle feeder address\
validator = "" # validator address\
key_name = "" # local key name for oracle feeder\
key_password = "" # local key password for oracle feeder\
fee_denom = "ukrw"\
fee_gas = "50000"\
fee_amount = "750"\
home_cli = "/home/ubuntu/.terracli"\
chain_id = "columbus-2"\\

## functions
1. main feature : prevote and vote on terra oracle.\
2. risk management feature : when difference between calculated price and latest oracle price diverge more than stop_oracle_trigger, warn user via telegram and exit the program
