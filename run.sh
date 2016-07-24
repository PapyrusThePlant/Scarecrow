#!/bin/bash

print_help () {
  echo -e "Usage :\n    $0 [update]"
}

if [ $# -gt 1 ]
then
  print_help
  exit 1
fi

if [ "$1" == 'update' ]
then
  echo Updating requirements...
  git pull
  python3 -m pip install --user -U git+https://github.com/Rapptz/discord.py
  exit 0
elif [ "$1" != '' ]
then
  print_help
  exit 1
fi

echo Starting bot...
python3 -B main.py --logs logs/scarecrow.log &

