#!/bin/bash

if [ ! -d './venv' ]
then
    echo Creating new virtual environment...
    python3.5 -m virtualenv venv
fi

# Activate the virtual environment
source venv/bin/activate

if [ "$1" == 'update' ]
then
    branch=$(git rev-parse --abbrev-ref HEAD)
    echo Pulling last version from ${branch}...
    git pull

    echo Updating requirements...
    pip install -U -r requirements.txt
    exit 0
fi

rm logs/*
sleep_time=1
while true
do
    # Execute the bot
    start_time=`date +%s`
    python3 -B run.py "$@"
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

# Deactivate the virtual environment
deactivate