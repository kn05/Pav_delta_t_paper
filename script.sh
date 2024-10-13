#!/bin/bash

echo "Run!"

for ((dt=1 ; dt < 11 ; dt++));
do
for ((dtt=1 ; dtt < 11 ; dtt++));
do
/home/kimbell/anaconda3/envs/SNN/bin/python /home/kimbell/triplet_izhikevich_pavlovian/2023_8_6/1/izhikevich_pavlovian_gpu_stim.py $dt $dtt
done
done