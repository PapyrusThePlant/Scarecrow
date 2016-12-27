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

sleep_time=1
while true
do
    # Execute the bot
    start_time=`date +%s`
    python3 -B scarecrow.py $1
    exit_code=$?
    end_time=`date +%s`

    # Check for the exit code
    if [ $exit_code -eq 1 ]
    then
        # Restart is asked, sleep for a while
        sleep $sleep_time
    else
        # Exit with the bot's exit code
        exit $exit_code
    fi

    # Compute the next sleep time
    if [ $(($end_time - $start_time)) -ge 45 ]
    then
        # The execution was long enough, reset the sleep time
        sleep_time=1
    else
        # Double the sleep time but cap it to 45
        sleep_time=$(($sleep_time > 22 ? 45 : $sleep_time * 2))
    fi
done
