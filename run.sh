#!/bin/bash

if [ "$1" == 'update' ]
then
  # TODO : Do not re-install the lib if no newer version is available
  # TODO : venv
  echo Updating requirements...
  git pull
  python3 -m pip install --user -U git+https://github.com/PapyrusThePlant/discord.py
  exit 0
fi

while true
do
  python3 -B scarecrow.py $1 &
  BOT_PID=$!
  wait $BOT_PID
  BOT_STATUS=$?
  if [ $BOT_STATUS -ne 1 ]
  then
    break
   fi
done
