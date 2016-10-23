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
  # TODO : Check for a running instance of the bot?
  echo Updating requirements...
  git pull
  python3 -m pip install --user -U git+https://github.com/PapyrusThePlant/discord.py
  exit 0
elif [ $# -gt 0 ]
then
  print_help
  exit 1
fi

while true
do
  python3 -B scarecrow.py --logs file &
  BOT_PID=$!
  wait $BOT_PID
  BOT_STATUS=$?
  if [ $BOT_STATUS -ne 10 ]
  then
    break
   fi
done
