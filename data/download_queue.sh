#!/bin/bash
# Queue: after udam zip done, download D04 and D24 damage zips + key longterm months
PY=/c/Users/wfy/.conda/envs/shm/python.exe
cd /d/event-camera/SHM
$PY src/data/s3_download.py 15117569 OGW_CFRP_Temperature_dam_D04.zip 16 >> data/download.log 2>&1
$PY src/data/s3_download.py 15130196 OGW_CFRP_Temperature_dam_D24.zip 16 >> data/download.log 2>&1
# long-term damage-onset months (mass 2021-04, dent 2021-05, hole 2022-07)
for f in "51426359 measurements_2021_03.pickle" "51426365 measurements_2021_04.pickle" \
         "51426368 measurements_2021_05.pickle" "51426374 measurements_2021_06.pickle" \
         "51426446 measurements_2022_07.pickle" "51426449 measurements_2022_08.pickle"; do
  set -- $f
  $PY src/data/s3_download.py $1 $2 10 >> data/download_lt.log 2>&1
done
echo "QUEUE COMPLETE"
